"""Which web pages may talk to the agent.

The agent listens on localhost, which keeps other *machines* out but not other
*websites*: every page the operator has open can reach 127.0.0.1. WebSockets
are not covered by CORS, so without an Origin check any site could open the
manual-control socket and fly the drone.

Every refusal here is paired with the permitted path. A test that only checks
denial also passes when the endpoint is simply broken.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cropwatcher.api import rest

SITE = "https://drone-capstone.vercel.app"
EVIL = "https://evil.example"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(rest.core, "scan", lambda *a, **k: [])
    rest.state.release()
    rest.state.manual = None
    yield TestClient(rest.app)
    rest.state.release()


class TestManualSocketOrigin:
    def test_refuses_an_unknown_site(self, client):
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            client.websocket_connect("/ws/manual", headers={"origin": EVIL}) as ws,
        ):
            ws.receive_json()
        assert closed.value.code == 1008

    def test_refuses_before_touching_the_radio(self, client, monkeypatch):
        def must_not_connect(*_a, **_k):
            raise AssertionError("radio opened for a refused origin")

        monkeypatch.setattr(rest.core, "connect", must_not_connect)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/manual", headers={"origin": EVIL}) as ws,
        ):
            ws.receive_json()

    @pytest.mark.parametrize("origin", [SITE, "tauri://localhost", "http://tauri.localhost"])
    def test_accepts_known_origins(self, client, origin):
        # Busy, so the accepted socket answers without needing a radio.
        rest.state.claim("a test")
        with client.websocket_connect("/ws/manual", headers={"origin": origin}) as ws:
            assert "busy" in ws.receive_json()["error"]

    def test_accepts_a_non_browser_client(self, client):
        """No Origin means a local script or the CLI, not a web page."""
        rest.state.claim("a test")
        with client.websocket_connect("/ws/manual") as ws:
            assert "busy" in ws.receive_json()["error"]

    def test_extra_origin_from_environment(self, client, monkeypatch):
        monkeypatch.setenv("CROPWATCHER_ALLOWED_ORIGINS", "https://preview.example/, ")
        rest.state.claim("a test")
        with client.websocket_connect(
            "/ws/manual", headers={"origin": "https://preview.example"}
        ) as ws:
            assert "busy" in ws.receive_json()["error"]


class TestCors:
    def test_site_can_read_health(self, client):
        response = client.get("/health", headers={"origin": SITE})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == SITE

    def test_unknown_site_gets_no_cors_grant(self, client):
        response = client.get("/health", headers={"origin": EVIL})
        assert "access-control-allow-origin" not in response.headers

    def test_private_network_preflight_is_answered(self, client):
        """Chrome will not let a public https page reach 127.0.0.1 without it."""
        response = client.options(
            "/health",
            headers={
                "origin": SITE,
                "access-control-request-method": "GET",
                "access-control-request-private-network": "true",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-private-network") == "true"

    def test_site_cannot_preflight_a_flight(self, client):
        """GET only: a browser tab must never be able to start a flight."""
        response = client.options(
            "/flight/mission",
            headers={
                "origin": SITE,
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type",
            },
        )
        assert response.status_code == 400
