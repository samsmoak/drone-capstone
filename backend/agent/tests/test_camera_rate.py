"""camera/rate.py: the measured frame rate, and the GAP8's own timings."""

from __future__ import annotations

from cropwatcher.camera.rate import (
    TIMING_STALE_S,
    WINDOW_S,
    DeckTiming,
    FrameRate,
    parse_timing,
)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_no_frames_reports_nothing_not_zero_gaps():
    rate = FrameRate(Clock())
    s = rate.summary()
    assert s["frames"] == 0 and s["fps"] == 0
    assert s["mean_bytes"] is None and s["longest_gap_s"] is None and s["format"] is None


def test_fps_and_size_over_the_window():
    clock = Clock()
    rate = FrameRate(clock)
    for _ in range(40):                    # 4 a second for 10 s
        rate.add(79056, 0)
        clock.t += 0.25
    s = rate.summary()
    assert s["fps"] == 4.0
    assert s["mean_bytes"] == 79056
    assert s["format"] == "raw"
    assert s["longest_gap_s"] == 0.25


def test_old_frames_leave_the_window():
    clock = Clock()
    rate = FrameRate(clock)
    rate.add(1000, 1)
    clock.t += WINDOW_S + 0.1
    assert rate.summary()["frames"] == 0


def test_a_feed_that_just_stopped_shows_its_open_gap():
    clock = Clock()
    rate = FrameRate(clock)
    rate.add(8000, 1)
    clock.t += 0.2
    rate.add(8000, 1)
    clock.t += 6.0                          # nothing since
    s = rate.summary()
    assert s["longest_gap_s"] == 6.0
    assert s["format"] == "jpeg"


def test_parse_the_streamers_line():
    cost = parse_timing("GAP8: capture=76ms, encoding=0 ms (79056 bytes), transfer=32 ms")
    assert cost is not None
    assert (cost.capture_ms, cost.encoding_ms, cost.bytes, cost.transfer_ms) == (76, 0, 79056, 32)


def test_other_console_lines_are_ignored():
    assert parse_timing("ESP32: Client connected") is None
    assert parse_timing("capture=76ms") is None


def test_deck_timing_averages_recent_lines():
    clock = Clock()
    timing = DeckTiming(clock)
    timing.feed_line("capture=80ms, encoding=20 ms (9000 bytes), transfer=20 ms")
    timing.feed_line("capture=60ms, encoding=40 ms (11000 bytes), transfer=40 ms")
    s = timing.summary()
    assert s is not None
    assert s["capture_ms"] == 70.0 and s["encoding_ms"] == 30.0 and s["transfer_ms"] == 30.0
    assert s["bytes"] == 10000
    assert s["deck_fps"] == round(1000 / 130, 2)


def test_deck_timing_goes_quiet_when_the_deck_does():
    clock = Clock()
    timing = DeckTiming(clock)
    timing.feed_line("capture=76ms, encoding=0 ms (79056 bytes), transfer=32 ms")
    clock.t += TIMING_STALE_S + 0.1
    assert timing.summary() is None


def test_deck_timing_without_any_line_is_none():
    assert DeckTiming(Clock()).summary() is None
