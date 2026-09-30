"""The mission report: what actually happened at each inspection point.

For the operator after a mission flight, and for the lab: the numbers the
mission controller's four constants must be set from (ARRIVE_M, SETTLE_S,
SETTLE_TIMEOUT_S, TRANSIT_MARGIN_S). Without it "measure the constants from
the trace" means reading thousands of CSV rows by hand, and nobody can repeat
the reading. (mission-verification.txt, PART 2.)

WHAT IT READS — everything a mission flight flown FROM THE APP already writes:
    the control trace   flights/<day>/trace_<id[:8]>.csv   (telemetry/trace.py,
                        session._start_trace): the commanded point target_x/y
                        and height, the estimate stateEstimate.x/y, drift_m,
                        the loop's state and keys, at 10 Hz
    the flight CSV      flights/<day>/flight_<id[:8]>_*.csv (telemetry/row.py):
                        point_id on every row taken while holding
    the plan flown      sessions/<session>/missions/<flight id>.json
                        (session._keep_plan_flown): the mission exactly as
                        flown, from its real start
It finds them the way the data pipeline does (pipeline/sources.py), never
needs a drone, and never changes a file.

`cropwatcher mission` (the terminal) writes no trace and no plan flown and
records under the flight id "cli" — so a mission flown from the terminal
cannot be reported on, and this says so rather than guessing.

The calculation is plain functions over rows (TraceRow, StampRow), so it is
tested without a disk. A trace with a gap, a point never reached, a flight that
ended early: each is reported in words, never a crash and never a silent zero.

IT SUGGESTS. People decide the constants, and write the measurement and the
flights it came from beside each one (CLAUDE.md: never invent a threshold).
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
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

#: The commanded point has "reached" a spot when it is within the loop's own
#: goal tolerance of it on both motions (manual.py GOAL_REACHED_M, for the
#: glide in x-y and for the height glide): at most √2 × GOAL_REACHED_M in 3-D.
REACHED_M = math.sqrt(2.0) * GOAL_REACHED_M + 1e-4     # + the trace's 4-decimal rounding
#: A pause in the 10 Hz trace longer than this is samples lost, not jitter.
GAP_S = 3 * PERIOD_MS / 1000.0

Spot = tuple[float, float, float]


class ReportError(Exception):
    """The flight cannot be reported on. Words for the operator."""


# ── the rows ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraceRow:
    """One control-trace sample. t_s is seconds on the flight's own clock."""

    t_s: float
    state: str = ""
    keys: str = ""
    target: Spot | None = None                 # commanded x, y, height above floor
    estimate: tuple[float, float] | None = None
    drift_m: float = 0.0
    #: stateEstimate.z − posCtl.targetZ: how far the drone is off the height the
    #: firmware is holding. Both are in the estimator's frame, so this needs no
    #: floor (CLAUDE.md invariant 4 — Lighthouse z = 0 is not the floor).
    height_error_m: float | None = None


@dataclass(frozen=True)
class StampRow:
    """One flight-CSV row: when, and the inspection point it was stamped with."""

    t_s: float
    point_id: str | None


# ── the report ────────────────────────────────────────────────────────────


@dataclass
class LegReview:
    to: str                                   # a point id, or "start"
    label: str | None
    leg_m: float
    planned_s: float
    transit_s: float | None = None
    reached: bool = False
    #: Settling and holding — None for the return leg.
    settle_s: float | None = None
    hold_s: float | None = None
    hold_required_s: float | None = None
    hold_long_enough: bool | None = None
    hold_drift_median_m: float | None = None
    hold_drift_p95_m: float | None = None
    hold_drift_worst_m: float | None = None
    #: The same, vertically. THE SPEC's arrival (drift_m, ARRIVE_M) is x-y only;
    #: the height is the flight system's goal. Reported, not suggested from.
    hold_height_median_m: float | None = None
    hold_height_p95_m: float | None = None
    hold_height_worst_m: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def over_plan_s(self) -> float | None:
        return None if self.transit_s is None else self.transit_s - self.planned_s


@dataclass
class FlightReview:
    flight_id: str
    mission_id: str
    revision: int
    legs: list[LegReview]
    estimate_s: float
    flown_s: float | None
    notes: list[str] = field(default_factory=list)

    @property
    def points(self) -> list[LegReview]:
        return [leg for leg in self.legs if leg.to != "start"]

    @property
    def longer_than_estimate(self) -> bool:
        return self.flown_s is not None and self.flown_s > self.estimate_s

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["longer_than_estimate"] = self.longer_than_estimate
        for leg, raw in zip(self.legs, out["legs"], strict=True):
            raw["over_plan_s"] = leg.over_plan_s
        return out


@dataclass(frozen=True)
class Suggestion:
    constant: str
    current: float
    measured: float | None
    rule: str
    source: str                                # the flight and point it came from

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── the calculation, over rows ────────────────────────────────────────────


def review(plan: Mission, trace: Sequence[TraceRow] | None, stamps: Sequence[StampRow], *,
           flight_id: str) -> FlightReview:
    """What happened at each point of `plan` (the mission AS FLOWN), from the
    flight's trace and stamped rows."""
    estimate = plan.estimated_duration_s(move_speed_m_s=MOVE_SPEED_M_S,
                                         climb_rate_m_s=CLIMB_RATE_M_S)
    result = FlightReview(flight_id=flight_id, mission_id=plan.id, revision=plan.revision,
                          legs=[], estimate_s=estimate, flown_s=None)
    rows = sorted(trace or (), key=lambda r: r.t_s)
    stamps = sorted(stamps, key=lambda s: s.t_s)
    if not rows:
        result.notes.append(
            "There is no control trace for this flight, so transit, settle and hold drift "
            "cannot be measured (a mission flown from the terminal writes none).")
    result.notes += _gaps(rows)

    start: Spot = (plan.home[0], plan.home[1], plan.cruise_height_m)
    previous, search_from = start, rows[0].t_s if rows else 0.0
    ended_early = False
    for point in plan.points:
        spot: Spot = (point.x_m, point.y_m, point.z_m)
        leg = LegReview(to=point.id, label=point.label, leg_m=math.dist(previous, spot),
                        planned_s=math.dist(previous, spot) / MOVE_SPEED_M_S,
                        hold_required_s=point.hold_s)
        result.legs.append(leg)
        if ended_early:
            leg.notes.append("Not flown: the flight ended before it.")
            continue
        held = [s.t_s for s in stamps if s.point_id == point.id]
        reach = _transit(leg, rows, previous, spot, search_from) if rows else None
        leg.reached = reach is not None or bool(held)
        if held:
            _hold(leg, rows, stamps, spot, held, reach)
        if not leg.reached:
            ended_early = True
            if not rows:
                leg.notes.append("Never held, and there is no trace to say how close it got.")
            continue
        previous = spot
        search_from = held[-1] if held else (reach if reach is not None else search_from)

    if plan.return_to_start and not ended_early:
        leg = LegReview(to="start", label="back over the start",
                        leg_m=math.dist(previous, start),
                        planned_s=math.dist(previous, start) / MOVE_SPEED_M_S)
        result.legs.append(leg)
        if rows:
            leg.reached = _transit(leg, rows, previous, start, search_from) is not None

    if rows:
        result.flown_s, words = _flown(rows)
        if words:
            result.notes.append(words)
        if result.longer_than_estimate:
            assert result.flown_s is not None
            result.notes.append(
                f"The flight took {result.flown_s:.1f} s, longer than the planner's estimate of "
                f"{estimate:.1f} s. That estimate is the battery budget the session refuses "
                f"missions by — tell Samuel.")
    return result


def _transit(leg: LegReview, rows: Sequence[TraceRow], previous: Spot, spot: Spot,
             search_from: float) -> float | None:
    """When the commanded point reached `spot`, and how long it took from
    leaving `previous`. Returns the reach time, or None (with the reason in
    the leg's notes) if it never got there."""
    after = [r for r in rows if r.t_s >= search_from and r.target is not None]
    reach = next((r for r in after if math.dist(r.target, spot) <= REACHED_M), None)  # type: ignore[arg-type]
    if reach is None:
        closest = min((math.dist(r.target, spot) for r in after), default=None)  # type: ignore[arg-type]
        leg.notes.append(
            "Not reached: the commanded point never got there" +
            ("" if closest is None else f" (closest {closest:.2f} m)") + ".")
        return None
    left = [r for r in after if r.t_s <= reach.t_s
            and math.dist(r.target, previous) <= REACHED_M]  # type: ignore[arg-type]
    if left:
        leg.transit_s = reach.t_s - left[-1].t_s
    else:
        leg.notes.append("The commanded point was never seen at the spot this leg starts "
                         "from, so the transit time is unknown.")
    if _gap_between(rows, left[-1].t_s if left else search_from, reach.t_s):
        leg.notes.append("The trace has a gap during this transit; its time is approximate.")
    return reach.t_s


def _hold(leg: LegReview, rows: Sequence[TraceRow], stamps: Sequence[StampRow], spot: Spot,
          held: list[float], reach: float | None) -> None:
    interval = _median_interval([s.t_s for s in stamps])
    leg.hold_s = held[-1] - held[0]
    assert leg.hold_required_s is not None
    # The stamped rows are samples: the first and last are up to one interval
    # inside the real hold.
    leg.hold_long_enough = leg.hold_s + interval >= leg.hold_required_s
    if not leg.hold_long_enough:
        leg.notes.append(f"Held {leg.hold_s:.1f} s of the {leg.hold_required_s:.1f} s asked.")
    during = [r for r in rows if held[0] <= r.t_s <= held[-1] and r.estimate is not None]
    offs = sorted(math.dist(r.estimate, spot[:2]) for r in during)  # type: ignore[arg-type]
    if offs:
        leg.hold_drift_median_m = statistics.median(offs)
        leg.hold_drift_p95_m = _p95(offs)
        leg.hold_drift_worst_m = offs[-1]
    elif rows:
        leg.notes.append("The trace has no position while it held; no hold drift.")
    heights = sorted(abs(r.height_error_m) for r in rows
                     if held[0] <= r.t_s <= held[-1] and r.height_error_m is not None)
    if heights:
        leg.hold_height_median_m = statistics.median(heights)
        leg.hold_height_p95_m = _p95(heights)
        leg.hold_height_worst_m = heights[-1]
    if reach is None or not rows:
        return
    # Settle: from the commanded point reaching it to the drone within
    # ARRIVE_M and staying there until the hold began — the start of the
    # unbroken run of in-range samples that ends at HOLD_STARTED.
    before = [r for r in rows if reach <= r.t_s <= held[0] and r.estimate is not None]
    settled_at = None
    for r in reversed(before):
        if math.dist(r.estimate, spot[:2]) <= ARRIVE_M:  # type: ignore[arg-type]
            settled_at = r.t_s
        else:
            break
    if settled_at is None:
        leg.notes.append("No sample shows the drone within ARRIVE_M before the hold began.")
    else:
        leg.settle_s = max(0.0, settled_at - reach)


def _flown(rows: Sequence[TraceRow]) -> tuple[float | None, str]:
    """From arming (the mission's takeoff follows at once) to touchdown."""
    climbing = next((r.t_s for r in rows if r.state in ("armed", "flying")), None)
    landed = next((r.t_s for r in rows if r.state == "landed"
                   and climbing is not None and r.t_s > climbing), None)
    if climbing is None:
        return None, "The trace never shows the drone armed or flying."
    if landed is None:
        return rows[-1].t_s - climbing, ("The trace ends before the drone is recorded as "
                                         "landed; the flown time runs to its last sample.")
    return landed - climbing, ""


def _p95(ordered: Sequence[float]) -> float:
    """The 95th percentile by nearest rank: a value that was measured."""
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _median_interval(times: Sequence[float]) -> float:
    steps = [b - a for a, b in zip(times, times[1:], strict=False) if b > a]
    return statistics.median(steps) if steps else 0.0


def _gaps(rows: Sequence[TraceRow]) -> list[str]:
    return [f"The trace has a {b.t_s - a.t_s:.1f} s gap at +{a.t_s - rows[0].t_s:.1f} s "
            f"(the radio dropped samples)."
            for a, b in zip(rows, rows[1:], strict=False) if b.t_s - a.t_s > GAP_S]


def _gap_between(rows: Sequence[TraceRow], start: float, end: float) -> bool:
    inside = [r.t_s for r in rows if start <= r.t_s <= end]
    return any(b - a > GAP_S for a, b in zip(inside, inside[1:], strict=False))


# ── what the constants should be ──────────────────────────────────────────


def suggest(reviews: Sequence[FlightReview]) -> list[Suggestion]:
    """The four constants, from every flight given — each figure with the
    flight and point it came from, to be cited beside the constant."""

    def worst(values: list[tuple[float, str]]) -> tuple[float | None, str]:
        if not values:
            return None, "nothing measured"
        value, where = max(values)
        return value, where

    p95 = [(leg.hold_drift_p95_m, f"{r.flight_id} {leg.to}") for r in reviews
           for leg in r.points if leg.hold_drift_p95_m is not None]
    settles = [(leg.settle_s, f"{r.flight_id} {leg.to}") for r in reviews
               for leg in r.points if leg.settle_s is not None]
    overs = [(leg.over_plan_s, f"{r.flight_id} → {leg.to}") for r in reviews
             for leg in r.legs if leg.over_plan_s is not None]
    drift, drift_at = worst(p95)
    settle, settle_at = worst(settles)
    over, over_at = worst(overs)
    median_settle = statistics.median(v for v, _ in settles) if settles else None
    return [
        Suggestion("ARRIVE_M", ARRIVE_M, drift,
                   "above the worst 95th-percentile hold drift, or holding still would "
                   "never count as arrived", drift_at),
        Suggestion("SETTLE_S", SETTLE_S, median_settle,
                   "from the settle times measured (the median shown; the slowest is "
                   "SETTLE_TIMEOUT_S's figure)", f"{len(settles)} settles"),
        Suggestion("SETTLE_TIMEOUT_S", SETTLE_TIMEOUT_S, settle,
                   "well above the slowest settle measured", settle_at),
        Suggestion("TRANSIT_MARGIN_S", TRANSIT_MARGIN_S, over,
                   "above the largest (transit − planned) measured", over_at),
    ]


# ── reading the files ─────────────────────────────────────────────────────


def _seconds(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _float(value: str | None) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except ValueError:
        return None


def trace_rows(path: Path) -> list[TraceRow]:
    rows: list[TraceRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            try:
                at = _seconds(raw["recorded_at"])
            except (KeyError, ValueError):
                continue
            tx, ty = _float(raw.get("target_x_m")), _float(raw.get("target_y_m"))
            th = _float(raw.get("target_height_m"))
            ex, ey = _float(raw.get("stateEstimate.x")), _float(raw.get("stateEstimate.y"))
            ez, tz = _float(raw.get("stateEstimate.z")), _float(raw.get("posCtl.targetZ"))
            rows.append(TraceRow(
                t_s=at, state=raw.get("control_state") or "", keys=raw.get("keys") or "",
                target=None if tx is None or ty is None or th is None else (tx, ty, th),
                estimate=None if ex is None or ey is None else (ex, ey),
                drift_m=_float(raw.get("drift_m")) or 0.0,
                height_error_m=None if ez is None or tz is None else ez - tz))
    return rows


def stamp_rows(path: Path) -> list[StampRow]:
    with path.open(newline="", encoding="utf-8") as f:
        return [StampRow(_seconds(raw["recorded_at"]), raw.get("point_id") or None)
                for raw in csv.DictReader(f) if raw.get("recorded_at")]


def load(root: Path, flight_id: str) -> FlightReview:
    """Report on one flight from the files under the agent's data folder."""
    from cropwatcher.pipeline.sources import FlightNotFound, LocalFlightSource

    # The data pipeline's source is the one place that knows where a flight's
    # CSV and session folder are; the report reads the same files it does.
    source = LocalFlightSource(root)
    try:
        csv_path = source._find_csv(flight_id)
    except FlightNotFound as e:
        raise ReportError(str(e)) from e
    session = source._find_session(flight_id)
    plan_path = session / "missions" / f"{flight_id}.json" if session else None
    if plan_path is None or not plan_path.exists():
        raise ReportError(
            f"Flight {flight_id} kept no plan flown, so it was not a mission flown from the "
            f"app (a mission flown with `cropwatcher mission` keeps none).")
    try:
        plan = Mission.from_dict(json.loads(plan_path.read_text(encoding="utf-8"))["mission"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ReportError(f"The plan flown by {flight_id} could not be read: {e}") from e
    trace_path = csv_path.parent / f"trace_{flight_id[:8]}.csv"
    trace = trace_rows(trace_path) if trace_path.exists() else None
    stamps = stamp_rows(csv_path)
    origin = min([r.t_s for r in (trace or [])[:1]] + [s.t_s for s in stamps[:1]], default=0.0)
    return review(plan,
                  [replace(r, t_s=r.t_s - origin) for r in trace]
                  if trace is not None else None,
                  [StampRow(s.t_s - origin, s.point_id) for s in stamps],
                  flight_id=flight_id)


# ── words ─────────────────────────────────────────────────────────────────


def _n(value: float | None, unit: str, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f} {unit}"


def as_text(reviews: Sequence[FlightReview], suggestions: Sequence[Suggestion]) -> str:
    lines: list[str] = []
    for r in reviews:
        lines.append(f"\n  flight {r.flight_id} — mission {r.mission_id} r{r.revision}")
        for leg in r.legs:
            name = leg.to + (f" ({leg.label})" if leg.label else "")
            lines.append(f"\n    {name}   {'reached' if leg.reached else 'NOT REACHED'}")
            lines.append(f"      leg {leg.leg_m:.2f} m · planned {leg.planned_s:.1f} s · "
                         f"transit {_n(leg.transit_s, 's')}")
            if leg.to != "start":
                ok = {True: "enough", False: "SHORT", None: ""}[leg.hold_long_enough]
                lines.append(f"      settle {_n(leg.settle_s, 's')} · hold {_n(leg.hold_s, 's')} "
                             f"of {_n(leg.hold_required_s, 's')} {ok}")
                lines.append(f"      hold drift median {_n(leg.hold_drift_median_m, 'm', 3)} · "
                             f"p95 {_n(leg.hold_drift_p95_m, 'm', 3)} · "
                             f"worst {_n(leg.hold_drift_worst_m, 'm', 3)}")
                lines.append(f"      off its height median {_n(leg.hold_height_median_m, 'm', 3)}"
                             f" · p95 {_n(leg.hold_height_p95_m, 'm', 3)} · "
                             f"worst {_n(leg.hold_height_worst_m, 'm', 3)}")
            lines += [f"      ! {note}" for note in leg.notes]
        lines.append(f"\n    flown {_n(r.flown_s, 's')} against the estimate "
                     f"{r.estimate_s:.1f} s")
        lines += [f"    ! {note}" for note in r.notes]
    lines.append("\n  the constants — suggestions; people decide, and cite the flights")
    for s in suggestions:
        lines.append(f"    {s.constant:<17} now {s.current:g} · measured "
                     f"{_n(s.measured, '', 3).strip()} ({s.source})")
        lines.append(f"    {'':<17} {s.rule}")
    return "\n".join(lines)


def as_json(reviews: Sequence[FlightReview], suggestions: Sequence[Suggestion]) -> str:
    return json.dumps({"flights": [r.to_dict() for r in reviews],
                       "suggestions": [s.to_dict() for s in suggestions]}, indent=2)
