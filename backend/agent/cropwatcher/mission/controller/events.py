"""The mission controller's states and events — its contract with the rest of
the system.

The session publishes every event to the desktop app, and POINT_COMPLETE is
what the data pipeline's live runner will listen for. Change a name here and
both of those break, so these are fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MissionState(StrEnum):
    IDLE = "idle"
    TAKING_OFF = "taking_off"
    TRANSIT = "transit"            # gliding towards the next inspection point
    ARRIVING = "arriving"          # at the point, waiting for the drone to settle
    HOLDING = "holding"            # recording at the point
    RETURNING = "returning"        # flying back over home
    LANDING = "landing"
    DONE = "done"                  # terminal: landed, every point completed
    ABORTED = "aborted"            # terminal: a guard, a timeout, the flight ended early
    INTERRUPTED = "interrupted"    # terminal: the operator took over with the keys
    FAILED = "failed"              # terminal: an exception in the controller


TERMINAL_STATES = frozenset({
    MissionState.DONE, MissionState.ABORTED, MissionState.INTERRUPTED, MissionState.FAILED,
})


class EventKind(StrEnum):
    STARTED = "started"
    TAKEOFF_DONE = "takeoff_done"
    POINT_ARRIVED = "point_arrived"
    HOLD_STARTED = "hold_started"
    POINT_COMPLETE = "point_complete"    # the pipeline's live runner listens for this
    RETURNING = "returning"
    LANDED = "landed"
    DONE = "done"
    ABORTED = "aborted"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


TERMINAL_EVENTS = frozenset({
    EventKind.DONE, EventKind.ABORTED, EventKind.INTERRUPTED, EventKind.FAILED,
})


@dataclass(frozen=True)
class MissionEvent:
    kind: EventKind
    at_s: float                 # the controller's clock() when it happened
    point_id: str | None        # set for every point event
    detail: str                 # a sentence the operator reads: "P2 reached, 4 cm off"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "at_s": round(self.at_s, 3),
                "point_id": self.point_id, "detail": self.detail}
