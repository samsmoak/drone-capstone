"""The mission controller against THE SPEC, rule by rule
(docs/handoffs/sprint-1/undone/mission-controller.txt).

The flight here is SCRIPTED: a stand-in satisfying MissionFlight whose state,
goal_active, drift_m and operator_override each test sets by hand, and which
records every hold_at / fly_to / land. That isolates each rule, in
milliseconds. tests/mission/test_mission_sim.py proves the same rules against
the REAL manual flight system.

Every constant is imported — no test writes 0.10 or 1.0 itself (the seam, 4).
Every controller any test builds is checked for E1 when the test ends.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

import pytest

from cropwatcher.flight.manual import CLIMB_RATE_M_S, MOVE_SPEED_M_S, ControlState, Fix
from cropwatcher.mission.controller import (
    TERMINAL_STATES,
    EventKind,
    MissionController,
    MissionError,
    MissionEvent,
    MissionFlight,
    MissionState,
)
from cropwatcher.mission.controller.events import TERMINAL_EVENTS
from cropwatcher.mission.controller.mission_controller import (
    ARRIVE_M,
    SETTLE_S,
    SETTLE_TIMEOUT_S,
    TICK_S,
    TRANSIT_MARGIN_S,
)
from cropwatcher.mission.plan.mission import InspectionPoint, Mission
from tests.fakes import FakeClock
from tests.mission.plans import mission

K = EventKind
TAKEOFF_SPOT = Fix(-1.0, -1.0, 0.0)          # plans.mission()'s home


class ScriptedFlight:
    """MissionFlight, driven by hand. Commands are recorded and change only
    what a real flight would change at once: land() starts a landing (or
    disarms on the ground). Arriving is the test's call, not the stand-in's."""

    def __init__(self, *, assisted: bool = True) -> None:
        self.state = ControlState.ARMED
        self.assisted = assisted
        self.target: Fix | None = None
        self.target_height = 0.0
        self.drift_m = 0.0
        self.goal_active = False
        self.operator_override = False
        self.calls: list[tuple] = []
        self.goal: tuple[float, float, float] | None = None
        self.fail_on: str | None = None       # a command name that raises

    def _raise_if(self, name: str) -> None:
        if self.fail_on == name:
            raise RuntimeError(f"{name} blew up")

    def hold_at(self, height_m: float) -> None:
        self._raise_if("hold_at")
        self.calls.append(("hold_at", height_m))
        self.goal_active = True
        self.target_height = height_m

    def fly_to(self, x: float, y: float, height_m: float,
               speed_m_s: float | None = None) -> None:
        self._raise_if("fly_to")
        self.calls.append(("fly_to", x, y, height_m))
        self.speed = speed_m_s
        self.goal = (x, y, height_m)
        self.goal_active = True

    def land(self) -> None:
        self._raise_if("land")
        self.calls.append(("land",))
        if self.state is ControlState.FLYING:
            self.state = ControlState.LANDING
        elif self.state is ControlState.ARMED:
            self.state = ControlState.IDLE

    # the test's hand on the flight
    def airborne(self, at: Fix | None = TAKEOFF_SPOT) -> None:
        self.state = ControlState.FLYING
        self.goal_active = False
        self.target = at

    def arrive(self, drift: float = 0.0) -> None:
        assert self.goal is not None
        self.goal_active = False
        self.target = Fix(self.goal[0], self.goal[1], 0.0)
        self.drift_m = drift

    def commands(self) -> list[str]:
        return [c[0] for c in self.calls]


class BrokenFlight(ScriptedFlight):
    """A ScriptedFlight whose property named in `breaks` raises when read —
    the flight system failing under the controller."""

    breaks: str | None = None

    def __getattribute__(self, name: str):
        if name != "breaks" and name == object.__getattribute__(self, "breaks"):
            raise RuntimeError(f"{name} blew up")
        return object.__getattribute__(self, name)


def test_the_stand_ins_offer_everything_mission_flight_has():
    for flight in (ScriptedFlight(), BrokenFlight()):
        typed: MissionFlight = flight
        for name in ("state", "assisted", "target", "target_height", "drift_m",
                     "goal_active", "operator_override", "hold_at", "fly_to", "land"):
            assert hasattr(typed, name), name


_BUILT: list[MissionController] = []
_EVENTS: dict[int, list[MissionEvent]] = {}


@pytest.fixture(autouse=True)
def every_mission_ends_once():
    """E1, in every test: at most one terminal event, and nothing after it;
    exactly one once the state is terminal. E2: a terminal event means a
    terminal state."""
    _BUILT.clear()
    _EVENTS.clear()
    yield
    for mc in _BUILT:
        assert_one_terminal(_EVENTS[id(mc)], mc)


def assert_one_terminal(events: list[MissionEvent], mc: MissionController) -> None:
    terminal = [i for i, e in enumerate(events) if e.kind in TERMINAL_EVENTS]
    if mc.state in TERMINAL_STATES:
        assert len(terminal) == 1, [e.kind for e in events]
        assert terminal[0] == len(events) - 1, [e.kind for e in events]
        assert events[-1].kind.value == mc.state.value            # E2: they agree
    else:
        assert not terminal, [e.kind for e in events]


class Harness:
    def __init__(self, plan: Mission | None = None, *,
                 flight: ScriptedFlight | None = None,
                 listener: Callable[[MissionEvent], None] | None = None) -> None:
        self.clock = FakeClock()
        self.flight = flight or ScriptedFlight()
        self.events: list[MissionEvent] = []
        self.clock_at_event: list[float] = []

        def on_event(event: MissionEvent) -> None:
            self.events.append(event)
            self.clock_at_event.append(self.clock())
            if listener is not None:
                listener(event)

        self.mission = plan or mission()
        self.mc = MissionController(self.mission, self.flight, on_event=on_event,
                                    clock=self.clock, tick_s=0)
        _BUILT.append(self.mc)
        _EVENTS[id(self.mc)] = self.events

    # time
    def tick(self) -> None:
        self.clock.advance(TICK_S)
        self.mc.tick()

    def run(self, seconds: float) -> None:
        for _ in range(round(seconds / TICK_S)):
            self.tick()

    def until(self, done: Callable[[], bool], limit_s: float = 120.0) -> None:
        began = self.clock()
        while not done():
            assert self.clock() - began < limit_s, "never happened"
            self.tick()

    # reading
    def kinds(self) -> list[EventKind]:
        return [e.kind for e in self.events]

    def last(self, kind: EventKind) -> MissionEvent:
        return next(e for e in reversed(self.events) if e.kind is kind)

    # getting somewhere
    def take_off(self) -> None:
        self.mc.start()
        self.flight.airborne()
        self.tick()
        assert self.mc.state is MissionState.TRANSIT

    def to_arriving(self) -> None:
        self.flight.arrive()
        self.tick()
        assert self.mc.state is MissionState.ARRIVING

    def to_holding(self) -> None:
        self.until(lambda: self.mc.state is MissionState.HOLDING)

    def complete_point(self) -> None:
        held = self.mc.current_point_id
        self.until(lambda: self.mc.current_point_id != held)

    def fly_point(self) -> None:
        """TRANSIT → ARRIVING → HOLDING → POINT_COMPLETE, cleanly."""
        self.to_arriving()
        self.to_holding()
        self.complete_point()

    def to_returning(self) -> None:
        self.take_off()
        for _ in self.mission.points:
            self.fly_point()
        assert self.mc.state is MissionState.RETURNING

    def to_landing(self) -> None:
        self.to_returning()
        self.flight.arrive()
        self.until(lambda: self.mc.state is MissionState.LANDING)


def full_sequence(points: tuple[str, ...], returning: bool) -> list[tuple[EventKind, str | None]]:
    seq: list[tuple[EventKind, str | None]] = [(K.STARTED, None), (K.TAKEOFF_DONE, None)]
    for p in points:
        seq += [(K.POINT_ARRIVED, p), (K.HOLD_STARTED, p), (K.POINT_COMPLETE, p)]
    if returning:
        seq.append((K.RETURNING, None))
    return seq + [(K.LANDED, None), (K.DONE, None)]


def one_point(**changes) -> Mission:
    return mission(points=(InspectionPoint("P1", -1.0, 0.9, 0.40, 5.0),), **changes)


# ── BUILT ─────────────────────────────────────────────────────────────────


def test_it_is_built():
    assert MissionController.BUILT is True


# ── S1, S2 — starting ─────────────────────────────────────────────────────


def test_S1_refuses_an_unassisted_flight_and_commands_nothing():
    h = Harness(flight=ScriptedFlight(assisted=False))
    with pytest.raises(MissionError, match="position"):
        h.mc.start()
    assert h.flight.calls == []
    assert h.events == []
    assert h.mc.state is MissionState.IDLE


def test_S1_start_twice_raises_and_the_second_does_nothing():
    h = Harness()
    h.mc.start()
    calls, events = list(h.flight.calls), list(h.events)
    with pytest.raises(MissionError, match="already"):
        h.mc.start()
    assert h.flight.calls == calls
    assert h.events == events


def test_S1_a_mission_aborted_before_it_started_cannot_start():
    h = Harness()
    h.mc.abort("the operator cancelled")
    calls = list(h.flight.calls)
    with pytest.raises(MissionError):
        h.mc.start()
    assert h.flight.calls == calls


def test_S2_start_emits_started_holds_at_the_cruise_height_and_takes_off():
    h = Harness()
    h.mc.start()
    assert h.kinds() == [K.STARTED]
    assert h.events[0].point_id is None
    assert h.flight.calls == [("hold_at", h.mission.cruise_height_m)]
    assert h.mc.state is MissionState.TAKING_OFF


def test_S2_with_tick_s_zero_there_is_no_thread_the_caller_ticks():
    h = Harness()
    h.mc.start()
    h.flight.airborne()
    h.clock.advance(5.0)
    time.sleep(0.05)                                 # a thread would have ticked
    assert h.mc.state is MissionState.TAKING_OFF
    assert not any(t.name == "mission-controller" for t in threading.enumerate())
    h.tick()
    assert h.mc.state is MissionState.TRANSIT


def test_a_takeoff_the_flight_refuses_fails_the_mission_and_says_so():
    """Not in THE SPEC: hold_at() raising (nothing armed). Recorded in the
    feature doc as an experiment decision."""
    flight = ScriptedFlight()
    flight.fail_on = "hold_at"
    h = Harness(flight=flight)
    with pytest.raises(MissionError, match="takeoff was refused"):
        h.mc.start()
    assert h.kinds() == [K.STARTED, K.FAILED]
    assert h.mc.state is MissionState.FAILED
    assert "land" not in flight.commands()


# ── T1 — terminal does nothing ────────────────────────────────────────────


def test_T1_a_terminal_mission_ticks_to_nothing():
    h = Harness()
    h.take_off()
    h.mc.abort("stop")
    calls, events = list(h.flight.calls), list(h.events)
    h.flight.operator_override = True
    h.flight.state = ControlState.STOPPED
    h.run(SETTLE_TIMEOUT_S * 2)
    assert h.flight.calls == calls
    assert h.events == events


def test_ticking_before_start_does_nothing():
    h = Harness()
    h.flight.state = ControlState.IDLE
    h.run(1.0)
    assert h.events == []
    assert h.flight.calls == []
    assert h.mc.state is MissionState.IDLE


# ── T2 — the operator takes over ──────────────────────────────────────────


def _reach(h: Harness, state: MissionState) -> None:
    if state is MissionState.TAKING_OFF:
        h.mc.start()
        h.flight.state = ControlState.FLYING          # mid-climb
    elif state is MissionState.TRANSIT:
        h.take_off()
    elif state is MissionState.ARRIVING:
        h.take_off()
        h.to_arriving()
    elif state is MissionState.HOLDING:
        h.take_off()
        h.to_arriving()
        h.to_holding()
    elif state is MissionState.RETURNING:
        h.to_returning()
    elif state is MissionState.LANDING:
        h.to_landing()
    assert h.mc.state is state


NON_TERMINAL_FLYING = [MissionState.TAKING_OFF, MissionState.TRANSIT, MissionState.ARRIVING,
                       MissionState.HOLDING, MissionState.RETURNING, MissionState.LANDING]


@pytest.mark.parametrize("state", NON_TERMINAL_FLYING)
def test_T2_an_override_in_any_state_interrupts_and_nothing_is_commanded_after(state):
    h = Harness()
    _reach(h, state)
    calls = list(h.flight.calls)
    h.flight.operator_override = True
    h.tick()
    assert h.mc.state is MissionState.INTERRUPTED
    assert h.events[-1].kind is K.INTERRUPTED
    # Nothing now, nothing later — not even after the flight "arrives".
    h.flight.goal_active = False
    h.flight.state = ControlState.FLYING
    h.run(SETTLE_TIMEOUT_S + 5.0)
    assert h.flight.calls == calls
    assert h.mc.current_point_id is None


def test_T2_outranks_T3_and_T4():
    h = Harness()
    h.take_off()
    h.flight.operator_override = True
    h.flight.state = ControlState.LANDING
    h.clock.advance(1000.0)                          # every timeout long gone
    h.mc.tick()
    assert h.mc.state is MissionState.INTERRUPTED
    assert "land" not in h.flight.commands()


# ── T3 — the flight ended under the mission ───────────────────────────────


ENDED = [ControlState.LANDING, ControlState.LANDED, ControlState.STOPPED, ControlState.IDLE]


@pytest.mark.parametrize("flight_state", ENDED)
@pytest.mark.parametrize("state", [MissionState.TAKING_OFF, MissionState.TRANSIT,
                                   MissionState.ARRIVING, MissionState.HOLDING,
                                   MissionState.RETURNING])
def test_T3_the_flight_ending_mid_mission_aborts_naming_it_and_never_lands(state, flight_state):
    h = Harness()
    _reach(h, state)
    lands = h.flight.commands().count("land")
    h.flight.state = flight_state
    h.tick()
    assert h.mc.state is MissionState.ABORTED
    assert str(flight_state) in h.events[-1].detail
    assert h.flight.commands().count("land") == lands
    assert h.mc.current_point_id is None


def test_T3_outranks_a_timeout():
    h = Harness()
    h.take_off()
    h.flight.state = ControlState.STOPPED
    h.clock.advance(1000.0)
    h.mc.tick()
    assert "stopped" in h.events[-1].detail
    assert "land" not in h.flight.commands()


# ── T4, T7, T8, T10 — timeouts ────────────────────────────────────────────


def _times_out_at(h: Harness, deadline: float, what: str, point_id: str | None) -> None:
    """Still going two ticks before the deadline; ABORTED, landed and named
    within two ticks after it (the fake clock steps by TICK_S)."""
    h.until(lambda: h.clock() >= deadline - 2 * TICK_S)
    assert h.mc.state not in TERMINAL_STATES
    h.run(3 * TICK_S)
    assert h.mc.state is MissionState.ABORTED
    event = h.events[-1]
    assert "timed out" in event.detail
    assert what in event.detail
    assert event.point_id == point_id
    assert h.flight.calls[-1] == ("land",)


def test_T7_the_takeoff_times_out():
    h = Harness()
    h.mc.start()
    h.flight.state = ControlState.FLYING              # up, but the goal never ends
    limit = h.mission.cruise_height_m / CLIMB_RATE_M_S + TRANSIT_MARGIN_S
    _times_out_at(h, limit, "takeoff", None)


def test_T7_a_drone_that_never_leaves_the_ground_times_out_and_is_disarmed():
    h = Harness()
    h.mc.start()                                      # flight stays ARMED
    limit = h.mission.cruise_height_m / CLIMB_RATE_M_S + TRANSIT_MARGIN_S
    _times_out_at(h, limit, "takeoff", None)
    assert h.flight.state is ControlState.IDLE


def test_T8_a_leg_times_out_from_its_straight_3d_length():
    h = Harness()
    h.take_off()
    p1 = h.mission.points[0]
    start = (TAKEOFF_SPOT.x, TAKEOFF_SPOT.y, h.mission.cruise_height_m)
    leg = math.dist(start, (p1.x_m, p1.y_m, p1.z_m))
    began = h.last(K.TAKEOFF_DONE).at_s
    _times_out_at(h, began + leg / MOVE_SPEED_M_S + TRANSIT_MARGIN_S, "P1", "P1")


@pytest.mark.parametrize("speed", [0.10, 0.15, 0.20])
def test_T8_a_leg_flies_and_times_out_at_the_missions_speed(speed):
    """Steady / Normal / Brisk (mission.py): fly_to is given the mission's
    speed, and the leg's timeout is the leg at THAT speed — a Steady mission
    is not timed out as if it were Brisk."""
    h = Harness(mission(speed_m_s=speed))
    h.take_off()
    assert h.flight.speed == speed
    p1 = h.mission.points[0]
    start = (TAKEOFF_SPOT.x, TAKEOFF_SPOT.y, h.mission.cruise_height_m)
    leg = math.dist(start, (p1.x_m, p1.y_m, p1.z_m))
    began = h.last(K.TAKEOFF_DONE).at_s
    _times_out_at(h, began + leg / speed + TRANSIT_MARGIN_S, "P1", "P1")


def test_T8_the_second_leg_runs_from_the_first_point():
    h = Harness()
    h.take_off()
    h.fly_point()
    p1, p2 = h.mission.points[0], h.mission.points[1]
    leg = math.dist((p1.x_m, p1.y_m, p1.z_m), (p2.x_m, p2.y_m, p2.z_m))
    began = h.last(K.POINT_COMPLETE).at_s
    _times_out_at(h, began + leg / MOVE_SPEED_M_S + TRANSIT_MARGIN_S, "P2", "P2")
    assert h.mc.completed_point_ids == ("P1",)       # T13: never skipped past


def test_T8_the_return_leg_times_out_too():
    h = Harness()
    h.to_returning()
    last = h.mission.points[-1]
    leg = math.dist((last.x_m, last.y_m, last.z_m),
                    (TAKEOFF_SPOT.x, TAKEOFF_SPOT.y, h.mission.cruise_height_m))
    began = h.last(K.RETURNING).at_s
    _times_out_at(h, began + leg / MOVE_SPEED_M_S + TRANSIT_MARGIN_S, "back", None)


def test_T10_arriving_times_out_and_drift_never_restarts_it():
    h = Harness()
    h.take_off()
    h.to_arriving()
    began = h.last(K.POINT_ARRIVED).at_s
    # Drift in and out every half SETTLE_S: each dip restarts T9's wait, so it
    # never settles — and T10 runs on regardless.
    flip = [False]

    def wobble() -> None:
        flip[0] = not flip[0]
        h.flight.drift_m = ARRIVE_M * (2 if flip[0] else 0.5)

    while h.mc.state is MissionState.ARRIVING and h.clock() < began + 2 * SETTLE_TIMEOUT_S:
        wobble()
        h.run(SETTLE_S / 2)
    assert h.mc.state is MissionState.ABORTED
    assert h.events[-1].at_s == pytest.approx(began + SETTLE_TIMEOUT_S, abs=SETTLE_S / 2 + TICK_S)
    assert "timed out" in h.events[-1].detail
    assert h.events[-1].point_id == "P1"
    assert h.flight.calls[-1] == ("land",)
    assert K.HOLD_STARTED not in h.kinds()


def test_T10_settling_over_the_start_times_out():
    h = Harness()
    h.to_returning()
    h.flight.arrive(drift=ARRIVE_M * 3)
    h.tick()
    began = h.clock()
    h.run(SETTLE_TIMEOUT_S + 2 * TICK_S)
    assert h.mc.state is MissionState.ABORTED
    assert h.events[-1].at_s == pytest.approx(began + SETTLE_TIMEOUT_S, abs=2 * TICK_S)
    assert h.flight.calls[-1] == ("land",)


def test_LANDING_has_no_timeout_it_waits_for_the_flight():
    """THE SPEC gives LANDING no timeout: the manual system's own landing
    always ends. (T4's "unless the state is stopped" cannot be reached through
    the flight: a stop the controller did not ask for is T3, first.)"""
    h = Harness()
    h.to_landing()
    h.flight.state = ControlState.LANDING
    h.run(SETTLE_TIMEOUT_S * 3)
    assert h.mc.state is MissionState.LANDING


# ── T6 — takeoff done ─────────────────────────────────────────────────────


def test_T6_takeoff_ends_only_when_the_goal_ends_and_the_flight_is_flying():
    h = Harness()
    h.mc.start()
    h.flight.goal_active = False                      # but still ARMED
    h.run(1.0)
    assert h.mc.state is MissionState.TAKING_OFF
    h.flight.state = ControlState.FLYING
    h.flight.goal_active = True                       # flying, still climbing
    h.flight.target = TAKEOFF_SPOT
    h.run(1.0)
    assert h.mc.state is MissionState.TAKING_OFF
    h.flight.goal_active = False
    h.tick()
    assert h.kinds() == [K.STARTED, K.TAKEOFF_DONE]
    p1 = h.mission.points[0]
    assert h.flight.calls[-1] == ("fly_to", p1.x_m, p1.y_m, p1.z_m)
    assert h.mc.state is MissionState.TRANSIT


def test_T6_records_the_takeoff_spot_from_the_commanded_point():
    h = Harness(one_point())
    h.mc.start()
    h.flight.airborne(Fix(0.25, -0.75, 30.0))
    h.tick()
    h.fly_point()
    assert h.flight.calls[-1] == ("fly_to", 0.25, -0.75, h.mission.cruise_height_m)


def test_T6_no_position_to_record_fails_the_mission_in_words():
    """THE SPEC is silent on a flight with no target at T6; the exception path
    (land, FAILED) is the answer, with the cause named."""
    h = Harness()
    h.mc.start()
    h.flight.airborne(at=None)
    h.tick()
    assert h.mc.state is MissionState.FAILED
    assert "position" in h.events[-1].detail
    assert h.flight.calls[-1] == ("land",)


# ── T8 — transit ──────────────────────────────────────────────────────────


def test_T8_fly_to_is_called_once_per_point_on_entering():
    h = Harness()
    h.take_off()
    h.run(5.0)                                        # transit, not arrived yet
    assert h.flight.commands().count("fly_to") == 1
    h.to_arriving()
    arrived = h.last(K.POINT_ARRIVED)
    assert arrived.point_id == "P1"
    assert "P1" in arrived.detail


def test_T8_point_arrived_reports_the_drift_then():
    h = Harness()
    h.take_off()
    h.flight.arrive(drift=0.04)
    h.tick()
    assert "4 cm" in h.last(K.POINT_ARRIVED).detail


# ── T9 — settling ─────────────────────────────────────────────────────────


def test_T9_settled_means_within_arrive_m_continuously_for_settle_s():
    h = Harness()
    h.take_off()
    h.to_arriving()
    h.flight.drift_m = ARRIVE_M                       # "≤ ARRIVE_M" includes it
    h.until(lambda: h.mc.state is MissionState.HOLDING)
    waited = h.last(K.HOLD_STARTED).at_s - h.last(K.POINT_ARRIVED).at_s
    assert SETTLE_S <= waited <= SETTLE_S + 2 * TICK_S


def test_T9_drift_over_arrive_m_restarts_the_settle_wait():
    h = Harness()
    h.take_off()
    h.to_arriving()
    h.run(SETTLE_S * 0.8)                             # most of the way there
    h.flight.drift_m = ARRIVE_M * 1.5
    h.tick()
    spike = h.clock()
    h.flight.drift_m = 0.0
    h.until(lambda: h.mc.state is MissionState.HOLDING)
    assert h.last(K.HOLD_STARTED).at_s - spike >= SETTLE_S


def test_T9_drift_restarts_the_wait_but_not_T10():
    h = Harness()
    h.take_off()
    h.to_arriving()
    began = h.last(K.POINT_ARRIVED).at_s
    h.flight.drift_m = ARRIVE_M * 2
    h.until(lambda: h.clock() >= began + SETTLE_TIMEOUT_S - SETTLE_S / 2)
    h.flight.drift_m = 0.0                            # settles, but too late
    h.run(SETTLE_S)
    assert h.mc.state is MissionState.ABORTED


# ── T11–T13 — holding, and current_point_id ───────────────────────────────


def test_T11_to_T13_current_point_id_is_set_exactly_while_holding():
    h = Harness()
    seen: list[tuple[MissionState, str | None]] = []
    h.mc.start()
    h.flight.airborne()
    while h.mc.state not in TERMINAL_STATES:
        h.tick()
        seen.append((h.mc.state, h.mc.current_point_id))
        if h.flight.goal_active and h.mc.state in (MissionState.TRANSIT,
                                                   MissionState.RETURNING):
            h.flight.arrive()
        if h.mc.state is MissionState.LANDING:
            h.flight.state = ControlState.LANDED
    for state, point in seen:
        assert (point is not None) == (state is MissionState.HOLDING), (state, point)  # C1
    held = [p for s, p in seen if p is not None]
    assert list(dict.fromkeys(held)) == ["P1", "P2", "P3"]
    assert h.mc.completed_point_ids == ("P1", "P2", "P3")


def test_T11_the_point_is_set_before_hold_started_is_heard():
    heard: list[str | None] = []
    h: Harness

    def listener(e: MissionEvent) -> None:
        if e.kind is K.HOLD_STARTED:
            heard.append(h.mc.current_point_id)

    h = Harness(listener=listener)
    h.take_off()
    h.to_arriving()
    h.to_holding()
    assert heard == ["P1"]


def test_T13_the_point_is_cleared_and_completed_before_point_complete_is_heard():
    seen: list[tuple[str | None, tuple[str, ...]]] = []
    h: Harness

    def listener(e: MissionEvent) -> None:
        if e.kind is K.POINT_COMPLETE:
            seen.append((h.mc.current_point_id, h.mc.completed_point_ids))

    h = Harness(listener=listener)
    h.take_off()
    h.fly_point()
    assert seen == [(None, ("P1",))]


def test_T12_the_hold_lasts_hold_s_by_the_clock():
    h = Harness()
    h.take_off()
    for point in h.mission.points:
        h.fly_point()
        started = next(e for e in h.events
                       if e.kind is K.HOLD_STARTED and e.point_id == point.id)
        done = h.last(K.POINT_COMPLETE)
        assert done.point_id == point.id
        assert point.hold_s <= done.at_s - started.at_s <= point.hold_s + 2 * TICK_S


def test_T12_drift_while_holding_neither_restarts_nor_ends_the_hold():
    h = Harness()
    h.take_off()
    h.to_arriving()
    h.to_holding()
    began = h.clock()
    h.flight.drift_m = ARRIVE_M * 5
    h.run(h.mission.points[0].hold_s / 2)
    assert h.mc.state is MissionState.HOLDING
    assert h.mc.current_point_id == "P1"
    h.flight.drift_m = 0.0
    h.until(lambda: h.mc.state is not MissionState.HOLDING)
    assert h.clock() - began <= h.mission.points[0].hold_s + 2 * TICK_S


# ── T14, T15 — the end ────────────────────────────────────────────────────


def _fly_it_all(h: Harness) -> None:
    h.take_off()
    for _ in h.mission.points:
        h.fly_point()
    if h.mission.return_to_start:
        h.flight.arrive()
        h.until(lambda: h.mc.state is MissionState.LANDING)
    assert h.mc.state is MissionState.LANDING
    h.flight.state = ControlState.LANDED
    h.tick()


def test_T14_T15_with_return_to_start_the_events_are_exactly_the_spec():
    h = Harness(mission(return_to_start=True))
    _fly_it_all(h)
    assert [(e.kind, e.point_id) for e in h.events] == full_sequence(
        ("P1", "P2", "P3"), returning=True)
    assert h.mc.state is MissionState.DONE
    back = [c for c in h.flight.calls if c[0] == "fly_to"][-1]
    assert back == ("fly_to", TAKEOFF_SPOT.x, TAKEOFF_SPOT.y, h.mission.cruise_height_m)
    assert h.flight.commands().count("land") == 1


def test_T14_T15_without_return_to_start_it_lands_after_the_last_point():
    h = Harness(mission(return_to_start=False))
    _fly_it_all(h)
    assert [(e.kind, e.point_id) for e in h.events] == full_sequence(
        ("P1", "P2", "P3"), returning=False)
    assert h.flight.commands() == ["hold_at", "fly_to", "fly_to", "fly_to", "land"]


def test_T14_landing_waits_for_the_settle_over_the_start():
    h = Harness()
    h.to_returning()
    h.flight.arrive(drift=ARRIVE_M * 2)
    h.run(SETTLE_S * 2)
    assert h.mc.state is MissionState.RETURNING
    assert "land" not in h.flight.commands()
    h.flight.drift_m = 0.0
    h.until(lambda: h.mc.state is MissionState.LANDING)
    assert h.flight.calls[-1] == ("land",)


@pytest.mark.parametrize("flight_state", [ControlState.STOPPED, ControlState.IDLE])
def test_T15_stopped_or_idle_before_landed_aborts_naming_it(flight_state):
    h = Harness()
    h.to_landing()
    h.flight.state = flight_state
    h.tick()
    assert h.mc.state is MissionState.ABORTED
    assert str(flight_state) in h.events[-1].detail
    assert K.LANDED not in h.kinds()
    assert h.flight.commands().count("land") == 1


def test_T15_landing_is_not_mistaken_for_T3():
    h = Harness()
    h.to_landing()
    assert h.flight.state is ControlState.LANDING     # the controller asked
    h.run(2.0)
    assert h.mc.state is MissionState.LANDING


# ── A1, A2 — abort from outside ───────────────────────────────────────────


@pytest.mark.parametrize("state,flight_state,lands", [
    (MissionState.IDLE, ControlState.ARMED, True),
    (MissionState.TAKING_OFF, ControlState.ARMED, True),
    (MissionState.TAKING_OFF, ControlState.FLYING, True),
    (MissionState.TRANSIT, ControlState.FLYING, True),
    (MissionState.ARRIVING, ControlState.FLYING, True),
    (MissionState.HOLDING, ControlState.FLYING, True),
    (MissionState.RETURNING, ControlState.FLYING, True),
    (MissionState.LANDING, ControlState.LANDING, False),
    (MissionState.HOLDING, ControlState.STOPPED, False),
    (MissionState.HOLDING, ControlState.LANDING, False),
    (MissionState.HOLDING, ControlState.LANDED, False),
])
def test_A2_abort_lands_only_a_flying_or_armed_flight(state, flight_state, lands):
    h = Harness()
    if state is not MissionState.IDLE:
        _reach(h, state)
    h.flight.state = flight_state
    before = h.flight.commands().count("land")
    h.mc.abort("the operator pressed Land")
    assert h.mc.state is MissionState.ABORTED
    assert h.flight.commands().count("land") == before + (1 if lands else 0)
    assert h.events[-1].kind is K.ABORTED
    assert h.events[-1].detail == "the operator pressed Land"
    assert h.mc.current_point_id is None
    expected_point = "P1" if state in (MissionState.TRANSIT, MissionState.ARRIVING,
                                       MissionState.HOLDING) else None
    assert h.events[-1].point_id == expected_point                             # E3


@pytest.mark.parametrize("ending", ["abort", "interrupt", "fail", "done"])
def test_A1_abort_after_the_end_does_nothing(ending):
    h = Harness()
    if ending == "done":
        _fly_it_all(h)
    else:
        h.mc.start()
        h.flight.airborne()
        if ending == "fail":
            h.flight.fail_on = "fly_to"
        h.tick()
        if ending == "abort":
            h.mc.abort("first")
        elif ending == "interrupt":
            h.flight.operator_override = True
            h.tick()
    assert h.mc.state in TERMINAL_STATES
    calls, events = list(h.flight.calls), list(h.events)
    h.mc.abort("again")
    h.mc.abort("and again")
    assert h.flight.calls == calls
    assert h.events == events


# ── E3, E4 — what an event carries ────────────────────────────────────────


def test_E3_E4_point_ids_and_times_on_a_whole_mission():
    h = Harness()
    _fly_it_all(h)
    point_kinds = {K.POINT_ARRIVED, K.HOLD_STARTED, K.POINT_COMPLETE}
    for e in h.events:
        assert (e.point_id is not None) == (e.kind in point_kinds), e
    assert [e.at_s for e in h.events] == h.clock_at_event     # E4: clock() when emitted
    assert h.events[0].at_s == 0.0


def test_E3_a_terminal_event_mid_transit_carries_the_point():
    h = Harness()
    h.take_off()
    h.fly_point()
    h.flight.operator_override = True
    h.tick()
    assert h.events[-1].point_id == "P2"


# ── E5 — listeners ────────────────────────────────────────────────────────


def test_E5_a_listener_that_raises_does_not_stop_the_mission():
    def broken(event: MissionEvent) -> None:
        raise RuntimeError("the app is gone")

    h = Harness(listener=broken)
    _fly_it_all(h)
    assert h.mc.state is MissionState.DONE
    assert h.kinds() == [k for k, _ in full_sequence(("P1", "P2", "P3"), True)]


def test_E5_a_listener_may_call_back_into_the_controller():
    h: Harness
    reads: list[tuple] = []

    def listener(event: MissionEvent) -> None:
        reads.append((h.mc.state, h.mc.current_point_id, h.mc.completed_point_ids))

    h = Harness(listener=listener)
    _fly_it_all(h)
    assert len(reads) == len(h.events)


def test_E1_an_abort_from_inside_a_listener_comes_after_the_event_being_heard():
    h: Harness

    def listener(event: MissionEvent) -> None:
        if event.kind is K.POINT_COMPLETE:
            h.mc.abort("stopped from the app")

    h = Harness(listener=listener)
    h.take_off()
    h.fly_point()
    assert h.kinds()[-2:] == [K.POINT_COMPLETE, K.ABORTED]


def test_E1_E5_an_abort_racing_a_tick_is_delivered_after_the_ticks_events():
    """The session's thread aborts while the controller's thread is still
    telling the listener about POINT_COMPLETE. The listener runs with no lock
    held, and ABORTED still arrives after it — never before."""
    in_listener, release = threading.Event(), threading.Event()
    h: Harness

    def listener(event: MissionEvent) -> None:
        if event.kind is K.POINT_COMPLETE:
            in_listener.set()
            assert release.wait(5.0)

    h = Harness(listener=listener)
    h.take_off()
    h.to_arriving()
    h.to_holding()
    h.clock.advance(h.mission.points[0].hold_s + TICK_S)
    ticker = threading.Thread(target=h.mc.tick)
    ticker.start()
    assert in_listener.wait(5.0)
    h.mc.abort("the session ended")                  # returns: someone is delivering
    assert h.mc.state is MissionState.ABORTED        # E2: at once
    assert K.ABORTED not in h.kinds()                # not yet heard
    release.set()
    ticker.join(5.0)
    assert h.kinds()[-2:] == [K.POINT_COMPLETE, K.ABORTED]


# ── the exception path ────────────────────────────────────────────────────


def test_an_exception_inside_tick_lands_and_fails_the_mission():
    flight = ScriptedFlight()
    h = Harness(flight=flight)
    h.mc.start()
    flight.airborne()
    flight.fail_on = "fly_to"
    h.tick()                                          # TAKEOFF_DONE, then fly_to raises
    assert h.mc.state is MissionState.FAILED
    assert "fly_to blew up" in h.events[-1].detail
    assert h.events[-1].point_id == "P1"
    assert flight.calls[-1] == ("land",)


def test_an_exception_read_from_the_flight_while_flying_lands_and_fails():
    flight = BrokenFlight()
    h = Harness(flight=flight)
    h.take_off()
    h.to_arriving()
    flight.breaks = "drift_m"
    h.tick()
    assert h.mc.state is MissionState.FAILED
    assert "drift_m blew up" in h.events[-1].detail
    assert h.events[-1].point_id == "P1"
    assert flight.calls[-1] == ("land",)


def test_an_exception_on_the_ground_fails_without_landing():
    flight = BrokenFlight()
    h = Harness(flight=flight)
    h.mc.start()                                      # still ARMED, climbing
    flight.breaks = "goal_active"
    h.tick()
    assert h.mc.state is MissionState.FAILED
    assert "land" not in flight.commands()


def test_a_land_that_raises_after_a_failure_still_ends_failed():
    flight = BrokenFlight()
    h = Harness(flight=flight)
    h.take_off()
    h.to_arriving()
    flight.fail_on = "land"
    flight.breaks = "drift_m"
    h.tick()
    assert h.mc.state is MissionState.FAILED
    assert "drift_m blew up" in h.events[-1].detail


# ── R1 — the thread ───────────────────────────────────────────────────────


class CooperativeFlight(ScriptedFlight):
    """A flight that does what it is told at once: up on hold_at, there on
    fly_to, down on land. For the one test that runs on real time."""

    def hold_at(self, height_m: float) -> None:
        super().hold_at(height_m)
        self.airborne()

    def fly_to(self, x: float, y: float, height_m: float,
               speed_m_s: float | None = None) -> None:
        super().fly_to(x, y, height_m, speed_m_s)
        self.arrive()

    def land(self) -> None:
        super().land()
        self.state = ControlState.LANDED


def test_R1_the_thread_flies_a_short_mission_to_done_while_others_read_it():
    plan = mission(points=(InspectionPoint("P1", -1.0, 0.9, 0.40, 0.3),
                           InspectionPoint("P2", 0.9, 0.9, 0.50, 0.3)),
                   return_to_start=False)
    events: list[MissionEvent] = []
    mc = MissionController(plan, CooperativeFlight(), on_event=events.append, tick_s=0.01)
    _BUILT.append(mc)
    _EVENTS[id(mc)] = events
    seen: set[str | None] = set()
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:                              # the session, at far over 10 Hz
        try:
            while not stop.is_set():
                seen.add(mc.current_point_id)
                mc.completed_point_ids  # noqa: B018
                mc.state  # noqa: B018
                time.sleep(0.001)
        except BaseException as e:                     # pragma: no cover - the failure
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    mc.start()
    deadline = time.monotonic() + 2 * (SETTLE_S + 0.3) + 5.0
    while mc.state not in TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    for t in threads:
        t.join(2.0)
    assert mc.state is MissionState.DONE, [e.kind for e in events]
    assert not errors
    assert {"P1", "P2", None} <= seen
    assert [(e.kind, e.point_id) for e in events] == full_sequence(("P1", "P2"), False)
    time.sleep(0.05)
    assert not any(t.name == "mission-controller" for t in threading.enumerate())
