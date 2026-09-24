"""The AI deck's own camera, read from its Wi-Fi image streamer.

    CROPWATCHER_CAMERA=deck  [CROPWATCHER_DECK_ADDR=192.168.4.1:5000]

WHAT IS ON THE OTHER END. The GAP8 runs Bitcraze's
`aideck_gap8_wifi_img_streamer_with_ap` (flashed by flash_gap8.py). The deck
raises its own access point — "WiFi streaming example" — and serves CPX packets
over TCP on port 5000. This laptop must be JOINED to that access point, and
while it is, it has no internet unless a second network adapter provides it.

THE WIRE FORMAT, measured from a real capture on 2026-09-23:

    every packet    <HBB   length (counts the 2 routing bytes), routing, routing
    image header    <BHHBBI  magic 0xBC, width, height, depth, format, size
    then            data packets, 1020 payload bytes each, until `size` bytes

  measured header   324 x 244, depth 1, format 0 (raw), size 79056 = 324*244

Format 0 is the sensor's raw bytes — one per pixel — and is re-encoded as a
greyscale PNG with the same hand-written encoder as the test pattern. Format 1
is already a JPEG and is passed through untouched.

THE SIZE COMES FROM EACH FRAME'S HEADER, never a constant. The one constant the
code had — 320x320 — was a guess, and the deck measured 324x244.

NOT MEASURED YET: a whole frame. The only capture stalled after 24 KB of the
first 79 KB frame. So a stalled socket is treated as the normal failure here —
read timeouts, reconnect with backoff, and a frame older than STALE_S is not
reported as live.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from cropwatcher.camera.source import CameraStatus, png_grey

log = logging.getLogger(__name__)

DEFAULT_ADDR = ("192.168.4.1", 5000)

#: CPX packet header: payload length (including the 2 routing bytes), routing.
_PACKET = struct.Struct("<HBB")
#: The streamer's image header, carried in the first packet of every frame.
_IMAGE = struct.Struct("<BHHBBI")
IMAGE_MAGIC = 0xBC

FORMAT_RAW = 0
FORMAT_JPEG = 1

#: A raw 324x244 frame is 79 KB. Anything claiming far more is a desynced
#: stream, and trusting it would buffer garbage until memory runs out.
MAX_FRAME_BYTES = 2_000_000

#: A frame older than this is not "live". The window treats 2 s as stale too.
STALE_S = 2.0
#: How long a read may block before the stream is considered stalled.
READ_TIMEOUT_S = 5.0
RECONNECT_MAX_S = 5.0


class StreamError(Exception):
    """The byte stream does not look like the deck's image streamer."""


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    format: int
    data: bytes


def read_frame(read: Callable[[int], bytes]) -> Frame:
    """Read packets until one whole image has arrived.

    `read(n)` must return exactly n bytes or raise. Packets before an image
    header — joining mid-frame is the normal case on connect — are skipped.
    """
    while True:
        length, _, _ = _PACKET.unpack(read(_PACKET.size))
        body = read(_body_len(length))
        if len(body) < _IMAGE.size or body[0] != IMAGE_MAGIC:
            continue  # the tail of a frame we joined halfway through
        magic, width, height, _depth, fmt, size = _IMAGE.unpack_from(body)
        if size == 0 or size > MAX_FRAME_BYTES:
            raise StreamError(f"implausible frame size {size}")
        if fmt == FORMAT_RAW and size != width * height:
            raise StreamError(f"raw frame {width}x{height} claims {size} bytes")
        data = bytearray()
        while len(data) < size:
            length, _, _ = _PACKET.unpack(read(_PACKET.size))
            data.extend(read(_body_len(length)))
        if len(data) != size:
            raise StreamError(f"frame overran: {len(data)} of {size} bytes")
        return Frame(width=width, height=height, format=fmt, data=bytes(data))


def _body_len(length: int) -> int:
    if length < 2:
        raise StreamError(f"packet length {length} is shorter than its routing")
    return length - 2


def encode(frame: Frame) -> tuple[bytes, str]:
    """The frame as something an <img> can show, with its content type."""
    if frame.format == FORMAT_JPEG:
        return frame.data, "image/jpeg"
    if frame.format == FORMAT_RAW:
        w, h = frame.width, frame.height
        rows = [bytearray(frame.data[y * w:(y + 1) * w]) for y in range(h)]
        return png_grey(rows, w, h), "image/png"
    raise StreamError(f"unknown image format {frame.format}")


def _unreachable(host: str, port: int, e: OSError) -> str:
    detail = e.strerror or str(e)
    if (host, port) == DEFAULT_ADDR:
        return (f"Cannot reach the AI deck at {host}:{port}, its own access point. "
                "Set the drone's Wi-Fi network in Drone Wi-Fi, or join this laptop to "
                f"\"WiFi streaming example\". ({detail})")
    return (f"Cannot reach the AI deck at {host}:{port}. Is this laptop on the same "
            f"network as the drone? ({detail})")


def parse_addr(value: str | None) -> tuple[str, int]:
    if not value:
        return DEFAULT_ADDR
    host, _, port = value.rpartition(":")
    return (host or value, int(port) if host else DEFAULT_ADDR[1])


def _socket_reader(sock: socket.socket) -> Callable[[int], bytes]:
    def read(n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("the deck closed the stream")
            buf.extend(chunk)
        return bytes(buf)
    return read


Connect = Callable[[tuple[str, int]], socket.socket]


def _connect(addr: tuple[str, int]) -> socket.socket:
    sock = socket.create_connection(addr, timeout=READ_TIMEOUT_S)
    sock.settimeout(READ_TIMEOUT_S)
    return sock


class DeckStream:
    """A FrameSource backed by the deck's streamer.

    A background thread owns the socket and keeps only the LATEST frame, so
    `frame()` never waits on the network and a slow window never backs up the
    stream. It reconnects forever with backoff: the deck going out of range or
    being power-cycled is ordinary, not fatal.
    """

    def __init__(
        self,
        addr: tuple[str, int] = DEFAULT_ADDR,
        connect: Connect = _connect,
        clock: Callable[[], float] = time.monotonic,
        start: bool = True,
    ) -> None:
        self._addr = addr
        self._connect = connect
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: tuple[bytes, str, float, int, int] | None = None
        self._problem: str | None = "Connecting to the AI deck…"
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self.deck_fitted: bool | None = None
        self._thread = threading.Thread(target=self._run, name="deck-camera", daemon=True)
        if start:
            self._thread.start()

    @property
    def content_type(self) -> str:
        with self._lock:
            return self._latest[1] if self._latest else "image/png"

    def frame(self) -> bytes | None:
        with self._lock:
            latest = self._latest
        if latest is None or self._clock() - latest[2] > STALE_S:
            return None
        return latest[0]

    def status(self) -> CameraStatus:
        with self._lock:
            latest, problem = self._latest, self._problem
        fresh = latest is not None and self._clock() - latest[2] <= STALE_S
        if fresh and latest is not None:
            return CameraStatus(
                live=True, kind="ai-deck", reason=None, deck_fitted=self.deck_fitted,
                width=latest[3], height=latest[4],
            )
        host, port = self.addr
        return CameraStatus(
            live=False,
            kind="ai-deck",
            reason=problem or (
                f"No frame from the AI deck at {host}:{port} in the last "
                f"{STALE_S:.0f} s. The stream has stalled."
            ),
            deck_fitted=self.deck_fitted,
        )

    def close(self) -> None:
        self._stop.set()
        self._drop_socket()

    @property
    def addr(self) -> tuple[str, int]:
        with self._lock:
            return self._addr

    def set_host(self, host: str) -> None:
        """Stream from the deck at `host` from now on — the address it reported
        after joining the operator's network. The open connection, if any, is
        dropped so the next frame comes from the new address."""
        with self._lock:
            if self._addr[0] == host:
                return
            self._addr = (host, self._addr[1])
            self._latest = None
            self._problem = f"Connecting to the AI deck at {host}…"
        log.info("deck camera moving to %s", host)
        self._drop_socket()

    def _drop_socket(self) -> None:
        with self._lock:
            sock = self._sock
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def pump(self, read: Callable[[int], bytes]) -> None:
        """Read one frame and make it the latest. The thread's unit of work,
        exposed so tests can drive it without a socket."""
        frame = read_frame(read)
        data, ctype = encode(frame)
        with self._lock:
            self._latest = (data, ctype, self._clock(), frame.width, frame.height)
            self._problem = None

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            addr = self.addr
            host, port = addr
            try:
                sock = self._connect(addr)
            except OSError as e:
                self._set_problem(_unreachable(host, port, e))
            else:
                log.info("deck camera connected at %s:%s", host, port)
                backoff = 0.5
                with self._lock:
                    self._sock = sock
                try:
                    read = _socket_reader(sock)
                    while not self._stop.is_set():
                        self.pump(read)
                except (OSError, StreamError) as e:
                    log.warning("deck camera stream ended: %s", e)
                    self._set_problem(
                        f"The AI deck's stream stopped ({e}). Reconnecting."
                    )
                finally:
                    with self._lock:
                        self._sock = None
                    sock.close()
            self._stop.wait(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_S)

    def _set_problem(self, reason: str) -> None:
        with self._lock:
            self._problem = reason
