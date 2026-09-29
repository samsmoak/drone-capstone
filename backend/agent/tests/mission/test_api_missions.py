"""The rooms-and-missions routes: behind the token, honest about problems, and
refusing in words."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cropwatcher.api import rest
from cropwatcher.api.tokens import HEADER
from cropwatcher.session import Session
from cropwatcher.sync.cloud import Operator
from cropwatcher.sync.outbox import Outbox
from tests.mission.plans import mission, room
from tests.test_session import FakeLink
from tests.test_sync import FakeCloud


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CROPWATCHER_STANDBY", "0")
    cloud = FakeCloud()
    cloud.sign_in = lambda email, password: Operator("user-1", email, "Ada", "operator")
    session = Session(cloud=cloud, outbox=Outbox(tmp_path / "outbox"),
                      link_factory=FakeLink, publish=rest.agent.hub.publish)
    monkeypatch.setattr(rest.agent, "session", session)
    return TestClient(rest.app)


def token() -> dict[str, str]:
    return {HEADER: rest.agent.token}


@pytest.mark.parametrize("method, path", [
    ("get", "/rooms"), ("get", "/missions"), ("get", "/plan/limits"),
    ("post", "/rooms"), ("post", "/missions"), ("post", "/missions/validate"),
    ("post", "/missions/m1/delete"), ("post", "/session/mission"),
])
def test_every_route_needs_the_token(api, method, path):
    response = getattr(api, method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 401


def test_a_room_then_a_mission_round_trip_with_their_problems(api):
    saved = api.post("/rooms", json=room().to_dict(), headers=token())
    assert saved.status_code == 200
    body = saved.json()
    assert body["id"] == "lab" and body["valid"] is True
    assert body["outer"] == {"vertices": [[-2.0, -2.0], [2.0, -2.0], [2.0, 2.0], [-2.0, 2.0]],
                             "measured": False}
    assert [p["code"] for p in body["problems"]] == ["coverage_not_measured"]

    made = api.post("/missions", json=mission().to_dict(), headers=token()).json()
    assert made["valid"] is True
    assert made["estimated_duration_s"] > sum(p["hold_s"] for p in made["points"])
    listed = api.get("/missions", headers=token()).json()
    assert [m["id"] for m in listed] == ["m1"]


def test_an_unsafe_draft_is_reported_not_refused(api):
    api.post("/rooms", json=room().to_dict(), headers=token())
    draft = mission(home=(0.0, 0.0)).to_dict()            # home on the table
    checked = api.post("/missions/validate", json={"mission": draft}, headers=token()).json()
    assert checked["valid"] is False
    assert any(p["where"] == "home" for p in checked["problems"])


def test_a_draft_room_can_be_checked_before_it_is_saved(api):
    checked = api.post("/missions/validate", headers=token(),
                       json={"mission": mission().to_dict(), "room": room().to_dict()}).json()
    assert checked["valid"] is True


def test_a_malformed_plan_is_a_422_in_words(api):
    response = api.post("/rooms", headers=token(),
                        json={"id": "r", "name": "R", "geofence": {"vertices": [[0, 0], [1, 1]]}})
    assert response.status_code == 422
    assert "at least 3" in response.json()["detail"]


def test_a_room_in_use_is_a_409(api):
    api.post("/rooms", json=room().to_dict(), headers=token())
    api.post("/missions", json=mission().to_dict(), headers=token())
    response = api.post("/rooms/lab/delete", headers=token())
    assert response.status_code == 409
    assert "uses this room" in response.json()["detail"]


def test_a_missing_mission_is_a_404(api):
    assert api.get("/missions/nope", headers=token()).status_code == 404


def test_flying_a_mission_before_the_checks_is_refused_in_words(api):
    api.post("/auth/sign-in", json={"email": "a@b.c", "password": "x"}, headers=token())
    response = api.post("/session/mission", json={"mission_id": "m1"}, headers=token())
    assert response.status_code == 409
    assert "checks" in response.json()["detail"]


def test_the_limits_the_editor_clamps_to(api):
    limits = api.get("/plan/limits", headers=token()).json()
    assert limits["min_hold_s"] == 5.0
    assert limits["z_max_m"] == 1.0
    assert limits["default_clearance_m"] == 0.25
