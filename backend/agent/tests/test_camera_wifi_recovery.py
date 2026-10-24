"""Getting the camera back on the network without restarting the drone
(2026-10-24): ask where it is, then rejoin — against a fake drone that answers
the way drone_wifi v4 and the patched ESP32 do."""

from __future__ import annotations

import threading

import pytest

from cropwatcher.camera import wifi
from cropwatcher.camera.wifi import (
    CMD_APPLY,
    CMD_KEY,
    CMD_REPORT,
    CMD_SSID,
    CODE_OK,
    CODE_UNSUPPORTED,
    Phase,
    reason_words,
)
from tests.test_camera_wifi import FakeDrone, make


class FakeV4(FakeDrone):
    """drone_wifi v4. `can_rejoin`: the deck carries bundle 2 (the patched
    ESP32). `on_network`: the deck is on the network right now."""

    def __init__(self, *, can_rejoin=True, on_network=True, version=4, reason=201, **kw):
        super().__init__(**kw)
        self.can_rejoin = can_rejoin
        self.on_network = on_network
        self.version = version
        self.reason = reason

    def _receive(self, pkt: bytes) -> None:
        cmd = pkt[0]
        if cmd == CMD_REPORT and self.flashed:
            self.sent.append(pkt)
            if self.version < 4:
                self._reply(cmd, 1)                     # v3: an unknown command
            elif not self.can_rejoin:
                self._reply(cmd, CODE_UNSUPPORTED)
            else:
                self._reply(cmd, CODE_OK)
                threading.Timer(0.05, self._report).start()
            return
        if cmd == CMD_APPLY and self.flashed and self.applied and self.can_rejoin:
            self.sent.append(pkt)
            self._reply(cmd, CODE_OK)                   # v4: a rejoin is allowed
            self.on_network = True
            threading.Timer(0.05, self._join).start()
            return
        super()._receive(pkt)

    def _report(self) -> None:
        say = self.console.receivedChar.call
        if self.on_network:
            say(f"WiFi connected to ip: {self.ip}\n")
        else:
            say(f"CPX: ESP32: I (9) WIFI: not connected, last reason {self.reason}\n")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(wifi, "REPLY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(wifi, "JOIN_TIMEOUT_S", 1.0)
    monkeypatch.setattr(wifi, "REPORT_WAIT_S", 0.5)


def configured():
    deck, states, ips = make()
    deck.configure("Lab", "correct horse")
    return deck, states, ips


def network_packets(drone) -> list[bytes]:
    return [p for p in drone.sent if p[0] in (CMD_SSID, CMD_KEY, CMD_APPLY)]


class TestALinkThatOpensOnAJoinedDeck:
    def test_it_asks_and_never_rejoins_a_deck_that_is_fine(self):
        deck, _, ips = configured()
        deck._joined = ("Lab", "10.0.0.41")
        drone = FakeV4(applied=True, on_network=True)
        state = deck.apply(drone)
        assert state.phase is Phase.JOINED and state.ip == "10.0.0.42"
        assert ips == ["10.0.0.42"]
        assert network_packets(drone) == []          # no rejoin: the picture keeps going

    def test_a_new_network_is_sent_not_asked_about(self):
        """Asking would find the deck happy on the OLD network and keep it there."""
        deck, _, _ = configured()
        deck._joined = ("Old network", "10.0.0.5")
        drone = FakeV4(applied=True, on_network=True)
        assert deck.apply(drone).phase is Phase.JOINED
        assert not any(p[0] == CMD_REPORT for p in drone.sent)
        assert any(p[0] == CMD_APPLY for p in drone.sent)

    def test_a_deck_off_the_network_is_rejoined(self):
        deck, _, _ = configured()
        deck._joined = ("Lab", "10.0.0.41")
        drone = FakeV4(applied=True, on_network=False, ip="10.0.0.77")
        state = deck.apply(drone)
        assert state.phase is Phase.JOINED and state.ip == "10.0.0.77"
        assert any(p[0] == CMD_APPLY for p in drone.sent)

    def test_a_fresh_drone_is_not_asked_it_is_given_the_network(self):
        deck, _, _ = configured()
        drone = FakeV4(applied=False)
        assert deck.apply(drone).phase is Phase.JOINED
        assert not any(p[0] == CMD_REPORT for p in drone.sent)


class TestRecover:
    def test_it_answered_at_a_new_address(self):
        deck, _, ips = configured()
        drone = FakeV4(applied=True, on_network=True, ip="10.0.0.99")
        assert deck.recover(drone, "No answer at 10.0.0.42.") == "answered"
        assert ips == ["10.0.0.99"]
        assert network_packets(drone) == []

    def test_not_on_the_network_it_rejoins_without_a_restart(self):
        deck, _, _ = configured()
        drone = FakeV4(applied=True, on_network=False)
        assert deck.recover(drone, "No answer.") == "rejoined"
        assert deck.state().phase is Phase.JOINED

    def test_the_decks_reason_is_kept_when_it_says_it_is_off(self):
        deck, _, _ = configured()
        drone = FakeV4(applied=True, on_network=False, reason=201)
        deck.recover(drone, "No answer.")
        assert "cannot find the network" in (deck.state().reason or "")

    def test_a_v3_drone_cannot_be_asked(self):
        deck, _, _ = configured()
        drone = FakeV4(applied=True, version=3)
        assert deck.recover(drone, "No answer.") == "unsupported"
        assert network_packets(drone) == []          # an old deck is never re-applied
        # Never left on "Asking…": what it can do, and the fix.
        state = deck.state()
        assert state.phase is Phase.FAILED and state.needs_restart
        assert "Set up" in (state.message or "") and "Asking" not in (state.message or "")

    def test_an_old_deck_on_a_v4_drone_cannot_be_asked(self):
        deck, _, _ = configured()
        drone = FakeV4(applied=True, can_rejoin=False)
        assert deck.recover(drone, "No answer.") == "unsupported"
        assert network_packets(drone) == []

    def test_no_answer_over_the_radio(self):
        deck, _, _ = configured()
        assert deck.recover(FakeV4(flashed=False), "No answer.") == "unreachable"
        assert "did not answer over the radio" in (deck.state().message or "")

    def test_nothing_to_rejoin_without_a_network(self):
        deck, _, _ = make()
        assert deck.recover(FakeV4(), "No answer.") == "no-network"

    def test_one_conversation_at_a_time(self):
        deck, _, _ = configured()
        assert deck._busy.acquire(blocking=False)
        try:
            assert deck.recover(FakeV4(), "No answer.") == "busy"
            assert deck.apply(FakeV4()).phase is Phase.WAITING   # untouched
        finally:
            deck._busy.release()


class TestReasons:
    def test_known_codes_are_words(self):
        assert reason_words(15) == "the password was not accepted"
        assert "lost the signal" in (reason_words(200) or "")
        assert reason_words(77) == "it dropped off (reason 77)"
        assert reason_words(None) is None and reason_words(0) is None

    def test_a_drop_says_why(self):
        deck, _, _ = configured()
        drone = FakeV4(applied=False)
        deck.apply(drone)
        stop = deck.watch(drone)
        try:
            drone.console.receivedChar.call(
                "CPX: ESP32: I (5) WIFI: Disconnected from access point, reason 200\n")
        finally:
            stop()
        state = deck.state()
        assert state.phase is Phase.RECONNECTING
        assert "lost the signal" in (state.message or "")

    def test_a_join_that_fails_says_why(self):
        deck, _, _ = configured()

        class WrongPassword(FakeV4):
            def _join(self) -> None:
                for _ in range(wifi.MAX_DISCONNECTS):
                    self.console.receivedChar.call(
                        "CPX: ESP32: I (1) WIFI: Disconnected from access point, reason 15\n")

        state = deck.apply(WrongPassword(applied=False))
        assert state.phase is Phase.FAILED
        assert "password was not accepted" in (state.message or "")

    def test_the_phase_has_an_age(self):
        deck, _, _ = configured()
        assert deck.phase_age() >= 0


class TestTheLadder:
    """Agent.recover_camera: ask and rejoin first; restart the drone only when
    the deck cannot, never more than once a minute, and never in a session."""

    def agent(self, outcome: str, restarts_ok: bool = True):
        import time as _time
        from types import SimpleNamespace

        from cropwatcher.api import rest

        restarts: list[str] = []
        fake = SimpleNamespace(
            _cf=object(), _last_recover=0.0, _last_rejoin=0.0,
            deck_wifi=SimpleNamespace(recover=lambda cf, why: outcome),
            rejoin=lambda *, reason: restarts.append(reason) or restarts_ok)
        fake.recover_camera = lambda why: rest.Agent.recover_camera(fake, why)
        return fake, restarts, _time

    def test_a_deck_that_answers_is_never_restarted(self):
        fake, restarts, _ = self.agent("answered")
        assert fake.recover_camera("No answer.") == "answered"
        assert restarts == []

    def test_a_rejoin_is_enough(self):
        fake, restarts, _ = self.agent("rejoined")
        assert fake.recover_camera("No answer.") == "rejoined" and restarts == []

    def test_old_camera_software_falls_back_to_a_restart(self):
        fake, restarts, _ = self.agent("unsupported")
        assert fake.recover_camera("No answer.") == "restarted"
        assert restarts == ["No answer."]

    def test_a_restart_refused_in_a_session_is_reported_as_it_was(self):
        fake, restarts, _ = self.agent("unsupported", restarts_ok=False)
        assert fake.recover_camera("No answer.") == "unsupported"

    def test_never_more_than_one_restart_a_minute(self):
        fake, restarts, time_ = self.agent("needs_restart")
        fake._last_rejoin = time_.monotonic()          # restarted a moment ago
        assert fake.recover_camera("No answer.") == "needs_restart"
        assert restarts == []

    def test_no_drone_no_recovery(self):
        fake, _, _ = self.agent("answered")
        fake._cf = None
        assert fake.recover_camera("No answer.") == "no-drone"


class TestTheRoute:
    def test_it_needs_a_connected_drone(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from cropwatcher.api import rest
        from cropwatcher.api.tokens import HEADER

        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(rest.agent, "_cf", None)
        client = TestClient(rest.app)
        response = client.post("/camera/wifi/rejoin", headers={HEADER: rest.agent.token})
        assert response.status_code == 409 and "Connect the drone" in response.json()["detail"]

    def test_it_recovers_in_the_background_and_answers_at_once(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from cropwatcher.api import rest
        from cropwatcher.api.tokens import HEADER

        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        asked = threading.Event()
        monkeypatch.setattr(rest.agent, "_cf", object())
        monkeypatch.setattr(rest.agent, "recover_camera",
                            lambda why: asked.set() or "answered")
        response = TestClient(rest.app).post("/camera/wifi/rejoin",
                                             headers={HEADER: rest.agent.token})
        assert response.status_code == 200
        assert asked.wait(2)
