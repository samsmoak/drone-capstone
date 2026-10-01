"""The end-to-end scenarios: the mission controller flying the simulated drone
(tests/sim_drone.py) through the REAL manual flight system, on one FakeClock,
tick_s=0 (mission-verification.txt, PART 3; the seam, 3).

Each scenario names the rules of THE SPEC it proves. Every constant is
imported (the seam, 4). Every mission here is checked for E1 when its test
ends.
"""

from __future__ import annotations

import math

import pytest

from cropwatcher.flight.manual import (
    CLIMB_RATE_M_S,
    HEARTBEAT_TIMEOUT_S,
    LAND_S,
    MOVE_SPEED_M_S,
    ControlState,
    Fix,
    Intent,
    ManualController,
)
from cropwatcher.mission.controller import (
    TERMINAL_STATES,
    EventKind,
    MissionController,
    MissionEvent,
    MissionState,
)
from cropwatcher.mission.controller.events import TERMINAL_EVENTS
from cropwatcher.mission.controller.mission_controller import ARRIVE_M, SETTLE_S
from cropwatcher.mission.plan.mission import Mission
from cropwatcher.mission.plan.validate import errors, validate_mission
from tests.mission.plans import OUTER, mission, room
from tests.sim_drone import MANUAL_TICK_S, SimDrone

K = EventKind


class RecordedFlight:
    """The real ManualController, with every command the mission controller
    gives it written down. Everything else is read straight through."""

    def __init__(self, ctl: ManualController, clock) -> None:
        self._ctl = ctl
        self._clock = clock
        self.calls: list[tuple[str, float]] = []    # (command, when)

    def __getattr__(self, name: str):
        return getattr(self._ctl, name)

    def hold_at(self, height_m: float) -> None:
        self.calls.append(("hold_at", self._clock()))
        self._ctl.hold_at(height_m)

    def fly_to(self, x: float, y: float, height_m: float,
               speed_m_s: float | None = None) -> None:
        self.calls.append(("fly_to", self._clock()))
        self._ctl.fly_to(x, y, height_m, speed_m_s=speed_m_s)

    def land(self) -> None:
        self.calls.append(("land", self._clock()))
        self._ctl.land()

    def commands(self) -> list[str]:
        return [c for c, _ in self.calls]

    def after(self, t: float) -> list[str]:
        return [c for c, when in self.calls if when > t]


_FLOWN: list[Scenario] = []


@pytest.fixture(autouse=True)
def every_mission_ends_once():
    """E1, in every scenario: exactly one terminal event, and it is the last."""
    _FLOWN.clear()
    yield
    for s in _FLOWN:
        kinds = [e.kind for e in s.events]
        terminal = [i for i, k in enumerate(kinds) if k in TERMINAL_EVENTS]
        if s.mc.state in TERMINAL_STATES:
            assert len(terminal) == 1, kinds
            assert terminal[0] == len(kinds) - 1, kinds
        else:
            assert not terminal, kinds


class Scenario:
    def __init__(self, plan: Mission | None = None, *, listener=None, **drone) -> None:
        self.plan = plan or mission()
        # Only a mission the session would fly: inside the test room's fence
        # and height band, every leg clear of its table (plans.room()).
        assert not errors(validate_mission(self.plan, room(), outer=OUTER))
        home = self.plan.home
        self.sim = SimDrone(start=Fix(home[0], home[1], 0.0), **drone)
        self.flight = RecordedFlight(self.sim.ctl, self.sim.clock)
        self.events: list[MissionEvent] = []

        def on_event(event: MissionEvent) -> None:
            self.events.append(event)
            if listener is not None:
                listener(event)

        self.sim.arm()                                  # what the session does
        self.mc = MissionController(self.plan, self.flight, on_event=on_event,
                                    clock=self.sim.clock, tick_s=0)
        _FLOWN.append(self)

    @property
    def limit_s(self) -> float:
        """Twice the planner's estimate: long enough for any honest flight,
        short enough that a hang fails fast."""
        return 2 * self.plan.estimated_duration_s(move_speed_m_s=MOVE_SPEED_M_S,
                                                  climb_rate_m_s=CLIMB_RATE_M_S) + 30

    def start(self) -> None:
        self.mc.start()

    def fly(self) -> float:
        """Start (if not started) and fly to a terminal state; the simulated
        seconds it took."""
        if self.mc.state is MissionState.IDLE:
            self.start()
        return self.sim.run_until(self.mc, lambda: self.mc.state in TERMINAL_STATES,
                                  limit_s=self.limit_s)

    def until(self, done) -> None:
        if self.mc.state is MissionState.IDLE:
            self.start()
        self.sim.run_until(self.mc, done, limit_s=self.limit_s)

    def kinds(self) -> list[EventKind]:
        return [e.kind for e in self.events]

    def last(self, kind: EventKind) -> MissionEvent:
        return next(e for e in reversed(self.events) if e.kind is kind)


def spec_sequence(points: tuple[str, ...], returning: bool) -> list[tuple[EventKind, str | None]]:
    seq: list[tuple[EventKind, str | None]] = [(K.STARTED, None), (K.TAKEOFF_DONE, None)]
    for p in points:
        seq += [(K.POINT_ARRIVED, p), (K.HOLD_STARTED, p), (K.POINT_COMPLETE, p)]
    if returning:
        seq.append((K.RETURNING, None))
    return seq + [(K.LANDED, None), (K.DONE, None)]


# ── the whole mission ─────────────────────────────────────────────────────


@pytest.mark.parametrize("returning", [True, False])
def test_three_points_in_order_with_exactly_the_specs_events(returning):
    """T6–T15, E1."""
    s = Scenario(mission(return_to_start=returning))
    s.fly()
    assert s.mc.state is MissionState.DONE
    assert [(e.kind, e.point_id) for e in s.events] == spec_sequence(
        ("P1", "P2", "P3"), returning)
    assert s.mc.completed_point_ids == ("P1", "P2", "P3")
    assert s.flight.commands() == ["hold_at", "fly_to", "fly_to", "fly_to"] + (
        ["fly_to"] if returning else []) + ["land"]
    assert s.sim.ctl.state is ControlState.LANDED


@pytest.mark.parametrize("returning", [True, False])
def test_the_commentary_says_what_comes_next(returning):
    """The Command log reads each event's words as the mission's commentary:
    where it is going next, which point is the last, and when it lands."""
    s = Scenario(mission(return_to_start=returning))
    s.fly()
    said = {(e.kind, e.point_id): e.detail for e in s.events}
    assert said[(K.POINT_COMPLETE, "P1")] == "P1 complete — flying to P2"
    assert said[(K.POINT_COMPLETE, "P2")] == "P2 complete — flying to P3"
    assert said[(K.POINT_ARRIVED, "P3")].startswith("P3 reached — the last point, ")
    assert "the last point" not in said[(K.POINT_ARRIVED, "P1")]
    if returning:
        assert said[(K.POINT_COMPLETE, "P3")] == (
            "P3 complete — the last point; returning to the start")
        assert said[(K.RETURNING, None)] == "Returning over the start, then landing"
    else:
        assert said[(K.POINT_COMPLETE, "P3")] == "P3 complete — the last point; landing now"


def test_a_steady_mission_completes_and_takes_longer_than_a_brisk_one():
    """The real manual flight system, at the mission's speed (2026-10-01)."""
    times = {}
    for speed in (0.10, 0.20):
        s = Scenario(mission(return_to_start=True, speed_m_s=speed))
        s.fly()
        assert s.mc.state is MissionState.DONE
        times[speed] = s.events[-1].at_s
    assert times[0.10] > times[0.20]


def test_every_hold_lasts_hold_s_and_the_point_is_stamped_only_while_holding_there():
    """C1, T11–T13: sampled every manual tick, in all three dimensions. THE
    SPEC's arrival is x-y (drift_m); the height is the flight system's goal —
    this proves the two together put the drone AT the point, not over it."""
    s = Scenario()
    points = {p.id: p for p in s.plan.points}
    bad: list[str] = []

    def sample() -> None:
        point_id = s.mc.current_point_id
        holding = s.mc.state is MissionState.HOLDING
        if (point_id is not None) != holding:
            bad.append(f"{s.sim.clock():.2f}: {point_id} while {s.mc.state}")
        if point_id is not None:
            p = points[point_id]
            off = math.dist(s.sim.true_xy, (p.x_m, p.y_m))
            if off > ARRIVE_M:
                bad.append(f"{s.sim.clock():.2f}: {point_id} stamped {off:.3f} m away")
            high = abs(s.sim.true_height - p.z_m)
            if high > ARRIVE_M:
                bad.append(f"{s.sim.clock():.2f}: {point_id} stamped {high:.3f} m off "
                           f"its height")

    s.sim.watch(sample)
    s.fly()
    assert bad == []
    for p in s.plan.points:
        began = next(e for e in s.events if e.kind is K.HOLD_STARTED and e.point_id == p.id)
        ended = next(e for e in s.events if e.kind is K.POINT_COMPLETE and e.point_id == p.id)
        assert ended.at_s - began.at_s >= p.hold_s


@pytest.mark.parametrize("returning", [True, False])
def test_it_touches_down_over_the_start_or_at_the_last_point(returning):
    """T14."""
    s = Scenario(mission(return_to_start=returning))
    s.fly()
    assert s.sim.landed_at is not None
    last = s.plan.points[-1]
    where = s.plan.home if returning else (last.x_m, last.y_m)
    assert math.dist(s.sim.landed_at, where) <= ARRIVE_M


# ── the drone is imperfect ────────────────────────────────────────────────


def test_noise_under_arrive_m_still_completes():
    """T9, with the estimate wandering: a quarter of ARRIVE_M per axis."""
    s = Scenario(noise_m=ARRIVE_M / 4, seed=3)
    s.fly()
    assert s.mc.state is MissionState.DONE
    assert s.mc.completed_point_ids == ("P1", "P2", "P3")


def test_a_steady_drift_is_held_against_and_the_mission_completes():
    s = Scenario(drift_m_s=(0.02, -0.01))
    s.fly()
    assert s.mc.state is MissionState.DONE


def test_a_gust_while_arriving_restarts_the_settle_wait_and_it_still_completes():
    """T9: drift past ARRIVE_M restarts the wait; the mission carries on."""
    s = Scenario()
    s.until(lambda: s.mc.state is MissionState.ARRIVING)
    s.sim.step(SETTLE_S / 2, s.mc)
    assert s.mc.state is MissionState.ARRIVING
    s.sim.push(0.25, 0.0)
    last_over = [0.0]

    def track() -> None:
        if s.mc.state is MissionState.ARRIVING and s.sim.ctl.drift_m > ARRIVE_M:
            last_over[0] = s.sim.clock()

    s.sim.watch(track)
    s.until(lambda: s.mc.state is MissionState.HOLDING)
    assert last_over[0] > 0, "the gust never pushed it past ARRIVE_M"
    assert s.last(K.HOLD_STARTED).at_s - last_over[0] >= SETTLE_S - MANUAL_TICK_S
    s.fly()
    assert s.mc.state is MissionState.DONE


# ── what goes wrong ───────────────────────────────────────────────────────


def test_a_stalled_drone_times_out_lands_and_flies_nowhere_after():
    """T4, T8."""
    s = Scenario()
    s.until(lambda: s.mc.state is MissionState.TRANSIT)
    s.sim.stall()
    s.fly()
    assert s.mc.state is MissionState.ABORTED
    ended = s.events[-1]
    assert "timed out" in ended.detail
    assert ended.point_id == "P1"
    landed_at = next(when for c, when in s.flight.calls if c == "land")
    assert s.flight.after(landed_at) == []
    assert s.sim.ctl.state in (ControlState.LANDING, ControlState.LANDED)
    assert s.mc.completed_point_ids == ()


def test_a_key_held_mid_transit_interrupts_and_the_drone_stays_the_operators():
    """T2: no fly_to and no land() after; the drone holds where it is."""
    s = Scenario()
    s.until(lambda: s.mc.state is MissionState.TRANSIT)
    s.sim.step(3.0, s.mc)
    s.sim.hold_key(Intent(left=True))
    s.sim.step(MANUAL_TICK_S * 2, s.mc)
    s.sim.hold_key(Intent())                            # and lets go
    s.fly()
    assert s.mc.state is MissionState.INTERRUPTED
    interrupted = s.events[-1].at_s
    assert s.events[-1].point_id == "P1"
    s.sim.step(2.0)                                     # settle after the key
    held = s.sim.true_xy
    s.sim.step(5.0, s.mc)
    assert s.flight.after(interrupted) == []
    assert s.sim.ctl.state is ControlState.FLYING       # the operator's, in the air
    assert math.dist(s.sim.true_xy, held) < 0.01        # holding its spot


def test_the_guard_landing_it_mid_mission_aborts_naming_landing():
    """T3."""
    s = Scenario()
    s.until(lambda: s.mc.state is MissionState.HOLDING)
    lands = s.flight.commands().count("land")
    s.sim.guard_lands()
    s.fly()
    assert s.mc.state is MissionState.ABORTED
    assert "landing" in s.events[-1].detail
    assert s.flight.commands().count("land") == lands
    assert s.mc.current_point_id is None


def test_an_emergency_stop_mid_mission_aborts_and_land_is_never_called():
    """T3."""
    s = Scenario()
    s.until(lambda: s.mc.state is MissionState.TRANSIT)
    s.sim.emergency_stop()
    s.fly()
    assert s.mc.state is MissionState.ABORTED
    assert "stopped" in s.events[-1].detail
    assert "land" not in s.flight.commands()


def test_a_quiet_window_lands_it_by_the_dead_man_and_aborts():
    """T3: the heartbeat stays with the app, and the mission cannot defeat it."""
    s = Scenario()
    s.until(lambda: s.mc.state is MissionState.ARRIVING)
    s.sim.window_goes_quiet()
    quiet_at = s.sim.clock()
    s.fly()
    assert s.mc.state is MissionState.ABORTED
    assert "landing" in s.events[-1].detail
    assert s.events[-1].at_s - quiet_at <= HEARTBEAT_TIMEOUT_S + 2 * 0.1
    assert "land" not in s.flight.after(quiet_at)
    s.sim.step(LAND_S + 1.0)
    assert s.sim.ctl.state is ControlState.LANDED


def test_a_listener_that_raises_does_not_stop_the_mission():
    """E5."""
    def broken(event: MissionEvent) -> None:
        raise RuntimeError("the app went away")

    s = Scenario(listener=broken)
    s.fly()
    assert s.mc.state is MissionState.DONE


def test_the_flown_time_against_the_planners_estimate(record_property, capsys):
    """Mission.estimated_duration_s is the number the battery refusal uses. A
    flight longer than it is a battery budget that is wrong: this REPORTS the
    comparison rather than asserting it away (mission-verification.txt PART 3),
    and the feature doc carries what it found."""
    for returning in (True, False):
        s = Scenario(mission(return_to_start=returning))
        s.fly()
        flown = s.events[-1].at_s - s.events[0].at_s
        estimate = s.plan.estimated_duration_s(move_speed_m_s=MOVE_SPEED_M_S,
                                               climb_rate_m_s=CLIMB_RATE_M_S)
        record_property(f"flown_s_return_{returning}", round(flown, 1))
        record_property(f"estimate_s_return_{returning}", round(estimate, 1))
        with capsys.disabled():
            print(f"\n  return_to_start={returning}: flown {flown:.1f} s in simulation, "
                  f"estimate {estimate:.1f} s ({flown - estimate:+.1f} s)")
        assert s.mc.state is MissionState.DONE
