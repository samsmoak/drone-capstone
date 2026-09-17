"""Guarded flight and the hover test, against a simulated drone.

The simulator answers the high-level commander like the firmware: takeoff
climbs to the commanded absolute z, land descends to it. Faults are injected
into its telemetry to prove each guard verdict is acted on in flight.
"""

from __future__ import annotations

import threading
from types import MappingProxyType, SimpleNamespace

import pytest

from cropwatcher.flight.checks import ReadyReport
from cropwatcher.flight.control import FlightAborted, GuardedFlight, Phase
from cropwatcher.flight.programs import HoverTest, Outcome, run_hover_test
from cropwatcher.safety.flight_guard import (
    FlightGuard,
    GuardContext,
    PositioningStatus,
    Reason,
)
from cropwatcher.telemetry.stream import Snapshot

GROUND = 0.012


class SimDrone:
    """Firmware-shaped enough for the flight layer: commands in, estimate out."""

    def __init__(self, clock) -> None:
        self.clock = clock
        self.z = GROUND
        self.x = 0.0
        self.target_z = GROUND
        self.motors_on = False
        self.commands: list[tuple] = []
        self.faults: dict[str, float] = {}
        self.fault_after: float | None = None

        hlc = SimpleNamespace(
            takeoff=lambda z, d: self._cmd("takeoff", z, d),
            land=lambda z, d: self._cmd("land", z, d),
            stop=lambda: self._cmd("hlc_stop"),
        )
        commander = SimpleNamespace(send_stop_setpoint=lambda: self._cmd("stop_setpoint"))
        self.cf = SimpleNamespace(high_level_commander=hlc, commander=commander)

    def _cmd(self, name, *args):
        self.commands.append((name, *args))
        if name in ("takeoff", "land"):
            self.target_z = args[0]
            self.motors_on = True
        if name in ("stop_setpoint",):
            self.motors_on = False

    def names(self):
        return [c[0] for c in self.commands]

    def snapshot(self) -> Snapshot:
        # Instant tracking is enough: the guard sees the commanded height.
        if self.motors_on:
            self.z = self.target_z
        values = {
            "stateEstimate.x": self.x, "stateEstimate.y": 0.0, "stateEstimate.z": self.z,
            "stateEstimate.vx": 0.0, "stateEstimate.vy": 0.0, "stateEstimate.vz": 0.0,
            "kalman.varPX": 0.0004, "kalman.varPY": 0.0004,
            "lighthouse.bsReceive": 0b11, "pm.vbat": 3.9, "pm.state": 0, "supervisor.info": 0,
        }
        if self.fault_after is not None and self.clock.now >= self.fault_after:
            values |= self.faults
        return Snapshot(MappingProxyType(values), updated_at=self.clock.now)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def report() -> ReadyReport:
    return ReadyReport(
        hardware_id="cf-test", vbat=4.0, endurance_s=200, ground_z_m=GROUND,
        takeoff_xy=(0.0, 0.0), estimate_spread_m=0.005,
        positioning=PositioningStatus((0, 1), (0, 1), (0, 1), (0, 1), (0.0004,) * 3),
    )


def make_flight(height: float = 0.3):
    clock = Clock()
    drone = SimDrone(clock)
    phases: list = []
    guard = FlightGuard(GuardContext(
        ground_z=GROUND, fence_half_extent_m=2.0, max_height_m=1.0,
        takeoff_xy=(0.0, 0.0), target_height_m=height,
    ))
    flight = GuardedFlight(
        drone.cf, drone.snapshot, guard, report(),
        clock=clock, sleep=clock.sleep, on_phase=phases.append,
    )
    return flight, drone, clock, phases


class TestHoverTest:
    def test_completes_and_lands_relative_to_ground(self):
        flight, drone, _, phases = make_flight()
        result = run_hover_test(flight, HoverTest(height_m=0.3, hold_s=10))

        assert result.outcome is Outcome.COMPLETED
        assert drone.commands[0] == ("takeoff", pytest.approx(GROUND + 0.3), 2.5)
        assert ("land", GROUND, 3.0) in drone.commands
        assert [p.phase for p in phases] == [
            Phase.TAKING_OFF, Phase.HOLDING, Phase.LANDING, Phase.GROUNDED,
        ]
        assert flight.phase is Phase.GROUNDED

    def test_battery_low_mid_flight_ends_the_operation_gracefully(self):
        flight, drone, _, _ = make_flight()
        drone.faults = {"pm.state": 3}
        drone.fault_after = 5.0
        result = run_hover_test(flight, HoverTest(hold_s=10))

        assert result.outcome is Outcome.LANDED_BY_GUARD
        assert result.reason is Reason.BATTERY_LOW
        assert "land" in drone.names()
        assert "stop_setpoint" not in drone.names()

    def test_the_crash_trace_stops_the_motors_instead_of_flying_on(self):
        flight, drone, _, phases = make_flight()
        drone.faults = {"stateEstimate.z": GROUND - 1.53, "kalman.varPX": 4.4}
        drone.fault_after = 4.0
        drone.motors_on = False  # the estimate, not the command, goes wrong
        result = run_hover_test(flight, HoverTest(hold_s=10))

        assert result.outcome is Outcome.STOPPED
        assert result.reason is Reason.POSITION_LOST
        assert "stop_setpoint" in drone.names()
        assert "land" not in drone.names()
        assert phases[-1].phase is Phase.STOPPED

    def test_drift_lands(self):
        flight, drone, clock, _ = make_flight()
        drone.faults = {"stateEstimate.x": 0.5}
        drone.fault_after = 6.0
        result = run_hover_test(flight, HoverTest(hold_s=10))
        assert result.reason is Reason.DRIFT
        assert result.outcome is Outcome.LANDED_BY_GUARD

    @pytest.mark.parametrize(("height", "hold"), [(0.05, 10), (1.5, 10), (0.3, 0.5), (0.3, 120)])
    def test_rejects_out_of_range_programs(self, height, hold):
        with pytest.raises(ValueError):
            HoverTest(height_m=height, hold_s=hold)


class TestOperatorRequests:
    def test_land_request_during_hold(self):
        flight, drone, clock, _ = make_flight()
        original_sleep = clock.sleep

        def sleep_and_request(s):
            original_sleep(s)
            if 6.0 <= clock.now < 6.06:
                flight.request_land()

        flight._sleep = sleep_and_request
        result = run_hover_test(flight, HoverTest(hold_s=10))
        assert result.outcome is Outcome.LANDED_BY_OPERATOR
        assert "land" in drone.names()

    def test_emergency_stop_acts_immediately(self):
        flight, drone, _, _ = make_flight()
        flight.request_stop()
        assert "stop_setpoint" in drone.names()

    def test_emergency_stop_interrupts_a_landing(self):
        flight, drone, clock, _ = make_flight()
        flight.takeoff(0.3)
        original_sleep = clock.sleep

        def sleep_and_stop(s):
            original_sleep(s)
            if flight.phase is Phase.LANDING and clock.now > 3.5:
                flight.request_stop()

        flight._sleep = sleep_and_stop
        with pytest.raises(FlightAborted):
            flight.land()
        assert flight.phase is Phase.STOPPED

    def test_requests_from_another_thread(self):
        flight, drone, _, _ = make_flight()
        t = threading.Thread(target=flight.request_land)
        t.start()
        t.join()
        with pytest.raises(FlightAborted):
            flight.takeoff(0.3)
        assert "land" in drone.names()
