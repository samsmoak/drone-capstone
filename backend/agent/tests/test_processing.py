"""The DPP switch: flights processed by the data pipeline when they land, one
at a time, in a process of their own — chosen per session, on by default in
Auto and off in Manual."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cropwatcher import history
from cropwatcher.api import rest
from cropwatcher.api.tokens import HEADER
from cropwatcher.processing import JobState, ProcessingQueue, default_command
from cropwatcher.session import Mode, Session, SessionError, State
from cropwatcher.sync.cloud import Operator
from cropwatcher.sync.outbox import Kind, Outbox
from tests.test_session import FakeLink, sign_in, start_and_confirm, wait_for
from tests.test_sync import FakeCloud


def succeeds(_flight_id: str) -> list[str]:
    return [sys.executable, "-c", "print('saved')"]


def fails(flight_id: str) -> list[str]:
    return [sys.executable, "-c",
            f"print('  No readings for flight {flight_id} on this computer.'); "
            f"raise SystemExit(2)"]


def hangs(_flight_id: str) -> list[str]:
    return [sys.executable, "-c", "import time; time.sleep(30)"]


class TestTheQueue:
    def test_a_flight_runs_and_is_done(self):
        seen: list[str] = []
        q = ProcessingQueue(command=succeeds, on_change=lambda job: seen.append(job.state))
        q.submit("f1")
        assert q.wait_idle()
        assert q.job("f1").state == JobState.DONE and q.job("f1").error is None
        # The worker marks the job done, THEN notifies: wait_idle can return in
        # between, so wait for the notification itself (this raced ~1 run in 3).
        assert wait_for(lambda: seen[-1:] == ["done"])
        assert seen == ["queued", "running", "done"]

    def test_a_failure_says_why_in_the_pipelines_own_words(self):
        q = ProcessingQueue(command=fails)
        q.submit("f1")
        assert q.wait_idle()
        job = q.job("f1")
        assert job.state == JobState.FAILED
        assert job.error == "No readings for flight f1 on this computer."

    def test_a_stuck_pipeline_is_stopped(self):
        q = ProcessingQueue(command=hangs, timeout_s=0.3)
        q.submit("f1")
        assert q.wait_idle(10)
        assert q.job("f1").state == JobState.FAILED
        assert "longer than" in q.job("f1").error

    def test_a_pipeline_that_cannot_start_is_a_failure_not_a_crash(self):
        q = ProcessingQueue(command=lambda _: ["/no/such/program"])
        q.submit("f1")
        assert q.wait_idle()
        assert "could not be started" in q.job("f1").error

    def test_flights_run_one_at_a_time_in_order(self):
        order: list[str] = []
        q = ProcessingQueue(command=succeeds, on_change=lambda job: job.state == "running"
                            and order.append(job.flight_id))
        for fid in ("a", "b", "c"):
            q.submit(fid)
        assert q.wait_idle()
        assert order == ["a", "b", "c"]

    def test_queuing_one_already_waiting_changes_nothing(self):
        q = ProcessingQueue(command=hangs, timeout_s=5)
        first = q.submit("f1")
        assert q.submit("f1") is first
        q.close()

    @pytest.mark.parametrize("bad", ["", "../x", "a/b", "x" * 65, "a b"])
    def test_an_id_that_could_leave_the_folder_is_refused(self, bad):
        with pytest.raises(ValueError):
            ProcessingQueue(command=succeeds).submit(bad)

    def test_the_command_is_the_cli_frozen_or_not(self, monkeypatch):
        assert default_command("f1")[-3:] == ["process", "--flight", "f1"]
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert default_command("f1") == [sys.executable, "process", "--flight", "f1"]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    cloud = FakeCloud()
    cloud.sign_in = lambda email, password: Operator("user-1", email, "Ada", "operator")
    cloud.sign_out = lambda: None
    link = FakeLink()
    events: list[tuple[str, dict]] = []
    outbox = Outbox(tmp_path / "outbox")
    queue = ProcessingQueue(command=succeeds)
    session = Session(cloud=cloud, outbox=outbox, link_factory=lambda: link,
                      publish=lambda kind, payload: events.append((kind, payload)),
                      processing=queue)
    return SimpleNamespace(session=session, link=link, outbox=outbox, events=events,
                           queue=queue)


def fly_manual_and_land(rig) -> str:
    rig.session.arm_manual()
    flight_id = rig.session.snapshot().flight["id"]
    rig.link.manual_controller.state = "landed"
    assert wait_for(lambda: rig.session.snapshot().state is State.READY)
    rig.link.manual_controller.state = "idle"
    return flight_id


def flight_line(rig, flight_id):
    meta = json.loads((rig.session.history.folder / "meta.json").read_text())
    return next(f for f in meta["flights"] if f["id"] == flight_id)


class TestTheSwitch:
    def test_off_by_default_in_manual_on_by_default_in_auto(self, rig):
        sign_in(rig)
        assert rig.session.snapshot().processing["on"] is False
        rig.session.set_mode(Mode.AUTO)
        assert rig.session.snapshot().processing == {"on": True, "chosen": False, "jobs": [],
                                                      "last_flight_id": None}

    def test_a_manual_flight_with_it_off_is_not_processed(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        flight_id = fly_manual_and_land(rig)
        assert rig.queue.job(flight_id) is None
        assert flight_line(rig, flight_id)["processing"] is None
        assert rig.session.snapshot().processing["last_flight_id"] == flight_id

    def test_turned_on_a_manual_flight_is_processed_when_it_lands(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.set_processing(True)
        flight_id = fly_manual_and_land(rig)
        assert rig.queue.wait_idle()
        assert rig.queue.job(flight_id).state == JobState.DONE
        assert wait_for(lambda: flight_line(rig, flight_id)["processing"] == "done")
        jobs = rig.session.snapshot().processing["jobs"]
        assert jobs[0]["flight_id"] == flight_id and jobs[0]["state"] == "done"
        assert any(kind == "processing" for kind, _ in rig.events)

    def test_the_choice_is_read_as_a_flight_begins(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.arm_manual()
        flight_id = rig.session.snapshot().flight["id"]
        assert flight_line(rig, flight_id)["processing"] is None
        rig.session.set_processing(True)                 # mid-flight: for the next one
        rig.link.manual_controller.state = "landed"
        assert wait_for(lambda: rig.session.snapshot().state is State.READY)
        assert rig.queue.job(flight_id) is None

    def test_the_operators_choice_outlasts_a_mode_change(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.set_processing(False)
        rig.session.set_mode(Mode.AUTO)
        assert rig.session.snapshot().processing["on"] is False
        assert rig.session.snapshot().processing["chosen"] is True

    def test_the_choice_is_per_session(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.set_processing(True)
        rig.session.end()
        assert rig.session.snapshot().processing["on"] is False
        assert rig.session.snapshot().processing["chosen"] is False

    def test_it_is_in_the_audit_trail(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.set_processing(True)
        actions = [r.payload for r in rig.outbox.pending(Kind.AUDIT)]
        assert any(a["action"] == "processing_set" and a["detail"] == {"on": True,
                                                                       "mode": "manual"}
                   for a in actions)

    def test_signed_out_it_cannot_be_set(self, rig):
        with pytest.raises(SessionError, match="Sign in"):
            rig.session.set_processing(True)

    def test_a_flight_can_be_processed_by_hand_afterwards(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        flight_id = fly_manual_and_land(rig)
        rig.session.process_flight(flight_id)
        assert rig.queue.wait_idle()
        assert wait_for(lambda: flight_line(rig, flight_id)["processing"] == "done")

    def test_a_flight_still_recording_cannot_be_processed(self, rig):
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.arm_manual()
        with pytest.raises(SessionError, match="still recording"):
            rig.session.process_flight(rig.session.snapshot().flight["id"])


def test_a_closed_sessions_flight_is_recorded_in_its_file(tmp_path):
    folder = tmp_path / "s1"
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps({"flights": [{"id": "f1"}, {"id": "f2"}]}))
    assert history.set_flight_processing("f2", "failed", "why", root=tmp_path)
    flights = json.loads((folder / "meta.json").read_text())["flights"]
    assert flights[1]["processing"] == "failed" and flights[1]["processing_error"] == "why"
    assert "processing" not in flights[0]
    assert not history.set_flight_processing("nope", "done", root=tmp_path)


class TestTheRoutes:
    @pytest.fixture
    def api(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CROPWATCHER_STANDBY", "0")
        cloud = FakeCloud()
        cloud.sign_in = lambda email, password: Operator("user-1", email, "Ada", "operator")
        session = Session(cloud=cloud, outbox=Outbox(tmp_path / "outbox"),
                          link_factory=FakeLink, publish=rest.agent.hub.publish,
                          processing=ProcessingQueue(command=succeeds))
        monkeypatch.setattr(rest.agent, "session", session)
        return SimpleNamespace(client=TestClient(rest.app), root=tmp_path, session=session)

    def headers(self):
        return {HEADER: rest.agent.token}

    @pytest.mark.parametrize("method, path", [
        ("post", "/session/processing"), ("get", "/flights/f1/result"),
        ("post", "/flights/f1/process"),
    ])
    def test_every_route_needs_the_token(self, api, method, path):
        kwargs = {"json": {"on": True}} if method == "post" else {}
        assert getattr(api.client, method)(path, **kwargs).status_code == 401

    def test_the_switch(self, api):
        api.session.sign_in("ada@example.com", "pw")
        body = api.client.post("/session/processing", json={"on": True},
                               headers=self.headers()).json()
        assert body["processing"]["on"] is True

    def test_no_result_yet_is_a_404_in_words(self, api):
        response = api.client.get("/flights/f1/result", headers=self.headers())
        assert response.status_code == 404
        assert "has not been processed" in response.json()["detail"]

    def test_a_result_comes_back_whole(self, api):
        folder = api.root / "results" / "f1"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"flight_id": "f1", "points": []}))
        body = api.client.get("/flights/f1/result", headers=self.headers()).json()
        assert body["result"] == {"flight_id": "f1", "points": []} and body["job"] is None

    def test_an_id_that_could_leave_the_folder_is_a_404(self, api):
        response = api.client.get("/flights/..%2Fx/result", headers=self.headers())
        assert response.status_code == 404
