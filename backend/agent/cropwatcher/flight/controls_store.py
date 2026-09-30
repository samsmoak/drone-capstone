"""The operator's choice of arrow frame and their marked spot, kept on the laptop.

One file, `controls.json` in the agent's data folder (paths.py). It belongs to
the LIGHTHOUSE SETUP, not to a room or a mission: the operator's spot is a
point in the base stations' frame, and Manual flight has no room selected.
Re-running `cropwatcher geometry` redefines that frame, so a spot marked
before it means somewhere else afterwards — mark it again (manual-control.txt).

A missing or unreadable file is the defaults, never an error: the arrows must
work on a fresh laptop and after a bad write.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cropwatcher.flight.keyframe import KeyFrame
from cropwatcher.paths import data_dir

log = logging.getLogger(__name__)

FILENAME = "controls.json"

#: A marked spot further than this from the origin is not a place in a room
#: the base stations can cover (their range is about 5 m each way) — it is a
#: typo or a corrupt file.
MAX_SPOT_M = 20.0


@dataclass(frozen=True)
class Controls:
    key_frame: KeyFrame = KeyFrame.OPERATOR
    #: Where the operator stands, room metres; None: use the takeoff spot.
    operator: tuple[float, float] | None = None
    operator_marked_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_frame": str(self.key_frame),
            "operator": None if self.operator is None else [self.operator[0], self.operator[1]],
            "operator_marked_at": self.operator_marked_at,
        }

    def with_frame(self, frame: KeyFrame) -> Controls:
        return replace(self, key_frame=frame)

    def with_operator(self, xy: tuple[float, float] | None) -> Controls:
        if xy is None:
            return replace(self, operator=None, operator_marked_at=None)
        return replace(self, operator=(round(xy[0], 4), round(xy[1], 4)),
                       operator_marked_at=datetime.now(UTC).isoformat(timespec="seconds"))


def valid_spot(x: float, y: float) -> bool:
    return math.isfinite(x) and math.isfinite(y) and abs(x) <= MAX_SPOT_M and abs(y) <= MAX_SPOT_M


class ControlsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or data_dir() / FILENAME

    def load(self) -> Controls:
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            return Controls()
        except (OSError, ValueError):
            log.warning("controls: %s is unreadable; using the defaults", self.path)
            return Controls()
        if not isinstance(raw, dict):
            return Controls()
        try:
            frame = KeyFrame(raw.get("key_frame", KeyFrame.OPERATOR))
        except ValueError:
            frame = KeyFrame.OPERATOR
        spot = raw.get("operator")
        operator: tuple[float, float] | None = None
        if (isinstance(spot, list) and len(spot) == 2
                and all(isinstance(v, int | float) for v in spot)
                and valid_spot(float(spot[0]), float(spot[1]))):
            operator = (float(spot[0]), float(spot[1]))
        marked_at = raw.get("operator_marked_at")
        return Controls(frame, operator,
                        marked_at if operator is not None and isinstance(marked_at, str) else None)

    def save(self, controls: Controls) -> None:
        """Written whole, then renamed over the old file: a crash mid-write
        leaves the previous choice, never half a file."""
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(controls.to_dict(), indent=2))
        os.replace(tmp, path)
