"""The session checks, driven by a fake clock and a scripted telemetry source."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from cropwatcher.flight.checks import (
    CheckKey,
    ChecksFailed,
    CheckStatus,
    battery_percent,
    collect,
    read_hardware_id,
    run_checks,
    run_prop_test,
)
from cropwatcher.telemetry.stream import Snapshot

# The lab drone's real MCU id, read 2026-09-16.
LAB_CPU_ID = {"cpu.id0": "3080234", "cpu.id1": "859064082", "cpu.id2": "959656757"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def healthy(clock: FakeClock, **overrides: float) -> Snapshot:
    values = {
        "pm.vbat": 4.05, "sys.canfly": 1,
        "lighthouse.bsReceive": 0b11, "lighthouse.bsCalVal": 0b11,
        "lighthouse.bsGeoVal": 0b11, "lighthouse.bsAvailable": 0b1111,
        "kalman.varPX": 0.0004, "kalman.varPY": 0.0004, "kalman.varPZ": 0.0004,
        "stateEstimate.x": 0.10, "stateEstimate.y": -0.20, "stateEstimate.z": 0.012,
    } | overrides
    return Snapshot(MappingProxyType(values), updated_at=clock.now)


def make_cf(**params: str):
    values = LAB_CPU_ID | {"deck.bcLighthouse4": "1"} | params
    writes: list[tuple[str, str]] = []
    return SimpleNamespace(param=SimpleNamespace(
        get_value=lambda name: values[name],
        set_value=lambda name, value: writes.append((name, value)),
        writes=writes,
    ))


def run(cf, source, clock, **kwargs):
    steps: list = []
    report = collect(run_checks(cf, source, clock=clock, sleep=clock.sleep, **kwargs), steps.append)
    return report, steps


class TestHappyPath:
    def test_every_check_passes_in_order_and_reports_ground(self):
        clock = FakeClock()
        resets: list[bool] = []
        report, steps = run(make_cf(), lambda: healthy(clock), clock,
                            reset_estimator=lambda: resets.append(True))

        passed = [s.key for s in steps if s.status is CheckStatus.PASSED]
        assert passed == list(CheckKey)
        assert all(steps[i].status is CheckStatus.RUNNING for i in range(0, len(steps), 2))
        assert report.hardware_id == "cf-002f002a3334471239333335"
        assert report.ground_z_m == pytest.approx(0.012)
        assert report.takeoff_xy == pytest.approx((0.10, -0.20))
        assert resets == [True]

    def test_battery_step_carries_display_values(self):
        clock = FakeClock()
        _, steps = run(make_cf(), lambda: healthy(clock), clock)
        battery = next(s for s in steps
                       if s.key is CheckKey.BATTERY and s.status is CheckStatus.PASSED)
        assert battery.data == {"vbat": 4.05, "percent": 83, "canfly": True, "endurance_s": 200}


class TestFailures:
    def failing_step(self, cf, source, clock):
        steps: list = []
        with pytest.raises(ChecksFailed) as err:
            collect(run_checks(cf, source, clock=clock, sleep=clock.sleep), steps.append)
        assert steps[-1].status is CheckStatus.FAILED
        assert steps[-1] is err.value.result
        return steps[-1]

    def warning_step(self, cf, source, clock, key: CheckKey):
        """Positioning problems warn and degrade; they no longer block."""
        steps: list = []
        report = collect(run_checks(cf, source, clock=clock, sleep=clock.sleep), steps.append)
        warned = next(s for s in steps if s.key is key and s.status is CheckStatus.WARNING)
        assert not report.assisted
        assert report.unassisted_reason
        return report, warned

    def test_the_lab_crash_conditions_leave_the_drone_unassisted(self):
        """The 2026-09-16 conditions: 4 stations stored, 0 received.

        The operator may now fly by hand anyway — that is their call — but the
        drone must never be told it can hold a position. `assisted` False is
        what stops a program running and what switches off the guards that
        would otherwise steer by the accelerometer integrating.
        """
        clock = FakeClock()
        crash = lambda: healthy(  # noqa: E731
            clock, **{"lighthouse.bsReceive": 0, "kalman.varPX": 4.38, "kalman.varPY": 4.38})
        report, warned = self.warning_step(make_cf(), crash, clock, CheckKey.POSITIONING)
        assert "No base station signal" in warned.detail
        assert warned.data["stored"] == [0, 1, 2, 3]
        assert warned.data["received"] == []
        assert report.positioning.usable == ()

    def test_base_stations_get_time_to_lock_on(self):
        clock = FakeClock()
        source = lambda: healthy(  # noqa: E731
            clock, **({"lighthouse.bsReceive": 0} if clock.now < 3 else {}))
        report, _ = run(make_cf(), source, clock)
        assert report.positioning.usable == (0, 1)

    def test_firmware_refuses_to_arm(self):
        clock = FakeClock()
        failed = self.failing_step(make_cf(), lambda: healthy(clock, **{"sys.canfly": 0}), clock)
        assert failed.key is CheckKey.BATTERY
        assert "sys.canfly=0" in failed.detail

    def test_no_deck_leaves_the_drone_unassisted(self):
        clock = FakeClock()
        report, warned = self.warning_step(
            make_cf(**{"deck.bcLighthouse4": "0"}), lambda: healthy(clock), clock, CheckKey.DECK)
        assert "unassisted" in warned.detail
        assert not report.assisted

    def test_no_telemetry(self):
        clock = FakeClock()
        stale = lambda: Snapshot(MappingProxyType({}), updated_at=None)  # noqa: E731
        failed = self.failing_step(make_cf(), stale, clock)
        assert failed.key is CheckKey.TELEMETRY

    def test_z_settled_but_x_wandering_is_not_settled(self):
        # The exact hole: the old preflight looked at z only. It no longer
        # blocks, but a wandering estimate must never count as assisted.
        clock = FakeClock()
        wander = lambda: healthy(clock, **{"stateEstimate.x": clock.now * 0.5})  # noqa: E731
        report, warned = self.warning_step(make_cf(), wander, clock, CheckKey.ESTIMATE)
        assert "never settled" in warned.detail
        assert not report.assisted

    def test_unreadable_identity(self):
        clock = FakeClock()
        cf = make_cf()
        cf.param.get_value = lambda name: (_ for _ in ()).throw(KeyError(name))
        failed = self.failing_step(cf, lambda: healthy(clock), clock)
        assert failed.key is CheckKey.IDENTITY


class TestHelpers:
    def test_hardware_id_is_stable_and_distinct_from_the_radio_address(self):
        cf = make_cf()
        assert read_hardware_id(cf) == read_hardware_id(cf)
        assert "radio" not in read_hardware_id(cf)

    @pytest.mark.parametrize(("vbat", "percent"),
                             [(4.2, 100), (4.4, 100), (3.75, 50), (3.3, 0), (3.0, 0)])
    def test_battery_percent_is_clamped(self, vbat, percent):
        assert battery_percent(vbat) == percent


class TestPropTest:
    def test_reads_each_motor(self):
        clock = FakeClock()
        cf = make_cf()
        readings = iter([(4, 0), (4, 0), (5, 0b1011)])
        result = run_prop_test(cf, lambda: next(readings), clock=clock, sleep=clock.sleep)
        assert cf.param.writes == [("health.startPropTest", "1")]
        assert result.passed == (1, 2, 4)
        assert result.failed == (3,)
        assert not result.ok

    def test_all_four_pass(self):
        clock = FakeClock()
        readings = iter([(0, 0), (1, 0b1111)])
        assert run_prop_test(make_cf(), lambda: next(readings), clock=clock, sleep=clock.sleep).ok

    def test_times_out_without_a_result(self):
        clock = FakeClock()
        with pytest.raises(TimeoutError):
            run_prop_test(make_cf(), lambda: (7, 0), clock=clock, sleep=clock.sleep)
