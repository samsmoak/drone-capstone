"""One line per repeating message (cropwatcher/logfilter.py)."""

from __future__ import annotations

import logging

from cropwatcher.logfilter import RepeatFilter


def record(msg, *args, level=logging.WARNING, name="cropwatcher.flight.manual"):
    return logging.LogRecord(name, level, __file__, 1, msg, args, None)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_the_same_message_with_new_numbers_is_one_message():
    clock = Clock()
    f = RepeatFilter(window_s=10, clock=clock)
    assert f.filter(record("%d cm off the commanded point", 26))
    for cm in (27, 26, 24, 30):
        clock.t += 0.02
        assert not f.filter(record("%d cm off the commanded point", cm))


def test_after_the_window_it_says_how_many_were_dropped():
    clock = Clock()
    f = RepeatFilter(window_s=10, clock=clock)
    f.filter(record("not restarting the drone (no answer for %d s)", 5))
    for s in range(10, 40, 5):
        clock.t += 1
        f.filter(record("not restarting the drone (no answer for %d s)", s))
    clock.t = 11
    passed = record("not restarting the drone (no answer for %d s)", 60)
    assert f.filter(passed)
    assert "6 more like it" in passed.getMessage()


def test_different_messages_are_never_held_back():
    f = RepeatFilter(window_s=10, clock=Clock())
    assert f.filter(record("manual control: armed"))
    assert f.filter(record("manual control: landing"))
    assert f.filter(record("manual control: armed", name="cropwatcher.session"))
