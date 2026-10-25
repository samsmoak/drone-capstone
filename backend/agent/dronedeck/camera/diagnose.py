"""Why the camera sends nothing — read off the drone's own console.

MEASURED 2026-10-24: the deck ACCEPTED the agent's camera connection 106
times in a morning and sent not one byte; the window said "accepts the
connection but sends nothing" and the agent restarted the drone every two
minutes, to no effect. The connection was never the problem. Something on
the deck was silent, and the deck says which, on the console the radio
already carries (camera/wifi.py follow_console):

  ESP32 (its Wi-Fi chip)     "Client connected" / "Client disconnected" —
                             it took our connection
                             "Error occurred during sending: errno N" — a
                             frame could not go out over Wi-Fi
  GAP8 (the camera chip)     "Wifi client connection status: 1" — the ESP32
                             told it a client is there, so it starts sending
                             "Starting camera task..." — it booted
                             "capture=…ms, …" — one line per frame it made
                             "Failed to open camera" and friends — it cannot

(Bitcraze aideck-esp-firmware main/wifi.c and aideck-gap8-examples
wifi-img-streamer.c, 2025.02.) Put together, a silent connection is one of:

  GAP8_SILENT   the ESP32 takes clients, the GAP8 never answers: it is not
                running. Flashing the ESP32 leaves it so until the battery is
                unplugged ~10 s (Bitcraze Discussion #1305); a restart over
                the radio does not help — measured.
  NO_CAPTURE    the GAP8 hears the client and captures nothing: the camera.
  SEND_STUCK    frames are captured and do not leave: the deck's send stall
                (camera-firmware.txt), usually a weak signal.
  UNKNOWN       the console said nothing that settles it — say so; never guess.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: How far back the console counts. Long enough to cover a few silent
#: connects; short enough that a restart's fresh evidence wins quickly.
WINDOW_S = 30.0
#: Silent connects in a row before the camera is reported as not sending.
SILENT_CONNECTS = 3
#: Deck lines kept for the window to show, newest last.
KEEP_LINES = 12

GAP8_SILENT, NO_CAPTURE, SEND_STUCK, UNKNOWN = "gap8_silent", "no_capture", "send_stuck", "unknown"

_CLIENT_STATUS = re.compile(r"Wifi client connection status:\s*(\d+)")
_SEND_ERROR = re.compile(r"Error occurred during sending: errno (\d+)")
_GAP8_FAILED = ("Failed to open camera", "Camera task did not start",
                "Failed to allocate Memory", "Could not allocate memory",
                "Failed initialize JPEG encoder")


@dataclass(frozen=True)
class Diagnosis:
    code: str
    #: What is wrong and what to do, in the operator's words.
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def is_deck_line(line: str) -> bool:
    """A line from the AI deck (either chip), not the flight firmware's."""
    return any(key in line for key in (
        "GAP8", "ESP32", "Wifi client", "Client connected", "Client disconnected",
        "Error occurred during sending", "camera task", "Failed to", "capture=",
        "WiFi image streamer", "Waiting for connection", "got ip", "rssi:"))


class DeckConsole:
    """The deck's recent console lines, and what they add up to. Thread-safe:
    lines arrive on cflib's thread, the API reads on its own."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._events: deque[tuple[float, str]] = deque(maxlen=400)
        self._lines: deque[str] = deque(maxlen=KEEP_LINES)

    def feed_line(self, line: str) -> None:
        line = line.strip()
        if not line or not is_deck_line(line):
            return
        kind = self._kind(line)
        with self._lock:
            # Per-frame lines are counted, not kept: they would push out the
            # few lines that explain a failure.
            if kind != "capture":
                self._lines.append(line)
            if kind:
                self._events.append((self._clock(), kind))

    @staticmethod
    def _kind(line: str) -> str | None:
        if "capture=" in line:
            return "capture"
        status = _CLIENT_STATUS.search(line)
        if status:
            return "gap8_client" if status.group(1) != "0" else "gap8_client_gone"
        if _SEND_ERROR.search(line):
            return "send_error"
        if any(f in line for f in _GAP8_FAILED):
            return "gap8_failed"
        if "Starting camera task" in line or "WiFi image streamer" in line:
            return "gap8_started"
        if "Client connected" in line:
            return "esp_client"
        return None

    def recent(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def counts(self) -> dict[str, int]:
        now = self._clock()
        with self._lock:
            kinds = [k for t, k in self._events if now - t <= WINDOW_S]
        return {k: kinds.count(k) for k in set(kinds)}

    def diagnose(self, silent_connects: int) -> Diagnosis | None:
        """Why connections are silent — None while they are not."""
        if silent_connects < SILENT_CONNECTS:
            return None
        c = self.counts()
        if c.get("gap8_failed"):
            return Diagnosis(NO_CAPTURE, (
                "The camera chip reports it cannot use the camera (see the deck's lines "
                "below). Unplug the battery for 10 s; if it says the same after, the camera "
                "itself needs a look."))
        if c.get("capture") and c.get("send_error"):
            return Diagnosis(SEND_STUCK, (
                "The camera is taking pictures, but they are stuck leaving the drone over Wi-Fi — "
                "the signal is too weak for them. Bring the drone and the Wi-Fi closer together."))
        if c.get("gap8_client") and not c.get("capture"):
            return Diagnosis(NO_CAPTURE, (
                "The camera chip knows we are connected but takes no pictures. Unplug the battery "
                "for 10 s and plug it back in."))
        if c.get("esp_client") and not c.get("gap8_client"):
            return Diagnosis(GAP8_SILENT, (
                "The drone's Wi-Fi takes the connection, but its camera chip never answers — it is "
                "not running. Restarting over the radio does not wake it: unplug the battery for "
                "10 s, then plug it back in."))
        return Diagnosis(UNKNOWN, (
            f"The camera accepted {silent_connects} connections in a row and sent nothing, "
            "and the drone's console has not said why. Unplug the battery for 10 s and plug "
            "it back in."))

    def to_dict(self, silent_connects: int) -> dict[str, Any]:
        found = self.diagnose(silent_connects)
        return {"lines": self.recent(), "silent_connects": silent_connects,
                "diagnosis": found.to_dict() if found else None}
