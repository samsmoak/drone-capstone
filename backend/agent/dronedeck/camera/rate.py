"""How fast the camera really delivers, and where each frame's time goes.

Two measurements, from the two ends of the link, so a slow feed can be blamed
on the right part instead of guessed at:

  FrameRate   what ARRIVES here — frames a second, their size, the longest
              gap — over the last WINDOW_S. Counted as each whole frame is
              decoded (DeckStream.pump), so it is the rate the window and the
              recording can possibly get.
  DeckTiming  what the GAP8 SAYS each frame cost it. The image streamer prints
              one line per frame on the drone's console:

                  capture=76ms, encoding=0 ms (79056 bytes), transfer=32 ms

              capture is the sensor, encoding the JPEG encoder (0 for raw),
              transfer the send into the ESP32. They run one after another,
              so their sum bounds the rate the deck can produce.

READING THEM TOGETHER. transfer BLOCKS while the ESP32 cannot take more —
its Wi-Fi is behind — so a slow network shows up as a long transfer, not as
a gap the GAP8 cannot see. Hence:
  capture dominates             the sensor is the limit
  encoding dominates            the JPEG encoder is
  transfer dominates            the ESP32 / Wi-Fi is (what JPEG and the
                                ESP32's no-sleep patch are for)
  deck_fps well above fps here  frames are lost or held between the ESP32
                                and this laptop
That is the question these exist to answer (2026-10-24).
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: The span the rates are measured over. Long enough to smooth a frame or two,
#: short enough that a change of firmware or position shows within seconds.
WINDOW_S = 10.0
#: The deck's own timings stop counting once this old: a stopped feed prints
#: nothing, and an average of minutes-old lines would look current.
TIMING_STALE_S = 5.0
#: How many of the deck's lines are averaged.
TIMING_LINES = 20

#: Bitcraze's wifi-img-streamer.c, cpxPrintToConsole after every frame.
_TIMING = re.compile(
    r"capture=(\d+)\s*ms, encoding=(\d+)\s*ms \((\d+) bytes\), transfer=(\d+)\s*ms")

_FORMAT_NAME = {0: "raw", 1: "jpeg"}


class FrameRate:
    """Frames arriving here, over the last WINDOW_S. Thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._arrivals: deque[tuple[float, int]] = deque()
        self._format: int | None = None

    def add(self, nbytes: int, fmt: int) -> None:
        now = self._clock()
        with self._lock:
            self._arrivals.append((now, nbytes))
            self._format = fmt
            self._trim(now)

    def _trim(self, now: float) -> None:
        while self._arrivals and now - self._arrivals[0][0] > WINDOW_S:
            self._arrivals.popleft()

    def summary(self) -> dict[str, Any]:
        """fps and size over the window; the longest gap includes the one still
        open, so a feed that has just stopped shows it at once."""
        now = self._clock()
        with self._lock:
            self._trim(now)
            arrivals = list(self._arrivals)
            fmt = self._format
        times = [t for t, _ in arrivals]
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        if times:
            gaps.append(now - times[-1])
        return {
            "window_s": WINDOW_S,
            "frames": len(arrivals),
            "fps": round(len(arrivals) / WINDOW_S, 2),
            "mean_bytes": round(sum(n for _, n in arrivals) / len(arrivals)) if arrivals else None,
            "longest_gap_s": round(max(gaps), 2) if gaps else None,
            "format": _FORMAT_NAME.get(fmt) if fmt is not None else None,
        }


@dataclass(frozen=True)
class FrameCost:
    capture_ms: int
    encoding_ms: int
    bytes: int
    transfer_ms: int


def parse_timing(line: str) -> FrameCost | None:
    match = _TIMING.search(line)
    if not match:
        return None
    capture, encoding, size, transfer = (int(g) for g in match.groups())
    return FrameCost(capture, encoding, size, transfer)


class DeckTiming:
    """The GAP8's own account of its last frames, read off the console."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._costs: deque[tuple[float, FrameCost]] = deque(maxlen=TIMING_LINES)

    def feed_line(self, line: str) -> None:
        cost = parse_timing(line)
        if cost is not None:
            with self._lock:
                self._costs.append((self._clock(), cost))

    def summary(self) -> dict[str, Any] | None:
        """The mean of the recent lines, or None when the deck has said nothing
        lately (no link, no stream, or older firmware that prints nothing)."""
        now = self._clock()
        with self._lock:
            recent = [c for t, c in self._costs if now - t <= TIMING_STALE_S]
        if not recent:
            return None

        def mean(values: list[int]) -> float:
            return round(sum(values) / len(values), 1)

        capture = mean([c.capture_ms for c in recent])
        encoding = mean([c.encoding_ms for c in recent])
        transfer = mean([c.transfer_ms for c in recent])
        per_frame = capture + encoding + transfer
        return {
            "lines": len(recent),
            "capture_ms": capture,
            "encoding_ms": encoding,
            "transfer_ms": transfer,
            "bytes": round(sum(c.bytes for c in recent) / len(recent)),
            #: What the GAP8 could deliver if nothing downstream held it up.
            "deck_fps": round(1000.0 / per_frame, 2) if per_frame > 0 else None,
        }
