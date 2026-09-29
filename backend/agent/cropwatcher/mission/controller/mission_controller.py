"""The mission controller: takes a saved mission and flies it.

WHAT IT RECEIVES
    A Mission (mission/plan/mission.py) that has already passed validation
    AS IT WILL BE FLOWN (Mission.from_start): `home` is where the drone really
    is at Start, `points` are only the points to fly (an end point has already
    been applied — points after it are gone), and `return_to_start` already
    says whether to come back. Every point and every leg is inside the room's
    geofence and clear of its obstacles, from that real start. The session
    also checked the battery covers it and the checks passed. Fly `points`
    in order and honour `return_to_start` — nothing else to interpret.

WHAT IT FLIES WITH
    The manual flight system (flight/manual.py ManualController), already armed
    by the session, seen through MissionFlight (flight.py). The controller asks
    it for goals — hold_at() to take off, fly_to() for each point, land() at the
    end — and watches its state. It never talks to the drone.

WHAT IT DOES
    take off to the cruise height;
    for each inspection point, in order:
        fly_to() the point                     TRANSIT
        wait for the drone to settle on it     ARRIVING
        hold for the point's hold_s            HOLDING  (current_point_id set)
        report the point complete              POINT_COMPLETE
    fly back over home (the real start) if the mission says so  RETURNING
    land                                       LANDING → DONE

THE BODY IS HANNAH'S (docs/handoffs/mission-controller.txt). Until it is built,
BUILT is False and start() refuses — and the session checks BUILT before it
arms anything, so no motor turns for a mission this cannot fly.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from cropwatcher.mission.controller.events import MissionEvent, MissionState
from cropwatcher.mission.controller.flight import MissionFlight
from cropwatcher.mission.plan.mission import Mission

#: Starting values, each a guess until the lab replaces it with a measurement
#: and cites the flight trace beside it (the ticket, rule 9).
ARRIVE_M = 0.10
SETTLE_S = 1.0
SETTLE_TIMEOUT_S = 10.0
TRANSIT_MARGIN_S = 5.0
TICK_S = 0.1


class MissionError(RuntimeError):
    """The mission cannot start or continue. Words for the operator."""


class MissionController:
    #: False until the state machine below is built. The session refuses to
    #: arm a mission while it is False.
    BUILT = False

    def __init__(self, mission: Mission, flight: MissionFlight, *,
                 on_event: Callable[[MissionEvent], None],
                 clock: Callable[[], float] = time.monotonic,
                 tick_s: float = TICK_S) -> None:
        self.mission = mission
        self._flight = flight
        self._on_event = on_event
        self._clock = clock
        self._tick_s = tick_s
        self._state = MissionState.IDLE

    def start(self) -> None:
        """Run tick() on the controller's own thread, 10 times a second."""
        raise MissionError(
            "The mission controller is not built yet (docs/handoffs/"
            "mission-controller.txt), so this mission cannot fly. Nothing was armed.")

    def tick(self) -> None:
        """One step of the state machine. Tests drive this with a fake clock."""

    def abort(self, reason: str) -> None:
        """Land now; the state becomes ABORTED. Safe to call twice."""

    @property
    def state(self) -> MissionState:
        return self._state

    @property
    def current_point_id(self) -> str | None:
        """The inspection point being held, ONLY while HOLDING; None otherwise.
        Read from other threads: it stamps every telemetry row and frame."""
        return None

    @property
    def completed_point_ids(self) -> tuple[str, ...]:
        return ()
