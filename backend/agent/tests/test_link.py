"""DroneLink: every way in fails with an operator-readable reason, and every way
out stops the motors."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from cropwatcher.flight import link as link_module
from cropwatcher.flight.checks import ReadyReport
from cropwatcher.flight.link import DroneLink, LinkError
from cropwatcher.safety.flight_guard import PositioningStatus


class FakeScf:
    def __init__(self, fail_open: bool = False, hang_open: bool = False) -> None:
        self.fail_open = fail_open
        #: Stands in for cflib's open_link, which waits on an Event with no
        #: timeout and so never returns if the drone stops answering.
        self.hang_open = hang_open
        self.opened = False
        self.closed = False
        self.cf = SimpleNamespace(
            commander=SimpleNamespace(),
            high_level_commander=SimpleNamespace(land=lambda z, d: None),
        )

    def open_link(self) -> None:
        if self.fail_open:
            raise RuntimeError("Too many packets lost")
        if self.hang_open:
            threading.Event().wait()            # exactly what cflib does
        self.opened = True

    def close_link(self) -> None:
        self.closed = True


class FakeStream:
    def __init__(self, scf) -> None:
        self.started = self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def snapshot(self):
        return None


def make_link(scf: FakeScf | None = None, *, found=("radio://0/80/2M",), scan_error=None,
              configure_error=None):
    scf = scf or FakeScf()
    cuts: list[FakeScf] = []

    def scan():
        if scan_error:
            raise scan_error
        return list(found)

    def configure(cf):
        if configure_error:
            raise configure_error

    link = DroneLink(
        scf_factory=lambda uri: scf, scan=scan, stream_factory=FakeStream,
        configure=configure, cut_motors=cuts.append,
    )
    return link, scf, cuts


REPORT = ReadyReport(
    hardware_id="cf-1", vbat=4.0, endurance_s=200, ground_z_m=0.5,
    takeoff_xy=(0.1, 0.2), estimate_spread_m=0.01,
    positioning=PositioningStatus((0, 1), (0, 1), (0, 1), (0, 1), (0.0004,) * 3),
)


class TestOpen:
    def test_opens_configures_and_streams(self):
        link, scf, _ = make_link()
        link.open()
        assert link.is_open and scf.opened and link.stream.started

    def test_a_missing_dongle_says_the_dongle_is_missing(self, monkeypatch):
        monkeypatch.setattr(link_module, "_nothing_found_reason",
                            lambda: "No Crazyradio was found on USB.")
        link, _, _ = make_link(found=())
        with pytest.raises(LinkError, match="No Crazyradio was found"):
            link.open()
        assert not link.is_open

    def test_a_radio_someone_else_holds_says_so(self, monkeypatch):
        """A USB radio can be claimed by one process. The second one is told
        "no such device", which read as a flat battery and sent an operator to
        re-plug a working dongle four times on 2026-09-22 while the desktop
        app quietly held it."""
        from cropwatcher.flight import radio
        monkeypatch.setattr(radio, "radio_seen", lambda: True)
        monkeypatch.setattr(radio, "windows_driver_problem", lambda: None)
        reason = link_module._nothing_found_reason()
        assert "other program" in reason and "quit" in reason.lower()
        assert "switch it on" in reason.lower()
        assert "battery" not in reason.lower()[:120]   # not the first thing blamed

    def test_radio_unavailable(self):
        link, _, _ = make_link(scan_error=OSError("[Errno 19] No such device"))
        with pytest.raises(LinkError, match="Crazyradio could not be opened"):
            link.open()

    def test_link_fails_to_open(self):
        link, _, _ = make_link(FakeScf(fail_open=True))
        with pytest.raises(LinkError, match="link failed"):
            link.open()

    def test_a_drone_that_stops_answering_does_not_hang_for_ever(self):
        """cflib's SyncCrazyflie.open_link waits on an Event with NO timeout.
        A radio pulled mid-handshake therefore blocked the caller for good,
        and on 2026-09-22 that wedged the desktop app: the checks worker never
        returned and every later action answered "Something is already
        running"."""
        link, _, _ = make_link(FakeScf(hang_open=True))
        started = time.monotonic()
        with pytest.raises(LinkError, match="stopped answering while connecting"):
            link._open_link_within(link._scf_factory(link.uri), timeout_s=0.2)
        assert time.monotonic() - started < 5.0        # it gave up, not hung
        assert not link.is_open

    def test_the_timeout_message_says_what_to_check(self):
        link, _, _ = make_link(FakeScf(hang_open=True))
        with pytest.raises(LinkError) as caught:
            link._open_link_within(link._scf_factory(link.uri), timeout_s=0.1)
        text = str(caught.value)
        assert "Crazyradio" in text and "plugged in" in text

    def test_configure_failure_still_stops_motors_and_closes(self):
        link, scf, cuts = make_link(configure_error=RuntimeError("param timeout"))
        with pytest.raises(RuntimeError):
            link.open()
        assert cuts == [scf] and scf.closed and not link.is_open


class TestClose:
    def test_close_stops_stream_then_motors_then_link(self):
        link, scf, cuts = make_link()
        link.open()
        stream = link.stream
        link.close()
        assert stream.stopped and cuts == [scf] and scf.closed
        assert not link.is_open

    def test_close_twice_is_harmless(self):
        link, _, cuts = make_link()
        link.open()
        link.close()
        link.close()
        assert len(cuts) == 1

    def test_context_manager_closes_on_error(self):
        link, scf, cuts = make_link()
        with pytest.raises(ValueError), link:
            raise ValueError("mid-flight exception")
        assert cuts == [scf] and scf.closed


class TestFlightFactories:
    def test_nothing_flies_without_a_connection(self):
        link, _, _ = make_link()
        with pytest.raises(LinkError, match="Not connected"):
            link.guarded_flight(REPORT, target_height_m=0.3)

    def test_hold_program_guards_drift_from_the_checked_takeoff_point(self):
        link, _, _ = make_link()
        link.open()
        flight = link.guarded_flight(REPORT, target_height_m=0.3)
        assert flight.guard.context.takeoff_xy == (0.1, 0.2)
        assert flight.guard.context.ground_z == 0.5

    def test_waypoint_missions_do_not_guard_drift(self):
        link, _, _ = make_link()
        link.open()
        flight = link.guarded_flight(REPORT, target_height_m=None, hold_position=False)
        assert flight.guard.context.takeoff_xy is None

    def test_manual_controller_uses_the_checked_ground(self):
        link, _, _ = make_link()
        link.open()
        assert link.manual(REPORT)._ground_z == 0.5


class TestCrashRecovery:
    """cflib moved the request from `cf.platform` to `cf.supervisor`; either works."""

    def test_uses_the_supervisor_when_cflib_has_one(self):
        calls: list[str] = []
        cf = SimpleNamespace(
            supervisor=SimpleNamespace(
                send_crash_recovery_request=lambda: calls.append("supervisor")),
            platform=SimpleNamespace(send_crash_recovery_request=lambda: calls.append("platform")),
        )
        DroneLink._request_crash_recovery(cf)
        assert calls == ["supervisor"]

    def test_falls_back_to_the_platform_service(self):
        calls: list[str] = []
        cf = SimpleNamespace(
            platform=SimpleNamespace(send_crash_recovery_request=lambda: calls.append("platform")))
        DroneLink._request_crash_recovery(cf)
        assert calls == ["platform"]

    def test_a_cflib_without_either_does_not_raise(self):
        DroneLink._request_crash_recovery(SimpleNamespace())


class TestHealthTest:
    def test_a_failing_battery_half_still_returns_the_motor_result(self, monkeypatch):
        from cropwatcher.flight.checks import PropTestResult

        link, _, _ = make_link()
        motors = PropTestResult((1, 2, 3, 4), ())
        monkeypatch.setattr(link, "prop_test", lambda: motors)

        def broken():
            raise TimeoutError

        monkeypatch.setattr(link, "battery_test", broken)
        result = link.health_test()
        assert result.motors is motors
        assert result.battery is None
        assert "did not report" in result.battery_error
        assert not result.ok

