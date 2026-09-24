"""The AI deck's stream parser and source, against the wire format measured on
the real deck on 2026-09-23. No socket and no deck: streams are built here."""

from __future__ import annotations

import struct
import threading
import time

import pytest

from cropwatcher.camera.deck import (
    FORMAT_JPEG,
    FORMAT_RAW,
    STALE_S,
    DeckStream,
    Frame,
    StreamError,
    encode,
    parse_addr,
    read_frame,
)

#: The first 15 bytes the real deck sent: a CPX packet of length 13 carrying
#: the image header — 324x244, depth 1, raw, 79056 bytes.
REAL_HEADER = bytes.fromhex("0d006305bc4401f4000100d0340100")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def packet(body: bytes) -> bytes:
    return struct.pack("<HBB", len(body) + 2, 0x63, 0x05) + body


def image(width: int, height: int, data: bytes, fmt: int = FORMAT_RAW) -> bytes:
    header = struct.pack("<BHHBBI", 0xBC, width, height, 1, fmt, len(data))
    chunks = [data[i:i + 1020] for i in range(0, len(data), 1020)]
    return packet(header) + b"".join(packet(c) for c in chunks)


def reader(stream: bytes):
    pos = 0

    def read(n: int) -> bytes:
        nonlocal pos
        if pos + n > len(stream):
            raise ConnectionError("end of stream")
        out = stream[pos:pos + n]
        pos += n
        return out
    return read


class TestReadFrame:
    def test_the_real_deck_header_parses_as_measured(self):
        width, height, fmt, size = 324, 244, FORMAT_RAW, 79056
        data = bytes(range(256)) * (size // 256) + bytes(size % 256)
        chunks = b"".join(packet(data[i:i + 1020]) for i in range(0, size, 1020))
        frame = read_frame(reader(REAL_HEADER + chunks))
        assert (frame.width, frame.height, frame.format) == (width, height, fmt)
        assert frame.data == data

    def test_it_skips_the_tail_of_a_frame_joined_halfway(self):
        """Connecting mid-frame is the normal case, not an error."""
        stream = packet(b"\x11" * 1020) + packet(b"\x22" * 40) + image(4, 2, b"abcdefgh")
        frame = read_frame(reader(stream))
        assert frame.data == b"abcdefgh"

    def test_a_stream_that_ends_mid_frame_raises(self):
        """What the only real capture did: it stalled a third of the way in."""
        whole = image(324, 244, bytes(324 * 244))
        with pytest.raises(ConnectionError):
            read_frame(reader(whole[:24495]))

    def test_an_implausible_size_is_refused_rather_than_buffered(self):
        header = struct.pack("<BHHBBI", 0xBC, 10, 10, 1, FORMAT_JPEG, 50_000_000)
        with pytest.raises(StreamError):
            read_frame(reader(packet(header)))

    def test_a_raw_frame_whose_size_disagrees_with_its_shape_is_refused(self):
        header = struct.pack("<BHHBBI", 0xBC, 10, 10, 1, FORMAT_RAW, 99)
        with pytest.raises(StreamError):
            read_frame(reader(packet(header)))

    def test_a_packet_shorter_than_its_routing_is_refused(self):
        with pytest.raises(StreamError):
            read_frame(reader(struct.pack("<HBB", 1, 0, 0)))


class TestEncode:
    def test_raw_becomes_a_png_of_the_frame_s_own_size(self):
        data, ctype = encode(Frame(324, 244, FORMAT_RAW, bytes(324 * 244)))
        assert ctype == "image/png"
        assert data[:8] == PNG_MAGIC
        assert struct.unpack(">II", data[16:24]) == (324, 244)

    def test_jpeg_passes_through_untouched(self):
        jpeg = b"\xff\xd8 not really \xff\xd9"
        assert encode(Frame(8, 8, FORMAT_JPEG, jpeg)) == (jpeg, "image/jpeg")

    def test_an_unknown_format_is_an_error_not_a_picture(self):
        with pytest.raises(StreamError):
            encode(Frame(2, 2, 7, b"abcd"))


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class TestDeckStream:
    def make(self) -> tuple[DeckStream, Clock]:
        clock = Clock()
        return DeckStream(clock=clock, start=False), clock

    def test_before_any_frame_it_is_not_live_and_says_why(self):
        source, _ = self.make()
        assert source.frame() is None
        status = source.status()
        assert status.live is False
        assert status.kind == "ai-deck"
        assert status.reason

    def test_a_received_frame_is_served_with_its_size(self):
        source, _ = self.make()
        source.pump(reader(image(4, 2, b"abcdefgh")))
        assert source.frame() is not None
        assert source.content_type == "image/png"
        status = source.status()
        assert (status.live, status.width, status.height) == (True, 4, 2)

    def test_a_stale_frame_is_not_served_as_live(self):
        """A frozen last frame looks exactly like a working feed; it must not
        be served as one."""
        source, clock = self.make()
        source.pump(reader(image(4, 2, b"abcdefgh")))
        clock.t += STALE_S + 0.1
        assert source.frame() is None
        assert source.status().live is False

    def test_it_keeps_only_the_latest_frame(self):
        source, _ = self.make()
        source.pump(reader(image(2, 1, b"\x00\x00")))
        first = source.frame()
        source.pump(reader(image(2, 1, b"\xff\xff")))
        assert source.frame() != first

    def test_an_unreachable_deck_says_how_to_reach_it_and_keeps_trying(self):
        attempts = threading.Event()

        def refuse(addr):
            attempts.set()
            raise OSError(65, "No route to host")

        source = DeckStream(connect=refuse)
        try:
            assert attempts.wait(2)
            deadline = time.monotonic() + 2
            while "Cannot reach" not in (source.status().reason or ""):
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert "WiFi streaming example" in (source.status().reason or "")
        finally:
            source.close()


class TestParseAddr:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, ("192.168.4.1", 5000)),
            ("", ("192.168.4.1", 5000)),
            ("10.0.0.7:6000", ("10.0.0.7", 6000)),
            ("10.0.0.7", ("10.0.0.7", 5000)),
        ],
    )
    def test_it_defaults_to_the_deck_s_access_point(self, value, expected):
        assert parse_addr(value) == expected


class TestSetHost:
    def test_the_stream_follows_the_address_the_deck_reported(self):
        source = DeckStream(start=False)
        source.pump(reader(image(2, 1, b"\x00\x00")))
        source.set_host("10.0.0.42")
        assert source.addr == ("10.0.0.42", 5000)
        # The old address's frame is not presented as the new one's.
        assert source.frame() is None
        assert "10.0.0.42" in (source.status().reason or "")


class TestKick:
    def test_a_kick_cuts_the_backoff_short(self):
        attempts: list[float] = []

        def refuse(addr):
            attempts.append(time.monotonic())
            raise OSError(113, "No route to host")

        source = DeckStream(connect=refuse)
        try:
            time.sleep(1.2)                      # let the backoff grow past 0.8 s
            before = len(attempts)
            source.kick()
            deadline = time.monotonic() + 0.3
            while len(attempts) == before and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(attempts) > before, "the kick did not bring a retry forward"
        finally:
            source.close()


class TestUnreachableFor:
    def test_it_counts_from_the_first_failure_and_resets_on_a_new_host(self):
        clock = Clock()
        seen = threading.Event()

        def refuse(addr):
            seen.set()
            raise OSError(113, "No route to host")

        source = DeckStream(connect=refuse, clock=clock)
        try:
            assert seen.wait(2)
            wait = time.monotonic() + 2
            while source.unreachable_for() == 0.0 and time.monotonic() < wait:
                time.sleep(0.01)
            clock.t += 20
            assert source.unreachable_for() >= 20
            source.set_host("10.0.0.9")
            assert source.unreachable_for() == 0.0
        finally:
            source.close()


class TestNoFramesFor:
    def test_counts_from_the_last_frame_even_when_connects_succeed(self):
        clock = Clock()
        source = DeckStream(clock=clock, start=False)
        clock.t += 30
        assert source.no_frames_for() == 30
        source.pump(reader(image(2, 1, b"ab")))
        assert source.no_frames_for() == 0
        clock.t += 5
        assert source.no_frames_for() == 5
