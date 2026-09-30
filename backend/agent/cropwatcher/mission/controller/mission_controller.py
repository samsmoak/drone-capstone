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

THIS BODY IS SAMUEL'S EXPERIMENT (experiment/samuel, 2026-09-30), built to THE
SPEC in docs/handoffs/sprint-1/undone/mission-controller.txt — every rule is
cited by its number below (S1, T8, E5 ...). Hannah's ticket for the same body
is still open; this is not it.

HOW IT KEEPS THE SPEC'S PROMISES ACROSS THREADS
    One lock guards the state machine, and every command to the flight
    (hold_at, fly_to, land) is given while holding it, so an abort() from the
    session can never interleave with a tick half-way through a decision: once
    a mission is terminal, nothing more is commanded (T1, T2).

    Events are QUEUED under that lock and DELIVERED with no lock held (E5),
    by one caller at a time, in the order they were queued. Delivering
    straight after unlocking would let a tick's POINT_COMPLETE race an
    abort()'s ABORTED to the listener and arrive after it — the one ordering
    E1 forbids. A listener may call back into the controller (the session
    reads state, current_point_id and completed_point_ids from inside it).

    Time is read ONLY through `clock` (the seam, 3). The thread sleeps in real
    time between ticks, but every decision is taken on `clock`.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from cropwatcher.flight.manual import CLIMB_RATE_M_S, MOVE_SPEED_M_S, ControlState
from cropwatcher.mission.controller.events import (
    TERMINAL_STATES,
    EventKind,
    MissionEvent,
    MissionState,
)
from cropwatcher.mission.controller.flight import MissionFlight
from cropwatcher.mission.plan.mission import InspectionPoint, Mission

log = logging.getLogger(__name__)

#: Starting values, each a guess until the lab replaces it with a measurement
#: and cites the flight trace beside it (mission-verification.txt, PART 4).
ARRIVE_M = 0.10
SETTLE_S = 1.0
SETTLE_TIMEOUT_S = 10.0
TRANSIT_MARGIN_S = 5.0
TICK_S = 0.1

#: The flight has come down, or was stopped, without being asked to (T3).
_ENDED = (ControlState.LANDING, ControlState.LANDED, ControlState.STOPPED,
          ControlState.IDLE)
#: The states a mission is at an inspection point in — a terminal event from
#: one of them carries that point's id (E3).
_AT_A_POINT = (MissionState.TRANSIT, MissionState.ARRIVING, MissionState.HOLDING)

_TERMINAL_EVENT = {
    MissionState.DONE: EventKind.DONE,
    MissionState.ABORTED: EventKind.ABORTED,
    MissionState.INTERRUPTED: EventKind.INTERRUPTED,
    MissionState.FAILED: EventKind.FAILED,
}


class MissionError(RuntimeError):
    """The mission cannot start or continue. Words for the operator."""


class MissionController:
    #: The session refuses to arm a mission while this is False.
    BUILT = True

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

        self._lock = threading.Lock()
        self._events: deque[MissionEvent] = deque()
        self._dispatching = False
        self._started = False
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()

        self._index = 0                             # the point being flown to
        self._current_point_id: str | None = None
        self._completed: list[str] = []
        self._takeoff_xy: tuple[float, float] | None = None
        #: The commanded spot the next leg starts from: (x, y, height).
        self._leg_from: tuple[float, float, float] | None = None
        self._landing_asked = False                 # this controller called land()
        self._deadline: float | None = None
        self._deadline_what = ""
        self._settle_began: float | None = None     # T10: never restarted by drift
        self._within_since: float | None = None     # T9: restarted by drift
        self._returning_settle = False              # RETURNING: arrived, settling
        self._hold_began: float | None = None

    # ── the interface ────────────────────────────────────────────────────

    def start(self) -> None:
        """Checks, the takeoff, then the thread (S1, S2)."""
        with self._lock:
            if self._started or self._state is not MissionState.IDLE:
                raise MissionError("This mission has already been started.")       # S1
            if not self._flight.assisted:
                raise MissionError(                                                 # S1
                    "The drone has no position from the base stations, so a mission "
                    "cannot fly. Nothing was commanded.")
            self._started = True
            now = self._clock()
            refused: Exception | None = None
            self._queue(EventKind.STARTED, now, None,
                        f"Mission {self.mission.name} started: taking off to "
                        f"{self.mission.cruise_height_m:.2f} m")
            try:
                self._flight.hold_at(self.mission.cruise_height_m)                  # S2
            except Exception as e:
                # Not in THE SPEC: the flight system refused the takeoff (not
                # armed, a height it will not fly). Nothing is airborne, so
                # there is nothing to land; the mission ends FAILED, and the
                # caller hears it did not start.
                self._end_locked(MissionState.FAILED, now,
                                 f"The takeoff was refused: {e}")
                refused = e
            else:
                self._state = MissionState.TAKING_OFF
                self._set_deadline(                                                  # T7
                    now, self.mission.cruise_height_m / CLIMB_RATE_M_S + TRANSIT_MARGIN_S,
                    "the takeoff")
        self._dispatch()
        if refused is not None:
            raise MissionError(f"The takeoff was refused: {refused}") from refused
        if self._tick_s > 0:                                                         # S2
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="mission-controller")
            self._thread.start()

    def tick(self) -> None:
        """One step of the state machine. Tests drive this with a fake clock."""
        with self._lock:
            if self._started:
                now = self._clock()
                try:
                    self._step_locked(now)
                except Exception as e:
                    self._fail_locked(now, e)
        self._dispatch()

    def abort(self, reason: str) -> None:
        """Land now; the state becomes ABORTED. Safe to call twice (A1, A2)."""
        with self._lock:
            if self._state in TERMINAL_STATES:                                      # A1
                return
            now = self._clock()
            state = self._flight.state
            if state in (ControlState.FLYING, ControlState.ARMED):                  # A2
                self._land_locked()
            self._end_locked(MissionState.ABORTED, now, reason)
        self._dispatch()

    @property
    def state(self) -> MissionState:
        with self._lock:
            return self._state

    @property
    def current_point_id(self) -> str | None:
        """The inspection point being held, ONLY while HOLDING; None otherwise.
        Read from other threads: it stamps every telemetry row and frame."""
        with self._lock:                                                            # C2
            return self._current_point_id

    @property
    def completed_point_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._completed)

    # ── one tick (T1–T5) ─────────────────────────────────────────────────

    def _step_locked(self, now: float) -> None:
        if self._state in TERMINAL_STATES:                                          # T1
            return
        flight = self._flight
        if flight.operator_override:                                                # T2
            self._end_locked(MissionState.INTERRUPTED, now,
                             "The operator took over with the keys; the drone is "
                             "under manual control.")
            return
        state = flight.state
        if state in _ENDED and not self._landing_asked:                             # T3
            self._end_locked(MissionState.ABORTED, now,
                             f"The flight ended under the mission: the drone is {state}.")
            return
        if self._deadline is not None and now >= self._deadline:                   # T4
            if state is not ControlState.STOPPED:
                self._land_locked()
            self._end_locked(MissionState.ABORTED, now,
                             f"{self._deadline_what[:1].upper()}{self._deadline_what[1:]} "
                             f"timed out; landing.")
            return
        step = {                                                                    # T5
            MissionState.TAKING_OFF: self._taking_off,
            MissionState.TRANSIT: self._transit,
            MissionState.ARRIVING: self._arriving,
            MissionState.HOLDING: self._holding,
            MissionState.RETURNING: self._returning,
            MissionState.LANDING: self._landing,
        }.get(self._state)
        if step is not None:
            step(now)

    # ── the steps (T6–T15) ───────────────────────────────────────────────

    def _taking_off(self, now: float) -> None:
        flight = self._flight
        if flight.goal_active or flight.state is not ControlState.FLYING:           # T6
            return
        target = flight.target
        if target is None:
            # THE SPEC records flight.target here and has no answer for a
            # flight that has not reported a position yet: the exception path
            # (land, FAILED) is the answer, in words.
            raise MissionError("the drone reached its height without reporting a "
                               "position, so there is no takeoff spot")
        self._takeoff_xy = (target.x, target.y)
        self._leg_from = (target.x, target.y, self.mission.cruise_height_m)
        self._queue(EventKind.TAKEOFF_DONE, now, None,
                    f"Took off: holding at {self.mission.cruise_height_m:.2f} m")
        self._begin_point(now)

    def _begin_point(self, now: float) -> None:
        point = self._point
        self._state = MissionState.TRANSIT
        self._fly_leg_locked(now, (point.x_m, point.y_m, point.z_m),               # T8
                             f"the flight to {point.id}")

    def _transit(self, now: float) -> None:
        if self._flight.goal_active:                                                # T8
            return
        point = self._point
        self._queue(EventKind.POINT_ARRIVED, now, point.id,
                    f"{point.id} reached, {self._flight.drift_m * 100:.0f} cm off")
        self._state = MissionState.ARRIVING
        self._begin_settle(now, f"settling at {point.id}")

    def _arriving(self, now: float) -> None:
        if not self._settled(now):                                                  # T9
            return
        point = self._point
        self._deadline = None
        self._current_point_id = point.id                                           # T11
        self._hold_began = now
        self._queue(EventKind.HOLD_STARTED, now, point.id,
                    f"Holding at {point.id} for {point.hold_s:.0f} s")
        self._state = MissionState.HOLDING

    def _holding(self, now: float) -> None:
        point = self._point
        assert self._hold_began is not None
        if now - self._hold_began < point.hold_s:                                   # T12
            return
        self._current_point_id = None                                               # T13
        self._completed.append(point.id)
        self._queue(EventKind.POINT_COMPLETE, now, point.id, f"{point.id} complete")
        self._leg_from = (point.x_m, point.y_m, point.z_m)
        # Each branch sets its state BEFORE commanding, so a command that
        # raises is reported from the state it was entering (E3).
        if self._index + 1 < len(self.mission.points):
            self._index += 1
            self._begin_point(now)
        elif self.mission.return_to_start:                                          # T14
            assert self._takeoff_xy is not None
            x, y = self._takeoff_xy
            self._queue(EventKind.RETURNING, now, None, "Returning over the start")
            self._state = MissionState.RETURNING
            self._returning_settle = False
            self._fly_leg_locked(now, (x, y, self.mission.cruise_height_m),
                                 "the flight back to the start")
        else:                                                                       # T14
            self._state = MissionState.LANDING
            self._land_locked()

    def _returning(self, now: float) -> None:
        if not self._returning_settle:                                              # T14, T8
            if self._flight.goal_active:
                return
            self._returning_settle = True
            self._begin_settle(now, "settling over the start")
            return
        if not self._settled(now):                                                  # T14, T9
            return
        self._deadline = None
        self._state = MissionState.LANDING
        self._land_locked()

    def _landing(self, now: float) -> None:
        state = self._flight.state
        if state is ControlState.LANDED:                                            # T15
            self._queue(EventKind.LANDED, now, None, "Landed")
            self._end_locked(MissionState.DONE, now,
                             f"Mission complete: {len(self._completed)} of "
                             f"{len(self.mission.points)} points inspected")
        elif state in (ControlState.STOPPED, ControlState.IDLE):                    # T15
            self._end_locked(MissionState.ABORTED, now,
                             f"The flight stopped before it landed: the drone is {state}.")

    # ── helpers (lock held) ──────────────────────────────────────────────

    @property
    def _point(self) -> InspectionPoint:
        return self.mission.points[self._index]

    def _fly_leg_locked(self, now: float, to: tuple[float, float, float],
                        what: str) -> None:
        """fly_to() once, and the leg's timeout from this call (T8)."""
        assert self._leg_from is not None
        leg = math.dist(self._leg_from, to)
        self._flight.fly_to(*to)
        self._set_deadline(now, leg / MOVE_SPEED_M_S + TRANSIT_MARGIN_S, what)

    def _begin_settle(self, now: float, what: str) -> None:
        self._settle_began = now
        self._within_since = None
        self._set_deadline(now, SETTLE_TIMEOUT_S, what)                            # T10

    def _settled(self, now: float) -> bool:
        """drift_m within ARRIVE_M continuously for SETTLE_S (T9)."""
        if self._flight.drift_m > ARRIVE_M:
            self._within_since = None
            return False
        if self._within_since is None:
            self._within_since = now
        return now - self._within_since >= SETTLE_S

    def _set_deadline(self, now: float, seconds: float, what: str) -> None:
        self._deadline = now + seconds
        self._deadline_what = what

    def _land_locked(self) -> None:
        self._landing_asked = True
        self._flight.land()

    def _fail_locked(self, now: float, error: Exception) -> None:
        """An exception inside tick(): land if airborne, then FAILED. It never
        escapes, and never stops the manual system's own loop."""
        log.exception("mission controller: a tick failed")
        if self._state in TERMINAL_STATES:
            return
        try:
            if self._flight.state is ControlState.FLYING:
                self._land_locked()
        except Exception:
            log.exception("mission controller: land() failed after a tick failed")
        self._end_locked(MissionState.FAILED, now, f"The mission controller failed: {error}")

    def _end_locked(self, state: MissionState, now: float, detail: str) -> None:
        """The one way into a terminal state: its event, in the same step (E1,
        E2), with the point it ended at (E3); current_point_id cleared (C1)."""
        point_id = self._point.id if self._state in _AT_A_POINT else None
        self._current_point_id = None
        self._deadline = None
        self._state = state
        self._queue(_TERMINAL_EVENT[state], now, point_id, detail)
        self._halt.set()

    def _queue(self, kind: EventKind, now: float, point_id: str | None, detail: str) -> None:
        self._events.append(MissionEvent(kind=kind, at_s=now, point_id=point_id,
                                         detail=detail))

    # ── delivery and the thread ──────────────────────────────────────────

    def _dispatch(self) -> None:
        """Deliver queued events in order, one caller at a time, no lock held
        (E5). Whoever finds nobody delivering delivers everything queued —
        including events queued by others meanwhile."""
        while True:
            with self._lock:
                if self._dispatching or not self._events:
                    return
                self._dispatching = True
                event = self._events.popleft()
            try:
                self._on_event(event)
            except Exception:
                log.exception("mission controller: the event listener failed on %s",
                              event.kind)
            finally:
                with self._lock:
                    self._dispatching = False

    def _run(self) -> None:
        """tick() every tick_s until the mission ends. Scheduled on `clock`."""
        next_tick = self._clock()
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception:                       # tick() already contains its own
                log.exception("mission controller: the thread's tick failed")
            next_tick += self._tick_s
            delay = next_tick - self._clock()
            if delay < -self._tick_s:
                next_tick = self._clock()           # fell behind: resync, never burst
            self._halt.wait(max(0.0, delay))
