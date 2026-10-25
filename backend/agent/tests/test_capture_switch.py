"""The auto-capture switch and capturing by hand — the session and the API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dronedeck.api import rest
from dronedeck.api.tokens import HEADER
from dronedeck.audit import Action
from dronedeck.camera import TestPattern
from dronedeck.camera.recording import Recorder
from dronedeck.session import Mode, Session
from dronedeck.sync.cloud import Operator
from dronedeck.sync.outbox import Kind, Outbox
from tests.test_session import FakeLink, rig, sign_in, start_and_confirm  # noqa: F401
from tests.test_sync import FakeCloud


class TestTheSwitch:
    def test_on_by_default_in_both_modes(self, rig):  # noqa: F811
        sign_in(rig)
        assert rig.session.capture_auto() is True
        assert rig.session.snapshot().capture == {"auto": True, "chosen": False}
        rig.session.set_mode(Mode.AUTO)
        assert rig.session.capture_auto() is True

    def test_off_holds_until_the_session_ends(self, rig):  # noqa: F811
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.set_capture_auto(False)
        assert rig.session.snapshot().capture == {"auto": False, "chosen": True}
        rig.session.end()
        rig.session.wait_idle()
        assert rig.session.capture_auto() is True
        assert rig.session.snapshot().capture == {"auto": True, "chosen": False}

    def test_it_is_on_the_audit_trail(self, rig):  # noqa: F811
        start_and_confirm(rig, Mode.MANUAL)
        rig.session.set_capture_auto(False)
        actions = [r.payload["action"] for r in rig.outbox.pending(Kind.AUDIT)]
        assert str(Action.CAPTURE_SET) in actions

    def test_it_needs_someone_signed_in(self, rig):  # noqa: F811
        from dronedeck.session import SessionError
        with pytest.raises(SessionError):
            rig.session.set_capture_auto(False)


class TestTheRoutes:
    @pytest.fixture
    def api(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CROPWATCHER_STANDBY", "0")
        cloud = FakeCloud()
        cloud.sign_in = lambda email, password: Operator("user-1", email, "Ada", "operator")
        session = Session(cloud=cloud, outbox=Outbox(tmp_path / "outbox"),
                          link_factory=FakeLink, publish=rest.agent.hub.publish)
        recorder = Recorder(Outbox(tmp_path / "frames-outbox"),
                            auto=lambda: session.capture_auto())
        monkeypatch.setattr(rest.agent, "session", session)
        monkeypatch.setattr(rest.agent, "recorder", recorder)
        monkeypatch.setattr(rest.agent, "camera", TestPattern())
        return SimpleNamespace(client=TestClient(rest.app), root=tmp_path,
                               session=session, recorder=recorder)

    def headers(self):
        return {HEADER: rest.agent.token}

    @pytest.mark.parametrize("path, body", [
        ("/session/capture", {"auto": False}), ("/camera/capture", None),
    ])
    def test_both_need_the_token(self, api, path, body):
        assert api.client.post(path, json=body).status_code == 401

    def test_the_switch(self, api):
        api.session.sign_in("ada@example.com", "pw")
        body = api.client.post("/session/capture", json={"auto": False},
                               headers=self.headers()).json()
        assert body["capture"] == {"auto": False, "chosen": True}

    def test_a_capture_outside_a_session_is_refused_in_words(self, api):
        response = api.client.post("/camera/capture", headers=self.headers())
        assert response.status_code == 409
        assert "Start a session first" in response.json()["detail"]

    def test_a_capture_with_no_fresh_frame_is_refused(self, api, monkeypatch):
        from dronedeck.camera import NoCamera
        monkeypatch.setattr(rest.agent, "camera", NoCamera())
        api.recorder.start("s1", api.root / "s1")
        response = api.client.post("/camera/capture", headers=self.headers())
        assert response.status_code == 409
        assert "no fresh frame" in response.json()["detail"]

    def test_a_capture_is_saved_labelled_and_listed(self, api):
        api.session.sign_in("ada@example.com", "pw")
        api.session.set_capture_auto(False)            # auto off: manual still saves
        recording = api.recorder.start("s1", api.root / "s1")
        try:
            api.recorder.on_frame(b"auto", "image/png", 2, 1)       # not kept: auto off
            body = api.client.post("/camera/capture", headers=self.headers()).json()
            assert body["source"] == "manual" and body["upload"] is True
            listed = api.client.get("/camera/recording/frames?source=manual",
                                    headers=self.headers()).json()["frames"]
            assert [f["seq"] for f in listed] == [body["seq"]]
            summary = api.client.get("/camera/recording", headers=self.headers()).json()
            assert summary["manual"] == 1 and summary["auto"] is False
            assert recording.count == 1
        finally:
            api.recorder.stop()

    def test_an_unknown_source_is_a_422(self, api):
        response = api.client.get("/camera/recording/frames?source=other",
                                  headers=self.headers())
        assert response.status_code == 422


class TestHistory:
    """A session's captures stay findable after it ends — from its files."""

    def test_manual_captures_of_an_ended_session(self, tmp_path):
        from dronedeck import history
        from dronedeck.camera.recording import FrameRecording
        rec = FrameRecording("s9", tmp_path / "s9")
        rec.add(b"auto", "image/png", 2, 1)
        rec.add_manual(b"by-hand", "image/jpeg", 2, 1)
        listed = history.session_frames("s9", "manual", root=tmp_path)
        assert [(f["seq"], f["source"], f["upload"]) for f in listed] == [(2, "manual", True)]
        assert len(history.session_frames("s9", root=tmp_path)) == 2
        found = history.session_frame("s9", 2, root=tmp_path)
        assert found is not None and found[0].read_bytes() == b"by-hand"
        assert found[1] == "image/jpeg"
        assert history.session_frame("s9", 7, root=tmp_path) is None

    def test_a_path_in_the_id_is_refused(self, tmp_path):
        from dronedeck import history
        with pytest.raises(ValueError):
            history.session_frames("../etc", root=tmp_path)

    def test_an_index_from_before_source_existed_reads_as_auto(self, tmp_path):
        from dronedeck.camera.recording import read_index
        folder = tmp_path / "old"
        folder.mkdir()
        (folder / "frames.csv").write_text(
            "seq,recorded_at,t_s,file,width,height,bytes,x_m,y_m,z_m,upload,point_id\n"
            "1,2026-09-24T00:00:00+00:00,0.000,frames/000001.png,324,244,9,,,,1,\n")
        assert read_index(folder)[0]["source"] == "auto"
        assert read_index(folder, "manual") == []

    def test_the_routes(self, tmp_path, monkeypatch):
        from dronedeck.camera.recording import FrameRecording
        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        from dronedeck.history import sessions_dir
        rec = FrameRecording("s9", sessions_dir() / "s9")
        rec.add_manual(b"by-hand", "image/png", 2, 1)
        client = TestClient(rest.app)
        headers = {HEADER: rest.agent.token}
        listed = client.get("/history/sessions/s9/frames?source=manual", headers=headers)
        assert [f["seq"] for f in listed.json()["frames"]] == [1]
        frame = client.get("/history/sessions/s9/frames/1", headers=headers)
        assert frame.content == b"by-hand" and frame.headers["cache-control"] == "no-store"
        assert client.get("/history/sessions/s9/frames/5", headers=headers).status_code == 404
        assert client.get("/history/sessions/s9/frames").status_code == 401
