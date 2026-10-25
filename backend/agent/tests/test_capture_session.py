"""A capture session (2026-10-24): the Capture page's own session — the radio
and the camera's deck only, nothing flies. Before it, the Capture page ran
Control's flight checks, and a drone that would not arm (sys.canfly=0) could
not take a picture."""

from __future__ import annotations

import json
from types import MappingProxyType, SimpleNamespace

import pytest

from dronedeck.audit import Action
from dronedeck.flight.checks import (
    CheckKey,
    CheckResult,
    ChecksFailed,
    CheckStatus,
    collect,
    run_capture_checks,
)
from dronedeck.session import CAPTURE_NO_FLIGHT, SessionError, State
from dronedeck.sync.outbox import Kind
from dronedeck.telemetry.stream import Snapshot
from tests.test_session import rig, sign_in  # noqa: F401

WILL_NOT_ARM = CheckResult(CheckKey.BATTERY, CheckStatus.FAILED,
                           "The drone will not arm (sys.canfly=0) and has not said why")


def start_capture(rig):  # noqa: F811
    sign_in(rig)
    rig.session.start("capture")
    rig.session.wait_idle()


class TestOpening:
    def test_a_drone_that_will_not_arm_can_still_capture(self, rig):  # noqa: F811
        rig.link.check_failure = WILL_NOT_ARM          # a flight check would refuse it
        start_capture(rig)
        snap = rig.session.snapshot()
        assert snap.state is State.READY and snap.session_id is not None
        assert snap.purpose == "capture"
        assert [c["key"] for c in snap.checks] == ["identity", "camera"]
        assert "does not fly" in (snap.message or "")

    def test_a_flight_session_still_runs_every_check(self, rig):  # noqa: F811
        rig.link.check_failure = WILL_NOT_ARM
        sign_in(rig)
        rig.session.start()
        rig.session.wait_idle()
        assert rig.session.snapshot().state is State.CHECKS_FAILED

    def test_no_ai_deck_refuses_the_capture_session(self, rig):  # noqa: F811
        rig.link.capture_failure = CheckResult(CheckKey.CAMERA, CheckStatus.FAILED,
                                               "This drone has no AI deck")
        start_capture(rig)
        snap = rig.session.snapshot()
        assert snap.state is State.CHECKS_FAILED and "no AI deck" in (snap.message or "")

    def test_an_unknown_purpose_is_refused(self, rig):  # noqa: F811
        sign_in(rig)
        with pytest.raises(SessionError):
            rig.session.start("joyride")


class TestNothingFlies:
    @pytest.mark.parametrize("act", [
        lambda s: s.arm_manual(),
        lambda s: s.health_test(),
        lambda s: s.confirm_area(),
        lambda s: s.run_program("hover"),
    ])
    def test_every_flight_action_is_refused(self, rig, act):  # noqa: F811
        start_capture(rig)
        with pytest.raises(SessionError, match="capture session"):
            act(rig.session)
        assert CAPTURE_NO_FLIGHT.startswith("This is a capture session")


class TestOnlyWhatIsCapturedByHand:
    def test_auto_capture_is_off_and_cannot_be_turned_on(self, rig):  # noqa: F811
        start_capture(rig)
        assert rig.session.capture_auto() is False
        with pytest.raises(SessionError, match="by hand"):
            rig.session.set_capture_auto(True)


class TestTheRecord:
    def test_the_purpose_is_in_the_history_and_the_audit(self, rig):  # noqa: F811
        start_capture(rig)
        meta = json.loads((rig.session.history.folder / "meta.json").read_text())
        assert meta["purpose"] == "capture"
        starts = [r.payload for r in rig.outbox.pending(Kind.AUDIT)
                  if r.payload["action"] == str(Action.SESSION_START)]
        assert starts and starts[-1]["detail"]["purpose"] == "capture"

    def test_ending_returns_to_flight(self, rig):  # noqa: F811
        start_capture(rig)
        rig.session.end()
        rig.session.wait_idle()
        assert rig.session.snapshot().purpose == "flight"
        assert rig.session.capture_auto() is True

    def test_retry_keeps_the_light_checks(self, rig):  # noqa: F811
        rig.link.check_failure = WILL_NOT_ARM
        start_capture(rig)
        rig.session.retry()
        rig.session.wait_idle()
        assert rig.session.snapshot().state is State.READY
        assert rig.link.capture_runs == 2 and rig.link.checks_runs == 0


class TestTheRoute:
    def test_start_with_a_purpose(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from dronedeck.api import rest
        from dronedeck.api.tokens import HEADER

        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        asked: list[str] = []
        monkeypatch.setattr(rest.agent.session, "start",
                            lambda purpose="flight": asked.append(purpose))
        client = TestClient(rest.app)
        h = {HEADER: rest.agent.token}
        capture = client.post("/session/start", json={"purpose": "capture"}, headers=h)
        assert capture.status_code == 200
        assert client.post("/session/start", headers=h).status_code == 200
        assert asked == ["capture", "flight"]
        assert client.post("/session/start", json={"purpose": "x"}, headers=h).status_code == 422


class FakeParams:
    def __init__(self, ai: str | None) -> None:
        self.ai = ai

    def get_value(self, name: str) -> str:
        if self.ai is None:
            raise KeyError(name)
        return self.ai


def fake_cf(ai: str | None):
    return SimpleNamespace(param=FakeParams(ai))


def snap(**values) -> Snapshot:
    return Snapshot(MappingProxyType(values), 1.0)


class TestRunCaptureChecks:
    def run(self, cf, values, monkeypatch):
        from dronedeck.flight import checks
        monkeypatch.setattr(checks, "read_hardware_id", lambda _cf: "cf-lab")
        steps: list[CheckResult] = []
        report = collect(run_capture_checks(cf, lambda: snap(**values), clock=lambda: 1.0,
                                            sleep=lambda _s: None), steps.append)
        return report, [s for s in steps if s.status is not CheckStatus.RUNNING]

    def test_only_the_radio_and_the_deck_never_the_flight(self, monkeypatch):
        report, steps = self.run(fake_cf("1"), {"pm.vbat": 3.87}, monkeypatch)
        assert [s.key for s in steps] == [CheckKey.IDENTITY, CheckKey.TELEMETRY,
                                          CheckKey.BATTERY, CheckKey.CAMERA]
        assert all(s.status is CheckStatus.PASSED for s in steps)
        assert "information only" in steps[2].detail
        assert report.ai_deck is True and report.vbat == pytest.approx(3.87)

    def test_no_ai_deck_fails(self, monkeypatch):
        with pytest.raises(ChecksFailed):
            self.run(fake_cf("0"), {"pm.vbat": 3.9}, monkeypatch)

    def test_an_unreadable_deck_is_a_warning_not_a_refusal(self, monkeypatch):
        _, steps = self.run(fake_cf(None), {}, monkeypatch)
        assert steps[-1].key is CheckKey.CAMERA and steps[-1].status is CheckStatus.WARNING
        assert steps[2].status is CheckStatus.WARNING          # no battery reading
