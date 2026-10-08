"""The mission report: how a mission flight actually flew, point by point.

For the operator after a mission flight, and for the lab: the numbers the
mission controller's four constants must be set from (ARRIVE_M, SETTLE_S,
SETTLE_TIMEOUT_S, TRANSIT_MARGIN_S). Without it, "measure the constants from
the trace" means reading thousands of CSV rows by hand, and nobody can repeat
the reading (mission-verification.txt, PART 2).

FLIGHT PERFORMANCE ONLY. Where the drone went, how long it took, how still it
held. What the readings and frames at a point SAY is the data pipeline's
(pipeline/), and nothing here reads or judges it.

WHAT IT READS — what a mission flown from the app already writes:
    the control trace   flights/<day>/trace_<id[:8]>.csv   (telemetry/trace.py,
                        session._start_trace): the commanded point
                        target_x_m/target_y_m/target_height_m, the estimate
                        stateEstimate.x/y, drift_m, the loop's state and the
                        keys held, at the stream's 10 Hz
    the flight CSV      flights/<day>/flight_<id[:8]>_<time>.csv
                        (session._begin_flight, telemetry/row.py): point_id on
                        every row taken while holding
    the plan flown      sessions/<session>/missions/<flight id>.json
                        (session._keep_plan_flown): the mission exactly as
                        flown, from the drone's real start
It finds them by the rules the data pipeline uses (pipeline/sources.py), never
needs a drone, and never writes a file.

`cropwatcher mission` (the terminal) records under the flight id "cli" and
keeps no trace and no plan flown, so a flight flown from the terminal cannot
be reported on — this says so rather than guessing.

PLANNED TIME is the planner's own per-leg figure — the one
Mission.estimated_duration_s adds up, at the mission's own speed and the
climb rate — not leg / MOVE_SPEED_M_S: a Steady mission travels at half that
speed, and a leg that changes height can take longer than its distance says.
A test pins the two together.

The calculation is plain functions over rows (TraceRow, StampRow), so it is
tested without a disk. A trace with a gap, a point never reached, a flight
that ended early: each is reported in words, never a crash and never a silent
zero.

IT SUGGESTS. People decide the constants, and write the measurement and the
flights it came from beside each one (CLAUDE.md: never invent a threshold).
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cropwatcher.flight.manual import CLIMB_RATE_M_S, GOAL_REACHED_M, MOVE_SPEED_M_S
from cropwatcher.mission.controller.mission_controller import (
    ARRIVE_M,
    SETTLE_S,
    SETTLE_TIMEOUT_S,
    TRANSIT_MARGIN_S,
)
from cropwatcher.mission.plan.mission import Mission
from cropwatcher.telemetry.stream import PERIOD_MS

#: The commanded point has reached a spot when it is within the loop's own goal
#: tolerance on both motions (manual.py GOAL_REACHED_M, for the x-y glide and
#: for the height glide): at most √2 × GOAL_REACHED_M in 3-D, plus the trace's
#: 4-decimal rounding.
REACHED_M = math.sqrt(2.0) * GOAL_REACHED_M + 1e-4
#: The commanded point is standing still when two samples differ by no more
#: than the trace's rounding.
STILL_M = 1e-4
#: One sample of the trace and of the flight CSV: the telemetry stream's period.
SAMPLE_S = PERIOD_MS / 1000.0
#: A pause in the trace longer than this is samples lost, not jitter.
GAP_S = 3 * SAMPLE_S
#: A gap listed by itself; past this many, the rest are counted.
GAPS_LISTED = 5

#: The terminal records under this id (cli.py _record) and keeps no trace.
TERMINAL_FLIGHT_ID = "cli"
_FLIGHT_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

Spot = tuple[float, float, float]                       # x, y, height above the floor


class ReportError(Exception):
    """The flight cannot be reported on. Words for the operator."""


# ── the rows ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraceRow:
    """One control-trace sample. t_s is seconds from the flight's first record."""

    t_s: float
    state: str = ""
    keys: str = ""
    #: The commanded point: x, y and the height above the floor.
    target: Spot | None = None
    #: The estimator's x, y.
    estimate: tuple[float, float] | None = None
    #: How far the estimate is from the commanded point (manual.py drift_m) —
    #: the number THE SPEC's arrival is judged on.
    drift_m: float | None = None


@dataclass(frozen=True)
class StampRow:
    """One flight-CSV row: when, and the inspection point it was stamped with."""

    t_s: float
    point_id: str | None


# ── the report ────────────────────────────────────────────────────────────


@dataclass
class LegReview:
    """One leg flown and, for an inspection point, the settle and hold there."""

    to: str                                             # a point id, or "start"
    label: str | None
    leg_m: float
    planned_s: float
    reached: bool = False
    transit_s: float | None = None
    settle_s: float | None = None
    hold_s: float | None = None
    hold_required_s: float | None = None
    hold_long_enough: bool | None = None
    hold_drift_median_m: float | None = None
    hold_drift_p95_m: float | None = None
    hold_drift_worst_m: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def over_plan_s(self) -> float | None:
        return None if self.transit_s is None else self.transit_s - self.planned_s


@dataclass
class FlightReview:
    flight_id: str
    mission_id: str
    revision: int
    speed_m_s: float
    points: list[LegReview]
    return_leg: LegReview | None
    estimate_s: float
    flown_s: float | None
    notes: list[str] = field(default_factory=list)

    @property
    def legs(self) -> list[LegReview]:
        return self.points + ([self.return_leg] if self.return_leg is not None else [])

    @property
    def over_estimate(self) -> bool | None:
        return None if self.flown_s is None else self.flown_s > self.estimate_s


@dataclass
class Suggestion:
    """What one constant should be, from the flights given."""

    name: str
    current: float
    measured: float | None
    #: The flights and points the figure came from, to cite beside the constant.
    sources: list[str]
    rule: str
    #: True when the current value is on the right side of the rule, False when
    #: it is not, None when the rule is a judgement or nothing was measured.
    holds: bool | None


# ── the calculation ───────────────────────────────────────────────────────


def planned_leg_s(a: Spot, b: Spot, mission: Mission) -> float:
    """The planner's time for one leg, exactly as Mission.estimated_duration_s
    counts it: the horizontal distance at the mission's speed (never faster
    than the flight system moves) or the height change at the climb rate,
    whichever is longer. Settling and holding are not part of the leg."""
    speed = min(MOVE_SPEED_M_S, mission.speed_m_s)
    horizontal = math.hypot(b[0] - a[0], b[1] - a[1]) / speed
    vertical = abs(b[2] - a[2]) / CLIMB_RATE_M_S
    return max(horizontal, vertical)


def planner_estimate_s(mission: Mission) -> float:
    """The whole flight, as the session's battery check estimates it."""
    return mission.estimated_duration_s(move_speed_m_s=MOVE_SPEED_M_S,
                                        climb_rate_m_s=CLIMB_RATE_M_S)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile: always one of the values, never interpolated."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def _gaps(trace: Sequence[TraceRow]) -> list[tuple[float, float]]:
    return [(a.t_s, b.t_s - a.t_s) for a, b in zip(trace, trace[1:], strict=False)
            if b.t_s - a.t_s > GAP_S]


def _gap_within(gaps: Sequence[tuple[float, float]], start: float, end: float) -> bool:
    return any(start <= at < end for at, _ in gaps)


def _near(target: Spot | None, spot: Spot, within: float = REACHED_M) -> bool:
    return target is not None and math.dist(target, spot) <= within


def _moved(a: Spot | None, b: Spot | None) -> bool:
    if a is None or b is None:
        return True
    return max(abs(p - q) for p, q in zip(a, b, strict=True)) > STILL_M


def what_happened(trace: Sequence[TraceRow], start: int) -> str:
    """The first thing, from row `start` on, that stopped the flight going on:
    the operator's keys, a landing, a stop — or the trace simply ending."""
    for row in trace[start:]:
        if row.keys:
            return f"the operator took over ({row.keys} held at {row.t_s:.1f} s)"
        if row.state in ("landing", "landed"):
            return (f"the flight system began landing at {row.t_s:.1f} s (a guard, the "
                    f"dead-man, a timeout or Land)")
        if row.state == "stopped":
            return f"an emergency stop at {row.t_s:.1f} s"
        if row.state == "idle":
            return f"the drone disarmed at {row.t_s:.1f} s"
    if start >= len(trace):
        return "the trace ends here"
    last = trace[-1]
    return f"the trace ends at {last.t_s:.1f} s with the loop {last.state or 'in no state'}"


def _departure(trace: Sequence[TraceRow], cursor: int, spot: Spot) -> int | None:
    """The last sample with the commanded point still at `spot` before it set
    off for the next one — found from the first sample clearly away from it,
    walking back while the point was moving, so the time is right to a sample
    and not late by the easing's first centimetre."""
    away = next((i for i in range(cursor, len(trace))
                 if trace[i].target is not None and not _near(trace[i].target, spot)), None)
    if away is None:
        return None
    i = away
    while i > cursor and _moved(trace[i - 1].target, trace[i].target):
        i -= 1
    return i


def _hold_window(stamps: Sequence[StampRow], point_id: str) -> tuple[float, float] | None:
    times = [s.t_s for s in stamps if s.point_id == point_id]
    return (min(times), max(times)) if times else None


def _settled_at(trace: Sequence[TraceRow], begin: int, end: int) -> int | None:
    """The first sample from which the drift stays within ARRIVE_M through
    `end` — the start of the last unbroken run inside it."""
    if begin > end or any(trace[i].drift_m is None for i in range(begin, end + 1)):
        return None
    i = end
    while i >= begin and (trace[i].drift_m or 0.0) <= ARRIVE_M:
        i -= 1
    return None if i == end else i + 1


def _review_leg(trace: Sequence[TraceRow], stamps: Sequence[StampRow],
                gaps: Sequence[tuple[float, float]], cursor: int, previous: Spot,
                spot: Spot, leg: LegReview, point_id: str | None,
                hold_required_s: float | None) -> int | None:
    """Fill in `leg`; return the trace index to carry on from, or None when
    the flight went no further than this leg."""
    departed = _departure(trace, cursor, previous)
    if departed is None:
        leg.notes.append(f"not reached: the commanded point never set off for it — "
                         f"{what_happened(trace, cursor)}")
        return None
    arrived = next((i for i in range(departed + 1, len(trace))
                    if _near(trace[i].target, spot)), None)
    if arrived is None:
        leg.notes.append(f"not reached: {what_happened(trace, departed + 1)}")
        return None
    leg.reached = True
    leg.transit_s = trace[arrived].t_s - trace[departed].t_s
    if _gap_within(gaps, trace[departed].t_s, trace[arrived].t_s):
        leg.notes.append("the trace has a gap during this transit, so its time is "
                         "only as good as that gap")
    if point_id is None:
        return arrived

    leg.hold_required_s = hold_required_s
    window = _hold_window(stamps, point_id)
    # The stay at the spot ends when the commanded point leaves it (or the flight).
    stay_end = next((i - 1 for i in range(arrived + 1, len(trace))
                     if not _near(trace[i].target, spot)), len(trace) - 1)
    if window is not None:
        hold_from, hold_to = window
        settle_end = max((i for i in range(arrived, stay_end + 1)
                          if trace[i].t_s <= hold_from), default=arrived)
    else:
        settle_end = stay_end
    settled = _settled_at(trace, arrived, settle_end)
    if settled is not None:
        leg.settle_s = trace[settled].t_s - trace[arrived].t_s
    elif any(trace[i].drift_m is None for i in range(arrived, settle_end + 1)):
        leg.notes.append("no drift recorded while settling, so the settle time is unknown")
    else:
        closest = min(trace[i].drift_m or 0.0 for i in range(arrived, settle_end + 1))
        leg.notes.append(f"never settled within ARRIVE_M ({ARRIVE_M * 100:.0f} cm); the "
                         f"closest it came was {closest * 100:.1f} cm")

    if window is None:
        leg.notes.append(f"reached, but never held: no row of the flight CSV is stamped "
                         f"{point_id} — {what_happened(trace, arrived)}")
        return None
    hold_from, hold_to = window
    leg.hold_s = hold_to - hold_from
    if hold_required_s is not None:
        # The first and last stamped rows are a sample apart from the hold's ends.
        leg.hold_long_enough = leg.hold_s + SAMPLE_S >= hold_required_s - 1e-9
        if not leg.hold_long_enough:
            leg.notes.append(f"held {leg.hold_s:.1f} s of the {hold_required_s:.1f} s asked "
                             f"for — {what_happened(trace, arrived)}")
    drifts = [math.hypot(r.estimate[0] - spot[0], r.estimate[1] - spot[1])
              for r in trace if r.estimate is not None and hold_from <= r.t_s <= hold_to]
    if drifts:
        leg.hold_drift_median_m = statistics.median(drifts)
        leg.hold_drift_p95_m = percentile(drifts, 95)
        leg.hold_drift_worst_m = max(drifts)
    else:
        leg.notes.append("no position was traced while holding, so the hold drift is unknown")
    if _gap_within(gaps, hold_from, hold_to):
        leg.notes.append("the trace has a gap during this hold; the drift figures leave it out")
    after = next((i for i in range(arrived, len(trace)) if trace[i].t_s >= hold_to),
                 len(trace) - 1)
    if leg.hold_long_enough is False:
        return None
    return after


def review_flight(flight_id: str, mission: Mission, trace: Sequence[TraceRow],
                  stamps: Sequence[StampRow]) -> FlightReview:
    """The report for one flight, from its rows and the mission as flown."""
    trace = sorted(trace, key=lambda r: r.t_s)
    stamps = sorted(stamps, key=lambda s: s.t_s)
    cruise = mission.cruise_height_m
    home: Spot = (mission.home[0], mission.home[1], cruise)
    review = FlightReview(
        flight_id=flight_id, mission_id=mission.id, revision=mission.revision,
        speed_m_s=mission.speed_m_s, points=[], return_leg=None,
        estimate_s=planner_estimate_s(mission), flown_s=None)
    gaps = _gaps(trace)
    for at, length in gaps[:GAPS_LISTED]:
        review.notes.append(f"the trace has no samples for {length:.1f} s from {at:.1f} s "
                            f"(the radio dropped them)")
    if len(gaps) > GAPS_LISTED:
        review.notes.append(f"…and {len(gaps) - GAPS_LISTED} more gaps")
    if not trace:
        review.notes.append("there is no control trace, so nothing about the flying can be "
                            "measured: no transit, settle or drift")
    if not stamps:
        review.notes.append("the flight CSV has no rows, so no hold can be measured")

    # Take-off: THE SPEC's takeoff spot is the commanded x, y once at cruise height.
    def at_cruise(row: TraceRow) -> bool:
        return row.target is not None and abs(row.target[2] - cruise) <= GOAL_REACHED_M + STILL_M

    liftoff = next((i for i, r in enumerate(trace) if r.state == "flying"), None)
    top = None if liftoff is None else next(
        (i for i in range(liftoff, len(trace)) if at_cruise(trace[i])), None)
    if top is None:
        why = what_happened(trace, liftoff if liftoff is not None else 0)
        review.notes.append(f"it never reached its cruise height of {cruise:.2f} m — {why}")
    takeoff: Spot = home
    if top is not None:
        target = trace[top].target
        assert target is not None
        takeoff = (target[0], target[1], cruise)

    cursor: int | None = top
    previous = takeoff
    for point in mission.points:
        spot: Spot = (point.x_m, point.y_m, point.z_m)
        leg = LegReview(to=point.id, label=point.label, leg_m=math.dist(previous, spot),
                        planned_s=planned_leg_s(previous, spot, mission),
                        hold_required_s=point.hold_s)
        review.points.append(leg)
        if cursor is None:
            leg.notes.append("not flown: the flight ended before it")
        else:
            cursor = _review_leg(trace, stamps, gaps, cursor, previous, spot, leg,
                                 point.id, point.hold_s)
            if cursor is None:
                review.notes.append(f"the mission did not finish: it stopped at "
                                    f"{point.id} ({leg.notes[-1]})")
        previous = spot

    if mission.return_to_start:
        leg = LegReview(to="start", label=None, leg_m=math.dist(previous, takeoff),
                        planned_s=planned_leg_s(previous, takeoff, mission))
        review.return_leg = leg
        if cursor is None:
            leg.notes.append("not flown: the flight ended before it")
        else:
            _review_leg(trace, stamps, gaps, cursor, previous, takeoff, leg, None, None)

    # Flown time: lift-off to touch-down, against the planner's estimate.
    landed = None if liftoff is None else next(
        (i for i in range(liftoff, len(trace)) if trace[i].state == "landed"), None)
    if liftoff is None:
        review.notes.append("it never lifted off, so there is no flown time")
    elif landed is None:
        review.notes.append(f"it did not land normally ({what_happened(trace, liftoff)}), "
                            f"so the flown time is not compared with the estimate")
    else:
        review.flown_s = trace[landed].t_s - trace[liftoff].t_s
        if review.flown_s > review.estimate_s:
            review.notes.append(
                f"it flew {review.flown_s:.1f} s, {review.flown_s - review.estimate_s:.1f} s "
                f"longer than the planner's {review.estimate_s:.1f} s. That estimate is what "
                f"the battery check uses, so the battery budget for this mission is too "
                f"small — tell Samuel.")
    return review


def suggest_constants(reviews: Sequence[FlightReview]) -> list[Suggestion]:
    """What the four constants should be, from every flight given, each figure
    with the flights and points it came from."""

    def where(review: FlightReview, leg: LegReview) -> str:
        return f"{review.flight_id[:8]} {leg.to}"

    p95 = [(leg.hold_drift_p95_m, where(r, leg)) for r in reviews for leg in r.points
           if leg.hold_drift_p95_m is not None]
    settles = [(leg.settle_s, where(r, leg)) for r in reviews for leg in r.points
               if leg.settle_s is not None]
    overs = [(leg.over_plan_s, where(r, leg)) for r in reviews for leg in r.legs
             if leg.over_plan_s is not None]

    def worst(found: list[tuple[float, str]]) -> tuple[float | None, list[str]]:
        if not found:
            return None, []
        value = max(v for v, _ in found)
        return value, [w for v, w in found if v == value]

    arrive, arrive_from = worst(p95)
    slowest, slowest_from = worst(settles)
    over, over_from = worst(overs)
    median_settle = statistics.median(v for v, _ in settles) if settles else None

    def above(current: float, measured: float | None) -> bool | None:
        return None if measured is None else current > measured

    return [
        Suggestion("ARRIVE_M", ARRIVE_M, arrive, arrive_from,
                   "above the worst 95th-percentile hold drift, or holding still would "
                   "never count as arrived", above(ARRIVE_M, arrive)),
        Suggestion("SETTLE_S", SETTLE_S, median_settle, [w for _, w in settles],
                   "from the settle times measured (the median shown; every settle "
                   "listed as a source)", None),
        Suggestion("SETTLE_TIMEOUT_S", SETTLE_TIMEOUT_S, slowest, slowest_from,
                   "well above the slowest settle measured", above(SETTLE_TIMEOUT_S, slowest)),
        Suggestion("TRANSIT_MARGIN_S", TRANSIT_MARGIN_S, over, over_from,
                   "above the largest (transit − planned) measured",
                   above(TRANSIT_MARGIN_S, over)),
    ]


# ── finding and reading the files ─────────────────────────────────────────


@dataclass(frozen=True)
class FlightFiles:
    flight_id: str
    csv: Path | None
    trace: Path | None
    plan: Path | None
    notes: tuple[str, ...] = ()


def _parse_time(value: str) -> datetime:
    """Both files write ISO-8601 UTC; one without an offset is taken as UTC,
    so the two can always be subtracted."""
    at = datetime.fromisoformat(value)
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _first_and_last_time(path: Path) -> tuple[datetime, datetime] | None:
    first = last = None
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                at = _parse_time(row.get("recorded_at") or "")
            except ValueError:
                continue
            first = first or at
            last = at
    return None if first is None or last is None else (first, last)


def find_flight(flight_id: str, root: Path) -> FlightFiles:
    """The three records of one flight under the agent's data folder `root`.
    Raises ReportError when the flight cannot be reported on at all."""
    if flight_id == TERMINAL_FLIGHT_ID:
        raise ReportError(
            "A flight flown with `cropwatcher mission` from the terminal is recorded under "
            "the id \"cli\" and keeps no control trace and no plan flown, so it cannot be "
            "reported on. Fly the mission from the app.")
    if not _FLIGHT_ID.match(flight_id):
        raise ReportError(f"{flight_id!r} is not a flight id (a session's flights list them).")
    notes: list[str] = []
    flights, short = root / "flights", flight_id[:8]

    # The CSV: eight characters can collide, so the rows must name the whole id.
    found_csv = None
    for path in sorted(flights.glob(f"*/flight_{short}_*.csv")):
        try:
            with path.open(newline="", encoding="utf-8") as f:
                first = next(csv.DictReader(f), None)
        except OSError:
            continue
        if first is not None and first.get("flight_id") == flight_id:
            found_csv = path
            break

    # The trace has no flight_id column: tell a colliding one apart by when it ran.
    candidates = sorted(flights.glob(f"*/trace_{short}.csv"))
    found_trace = None
    if found_csv is not None and candidates:
        span = _first_and_last_time(found_csv)
        if span is not None:
            overlapping = []
            for path in candidates:
                times = _first_and_last_time(path)
                if times is not None and times[0] <= span[1] and times[1] >= span[0]:
                    overlapping.append((abs((times[0] - span[0]).total_seconds()), path))
            if overlapping:
                found_trace = min(overlapping)[1]
                if len(overlapping) > 1:
                    notes.append("more than one trace shares this flight's name and time; "
                                 "the one that began closest to the flight CSV was used")
    elif len(candidates) == 1:
        found_trace = candidates[0]
        notes.append("the flight CSV is missing, so the trace was matched by its "
                     "8-character name only")
    elif len(candidates) > 1:
        notes.append("the flight CSV is missing and several traces share this flight's "
                     "8-character name, so none was used")

    found_plan = None
    for meta_path in sorted((root / "sessions").glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(f.get("id") == flight_id for f in meta.get("flights") or []):
            plan = meta_path.parent / "missions" / f"{flight_id}.json"
            if plan.exists():
                found_plan = plan
            break

    if found_csv is None and found_trace is None and found_plan is None:
        raise ReportError(f"No record of flight {flight_id} on this computer "
                          f"(looked in {root}).")
    if found_plan is None:
        raise ReportError(
            f"Flight {flight_id} has no plan flown kept with it, so it is not a mission "
            f"flown from the app (a Manual flight, perhaps) and there are no inspection "
            f"points to report on.")
    return FlightFiles(flight_id, found_csv, found_trace, found_plan, tuple(notes))


def _number(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def trace_rows(raw: Sequence[dict[str, str]], origin: datetime) -> tuple[list[TraceRow], int]:
    """Trace CSV rows as TraceRows; also how many could not be read."""
    rows, bad = [], 0
    for row in raw:
        try:
            at = _parse_time(row.get("recorded_at") or "")
        except ValueError:
            bad += 1
            continue
        x, y = _number(row.get("target_x_m")), _number(row.get("target_y_m"))
        h = _number(row.get("target_height_m"))
        ex, ey = _number(row.get("stateEstimate.x")), _number(row.get("stateEstimate.y"))
        rows.append(TraceRow(
            t_s=(at - origin).total_seconds(),
            state=row.get("control_state") or "", keys=row.get("keys") or "",
            target=None if x is None or y is None or h is None else (x, y, h),
            estimate=None if ex is None or ey is None else (ex, ey),
            drift_m=_number(row.get("drift_m"))))
    return rows, bad


def stamp_rows(raw: Sequence[dict[str, str]], origin: datetime) -> tuple[list[StampRow], int]:
    """Flight-CSV rows as StampRows; also how many could not be read."""
    rows, bad = [], 0
    for row in raw:
        try:
            at = _parse_time(row.get("recorded_at") or "")
        except ValueError:
            bad += 1
            continue
        rows.append(StampRow((at - origin).total_seconds(), row.get("point_id") or None))
    return rows, bad


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_review(flight_id: str, root: Path) -> FlightReview:
    """Find a flight's records under `root` and report on it."""
    files = find_flight(flight_id, root)
    assert files.plan is not None
    try:
        kept = json.loads(files.plan.read_text(encoding="utf-8"))
        mission = Mission.from_dict(kept["mission"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ReportError(f"The plan flown for flight {flight_id} cannot be read "
                          f"({files.plan}): {e}") from None
    notes = list(files.notes)
    try:
        raw_trace = _read_csv(files.trace)
    except OSError as e:
        raw_trace = []
        notes.append(f"the control trace cannot be read: {e}")
    try:
        raw_stamps = _read_csv(files.csv)
    except OSError as e:
        raw_stamps = []
        notes.append(f"the flight CSV cannot be read: {e}")
    if files.trace is None:
        notes.append("no control trace was found for this flight")
    if files.csv is None:
        notes.append("no flight CSV was found for this flight")

    starts = []
    for raw in (raw_trace, raw_stamps):
        for row in raw:
            try:
                starts.append(_parse_time(row.get("recorded_at") or ""))
                break
            except ValueError:
                continue
    origin = min(starts) if starts else datetime.now(UTC)
    trace, bad_trace = trace_rows(raw_trace, origin)
    stamps, bad_stamps = stamp_rows(raw_stamps, origin)
    if bad_trace:
        notes.append(f"{bad_trace} unreadable trace rows were skipped")
    if bad_stamps:
        notes.append(f"{bad_stamps} unreadable flight-CSV rows were skipped")
    review = review_flight(flight_id, mission, trace, stamps)
    review.notes = notes + review.notes
    return review


# ── output ────────────────────────────────────────────────────────────────


def _s(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} s"


def _cm(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} cm"


def format_review(review: FlightReview) -> str:
    lines = [f"  flight {review.flight_id}",
             f"  mission {review.mission_id} (revision {review.revision}), "
             f"{review.speed_m_s * 100:.0f} cm/s", ""]
    for leg in review.legs:
        name = "back to the start" if leg.to == "start" else (
            f"{leg.to} {leg.label}" if leg.label else leg.to)
        lines.append(f"  {name}: {'reached' if leg.reached else 'NOT REACHED'}")
        lines.append(f"      leg {leg.leg_m:.2f} m · planned {leg.planned_s:.1f} s · "
                     f"transit {_s(leg.transit_s)}")
        if leg.to != "start":
            enough = {True: "enough", False: "TOO SHORT", None: "—"}[leg.hold_long_enough]
            lines.append(f"      settle {_s(leg.settle_s)} · hold {_s(leg.hold_s)} of "
                         f"{_s(leg.hold_required_s)} ({enough})")
            lines.append(f"      hold drift: median {_cm(leg.hold_drift_median_m)} · "
                         f"95th {_cm(leg.hold_drift_p95_m)} · "
                         f"worst {_cm(leg.hold_drift_worst_m)}")
        lines += [f"      {note}" for note in leg.notes]
    lines += ["", f"  flown {_s(review.flown_s)} against the planner's "
              f"{review.estimate_s:.1f} s"]
    lines += [f"  {note}" for note in review.notes]
    return "\n".join(lines)


def format_suggestions(suggestions: Sequence[Suggestion]) -> str:
    lines = ["  the constants, from these flights (they suggest; people decide):"]
    for s in suggestions:
        measured = "nothing measured" if s.measured is None else f"measured {s.measured:.3f}"
        verdict = {True: "the current value holds", False: "the current value DOES NOT hold",
                   None: "a judgement"}[s.holds]
        lines.append(f"    {s.name} = {s.current} — {measured}; {s.rule}; {verdict}")
        if s.sources:
            lines.append(f"      from {', '.join(s.sources)}")
    return "\n".join(lines)


def to_json(reviews: Sequence[FlightReview], suggestions: Sequence[Suggestion],
            errors: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
    def flight(r: FlightReview) -> dict[str, Any]:
        data = asdict(r)
        data["over_estimate"] = r.over_estimate
        for leg, raw in zip(r.legs, [*data["points"], *([data["return_leg"]]
                                                        if r.return_leg else [])], strict=True):
            raw["over_plan_s"] = leg.over_plan_s
        return data

    return {"flights": [flight(r) for r in reviews],
            "constants": [asdict(s) for s in suggestions],
            "errors": [{"flight_id": f, "message": m} for f, m in errors]}
