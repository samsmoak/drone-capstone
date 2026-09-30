"""The mission report (cropwatcher/mission/review.py): every figure exact on a
hand-built flight, the imperfect flights reported in words, the command line,
and a simulated mission written through the REAL FlightTrace whose report
agrees with what the simulator did (mission-verification.txt, PART 2)."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cropwatcher import cli
from cropwatcher.flight.manual import CLIMB_RATE_M_S, MOVE_SPEED_M_S, Fix
from cropwatcher.mission.controller import MissionController, MissionState
from cropwatcher.mission.controller.mission_controller import (
    ARRIVE_M,
    SETTLE_S,
    SETTLE_TIMEOUT_S,
    TRANSIT_MARGIN_S,
)
from cropwatcher.mission.plan.mission import InspectionPoint, Mission
from cropwatcher.mission.review import (
    StampRow,
    TraceRow,
    as_json,
    as_text,
    load,
    review,
    suggest,
)
from cropwatcher.telemetry import trace as flight_trace
from tests.mission.plans import mission
from tests.sim_drone import SimDrone

H = 0.40                                       # cruise height, and every point's


def plan(**changes) -> Mission:
    """A plan as data, for the hand-built flight — the report never checks
    it against a room. The simulated flight below flies plans.mission()."""
    base = Mission(
        id="m2", name="Two pumps", room_id="bare", home=(0.0, 0.0),
        points=(InspectionPoint("P1", 1.0, 0.0, H, 5.0, "Pump 1"),
                InspectionPoint("P2", 1.0, 1.0, H, 5.0, "Pump 2")),
        cruise_height_m=H, return_to_start=False)
    return base.edited(**changes) if changes else base


# ── a flight built by hand, every figure known ────────────────────────────
#
# tenths of a second:
#   0      armed; 5 flying; the commanded point over home at H
#   30     leaves home; glides 1 m to P1, reaching it at 90   → transit 6.0 s
#   90–94  the drone 0.15 m short; within ARRIVE_M from 95    → settle 0.5 s
#   105–155  P1 stamped                                        → hold 5.0 s
#   156    leaves P1; reaches P2 at 216                        → transit 6.0 s
#   216–220  0.15 m short; within from 221                     → settle 0.5 s
#   231–281  P2 stamped                                        → hold 5.0 s
#   285    landing; 315 landed; the trace ends at 320          → flown 31.5 s
#
# While holding, the drone is 0.02 m off, except five samples at 0.06 m and
# one at 0.09 m: 51 samples → median 0.02, p95 (nearest rank 49) 0.06,
# worst 0.09.

P1, P2 = (1.0, 0.0), (1.0, 1.0)
HOLDS = {"P1": (105, 155), "P2": (231, 281)}
SPIKES = {3: 0.06, 11: 0.06, 19: 0.06, 27: 0.06, 35: 0.06, 43: 0.09}


def _target(i: int) -> tuple[float, float]:
    if i <= 30:
        return (0.0, 0.0)
    if i <= 90:
        return ((i - 30) / 60, 0.0)
    if i <= 156:
        return P1
    if i <= 216:
        return (1.0, (i - 156) / 60)
    return P2


def _estimate(i: int) -> tuple[float, float]:
    tx, ty = _target(i)
    for name, (a, b) in HOLDS.items():
        if a <= i <= b:
            off = SPIKES.get(i - a, 0.02)
            return (tx + off, ty) if name == "P1" else (tx, ty + off)
    if 90 <= i < 95:
        return (P1[0] - 0.15, P1[1])
    if 216 <= i < 221:
        return (P2[0], P2[1] - 0.15)
    if 95 <= i < 105:
        return (P1[0] + 0.02, P1[1])
    if 221 <= i < 231:
        return (P2[0], P2[1] + 0.02)
    return (tx, ty)


def _state(i: int) -> str:
    return ("armed" if i < 5 else "flying" if i < 285 else "landing" if i < 315
            else "landed")


def hand_trace(last: int = 320, skip: range = range(0)) -> list[TraceRow]:
    rows = []
    for i in range(last + 1):
        if i in skip:
            continue
        target = _target(i)
        rows.append(TraceRow(t_s=i / 10, state=_state(i),
                             target=None if i < 5 else (target[0], target[1], H),
                             estimate=_estimate(i),
                             # 1 cm low, except one sample 3 cm high, while holding
                             height_error_m=0.03 if i in (110, 236) else -0.01))
    return rows


def hand_stamps(last: int = 320) -> list[StampRow]:
    def point(i: int) -> str | None:
        return next((p for p, (a, b) in HOLDS.items() if a <= i <= b), None)

    return [StampRow(i / 10, point(i)) for i in range(last + 1)]


def test_every_figure_of_a_two_point_flight_exactly():
    r = review(plan(), hand_trace(), hand_stamps(), flight_id="f1")
    p1, p2 = r.points
    assert [leg.to for leg in r.legs] == ["P1", "P2"]           # no return leg
    for leg in (p1, p2):
        assert leg.reached
        assert leg.leg_m == pytest.approx(1.0)
        assert leg.planned_s == pytest.approx(1.0 / MOVE_SPEED_M_S)
        assert leg.transit_s == pytest.approx(6.0)
        assert leg.over_plan_s == pytest.approx(6.0 - 1.0 / MOVE_SPEED_M_S)
        assert leg.settle_s == pytest.approx(0.5)
        assert leg.hold_s == pytest.approx(5.0)
        assert leg.hold_long_enough is True
        assert leg.hold_drift_median_m == pytest.approx(0.02)
        assert leg.hold_drift_p95_m == pytest.approx(0.06)
        assert leg.hold_drift_worst_m == pytest.approx(0.09)
        assert leg.hold_height_median_m == pytest.approx(0.01)
        assert leg.hold_height_p95_m == pytest.approx(0.01)
        assert leg.hold_height_worst_m == pytest.approx(0.03)
        assert leg.notes == []
    assert r.flown_s == pytest.approx(31.5)
    assert r.estimate_s == pytest.approx(plan().estimated_duration_s(
        move_speed_m_s=MOVE_SPEED_M_S, climb_rate_m_s=CLIMB_RATE_M_S))


def test_the_return_leg_is_reported_when_the_mission_returns():
    rows = hand_trace()
    # Back over home after P2's hold, then land.
    rows = [r if r.t_s <= 28.2 else TraceRow(
        t_s=r.t_s, state=r.state,
        target=(1.0 - min(1.0, (r.t_s - 28.2) / 1.0) * 1.0,
                1.0 - min(1.0, (r.t_s - 28.2) / 1.0) * 1.0, H) if r.target else None,
        estimate=r.estimate) for r in rows]
    r = review(plan(return_to_start=True), rows, hand_stamps(), flight_id="f1")
    back = r.legs[-1]
    assert back.to == "start"
    assert back.leg_m == pytest.approx(math.sqrt(2))
    assert back.reached
    assert back.transit_s == pytest.approx(1.0, abs=0.11)


def test_the_suggestions_cite_what_they_came_from():
    r = review(plan(), hand_trace(), hand_stamps(), flight_id="f1")
    s = {x.constant: x for x in suggest([r])}
    assert s["ARRIVE_M"].current == ARRIVE_M
    assert s["ARRIVE_M"].measured == pytest.approx(0.06)
    assert "f1" in s["ARRIVE_M"].source
    assert s["SETTLE_S"].current == SETTLE_S
    assert s["SETTLE_S"].measured == pytest.approx(0.5)
    assert s["SETTLE_TIMEOUT_S"].current == SETTLE_TIMEOUT_S
    assert s["SETTLE_TIMEOUT_S"].measured == pytest.approx(0.5)
    assert s["TRANSIT_MARGIN_S"].current == TRANSIT_MARGIN_S
    assert s["TRANSIT_MARGIN_S"].measured == pytest.approx(6.0 - 1.0 / MOVE_SPEED_M_S)


def test_suggestions_over_several_flights_take_the_worst_and_name_it():
    a = review(plan(), hand_trace(), hand_stamps(), flight_id="calm")
    worse = hand_trace()
    worse = [TraceRow(t_s=w.t_s, state=w.state, target=w.target,
                      estimate=(w.estimate[0] + 0.05, w.estimate[1])
                      if w.estimate and 10.5 <= w.t_s <= 15.5 else w.estimate)
             for w in worse]
    b = review(plan(), worse, hand_stamps(), flight_id="gusty")
    s = {x.constant: x for x in suggest([a, b])}
    assert s["ARRIVE_M"].measured == pytest.approx(0.11)
    assert s["ARRIVE_M"].source == "gusty P1"


def test_nothing_measured_suggests_nothing_rather_than_zero():
    s = suggest([review(plan(), None, [], flight_id="f")])
    assert all(x.measured is None for x in s)


# ── the imperfect flights ─────────────────────────────────────────────────


def test_a_trace_gap_is_reported_and_nothing_crashes():
    r = review(plan(), hand_trace(skip=range(50, 66)), hand_stamps(), flight_id="f")
    assert any("1.7 s gap" in n and "dropped" in n for n in r.notes)
    assert any("approximate" in n for n in r.points[0].notes)
    assert r.points[0].transit_s == pytest.approx(6.0)


def test_a_point_never_reached_says_how_close_it_got():
    rows = [TraceRow(t_s=x.t_s, state=x.state,
                     target=(x.target[0], min(x.target[1], 0.5), H) if x.target else None,
                     estimate=x.estimate) for x in hand_trace()]
    stamps = [s if s.point_id != "P2" else StampRow(s.t_s, None) for s in hand_stamps()]
    r = review(plan(), rows, stamps, flight_id="f")
    p2 = r.points[1]
    assert p2.reached is False
    assert any("Not reached" in n and "0.50 m" in n for n in p2.notes)
    assert p2.transit_s is None and p2.hold_s is None


def test_a_flight_that_ended_early_reports_the_points_it_never_flew():
    rows = hand_trace(last=180)                              # ends mid-transit to P2
    stamps = hand_stamps(last=180)
    r = review(plan(), rows, stamps, flight_id="f")
    assert r.points[0].reached
    assert r.points[1].reached is False
    assert any("landed" in n for n in r.notes)
    assert r.flown_s == pytest.approx(18.0)
    three = plan(points=(*plan().points, InspectionPoint("P3", 0.0, 1.0, H, 5.0)))
    r3 = review(three, rows, stamps, flight_id="f")
    assert any("ended before it" in n for n in r3.points[2].notes)


def test_no_trace_is_said_in_words_and_the_hold_still_comes_from_the_csv():
    r = review(plan(), None, hand_stamps(), flight_id="f")
    assert any("no control trace" in n for n in r.notes)
    p1 = r.points[0]
    assert p1.reached and p1.hold_s == pytest.approx(5.0)
    assert p1.transit_s is None and p1.settle_s is None and p1.hold_drift_p95_m is None
    assert r.flown_s is None


def test_a_short_hold_is_flagged():
    longer = tuple(InspectionPoint(p.id, p.x_m, p.y_m, p.z_m, 8.0, p.label)
                   for p in plan().points)
    r = review(plan(points=longer), hand_trace(), hand_stamps(), flight_id="f")
    assert r.points[0].hold_long_enough is False
    assert any("5.0 s of the 8.0 s" in n for n in r.points[0].notes)


def test_a_flight_longer_than_its_estimate_is_flagged_in_words():
    r = review(plan(), hand_trace(), hand_stamps(), flight_id="f")
    assert r.flown_s > r.estimate_s                          # 31.5 against ~28.3
    assert r.longer_than_estimate
    assert any("battery" in n and "Samuel" in n for n in r.notes)
    slow_plan = plan(cruise_height_m=H, points=tuple(
        InspectionPoint(p.id, p.x_m, p.y_m, p.z_m, 10.0, p.label) for p in plan().points))
    r = review(slow_plan, hand_trace(), hand_stamps(), flight_id="f")
    assert not r.longer_than_estimate
    assert not any("battery" in n for n in r.notes)


# ── the command line, on files ────────────────────────────────────────────

BASE = datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC)
FLIGHT = "a1b2c3d4-0000-4000-8000-000000000001"


def write_flight(root: Path, flight_id: str = FLIGHT, *, keep_plan: bool = True,
                 keep_trace: bool = True) -> None:
    day = root / "flights" / "2026-09-30"
    day.mkdir(parents=True, exist_ok=True)
    with (day / f"flight_{flight_id[:8]}_2026-09-30_10-00-00.csv").open(
            "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "recorded_at", "flight_id", "point_id"])
        for n, s in enumerate(hand_stamps()):
            w.writerow([n, (BASE + timedelta(seconds=s.t_s)).isoformat(), flight_id,
                        s.point_id or ""])
    if keep_trace:
        with (day / f"trace_{flight_id[:8]}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["recorded_at", "control_state", "keys", "target_height_m",
                        "climb_velocity_m_s", "target_x_m", "target_y_m", "target_yaw_deg",
                        "drift_m", "stateEstimate.x", "stateEstimate.y", "stateEstimate.z",
                        "posCtl.targetZ"])
            for r in hand_trace():
                t = r.target
                w.writerow([(BASE + timedelta(seconds=r.t_s)).isoformat(), r.state, "",
                            t[2] if t else 0.0, 0.0, t[0] if t else "", t[1] if t else "",
                            0.0 if t else "", 0.0, r.estimate[0], r.estimate[1],
                            1.4 + H + (r.height_error_m or 0.0), 1.4 + H])
    session = root / "sessions" / "s1"
    session.mkdir(parents=True, exist_ok=True)
    meta = session / "meta.json"
    flights = json.loads(meta.read_text())["flights"] if meta.exists() else []
    meta.write_text(json.dumps({"flights": [*flights, {"id": flight_id}]}))
    if keep_plan:
        (session / "missions").mkdir(exist_ok=True)
        (session / "missions" / f"{flight_id}.json").write_text(json.dumps(
            {"flight_id": flight_id, "mission": plan().to_dict(), "room": {}}))


def test_the_report_from_files_matches_the_report_from_rows(tmp_path):
    write_flight(tmp_path)
    on_disk = load(tmp_path, FLIGHT)
    in_memory = review(plan(), hand_trace(), hand_stamps(), flight_id=FLIGHT)
    for a, b in zip(on_disk.legs, in_memory.legs, strict=True):
        assert a.transit_s == pytest.approx(b.transit_s)
        assert a.settle_s == pytest.approx(b.settle_s)
        assert a.hold_s == pytest.approx(b.hold_s)
        assert a.hold_drift_p95_m == pytest.approx(b.hold_drift_p95_m)
        assert a.hold_height_worst_m == pytest.approx(b.hold_height_worst_m)
    assert on_disk.flown_s == pytest.approx(in_memory.flown_s)


def test_mission_report_prints_and_its_json_carries_the_same_numbers(tmp_path, monkeypatch,
                                                                      capsys):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    write_flight(tmp_path)
    assert cli.main(["mission-report", "--flight", FLIGHT]) == 0
    text = capsys.readouterr().out
    assert "P1 (Pump 1)" in text and "transit 6.0 s" in text and "ARRIVE_M" in text
    assert cli.main(["mission-report", "--flight", FLIGHT, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    expected = load(tmp_path, FLIGHT)
    got = data["flights"][0]
    assert got["flight_id"] == FLIGHT
    assert got["flown_s"] == pytest.approx(expected.flown_s)
    assert got["longer_than_estimate"] is True
    for leg, want in zip(got["legs"], expected.legs, strict=True):
        assert leg["to"] == want.to
        assert leg["transit_s"] == pytest.approx(want.transit_s)
        assert leg["settle_s"] == pytest.approx(want.settle_s)
        assert leg["over_plan_s"] == pytest.approx(want.over_plan_s)
        assert leg["hold_drift_p95_m"] == pytest.approx(want.hold_drift_p95_m)
    names = [s["constant"] for s in data["suggestions"]]
    assert names == ["ARRIVE_M", "SETTLE_S", "SETTLE_TIMEOUT_S", "TRANSIT_MARGIN_S"]


def test_mission_report_on_a_missing_flight_says_so_and_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    assert cli.main(["mission-report", "--flight", "nope"]) != 0
    assert "No readings for flight nope" in capsys.readouterr().out


def test_mission_report_on_a_flight_with_no_plan_flown_says_why(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    write_flight(tmp_path, keep_plan=False)
    assert cli.main(["mission-report", "--flight", FLIGHT]) != 0
    assert "cropwatcher mission" in capsys.readouterr().out


def test_mission_report_without_a_trace_still_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    write_flight(tmp_path, keep_trace=False)
    assert cli.main(["mission-report", "--flight", FLIGHT]) == 0
    assert "no control trace" in capsys.readouterr().out


def test_mission_report_over_several_flights(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
    other = "e5f6a7b8-0000-4000-8000-000000000002"
    write_flight(tmp_path)
    write_flight(tmp_path, other)
    assert cli.main(["mission-report", "--flight", FLIGHT, "--flight", other, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [f["flight_id"] for f in data["flights"]] == [FLIGHT, other]


# ── a simulated mission, through the REAL FlightTrace ─────────────────────


class SimSnapshot:
    def __init__(self, sim: SimDrone) -> None:
        self._values = {"stateEstimate.x": sim.position.x, "stateEstimate.y": sim.position.y,
                        "stateEstimate.z": sim.position_z, "posCtl.targetZ": sim.target_z}

    def get(self, name: str):
        return self._values.get(name)


@pytest.mark.parametrize("lag", [0.3, 1.0])
def test_a_simulated_mission_reports_what_the_simulator_did(tmp_path, monkeypatch, lag):
    flown = mission(return_to_start=False)          # valid in plans.room()
    sim = SimDrone(start=Fix(*flown.home, 0.0), lag_s=lag)

    class SimTime(datetime):
        @classmethod
        def now(cls, tz=None):                          # the trace's clock is the sim's
            return BASE + timedelta(seconds=sim.clock())

    monkeypatch.setattr(flight_trace, "datetime", SimTime)
    trace = flight_trace.FlightTrace(tmp_path / "trace.csv", sim.ctl)
    stamps: list[StampRow] = []
    truth: list[tuple[float, tuple[float, float] | None, tuple[float, float], str | None]] = []
    mc = MissionController(flown, sim.ctl, on_event=lambda e: None, clock=sim.clock, tick_s=0)
    every = [0]

    def record() -> None:
        target = sim.ctl.target
        truth.append((sim.clock(), None if target is None else (target.x, target.y),
                      sim.true_xy, mc.current_point_id))
        every[0] += 1
        if every[0] % 5 == 0:                           # 10 Hz, as the stream samples
            trace.sample(SimSnapshot(sim))
            stamps.append(StampRow(sim.clock(), mc.current_point_id))

    sim.watch(record)
    sim.arm()
    mc.start()
    sim.run_until(mc, lambda: mc.state in (MissionState.DONE, MissionState.ABORTED,
                                           MissionState.FAILED, MissionState.INTERRUPTED),
                  limit_s=240.0)
    sim.step(1.0)                                       # the trace records it landed
    trace.close()
    assert mc.state is MissionState.DONE

    from cropwatcher.mission.review import trace_rows
    rows = trace_rows(tmp_path / "trace.csv")
    origin = BASE.timestamp()
    rows = [replace(r, t_s=r.t_s - origin) for r in rows]
    report = review(flown, rows, stamps, flight_id="sim")

    period = 0.1 + 1e-6
    for leg, point in zip(report.points, flown.points, strict=True):
        spot = (point.x_m, point.y_m)
        # What the simulator did, at 50 Hz: the target reaching the point, and
        # the drone's last entry within ARRIVE_M before the hold began.
        reached = next(t for t, tgt, _, _ in truth
                       if tgt is not None and math.dist(tgt, spot) <= 0.0142)
        held = [t for t, _, _, pid in truth if pid == point.id]
        inside = None
        for t, _, true, _ in reversed([x for x in truth if reached <= x[0] <= held[0]]):
            if math.dist(true, spot) <= ARRIVE_M:
                inside = t
            else:
                break
        assert leg.reached
        assert leg.settle_s == pytest.approx(max(0.0, inside - reached), abs=2 * period)
        assert leg.hold_s == pytest.approx(held[-1] - held[0], abs=period)
        assert leg.hold_long_enough
        assert leg.hold_drift_worst_m < ARRIVE_M
        # Heights, from stateEstimate.z against posCtl.targetZ — no floor needed.
        assert leg.hold_height_worst_m is not None
        assert leg.hold_height_worst_m < ARRIVE_M
    if lag == 1.0:
        # A slower drone settles later — the report sees the lag it was given.
        assert max(leg.settle_s for leg in report.points) > 0.0
    assert as_text([report], suggest([report]))
    assert json.loads(as_json([report], suggest([report])))
