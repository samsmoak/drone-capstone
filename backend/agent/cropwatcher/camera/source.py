"""Where frames come from.

One protocol, so the thing that serves frames, the thing that records them and
the window all speak to a source without knowing which one it is. Today the only
sources are "there is no camera" and a generated test pattern; the deck's own
stream becomes a third when a lab session works out how to reach it.

THE PNG IS WRITTEN BY HAND, with zlib from the standard library. Pillow would be
a clearer twenty lines, but it is tens of megabytes into a PyInstaller binary
that ships to operators inside a 48 MB installer, for a picture nobody sees once
a real camera exists. The encoder below is the minimum valid PNG: one IHDR, one
IDAT of zlib-compressed scanlines, one IEND.
"""

from __future__ import annotations

import binascii
import struct
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Protocol

#: The generated pattern's size. NOT the deck's: its streamer measured 324x244
#: on 2026-09-23, and a real source reads the size from every frame's own header
#: rather than trusting a constant.
FRAME_W = 320
FRAME_H = 320


@dataclass(frozen=True)
class CameraStatus:
    """What the window is told about the camera, in words it can show."""

    #: A frame source is connected and producing frames.
    live: bool
    #: What is producing them: "none", "test-pattern", or the deck.
    kind: str
    #: Why there is nothing, when there is nothing. None while live.
    reason: str | None = None
    #: Whether the AI deck itself is fitted, as the DRONE reports it
    #: (deck.bcAI, read over the radio during the checks). None when no drone
    #: has been asked yet — which is not the same as "not fitted".
    deck_fitted: bool | None = None
    #: The size of the frames being served, once one has arrived.
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict:
        return {
            "live": self.live,
            "kind": self.kind,
            "reason": self.reason,
            "deck_fitted": self.deck_fitted,
            "width": self.width,
            "height": self.height,
        }


class FrameSource(Protocol):
    """Something that can be asked for the most recent frame."""

    @property
    def content_type(self) -> str: ...

    def frame(self) -> bytes | None:
        """The latest frame, or None when there is nothing to show."""
        ...

    def status(self) -> CameraStatus: ...


class NoCamera:
    """The honest default: there is no camera on this drone.

    It is a source like any other so that the route, the recorder and the window
    have one shape to handle rather than a null check each.
    """

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason or (
            "No camera datalink. The AI deck is fitted on this drone, but its "
            "Wi-Fi link is not connected and the flight agent serves no video."
        )
        self.deck_fitted: bool | None = None

    @property
    def content_type(self) -> str:
        return "image/png"

    def frame(self) -> bytes | None:
        return None

    def status(self) -> CameraStatus:
        return CameraStatus(
            live=False, kind="none", reason=self._reason, deck_fitted=self.deck_fitted
        )


class TestPattern:
    """A generated frame, so the whole path can be proven without a camera.

    It MOVES — a band sweeps down the frame once a second and the frame counter
    is drawn as a bar. A still image cannot tell you whether frames are arriving
    or whether one arrived and froze, which is the exact failure a camera feed
    has and the exact thing this is here to rehearse.
    """

    def __init__(self, fps: float = 10.0) -> None:
        self._fps = fps
        self._lock = threading.Lock()
        self._count = 0
        self._started = time.monotonic()
        self.deck_fitted: bool | None = None

    @property
    def content_type(self) -> str:
        return "image/png"

    def frame(self) -> bytes | None:
        with self._lock:
            self._count += 1
            count = self._count
        elapsed = time.monotonic() - self._started
        band = int((elapsed * self._fps * 4) % FRAME_H)
        return png_grey(_pattern_rows(band, count), FRAME_W, FRAME_H)

    def status(self) -> CameraStatus:
        return CameraStatus(
            live=True,
            kind="test-pattern",
            reason=None,
            deck_fitted=self.deck_fitted,
            width=FRAME_W,
            height=FRAME_H,
        )


def _pattern_rows(band: int, count: int) -> list[bytearray]:
    """320x320 greyscale: a gradient, a grid, a sweeping band and a counter bar."""
    rows: list[bytearray] = []
    for y in range(FRAME_H):
        row = bytearray(FRAME_W)
        for x in range(FRAME_W):
            value = (x * 255) // (FRAME_W - 1)
            if x % 40 == 0 or y % 40 == 0:
                value = 90
            row[x] = value
        if abs(y - band) < 6:
            for x in range(FRAME_W):
                row[x] = 255
        rows.append(row)
    # A bar along the bottom that advances with the frame count: a frozen feed
    # shows a still bar even while the band happens to sit off-screen.
    width = (count * 3) % FRAME_W
    for y in range(FRAME_H - 12, FRAME_H - 4):
        for x in range(width):
            rows[y][x] = 0
    return rows


def png_grey(rows: list[bytearray], width: int, height: int) -> bytes:
    """Encode 8-bit greyscale rows as a PNG. Standard library only."""
    raw = bytearray()
    for row in rows:
        raw.append(0)          # filter type 0 (None) for every scanline
        raw.extend(row)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", binascii.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )
