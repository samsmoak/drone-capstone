"""The rooms-and-missions routes: behind the token, honest about problems, and
refusing in words."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cropwatcher.api import rest
from cropwatcher.api.tokens import HEADER
from cropwatcher.mission.plan.geofence import Geofence
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


def test_from_drone_needs_the_token(api):
    assert api.get("/missions/m1/from-drone").status_code == 401


def test_from_drone_with_no_drone_is_the_mission_as_saved(api):
    api.post("/rooms", json=room().to_dict(), headers=token())
    api.post("/missions", json=mission(end_point_id="P2").to_dict(), headers=token())
    body = api.get("/missions/m1/from-drone", headers=token()).json()
    assert body["position"] is None
    assert body["mission"]["home"] == [-1.0, -1.0] and body["mission"]["valid"] is True


def test_from_drone_checks_the_path_from_the_drones_own_position(api, monkeypatch):
    api.post("/rooms", json=room().to_dict(), headers=token())
    api.post("/missions", json=mission().to_dict(), headers=token())
    # The path moves +0.5 in x with the drone; home → P1 then runs past the table.
    monkeypatch.setattr(rest.agent.session, "position", lambda: (-0.5, -1.0, 0.0))
    body = api.get("/missions/m1/from-drone", headers=token()).json()
    assert body["position"] == [-0.5, -1.0]
    assert body["mission"]["valid"] is False
    assert any(p["where"] == "home → P1" for p in body["mission"]["problems"])


def test_from_drone_for_an_unknown_mission_is_a_404(api):
    assert api.get("/missions/nope/from-drone", headers=token()).status_code == 404


def test_saving_a_mission_with_no_points_is_a_422_in_words(api):
    api.post("/rooms", json=room().to_dict(), headers=token())
    response = api.post("/missions", json=mission(points=()).to_dict(), headers=token())
    assert response.status_code == 422
    assert "at least one inspection point" in response.json()["detail"]


def test_from_drone_names_the_plan_that_will_fly_and_every_move(api):
    covered = room().edited(coverage=Geofence.rectangle(-2.0, -2.0, 1.0, 2.0))
    api.post("/rooms", json=covered.to_dict(), headers=token())
    api.post("/missions", json=mission().to_dict(), headers=token())
    body = api.get("/missions/m1/from-drone", headers=token()).json()
    assert {m["point_id"] for m in body["moves"]} == {"P2", "P3"}
    assert body["unfitted"] == []
    assert max(x for x, _ in body["space"]["vertices"]) == pytest.approx(1.0)


@pytest.mark.parametrize("method, path", [
    ("get", "/rooms/lab/coverage"), ("post", "/rooms/lab/survey/start"),
    ("get", "/survey"), ("post", "/survey/stop"),
])
def test_the_coverage_routes_need_the_token(api, method, path):
    response = getattr(api, method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 401


def test_a_room_with_nothing_measured_or_predicted_says_so(api):
    api.post("/rooms", json=room().to_dict(), headers=token())
    body = api.get("/rooms/lab/coverage", headers=token()).json()
    assert body == {"measured": None, "predicted": None, "survey": {"active": False}}


def test_a_survey_without_a_drone_is_a_409_in_words(api):
    api.post("/rooms", json=room().to_dict(), headers=token())
    response = api.post("/rooms/lab/survey/start", headers=token())
    assert response.status_code == 409 and "Connect the drone" in response.json()["detail"]


def test_an_unsaved_draft_is_fitted_without_being_saved(api):
    covered = room().edited(coverage=Geofence.rectangle(-2.0, -2.0, 1.0, 2.0))
    body = api.post("/missions/fit", json={"mission": mission().to_dict(),
                                           "room": covered.to_dict()}, headers=token()).json()
    assert {m["point_id"] for m in body["moves"]} == {"P2", "P3"}
    assert api.get("/missions", headers=token()).json() == []


def test_a_malformed_draft_is_a_422(api):
    response = api.post("/missions/fit", json={"mission": {}}, headers=token())
    assert response.status_code == 422 and "could not be read" in response.json()["detail"]
