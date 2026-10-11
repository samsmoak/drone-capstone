"""The mission controller — how a saved mission is flown.

It takes a validated Mission and flies it by giving goals to the manual flight
system (flight/manual.py): hold_at() for the takeoff height, fly_to() for each
inspection point. It never commands the drone itself, so autonomous flight
inherits everything tuned into manual flight — the easing, the leash, the
guards, the heartbeat dead-man — and nothing else.
"""

from cropwatcher.mission.controller.events import (
    TERMINAL_STATES,
    EventKind,
    MissionEvent,
    MissionState,
)
from cropwatcher.mission.controller.flight import MissionFlight
from cropwatcher.mission.controller.mission_controller import (
    MissionController,
    MissionError,
)

__all__ = [
    "TERMINAL_STATES", "EventKind", "MissionController", "MissionError",
    "MissionEvent", "MissionFlight", "MissionState",
]
