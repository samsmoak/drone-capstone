"""The flight trace: what the controller asked for next to what the drone did.

Written for every manual flight at the stream rate (10 Hz), beside the flight
CSV as `trace_<flight id>.csv`. The flight CSV records the environment; this
records control — which keys were held, the eased height target and climb speed
the agent commanded, the firmware's own height target and barometer estimate,
thrust, attitude, the four motors and the tuning in force.

It exists because the bounce of 2026-09-17 could only be diagnosed after the
fact from thrust and motor columns; the keys held and the target commanded were
not recorded anywhere, so whether a spin was a held key or a saturated yaw loop
had to be inferred. With this file it can be read.
"""

from __future__ import annotations

import csv
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

KEYS = ("up", "down", "forward", "back", "left", "right", "yaw_left", "yaw_right")

STREAM_COLUMNS = (
    "stateEstimate.z", "stateEstimate.vz",
    "posCtl.targetZ", "posCtl.targetVZ", "posEstAlt.estimatedZ", "posEstAlt.velocityZ",
    "stabilizer.thrust", "stabilizer.roll", "stabilizer.pitch", "stabilizer.yaw", "gyro.z",
    "motor.m1", "motor.m2", "motor.m3", "motor.m4",
    "pm.vbat", "lighthouse.bsReceive",
)


class FlightTrace:
    """Appends one row per telemetry sample while a manual flight runs."""

    def __init__(self, path: Path, controller: Any, *, tuning: str = "") -> None:
        self.path = path
        self._controller = controller
        self._tuning = tuning
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow([
            "recorded_at", "control_state", "keys", "target_height_m", "climb_velocity_m_s",
            *STREAM_COLUMNS, "tuning",
        ])
        self.rows = 0

    def sample(self, snap: Any) -> None:
        with self._lock:
            if self._file.closed:
                return
            intent = getattr(self._controller, "intent", None)
            keys = "+".join(k for k in KEYS if intent is not None and getattr(intent, k, False))
            self._writer.writerow([
                datetime.now(UTC).isoformat(),
                str(getattr(self._controller, "state", "")),
                keys,
                round(float(getattr(self._controller, "target_height", 0.0)), 4),
                round(float(getattr(self._controller, "climb_velocity", 0.0)), 4),
                *(snap.get(name) for name in STREAM_COLUMNS),
                self._tuning if self.rows == 0 else "",
            ])
            self.rows += 1
            if self.rows % 10 == 0:
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()


def subscribe(stream: Any, trace: FlightTrace) -> Callable[[], None]:
    """Feed a trace from a telemetry stream; returns the unsubscribe."""

    def on_sample(snap: Any) -> None:
        try:
            trace.sample(snap)
        except (OSError, ValueError):
            log.warning("flight trace write failed")

    unsubscribe: Callable[[], None] = stream.subscribe(on_sample)
    return unsubscribe
