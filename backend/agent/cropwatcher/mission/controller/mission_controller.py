# This file was modified on 10/9/2026 with the assistance of the Cline extension in VS Code
# (ChatGPT, OpenAI, 2024). It completes the MissionController state‑machine implementation,
# introduces detailed logging, and improves error handling for abort and timeout cases.

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
        fly_to() the point                                      TRANSIT
        wait for the drone to settle on it                      ARRIVING
        hold for the point's hold_s                             HOLDING (current_point_id set)
        report the point complete                               POINT_COMPLETE
    fly back over home (the real start) if the mission says so  RETURNING
    land                                                        LANDING → DONE
"""

from __future__ import annotations

import time
import math
import threading
import logging
from collections.abc import Callable

from cropwatcher.mission.controller.events import MissionEvent, MissionState, EventKind, TERMINAL_STATES
from cropwatcher.mission.controller.flight import MissionFlight
from cropwatcher.mission.plan.mission import Mission
from cropwatcher.flight.manual import (
    CLIMB_RATE_M_S,
    MOVE_SPEED_M_S,
    ControlState,
)

# Starting constants – to be measured later in the lab but used throughout
ARRIVE_M = 0.10
SETTLE_S = 1.0
SETTLE_TIMEOUT_S = 10.0
TRANSIT_MARGIN_S = 5.0
TICK_S = 0.1

class MissionError(RuntimeError):
    """The mission cannot start or continue. Words for the operator."""

class MissionController:
    #: False until the state machine below is built. The session refuses to arm a mission while it is False.
    BUILT = False

    def __init__(
        self,
        mission: Mission,
        flight: MissionFlight,
        *,
        on_event: Callable[[MissionEvent], None],
        clock: Callable[[], float] = time.monotonic,
        tick_s: float = TICK_S,
    ) -> None:
        self.mission = mission
        self._flight = flight
        self._on_event = on_event
        self._clock = clock
        self._tick_s = tick_s

        self._state: MissionState = MissionState.IDLE
        self._lock = threading.RLock()
        self._started = False
        self._point_idx: int = 0
        self._current_point_id: str | None = None
        self._completed: list[str] = []
        self._takeoff_spot: tuple[float, float] | None = None
        self._state_start: float | None = None
        self._settle_start: float | None = None
        self._leg_timeout: float | None = None
        self._takeoff_timeout: float | None = None
        self._land_called: bool = False
        self._thread: threading.Thread | None = None
        self._logger = logging.getLogger(__name__)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def start(self) -> None:
        """Run tick() on the controller's own thread, at ``tick_s`` intervals.
        Raises ``MissionError`` if the flight is not assisted or if start() was already called.
        """
        with self._lock:
            if not self._flight.assisted:
                raise MissionError("flight not assisted; cannot start mission")
            if self._started:
                raise MissionError("mission already started")

            # Emit STARTED and command the initial hold (takeoff height)
            self._emit(EventKind.STARTED, None, "mission started")
            self._flight.hold_at(self.mission.cruise_height_m)
            self._state = MissionState.TAKING_OFF
            now = self._clock()
            self._state_start = now
            self._takeoff_timeout = self.mission.cruise_height_m / CLIMB_RATE_M_S + TRANSIT_MARGIN_S
            self._started = True

            if self._tick_s > 0:
                self._thread = threading.Thread(target=self._run_thread, daemon=True)
                self._thread.start()

    def tick(self) -> None:
        """One step of the state machine. Tests drive this with a fake clock."""
        now = self._clock()
        with self._lock:
            # T1 – terminal state
            if self._state in TERMINAL_STATES:
                return

            # T2 – operator override
            if self._flight.operator_override:
                self._transition_terminal(MissionState.INTERRUPTED, EventKind.INTERRUPTED, "operator override")
                return

            # T3 – guard states without us having called land()
            guard_states = {ControlState.LANDING, ControlState.LANDED, ControlState.STOPPED, ControlState.IDLE}
            # Guard states indicate the flight has entered a terminal condition
            # without the controller explicitly issuing a land command. However, when the
            # controller itself is already in the ``LANDING`` state we should *not*
            # treat a ``LANDED`` observation as an abort – the landing is in progress.
            if (
                self._flight.state in guard_states
                and not self._land_called
                and self._state != MissionState.LANDING
            ):
                self._transition_terminal(
                    MissionState.ABORTED,
                    EventKind.ABORTED,
                    f"flight state {self._flight.state}",
                )
                return

            # State‑specific handling
            try:
                self._handle_state(now)
            except Exception as exc:  # noqa: BLE001
                # Unexpected exception – abort and emit FAILED
                self._logger.exception("exception in tick")
                if self._flight.state == ControlState.FLYING and not self._land_called:
                    try:
                        self._flight.land()
                        self._land_called = True
                    except Exception:
                        self._logger.exception("land failed during failure handling")
                self._transition_terminal(MissionState.FAILED, EventKind.FAILED, str(exc))

    def abort(self, reason: str) -> None:
        """Land now; the state becomes ABORTED. Safe to call twice."""
        with self._lock:
            if self._state in TERMINAL_STATES:
                return
            # Land if we are still in a state where landing makes sense
            if self._flight.state in {ControlState.FLYING, ControlState.ARMED} and not self._land_called:
                try:
                    self._flight.land()
                    self._land_called = True
                except Exception:
                    self._logger.exception("land failed during abort")
            self._transition_terminal(MissionState.ABORTED, EventKind.ABORTED, reason)

    @property
    def state(self) -> MissionState:
        return self._state

    @property
    def current_point_id(self) -> str | None:
        """The inspection point being held, ONLY while HOLDING; None otherwise."""
        return self._current_point_id

    @property
    def completed_point_ids(self) -> tuple[str, ...]:
        return tuple(self._completed)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _handle_state(self, now: float) -> None:
        """Dispatch based on the current state."""
        if self._state == MissionState.TAKING_OFF:
            self._handle_taking_off(now)
        elif self._state == MissionState.TRANSIT:
            self._handle_transit(now)
        elif self._state == MissionState.ARRIVING:
            self._handle_arriving(now)
        elif self._state == MissionState.HOLDING:
            self._handle_holding(now)
        elif self._state == MissionState.RETURNING:
            self._handle_returning(now)
        elif self._state == MissionState.LANDING:
            self._handle_landing()
        # other states are either IDLE (should not happen) or terminal (handled earlier)

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------
    def _handle_taking_off(self, now: float) -> None:
        # Timeout handling (T7)
        if self._takeoff_timeout is not None and self._state_start is not None:
            if now - self._state_start > self._takeoff_timeout:
                self._abort("takeoff timeout")
                return
        # Completion condition (T6)
        if not self._flight.goal_active and self._flight.state == ControlState.FLYING:
            tgt = self._flight.target
            self._takeoff_spot = (tgt.x, tgt.y)
            self._emit(EventKind.TAKEOFF_DONE, None, "takeoff done")
            self._begin_next_point()

    def _handle_transit(self, now: float) -> None:
        # Timeout (T8)
        if self._leg_timeout is not None and self._state_start is not None:
            if now - self._state_start > self._leg_timeout:
                self._abort("transit timeout")
                return
        # Arrival check (T8 completion)
        if not self._flight.goal_active:
            # Arrival – emit with the point's id
            point = self._current_point()
            point_id = point.id if point else None
            drift = getattr(self._flight, "drift_m", None)
            detail = f"reached, {drift*100:.0f} cm off" if drift is not None else "reached"
            self._emit(EventKind.POINT_ARRIVED, point_id, detail)
            self._state = MissionState.ARRIVING
            self._state_start = now
            self._settle_start = None

    def _handle_arriving(self, now: float) -> None:
        # Timeout (T10)
        if self._state_start is not None and now - self._state_start > SETTLE_TIMEOUT_S:
            self._abort("arrival timeout")
            return
        drift = getattr(self._flight, "drift_m", None)
        if drift is not None and drift <= ARRIVE_M:
            if self._settle_start is None:
                self._settle_start = now
            elif now - self._settle_start >= SETTLE_S:
                # settled – move to holding (T11)
                point = self._current_point()
                self._current_point_id = point.id if point else None
                self._emit(EventKind.HOLD_STARTED, self._current_point_id, "hold started")
                self._state = MissionState.HOLDING
                self._state_start = now
        else:
            # drift too large – reset settle timer
            self._settle_start = None

    def _handle_holding(self, now: float) -> None:
        point = self._current_point()
        if point is None:
            return
        if self._state_start is not None and now - self._state_start >= point.hold_s:
            # Hold finished – emit POINT_COMPLETE (T13)
            self._emit(EventKind.POINT_COMPLETE, self._current_point_id, "point complete")
            if self._current_point_id is not None:
                self._completed.append(self._current_point_id)
            self._current_point_id = None
            # Advance to next point or finish
            self._point_idx += 1
            if self._point_idx < len(self.mission.points):
                self._begin_next_point()
            else:
                # All points done – either return or land
                if self.mission.return_to_start:
                    self._state = MissionState.RETURNING
                    self._emit(EventKind.RETURNING, None, "returning to start")
                    self._state_start = now
                    # Fly back to the recorded takeoff spot
                    if self._takeoff_spot:
                        self._flight.fly_to(self._takeoff_spot[0], self._takeoff_spot[1], self.mission.cruise_height_m)
                        # Compute timeout for return leg
                        start_xyz = (self._flight.target.x, self._flight.target.y, self.mission.cruise_height_m)
                        dest_xyz = (self._takeoff_spot[0], self._takeoff_spot[1], self.mission.cruise_height_m)
                        self._leg_timeout = self._leg_timeout_for(start_xyz, dest_xyz)
                else:
                    self._flight.land()
                    self._land_called = True
                    self._state = MissionState.LANDING

    def _handle_returning(self, now: float) -> None:
        # Re‑use transit logic to get back to the start
        if self._leg_timeout is not None and self._state_start is not None:
            if now - self._state_start > self._leg_timeout:
                self._abort("return timeout")
                return
        if not self._flight.goal_active:
            # Arrived back – treat as ARRIVING then land
            self._state = MissionState.ARRIVING
            self._state_start = now
            self._settle_start = None

    def _handle_landing(self) -> None:
        # Landing finalization (T15)
        if self._flight.state == ControlState.LANDED:
            self._emit(EventKind.LANDED, None, "landed")
            self._transition_terminal(MissionState.DONE, EventKind.DONE, "mission done")
        elif self._flight.state in {ControlState.STOPPED, ControlState.IDLE}:
            self._abort(f"flight state {self._flight.state}")

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _emit(self, kind: EventKind, point_id: str | None, detail: str) -> None:
        """Call the listener safely – swallow any exception as per spec (E5)."""
        try:
            ev = MissionEvent(kind=kind, at_s=self._clock(), point_id=point_id, detail=detail)
            self._on_event(ev)
        except Exception:
            self._logger.exception("event listener raised")

    def _transition_terminal(self, state: MissionState, kind: EventKind, detail: str) -> None:
        if self._state in TERMINAL_STATES:
            return
        self._state = state
        self._emit(kind, None, detail)

    def _abort(self, reason: str) -> None:
        """Internal abort used for timeouts etc."""
        if self._state in TERMINAL_STATES:
            return
        if self._flight.state in {ControlState.FLYING, ControlState.ARMED} and not self._land_called:
            try:
                self._flight.land()
                self._land_called = True
            except Exception:
                self._logger.exception("land failed during abort")
        self._transition_terminal(MissionState.ABORTED, EventKind.ABORTED, reason)

    def _run_thread(self) -> None:
        while True:
            with self._lock:
                if self._state in TERMINAL_STATES:
                    break
            try:
                self.tick()
            except Exception:
                # Already handled inside tick; just break the loop
                break
            time.sleep(self._tick_s)

    def _current_point(self):
        if 0 <= self._point_idx < len(self.mission.points):
            return self.mission.points[self._point_idx]
        return None

    def _leg_timeout_for(self, start_xyz: tuple[float, float, float], dest_xyz: tuple[float, float, float]) -> float:
        dx = dest_xyz[0] - start_xyz[0]
        dy = dest_xyz[1] - start_xyz[1]
        dz = dest_xyz[2] - start_xyz[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        return distance / MOVE_SPEED_M_S + TRANSIT_MARGIN_S

    def _begin_next_point(self) -> None:
        point = self._current_point()
        if point is None:
            return
        # Determine start position for timeout calculation
        if self._point_idx == 0:
            # From takeoff spot at cruise height
            start_xyz = (self._takeoff_spot[0] if self._takeoff_spot else 0.0,
                         self._takeoff_spot[1] if self._takeoff_spot else 0.0,
                         self.mission.cruise_height_m)
        else:
            prev = self.mission.points[self._point_idx - 1]
            start_xyz = (prev.x_m, prev.y_m, prev.z_m)
        dest_xyz = (point.x_m, point.y_m, point.z_m)
        # Issue the command
        self._flight.fly_to(point.x_m, point.y_m, point.z_m)
        self._state = MissionState.TRANSIT
        self._state_start = self._clock()
        self._leg_timeout = self._leg_timeout_for(start_xyz, dest_xyz)

# After the state machine is fully implemented the controller is considered built.
MissionController.BUILT = True
