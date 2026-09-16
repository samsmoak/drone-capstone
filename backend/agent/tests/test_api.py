"""The agent's HTTP surface.

Tested with FastAPI's TestClient and no drone: the endpoints that matter here
are the ones that must answer sensibly when hardware is absent or a request is
malformed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cropwatcher.api import rest
from cropwatcher.flight.missions import hover_mission, lawnmower_mission


@pytest.fixture
def client(monkeypatch):
    # No radio in CI, so scanning finds nothing. That is a valid state the API
    # must handle, not an error.
    monkeypatch.setattr(rest.core, "scan", lambda *a, **k: [])
    rest.state.release()
    rest.state.manual = None
    return TestClient(rest.app)


class TestHealth:
    def test_health_answers_without_a_drone(self, client):
        """The web app polls this to decide whether the agent is installed, so
        it must never depend on hardware."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_status_reports_no_drone(self, client):
        body = client.get("/status").json()
        assert body["drone_connected"] is False
        assert body["busy"] is False


class TestMissionValidation:
    def test_dry_run_validates_without_hardware(self, client):
        mission = lawnmower_mission(1.0, 1.0, 0.5, 0.4)
        response = client.post("/flight/mission", json={
            "plan": mission.to_dict(), "fence_m": 2.0, "dry_run": True,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["validated"] is True
        assert body["flown"] is False
        assert body["waypoints"] == len(mission.waypoints)

    def test_malformed_plan_is_422_not_500(self, client):
        response = client.post("/flight/mission", json={
            "plan": {"waypoints": [{"x": "not a number"}]}, "dry_run": True,
        })
        assert response.status_code == 422
        assert "malformed plan" in response.json()["detail"]

    def test_unsafe_plan_is_refused_with_the_reason(self, client):
        mission = lawnmower_mission(20.0, 20.0, 1.0, 0.5)
        response = client.post("/flight/mission", json={
            "plan": mission.to_dict(), "fence_m": 1.0, "dry_run": True,
        })
        assert response.status_code == 422
        assert "outside the permitted" in response.json()["detail"]

    def test_empty_plan_is_rejected(self, client):
        response = client.post("/flight/mission", json={
            "plan": {"waypoints": []}, "dry_run": True,
        })
        assert response.status_code == 422

    def test_absurd_fence_is_rejected_by_the_schema(self, client):
        """Pydantic bounds stop a nonsense request before any flight code runs."""
        response = client.post("/flight/mission", json={
            "plan": hover_mission(0.5, 1.0).to_dict(), "fence_m": 9999, "dry_run": True,
        })
        assert response.status_code == 422


class TestHoverBounds:
    @pytest.mark.parametrize("height", [0, -1, 99])
    def test_implausible_heights_are_rejected(self, height):
        """A 99 m ceiling on an indoor micro-drone is a typo, not a request."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            rest.HoverRequest(height_m=height)

    @pytest.mark.parametrize("secs", [0, -5, 10_000])
    def test_implausible_durations_are_rejected(self, secs):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            rest.HoverRequest(secs=secs)

    def test_sensible_values_are_accepted(self):
        request = rest.HoverRequest(height_m=0.5, secs=30)
        assert request.height_m == 0.5


class TestBusyState:
    def test_second_flight_is_refused_while_one_is_running(self, client):
        """One drone, so one flight. A second must be refused, not queued —
        queueing would arm it the moment the first landed, unattended."""
        from fastapi import HTTPException

        rest.state.claim("mission: first")
        try:
            with pytest.raises(HTTPException) as e:
                rest.state.claim("mission: second")
            assert e.value.status_code == 409
            # The message must name what is holding the drone, so the UI can
            # tell the operator rather than just saying "busy".
            assert "mission: first" in str(e.value.detail)
        finally:
            rest.state.release()

    def test_release_clears_the_claim(self, client):
        rest.state.claim("something")
        rest.state.release()
        assert rest.state.busy is False
        rest.state.claim("something else")   # would raise if still held
        rest.state.release()


class TestStop:
    def test_stop_always_succeeds(self, client):
        """A stop that can fail is not a stop."""
        response = client.post("/flight/stop")
        assert response.status_code == 200
        assert response.json()["stopped"] is True

    def test_stop_works_when_nothing_is_running(self, client):
        assert client.post("/flight/stop").status_code == 200

    def test_stop_panics_the_manual_controller(self, client):
        from cropwatcher.api.manual import ManualController
        from tests.test_manual import FakeCommander

        controller = ManualController(FakeCommander())
        rest.state.manual = controller
        try:
            client.post("/flight/stop")
            assert controller.stats.panics == 1
        finally:
            rest.state.manual = None


class TestBindingDefault:
    def test_defaults_to_localhost(self):
        """This API can arm a drone and has no auth of its own."""
        assert rest.DEFAULT_HOST == "127.0.0.1"
