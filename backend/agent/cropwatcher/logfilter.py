"""One line per repeating message, not fifty a second.

On 2026-10-05 "N cm off the commanded point and still correcting" was written
at the manual loop's 50 Hz and "not restarting the drone (…)" every 5 s for
the length of a session: thousands of lines a minute in a log capped at
2 MB × 3, so the lines that explain a flight were rotated out by the noise.
Both come from code that must not change for this (flight/manual.py is
locked), so the log itself keeps one of each per window and says how many it
dropped.

Messages are the same when they differ only in their numbers ("26 cm off" and
"27 cm off" are one message). Warnings and errors still get through once per
window; nothing is lost but the repetition.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable

#: How long one message is kept to a single line.
WINDOW_S = 10.0

_NUMBERS = re.compile(r"[-+]?\d+(?:\.\d+)?")


class RepeatFilter(logging.Filter):
    def __init__(self, window_s: float = WINDOW_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self._window = window_s
        self._clock = clock
        self._lock = threading.Lock()
        #: message shape -> (when it was last let through, how many dropped since)
        self._seen: dict[tuple[str, int, str], tuple[float, int]] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.name, record.levelno, _NUMBERS.sub("#", record.getMessage()))
        now = self._clock()
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last[0] < self._window:
                self._seen[key] = (last[0], last[1] + 1)
                return False
            dropped = last[1] if last is not None else 0
            self._seen[key] = (now, 0)
        if dropped:
            record.msg = f"{record.getMessage()} (and {dropped} more like it in the last " \
                         f"{self._window:.0f} s)"
            record.args = ()
        return True
