"""camera/diagnose.py and the deck stream's silent connects (2026-10-24: the
deck accepted 106 connections in a morning and sent nothing)."""

from __future__ import annotations

import socket
import threading
import time

from cropwatcher.camera import deck
from cropwatcher.camera.deck import DeckStream
from cropwatcher.camera.diagnose import (
    GAP8_SILENT,
    KEEP_LINES,
    NO_CAPTURE,
    SEND_STUCK,
    SILENT_CONNECTS,
    UNKNOWN,
    WINDOW_S,
    DeckConsole,
)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def console(*lines: str) -> DeckConsole:
    c = DeckConsole(Clock())
    for line in lines:
        c.feed_line(line)
    return c


class TestDiagnosis:
    def test_nothing_to_say_until_connections_go_silent(self):
        c = console("ESP32: Client connected")
        assert c.diagnose(SILENT_CONNECTS - 1) is None

    def test_the_wifi_chip_takes_clients_and_the_camera_chip_never_answers(self):
        c = console("ESP32: Client connected", "ESP32: Client disconnected",
                    "ESP32: Client connected")
        found = c.diagnose(SILENT_CONNECTS)
        assert found is not None and found.code == GAP8_SILENT
        assert "unplug the battery" in found.message

    def test_the_camera_chip_hears_the_client_but_captures_nothing(self):
        c = console("ESP32: Client connected", "GAP8: Wifi client connection status: 1")
        found = c.diagnose(SILENT_CONNECTS)
        assert found is not None and found.code == NO_CAPTURE

    def test_a_camera_that_fails_to_open_says_so(self):
        c = console("GAP8: Starting camera task...", "GAP8: Failed to open camera")
        found = c.diagnose(SILENT_CONNECTS)
        assert found is not None and found.code == NO_CAPTURE
        assert "cannot use the camera" in found.message

    def test_frames_made_and_stuck_sending_is_the_signal(self):
        c = console("GAP8: Wifi client connection status: 1",
                    "GAP8: capture=76ms, encoding=0 ms (79056 bytes), transfer=1150948 ms",
                    "ESP32: Error occurred during sending: errno 113")
        found = c.diagnose(SILENT_CONNECTS)
        assert found is not None and found.code == SEND_STUCK

    def test_no_word_from_the_drone_is_said_plainly_never_guessed(self):
        found = console().diagnose(SILENT_CONNECTS + 2)
        assert found is not None and found.code == UNKNOWN
        assert f"{SILENT_CONNECTS + 2} connections" in found.message

    def test_old_lines_stop_counting(self):
        clock = Clock()
        c = DeckConsole(clock)
        c.feed_line("GAP8: Wifi client connection status: 1")
        clock.t += WINDOW_S + 1
        c.feed_line("ESP32: Client connected")
        found = c.diagnose(SILENT_CONNECTS)
        assert found is not None and found.code == GAP8_SILENT


class TestLines:
    def test_flight_firmware_lines_are_not_the_decks(self):
        c = console("SYS: Crazyflie 2.1 is up and running!", "LH: Lighthouse deck ready")
        assert c.recent() == []

    def test_per_frame_lines_are_counted_not_kept(self):
        c = console("ESP32: Client connected",
                    *["GAP8: capture=76ms, encoding=0 ms (79056 bytes), transfer=32 ms"] * 50)
        assert c.recent() == ["ESP32: Client connected"]
        assert c.counts()["capture"] == 50

    def test_only_the_newest_lines_are_kept(self):
        c = console(*[f"ESP32: Client connected #{i}" for i in range(KEEP_LINES + 5)])
        assert len(c.recent()) == KEEP_LINES
        assert c.recent()[-1].endswith(f"#{KEEP_LINES + 4}")

    def test_the_payload(self):
        out = console("ESP32: Client connected").to_dict(SILENT_CONNECTS)
        assert out["silent_connects"] == SILENT_CONNECTS
        assert out["diagnosis"]["code"] == GAP8_SILENT
        assert out["lines"] == ["ESP32: Client connected"]


class SilentSocket:
    """A deck that accepts and sends nothing: every read times out."""

    def settimeout(self, _t: float) -> None: ...
    def recv(self, _n: int) -> bytes:
        raise TimeoutError("timed out")
    def shutdown(self, _how: int) -> None: ...
    def close(self) -> None: ...


class TestSilentConnects:
    def test_they_are_counted_and_the_retries_slow_down(self, monkeypatch):
        monkeypatch.setattr(deck, "SILENT_BACKOFF_S", 0.4)
        monkeypatch.setattr(deck, "RECONNECT_FIRST_S", 0.01)
        times: list[float] = []
        done = threading.Event()

        def accept(addr):
            times.append(time.monotonic())
            if len(times) >= deck.SILENT_BACKOFF_AFTER + 2:
                done.set()
            return SilentSocket()

        source = DeckStream(connect=accept)            # type: ignore[arg-type]
        try:
            assert done.wait(5)
            assert source.silent_connects() >= deck.SILENT_BACKOFF_AFTER
            gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
            fast, slow = gaps[: deck.SILENT_BACKOFF_AFTER - 1], gaps[deck.SILENT_BACKOFF_AFTER:]
            assert all(g < 0.3 for g in fast)          # the first few: quick retries
            assert slow and all(g >= 0.35 for g in slow)
        finally:
            source.close()

    def test_a_byte_resets_the_count(self):
        source = DeckStream(start=False)
        source._silent = 5
        got = [0]
        read = deck._counting(lambda n: b"x" * n, got)
        read(3)
        assert got[0] == 3
        # The loop's own rule, applied as it applies it.
        source._silent = 0 if got[0] else source._silent + 1
        assert source.silent_connects() == 0

    def test_a_new_address_starts_the_count_again(self):
        source = DeckStream(start=False)
        source._silent = 4
        source.set_host("10.0.0.9")
        assert source.silent_connects() == 0

    def test_socket_timeout_is_an_oserror_the_loop_already_catches(self):
        assert issubclass(socket.timeout, OSError)


class TestTheCameraRoute:
    def test_the_drones_own_reason_replaces_sends_nothing(self, monkeypatch, tmp_path):
        import dataclasses

        from fastapi.testclient import TestClient

        from cropwatcher.api import rest

        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        stream = DeckStream(start=False)
        stream._silent = SILENT_CONNECTS
        monkeypatch.setattr(rest.agent, "camera", stream)
        monkeypatch.setattr(rest.agent, "deck_console", console("ESP32: Client connected"))
        real = rest.agent.session.snapshot
        monkeypatch.setattr(rest.agent.session, "snapshot", lambda: dataclasses.replace(
            real(), radio={"state": "connected"}))
        body = TestClient(rest.app).get("/camera").json()
        assert body["deck"]["diagnosis"]["code"] == GAP8_SILENT
        assert body["deck"]["lines"] == ["ESP32: Client connected"]
        assert body["connecting"] is False
        assert "unplug the battery" in body["reason"]
