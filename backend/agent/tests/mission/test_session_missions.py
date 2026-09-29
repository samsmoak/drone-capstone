"""A mission in the session: every refusal happens before anything arms, and a
built controller is handed the armed manual flight system and the room's fence.

The controller here is a stand-in with BUILT = True — the real body is
Hannah's (docs/handoffs/mission-controller.txt). What is under test is the
session's side of the contract.
"""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType, SimpleNamespace

import pytest

from cropwatcher.mission.controller import EventKind, MissionEvent, MissionState
from cropwatcher.mission.plan.store import PlanStore
from cropwatcher.session import Mode, Session, SessionError, State
from cropwatcher.sync.cloud import Operator
from cropwatcher.sync.outbox import Kind, Outbox
from cropwatcher.telemetry.stream import Snapshot
from tests.mission.plans import mission, room
from tests.test_session import REPORT, FakeLink, start_and_confirm, wait_for
from tests.test_sync import FakeCloud


class StandInController:
    BUILT = True

    def __init__(self, plan, flight, *, on_event, **_):
        self.plan, self.flight, self.on_event = plan, flight, on_event
        self.state = MissionState.IDLE
        self.current_point_id: str | None = None
        self.completed_point_ids: tuple[str, ...] = ()
        self.aborted: str | None = None
        STARTED.append(self)

    def start(self):
        self.state = MissionState.HOLDING
        self.current_point_id = "P1"
        self.on_event(MissionEvent(EventKind.HOLD_STARTED, 1.0, "P1", "Holding at P1"))

    def finish(self):
        self.state = MissionState.DONE
        self.current_point_id = None
        self.completed_point_ids = ("P1", "P2")
        self.on_event(MissionEvent(EventKind.DONE, 9.0, None, "Mission complete"))

    def abort(self, reason):
        self.aborted = reason
        self.state = MissionState.ABORTED


class NotBuilt(StandInController):
    BUILT = False


STARTED: list[StandInController] = []


class PositionedLink(FakeLink):
    """The fake link, with the drone sitting at `at` — on the mission's home."""

    def __init__(self, at=(-1.0, -1.0)):
        super().__init__()
        self.at = at
        self.guard_kwargs: dict = {}

    def snapshot(self) -> Snapshot:
        return Snapshot(MappingProxyType({
            "baro.temp": 30.0, "baro.pressure": 1013.0,
            "stateEstimate.x": self.at[0], "stateEstimate.y": self.at[1],
            "stateEstimate.z": 0.012}), 1.0)

    def manual_guard(self, report, **kwargs):
        self.guard_kwargs = kwargs
        return super().manual_guard(report, **kwargs)


def make_rig(tmp_path, monkeypatch, controller=StandInController, at=(-1.0, -1.0)):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    STARTED.clear()
    cloud = FakeCloud()
    cloud.sign_in = lambda email, password: Operator("user-1", email, "Ada", "operator")
    cloud.sign_out = lambda: None
    link = PositionedLink(at)
    events: list[tuple[str, dict]] = []
    outbox = Outbox(tmp_path / "outbox")
    plans = PlanStore()
    plans.save_room(room())
    plans.save_mission(mission())
    session = Session(cloud=cloud, outbox=outbox, link_factory=lambda: link,
                      publish=lambda kind, payload: events.append((kind, payload)),
                      plans=plans, mission_controller=controller)
    rig = SimpleNamespace(session=session, link=link, outbox=outbox, events=events, plans=plans)
    start_and_confirm(rig, Mode.AUTO)
    return rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


class TestRefusedBeforeAnythingArms:
    def assert_nothing_armed(self, rig):
        assert "arm" not in rig.link.manual_controller.events
        assert rig.session.snapshot().state is State.READY

    def test_in_manual(self, rig):
        rig.session.set_mode(Mode.MANUAL)
        with pytest.raises(SessionError, match="Switch to Auto"):
            rig.session.run_mission("m1")
        self.assert_nothing_armed(rig)

    def test_an_unknown_mission(self, rig):
        with pytest.raises(SessionError, match="No mission"):
            rig.session.run_mission("nope")
        self.assert_nothing_armed(rig)

    def test_an_unsafe_mission(self, rig):
        rig.plans.save_mission(mission(id="bad", points=()))
        with pytest.raises(SessionError, match="not safe to fly"):
            rig.session.run_mission("bad")
        self.assert_nothing_armed(rig)

    def test_off_the_home_mark(self, tmp_path, monkeypatch):
        rig = make_rig(tmp_path, monkeypatch, at=(0.8, -1.0))
        with pytest.raises(SessionError, match=r"1\.80 m from this mission's home"):
            rig.session.run_mission("m1")
        self.assert_nothing_armed(rig)

    def test_over_the_battery_budget(self, rig):
        rig.session.report = dataclasses.replace(REPORT, endurance_s=10.0)
        with pytest.raises(SessionError, match="battery"):
            rig.session.run_mission("m1")
        self.assert_nothing_armed(rig)

    def test_unassisted(self, rig):
        rig.session.report = dataclasses.replace(REPORT, assisted=False)
        with pytest.raises(SessionError, match="know where it is"):
            rig.session.run_mission("m1")
        self.assert_nothing_armed(rig)

    def test_while_the_controller_is_not_built(self, tmp_path, monkeypatch):
        rig = make_rig(tmp_path, monkeypatch, controller=NotBuilt)
        with pytest.raises(SessionError, match="not built yet.*Nothing was armed"):
            rig.session.run_mission("m1")
        self.assert_nothing_armed(rig)
        assert STARTED == []


class TestFlying:
    def fly(self, rig):
        rig.session.run_mission("m1", ambient="22C")
        assert wait_for(lambda: STARTED and STARTED[0].state is MissionState.HOLDING)
        return STARTED[0]

    def test_the_manual_flight_system_is_armed_and_handed_over(self, rig):
        flying = self.fly(rig)
        assert rig.link.manual_controller.events[:2] == ["arm", "start"]
        assert flying.flight is rig.link.manual_controller
        assert flying.plan.id == "m1"
        assert rig.session.snapshot().activity == "mission"

    def test_the_guard_watches_the_rooms_own_fence(self, rig):
        self.fly(rig)
        fence = rig.link.guard_kwargs["fence"]
        assert fence(0.0, 1.4) and not fence(0.0, 1.6)   # the 3 m room, not ±2 m

    def test_the_point_being_held_stamps_the_readings(self, rig):
        self.fly(rig)
        assert rig.session.current_point_id() == "P1"

    def test_events_reach_the_app_and_the_snapshot(self, rig):
        flying = self.fly(rig)
        summary = rig.session.snapshot().mission
        assert summary["state"] == "holding" and summary["current_point_id"] == "P1"
        flying.finish()
        assert rig.session.snapshot().mission["completed_point_ids"] == ["P1", "P2"]
        assert any(kind == "mission" for kind, _ in rig.events)

    def test_the_flight_is_named_after_the_mission_and_revision(self, rig):
        self.fly(rig)
        flights = [r.payload for r in rig.outbox.pending(Kind.FLIGHT)]
        assert flights[-1]["program"] == "mission:m1@r1"

    def test_the_plan_flown_is_kept_with_the_session(self, rig):
        self.fly(rig)
        flight_id = rig.session.snapshot().flight["id"]
        kept = rig.session.history.folder / "missions" / f"{flight_id}.json"
        data = json.loads(kept.read_text())
        assert data["mission"]["id"] == "m1" and data["room"]["id"] == "lab"

    def test_flying_marks_the_revision_flown(self, rig):
        self.fly(rig)
        assert wait_for(lambda: rig.plans.mission("m1").flown_revision == 1)

    def test_a_landing_under_the_mission_ends_it_and_frees_the_session(self, rig):
        flying = self.fly(rig)
        rig.link.manual_controller.state = "landed"
        assert wait_for(lambda: rig.session.snapshot().state is State.READY)
        assert flying.aborted == "the flight ended"
        assert rig.session.mission is None
        assert rig.session.current_point_id() is None

    def test_the_audit_trail_records_start_and_end(self, rig):
        flying = self.fly(rig)
        flying.finish()
        stages = [r.payload["detail"].get("stage") for r in rig.outbox.pending(Kind.AUDIT)
                  if r.payload["action"] == "mission_run"]
        assert stages == ["start", "end"]
