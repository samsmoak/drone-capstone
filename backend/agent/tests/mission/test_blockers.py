"""Every reason a mission cannot start, and the flight that says it flies when
it does not (2026-10-05: three re-flights with the supervisor LOCKED, thrust 0
the whole way, reported as started and landed)."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from cropwatcher import session as session_module
from cropwatcher.session import Mode, SessionError, State
from cropwatcher.telemetry.stream import Snapshot
from tests.mission.test_session_missions import POSITIONED, PositionedLink, make_rig

#: supervisor.info as read on the lab drone: 542 flying, 580 LOCKED.
FLYING_BITS, LOCKED_BITS = 542, 580


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def with_supervisor(rig, bits):
    base = PositionedLink.snapshot(rig.link)
    rig.link.snapshot = lambda: Snapshot(MappingProxyType({**base.values,
                                                           "supervisor.info": bits}), 1.0)


class TestTheList:
    def test_a_ready_mission_has_no_blockers(self, rig):
        assert rig.session.mission_blockers("m1") == []

    def test_a_locked_drone_is_named_with_what_to_do(self, rig):
        with_supervisor(rig, LOCKED_BITS)
        found = rig.session.mission_blockers("m1")
        assert [b["code"] for b in found] == ["motors"]
        assert "LOCKED" in found[0]["message"]
        assert "Reset drone" in found[0]["fix"]

    def test_every_reason_is_listed_not_only_the_first(self, rig):
        with_supervisor(rig, LOCKED_BITS)
        rig.session._set(mode=Mode.MANUAL)
        codes = [b["code"] for b in rig.session.mission_blockers("m1")]
        assert codes[:2] == ["mode", "motors"]

    def test_start_refuses_on_the_first_and_arms_nothing(self, rig):
        with_supervisor(rig, LOCKED_BITS)
        with pytest.raises(SessionError, match="locked its motors"):
            rig.session.run_mission("m1")
        assert "arm" not in rig.link.manual_controller.events
        assert rig.session.snapshot().state is State.READY

    def test_a_flying_supervisor_is_not_a_blocker(self, rig):
        with_supervisor(rig, FLYING_BITS)
        assert rig.session.mission_blockers("m1") == []


class TestMotorsThatDoNotSpin:
    def snap(self, **values):
        return Snapshot(MappingProxyType({**POSITIONED, **values}), 1.0)

    def test_locked_is_said_at_once(self):
        locked = self.snap(**{"supervisor.info": LOCKED_BITS})
        why = session_module._motors_not_spinning(locked, 0.0)
        assert why is not None and "LOCKED" in why and "Nothing flew" in why

    def test_zero_on_every_motor_past_the_grace_is_said(self):
        zeros = {f"motor.m{i}": 0 for i in range(1, 5)}
        assert session_module._motors_not_spinning(self.snap(**zeros), 0.5) is None
        why = session_module._motors_not_spinning(
            self.snap(**zeros), session_module.MOTORS_START_GRACE_S)
        assert why is not None and "all four read zero" in why

    def test_spinning_motors_are_fine(self):
        running = {f"motor.m{i}": 45000 for i in range(1, 5)}
        assert session_module._motors_not_spinning(
            self.snap(**{**running, "supervisor.info": FLYING_BITS}), 5.0) is None
