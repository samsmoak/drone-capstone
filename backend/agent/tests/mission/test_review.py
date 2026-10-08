"""The mission report (cropwatcher/mission/review.py; mission-verification.txt,
PART 2).

One hand-built flight, two points and the return, flown at Steady (10 cm/s)
so the planned times are not leg / MOVE_SPEED_M_S. Every figure it should
produce is worked out by hand beside the flight below, so a test can assert
it exactly. The variants — a gap, an unreached point, an aborted flight, the
operator taking over — are that same flight cut short or broken in one place.
"""

from __future__ import annotations

import csv
import inspect
import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cropwatcher import cli
from cropwatcher.flight.manual import CLIMB_RATE_M_S, MOVE_SPEED_M_S
from cropwatcher.mission.controller.mission_controller import (
    ARRIVE_M,
    SETTLE_S,
    SETTLE_TIMEOUT_S,
    TRANSIT_MARGIN_S,
)
from cropwatcher.mission.plan.mission import SPEED_PRESETS_M_S, InspectionPoint, Mission
from cropwatcher.mission.review import (
    ReportError,
    StampRow,
    TraceRow,
    find_flight,
    load_review,
    percentile,
    planned_leg_s,
    planner_estimate_s,
    review_flight,
    suggest_constants,
    to_json,
)
from cropwatcher.telemetry.trace import FlightTrace
from tests.mission import plans

FLIGHT = "3f2a9c1e-0b7d-4c55-9a21-6e8f00c4d2b1"
STEADY = min(SPEED_PRESETS_M_S)

MISSION = Mission(
    id="m2", name="Two pumps", room_id="lab", home=(0.0, 0.0),
    points=(InspectionPoint("P1", 1.0, 0.0, 0.4, 5.0, "Pump 1"),
            InspectionPoint("P2", 1.0, 0.5, 0.6, 5.0, "Pump 2")),
    cruise_height_m=0.4, return_to_start=True, speed_m_s=STEADY)

#: P1's hold: 51 samples, the estimate this far off the point. Sorted, the
#: 26th (median) is 1 cm, the 49th (nearest-rank 95th) 5 cm, the worst 7 cm.
P1_OFFSETS = [0.01] * 40 + [0.02] * 8 + [0.05] * 2 + [0.07]


def t(n: int) -> float:
    return n / 10


def lerp(a: tuple[float, ...], b: tuple[float, ...], frac: float) -> tuple[float, float, float]:
    x, y, z = (p + (q - p) * frac for p, q in zip(a, b, strict=True))
    return (x, y, z)


def flight() -> tuple[list[TraceRow], list[StampRow]]:
    """The whole flight, sample n at t = n / 10 s.

      n 0        armed on the floor
      n 1–4      lift-off (t 0.1) and the climb; at cruise at n 4: the
                 takeoff spot is (0, 0)
      n 10→30    transit to P1: last still at n 10, there at n 30 → 2.0 s
      n 30–34    settle: over ARRIVE_M, under, over again, then under from
                 n 34 → 0.4 s
      n 45–95    P1 held (stamped) → 5.0 s
      n 100→120  transit to P2 (rising 0.2 m) → 2.0 s; settled from n 123
                 → 0.3 s; held n 135–185 → 5.0 s, 2 cm off throughout
      n 190→220  back to the start → 3.0 s
      n 225      landing; landed at n 255 → flown 25.5 − 0.1 = 25.4 s
    """
    p1, p2, top = (1.0, 0.0, 0.4), (1.0, 0.5, 0.6), (0.0, 0.0, 0.4)
    rows: list[TraceRow] = []
    for n in range(256):
        state = "armed" if n == 0 else "landing" if 225 <= n < 255 else (
            "landed" if n == 255 else "flying")
        drift = 0.0
        if n == 0:
            target = None
        elif n <= 4:
            target = (0.0, 0.0, n / 10)
        elif n <= 10:
            target = top
        elif n <= 30:
            target = lerp(top, p1, (n - 10) / 20)
            drift = 0.1
        elif n <= 100:
            target = p1
        elif n <= 120:
            target = lerp(p1, p2, (n - 100) / 20)
            drift = 0.1
        elif n <= 190:
            target = p2
        elif n <= 220:
            target = lerp(p2, top, (n - 190) / 30)
            drift = 0.1
        else:
            target = top
        if 30 <= n <= 100:
            drift = {30: 3.0, 31: 2.0, 32: 0.5, 33: 1.2}.get(n, 0.5) * ARRIVE_M
        if 120 <= n <= 190:
            drift = (1.5 if n < 123 else 0.2) * ARRIVE_M
        estimate = (0.0, 0.0) if target is None else (target[0], target[1])
        if 45 <= n <= 95:
            estimate = (1.0 + P1_OFFSETS[n - 45], 0.0)
        if 135 <= n <= 185:
            estimate = (1.02, 0.5)
        rows.append(TraceRow(t(n), state, "", target, estimate, drift))
    stamps = [StampRow(t(n), "P1" if 45 <= n <= 95 else "P2" if 135 <= n <= 185 else None)
              for n in range(256)]
    return rows, stamps


def up_to(rows, n: int):
    return [r for r in rows if r.t_s <= t(n) + 1e-9]


# ── the figures, exactly ─────────────────────────────────────────────────


class TestEveryFigure:
    def setup_method(self):
        self.review = review_flight(FLIGHT, MISSION, *flight())
        self.p1, self.p2 = self.review.points
        self.back = self.review.return_leg

    def test_legs_and_planned_times_follow_the_missions_speed(self):
        assert self.p1.leg_m == pytest.approx(1.0)
        assert self.p1.planned_s == pytest.approx(1.0 / STEADY)           # 10 s, not 5
        # 0.5 m across at 10 cm/s outlasts 0.2 m up at the climb rate.
        assert self.p2.leg_m == pytest.approx(math.sqrt(0.5**2 + 0.2**2))
        assert self.p2.planned_s == pytest.approx(0.5 / STEADY)
        assert self.back is not None
        assert self.back.leg_m == pytest.approx(math.sqrt(1.0 + 0.25 + 0.04))
        assert self.back.planned_s == pytest.approx(math.hypot(1.0, 0.5) / STEADY)

    def test_transit_settle_and_hold(self):
        assert (self.p1.transit_s, self.p2.transit_s) == (pytest.approx(2.0), pytest.approx(2.0))
        assert self.back is not None and self.back.transit_s == pytest.approx(3.0)
        assert self.p1.settle_s == pytest.approx(0.4)        # drift back over restarts it
        assert self.p2.settle_s == pytest.approx(0.3)
        assert self.p1.hold_s == pytest.approx(5.0) and self.p1.hold_required_s == 5.0
        assert self.p1.hold_long_enough and self.p2.hold_long_enough
        assert self.p1.over_plan_s == pytest.approx(2.0 - 10.0)

    def test_hold_drift(self):
        assert self.p1.hold_drift_median_m == pytest.approx(0.01)
        assert self.p1.hold_drift_p95_m == pytest.approx(0.05)
        assert self.p1.hold_drift_worst_m == pytest.approx(0.07)
        assert self.p2.hold_drift_median_m == pytest.approx(0.02)
        assert self.p2.hold_drift_worst_m == pytest.approx(0.02)

    def test_reached_and_nothing_to_say(self):
        assert all(leg.reached for leg in self.review.legs)
        assert all(not leg.notes for leg in self.review.legs)
        assert self.review.notes == []

    def test_flown_time_against_the_planners(self):
        assert self.review.flown_s == pytest.approx(25.4)
        assert self.review.estimate_s == pytest.approx(planner_estimate_s(MISSION))
        assert self.review.over_estimate is False

    def test_the_constants_cite_where_each_figure_came_from(self):
        found = {s.name: s for s in suggest_constants([self.review])}
        assert found["ARRIVE_M"].measured == pytest.approx(0.05)
        assert found["ARRIVE_M"].sources == [f"{FLIGHT[:8]} P1"]
        assert found["ARRIVE_M"].holds is (ARRIVE_M > 0.05)
        assert found["SETTLE_S"].measured == pytest.approx(0.35)          # median of 0.4, 0.3
        assert found["SETTLE_S"].current == SETTLE_S
        assert found["SETTLE_TIMEOUT_S"].measured == pytest.approx(0.4)
        assert found["SETTLE_TIMEOUT_S"].sources == [f"{FLIGHT[:8]} P1"]
        assert found["SETTLE_TIMEOUT_S"].current == SETTLE_TIMEOUT_S
        # The largest transit − planned is P2's: 2.0 − 5.0.
        assert found["TRANSIT_MARGIN_S"].measured == pytest.approx(-3.0)
        assert found["TRANSIT_MARGIN_S"].sources == [f"{FLIGHT[:8]} P2"]
        assert found["TRANSIT_MARGIN_S"].current == TRANSIT_MARGIN_S

    def test_several_flights_together(self):
        other = replace(self.review, flight_id="ffffffff-0000")
        found = {s.name: s for s in suggest_constants([self.review, other])}
        assert found["ARRIVE_M"].sources == [f"{FLIGHT[:8]} P1", "ffffffff P1"]

    def test_nothing_measured_says_so(self):
        found = suggest_constants([])
        assert all(s.measured is None and s.holds is None and not s.sources for s in found)


class TestPlannedTimeIsThePlanners:
    """The report's planned leg times add up to Mission.estimated_duration_s,
    so the report and the battery check cannot quietly disagree."""

    @pytest.mark.parametrize("speed", SPEED_PRESETS_M_S)
    @pytest.mark.parametrize("returns", [True, False])
    def test_legs_add_up_to_the_estimate(self, speed, returns):
        mission = plans.mission(speed_m_s=speed, return_to_start=returns)
        settle = inspect.signature(Mission.estimated_duration_s).parameters["settle_s"].default
        cruise = mission.cruise_height_m
        stops = [(*mission.home, cruise), *((p.x_m, p.y_m, p.z_m) for p in mission.points)]
        if returns:
            stops.append((*mission.home, cruise))
        total = cruise / CLIMB_RATE_M_S
        total += sum(planned_leg_s(a, b, mission) + settle
                     for a, b in zip(stops, stops[1:], strict=False))
        total += sum(p.hold_s for p in mission.points)
        total += stops[-1][2] / CLIMB_RATE_M_S + 1.0
        assert total == pytest.approx(planner_estimate_s(mission), abs=1e-9)

    def test_never_faster_than_the_flight_system(self):
        brisk = replace(MISSION, speed_m_s=max(SPEED_PRESETS_M_S))
        assert planned_leg_s((0, 0, 0.4), (1, 0, 0.4), brisk) == pytest.approx(
            1.0 / min(MOVE_SPEED_M_S, brisk.speed_m_s))

    def test_a_climb_can_outlast_the_distance(self):
        assert planned_leg_s((0, 0, 0.2), (0.01, 0, 0.8), MISSION) == pytest.approx(
            0.6 / CLIMB_RATE_M_S)


class TestPercentile:
    def test_nearest_rank(self):
        assert percentile([3, 1, 2, 5, 4], 95) == 5
        assert percentile([3, 1, 2, 5, 4], 50) == 3
        assert percentile([7], 95) == 7


# ── when the flight went wrong: words, never a crash ─────────────────────


class TestWhenItGoesWrong:
    def test_a_gap_in_the_trace_is_reported(self):
        rows, stamps = flight()
        rows = [r for r in rows if not t(15) <= r.t_s < t(20) - 1e-9]
        review = review_flight(FLIGHT, MISSION, rows, stamps)
        assert any("no samples for 0.6 s from 1.4 s" in n for n in review.notes)
        p1 = review.points[0]
        assert p1.transit_s == pytest.approx(2.0)
        assert any("gap during this transit" in n for n in p1.notes)

    def test_a_point_never_reached(self):
        rows, stamps = flight()
        kept = up_to(rows, 110)
        stuck = kept[-1].target
        kept += [TraceRow(t(n), "landing" if n < 141 else "landed", "", stuck, stuck[:2], 0.0)
                 for n in range(111, 142)]
        review = review_flight(FLIGHT, MISSION, kept, up_to(stamps, 110))
        p1, p2 = review.points
        assert p1.reached and p1.hold_long_enough
        assert not p2.reached and p2.transit_s is None and p2.settle_s is None
        assert any("not reached" in n and "began landing at 11.1 s" in n for n in p2.notes)
        assert review.return_leg is not None and not review.return_leg.reached
        assert review.return_leg.notes == ["not flown: the flight ended before it"]
        assert any("did not finish" in n and "P2" in n for n in review.notes)
        assert review.flown_s == pytest.approx(14.0)

    def test_an_aborted_flight_mid_hold(self):
        rows, stamps = flight()
        kept = up_to(rows, 60) + [TraceRow(t(61), "stopped", "", None, None, 0.0)]
        review = review_flight(FLIGHT, MISSION, kept, up_to(stamps, 60))
        p1, p2 = review.points
        assert p1.reached and p1.hold_s == pytest.approx(1.5)
        assert p1.hold_long_enough is False
        assert any("of the 5.0 s" in n and "emergency stop at 6.1 s" in n for n in p1.notes)
        assert p2.notes == ["not flown: the flight ended before it"]
        assert review.flown_s is None and review.over_estimate is None
        assert any("did not land normally" in n and "emergency stop" in n for n in review.notes)

    def test_the_operator_taking_over(self):
        rows, stamps = flight()
        kept = up_to(rows, 105)
        last = kept[-1].target
        kept += [TraceRow(t(n), "flying", "forward", (last[0] - 0.01 * (n - 105), *last[1:]),
                          None, 0.0) for n in range(106, 131)]
        review = review_flight(FLIGHT, MISSION, kept, up_to(stamps, 105))
        p2 = review.points[1]
        assert not p2.reached
        assert any("the operator took over (forward held at 10.6 s)" in n for n in p2.notes)

    def test_reached_but_never_settled(self):
        rows, stamps = flight()
        kept = [replace(r, drift_m=2 * ARRIVE_M) if r.t_s >= t(30) else r
                for r in up_to(rows, 130)]
        kept.append(TraceRow(t(131), "landing", "", (1.0, 0.0, 0.4), (1.0, 0.0), 0.0))
        no_hold = [replace(s, point_id=None) for s in up_to(stamps, 131)]
        review = review_flight(FLIGHT, MISSION, kept, no_hold)
        p1 = review.points[0]
        assert p1.reached and p1.settle_s is None and p1.hold_s is None
        assert any("never settled" in n and f"{2 * ARRIVE_M * 100:.1f} cm" in n for n in p1.notes)
        assert any("never held" in n for n in p1.notes)

    def test_no_trace_and_no_csv(self):
        review = review_flight(FLIGHT, MISSION, [], [])
        assert all(not leg.reached for leg in review.legs)
        assert any("no control trace" in n for n in review.notes)
        assert any("no hold can be measured" in n for n in review.notes)
        assert review.flown_s is None

    def test_never_reached_cruise_height(self):
        rows, stamps = flight()
        low = [replace(r, target=(0.0, 0.0, 0.2)) if r.target else r for r in up_to(rows, 20)]
        review = review_flight(FLIGHT, MISSION, low, up_to(stamps, 20))
        assert any("never reached its cruise height" in n for n in review.notes)
        assert all(not leg.reached for leg in review.points)

    def test_a_flight_longer_than_its_estimate_says_so(self):
        rows, stamps = flight()
        rows[-1] = replace(rows[-1], t_s=60.0)
        review = review_flight(FLIGHT, MISSION, rows, stamps)
        assert review.flown_s == pytest.approx(59.9)
        assert review.over_estimate is True
        note = next(n for n in review.notes if "longer than the planner's" in n)
        assert "battery" in note and "Samuel" in note


# ── the files, as a flight writes them ───────────────────────────────────


START = datetime(2026, 10, 8, 14, 0, 0, tzinfo=UTC)


def write_flight(root: Path, flight_id: str = FLIGHT, *, start: datetime = START,
                 rows=None, stamps=None, plan: bool = True, session: str = "s1") -> None:
    """The three records, where and how the session writes them."""
    if rows is None or stamps is None:
        rows, stamps = flight()
    day = root / "flights" / start.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    trace_path = day / f"trace_{flight_id[:8]}.csv"
    FlightTrace(trace_path, controller=None).close()            # the real header
    with trace_path.open(newline="") as f:
        header = next(csv.reader(f))
    with trace_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, restval="")
        for r in rows:
            row = {"recorded_at": (start + timedelta(seconds=r.t_s)).isoformat(),
                   "control_state": r.state, "keys": r.keys,
                   "drift_m": "" if r.drift_m is None else round(r.drift_m, 4)}
            if r.target is not None:
                row |= {"target_x_m": round(r.target[0], 4), "target_y_m": round(r.target[1], 4),
                        "target_height_m": round(r.target[2], 4)}
            if r.estimate is not None:
                row |= {"stateEstimate.x": r.estimate[0], "stateEstimate.y": r.estimate[1]}
            writer.writerow(row)
    stamp = start.strftime("%Y-%m-%d_%H-%M-%S")
    with (day / f"flight_{flight_id[:8]}_{stamp}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "recorded_at", "flight_id", "point_id"])
        writer.writeheader()
        for i, s in enumerate(stamps):
            writer.writerow({"index": i, "flight_id": flight_id, "point_id": s.point_id or "",
                             "recorded_at": (start + timedelta(seconds=s.t_s)).isoformat()})
    folder = root / "sessions" / session
    (folder / "missions").mkdir(parents=True, exist_ok=True)
    meta = folder / "meta.json"
    flights = json.loads(meta.read_text())["flights"] if meta.exists() else []
    meta.write_text(json.dumps({"id": session, "flights": [*flights, {"id": flight_id}]}))
    if plan:
        (folder / "missions" / f"{flight_id}.json").write_text(json.dumps(
            {"flight_id": flight_id, "mission": MISSION.to_dict(), "room": {}, "moves": []}))


class TestFromTheFiles:
    def test_the_same_figures_as_from_the_rows(self, tmp_path):
        write_flight(tmp_path)
        from_files = load_review(FLIGHT, tmp_path)
        from_rows = review_flight(FLIGHT, MISSION, *flight())
        for a, b in zip(from_files.legs, from_rows.legs, strict=True):
            for name in ("leg_m", "planned_s", "transit_s", "settle_s", "hold_s",
                         "hold_drift_median_m", "hold_drift_p95_m", "hold_drift_worst_m"):
                assert getattr(a, name) == pytest.approx(getattr(b, name), abs=1e-6), name
        assert from_files.flown_s == pytest.approx(from_rows.flown_s, abs=1e-6)
        assert from_files.notes == []

    def test_a_colliding_short_id_is_told_apart(self, tmp_path):
        twin = FLIGHT[:8] + "-ffff-ffff-ffff-ffffffffffff"
        write_flight(tmp_path)
        write_flight(tmp_path, twin, start=START + timedelta(days=1), session="s2")
        files = find_flight(FLIGHT, tmp_path)
        assert files.csv is not None and files.csv.parent.name == "2026-10-08"
        assert files.trace is not None and files.trace.parent.name == "2026-10-08"
        assert find_flight(twin, tmp_path).trace.parent.name == "2026-10-09"

    def test_a_missing_trace_is_reported_not_fatal(self, tmp_path):
        write_flight(tmp_path)
        next((tmp_path / "flights").glob("*/trace_*.csv")).unlink()
        review = load_review(FLIGHT, tmp_path)
        assert any("no control trace was found" in n for n in review.notes)

    def test_a_flight_with_no_records(self, tmp_path):
        with pytest.raises(ReportError, match="No record of flight"):
            find_flight(FLIGHT, tmp_path)

    def test_a_manual_flight_has_no_plan_to_report_on(self, tmp_path):
        write_flight(tmp_path, plan=False)
        with pytest.raises(ReportError, match="no plan flown"):
            find_flight(FLIGHT, tmp_path)

    def test_a_terminal_flight_cannot_be_reported_on(self, tmp_path):
        with pytest.raises(ReportError, match="from the terminal"):
            find_flight("cli", tmp_path)

    @pytest.mark.parametrize("bad", ["../etc", "a*b", "", "x" * 65])
    def test_a_flight_id_is_never_a_path(self, tmp_path, bad):
        with pytest.raises(ReportError, match="not a flight id"):
            find_flight(bad, tmp_path)

    def test_it_never_writes(self, tmp_path):
        write_flight(tmp_path)
        before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
        load_review(FLIGHT, tmp_path)
        assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")} == before


# ── `cropwatcher mission-report` ─────────────────────────────────────────


class TestCommand:
    @pytest.fixture(autouse=True)
    def data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        return tmp_path

    def test_a_missing_flight_says_so_and_fails(self, capsys):
        assert cli.main(["mission-report", "--flight", FLIGHT]) == 1
        assert f"No record of flight {FLIGHT}" in capsys.readouterr().out

    def test_prints_the_report(self, data_dir, capsys):
        write_flight(data_dir)
        assert cli.main(["mission-report", "--flight", FLIGHT]) == 0
        out = capsys.readouterr().out
        assert "P1 Pump 1: reached" in out and "back to the start: reached" in out
        assert "TRANSIT_MARGIN_S" in out

    def test_json_is_valid_and_has_the_same_numbers(self, data_dir, capsys):
        write_flight(data_dir)
        assert cli.main(["mission-report", "--flight", FLIGHT, "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        review = load_review(FLIGHT, data_dir)
        assert data == json.loads(json.dumps(to_json([review], suggest_constants([review]))))
        p1 = data["flights"][0]["points"][0]
        assert p1["transit_s"] == pytest.approx(2.0, abs=1e-6)
        assert p1["over_plan_s"] == pytest.approx(-8.0, abs=1e-6)
        assert data["errors"] == []

    def test_json_names_a_missing_flight_and_fails(self, data_dir, capsys):
        write_flight(data_dir)
        code = cli.main(["mission-report", "--flight", FLIGHT, "--flight", "cli", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert code == 1
        assert len(data["flights"]) == 1
        assert data["errors"][0]["flight_id"] == "cli"
