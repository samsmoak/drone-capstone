"""Mission playback: one recorded flight, read back from this laptop so it can
be watched again — where the drone was at every moment, against the plan it
flew.

NOT A SIMULATION. Everything here was recorded on the flight; nothing is
recomputed or invented. A simulator would show what an ideal drone does with
the plan, and the failures worth replaying — a lost base station, drift, an
operator's keys, a guard landing — come from the room, not the plan.

WHAT IT READS — the files a flight already writes (none of them changes):
    the flight CSV      flights/<day>/flight_<id[:8]>_*.csv (telemetry/row.py),
                        10 Hz: position x_m, y_m (the room's frame — the
                        frame the plan is drawn in) and z_m (height above the
                        floor at takeoff, telemetry/reader.py), attitude,
                        speed, battery, temperature, pressure, the base
                        stations received, point_id while holding
    the control trace   flights/<day>/trace_<id[:8]>.csv (telemetry/trace.py),
                        10 Hz: the loop's state, the keys held, the commanded
                        point, drift — absent for a flight flown from the
                        terminal
    the plan flown      sessions/<session>/missions/<flight id>.json
                        (session._keep_plan_flown): the mission AS FLOWN and
                        its room — a mission flight from the app only
It finds them the way the data pipeline and the mission report do
(pipeline/sources.py LocalFlightSource), on the same clock as the report
(mission/review.py load): seconds from the earlier of the two files' first
rows, so a time on the slider and a time in the report are the same time.

WHAT IT GIVES BACK, all JSON-ready: `samples` (the flight CSV), `control`
(the trace), `gaps` (stretches with no samples — dropped packets), `events`
(what happened, in order, each in words), and the mission report for the
flight when it was a mission. The plan and room come back as objects; the
API turns them into the views the desktop map already draws.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cropwatcher.mission.plan.floorplan import Room
from cropwatcher.mission.plan.mission import Mission
from cropwatcher.mission.review import GAP_S, ReportError, _float, _seconds
from cropwatcher.mission.review import load as load_report
from cropwatcher.pipeline.sources import FlightNotFound, LocalFlightSource

#: An hour at 10 Hz, per file. Longer is cut, and says so: a page that has to
#: hold a whole day of samples is a page that never opens.
MAX_ROWS = 36_000

#: The loop's states (flight/manual.py ControlState), as the events say them.
_STATE_WORDS = {
    "idle": "Disarmed",
    "armed": "Armed",
    "flying": "Flying",
    "landing": "Landing",
    "landed": "Landed",
    "stopped": "Emergency stop — motors cut",
}


class PlaybackError(Exception):
    """The flight cannot be played back. Words for the operator."""


@dataclass
class Playback:
    flight_id: str
    started_at: str | None                          # the origin, ISO
    duration_s: float
    temp_unit: str | None
    samples: list[dict[str, Any]]
    control: list[dict[str, Any]]
    gaps: list[dict[str, float]]
    events: list[dict[str, Any]]
    truncated: bool
    mission: Mission | None = None
    room: Room | None = None
    moves: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def _r(value: float | None, digits: int) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def _read(path: Path) -> tuple[list[dict[str, str]], bool]:
    """A CSV's rows that carry a time, at most MAX_ROWS of them."""
    rows: list[dict[str, str]] = []
    cut = False
    with path.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            if not raw.get("recorded_at"):
                continue
            if len(rows) == MAX_ROWS:
                cut = True
                break
            rows.append(raw)
    return rows, cut


def _positioned(raw: dict[str, str]) -> bool | None:
    """Whether a base station was received for this row: the position was
    measured, not the IMU coasting. None in a file older than the column."""
    received = _float(raw.get("lighthouse_received"))
    return None if received is None else received > 0


def _sample(raw: dict[str, str], t_s: float) -> dict[str, Any]:
    vx, vy = _float(raw.get("vx_m_s")), _float(raw.get("vy_m_s"))
    return {
        "t_s": round(t_s, 3),
        "x_m": _r(_float(raw.get("x_m")), 4),
        "y_m": _r(_float(raw.get("y_m")), 4),
        "z_m": _r(_float(raw.get("z_m")), 4),
        "positioned": _positioned(raw),
        "yaw_deg": _r(_float(raw.get("yaw_deg")), 1),
        "roll_deg": _r(_float(raw.get("roll_deg")), 1),
        "pitch_deg": _r(_float(raw.get("pitch_deg")), 1),
        "speed_m_s": _r(math.hypot(vx, vy), 3) if vx is not None and vy is not None else None,
        "vz_m_s": _r(_float(raw.get("vz_m_s")), 3),
        "battery_v": _r(_float(raw.get("battery_v")), 3),
        "temp": _r(_float(raw.get("corrected_temp")), 2),
        "pressure_hpa": _r(_float(raw.get("station_pressure_hpa")), 2),
        "thrust": _r(_float(raw.get("thrust")), 0),
        "point_id": raw.get("point_id") or None,
    }


def _control(raw: dict[str, str], t_s: float) -> dict[str, Any]:
    tx, ty = _float(raw.get("target_x_m")), _float(raw.get("target_y_m"))
    th = _float(raw.get("target_height_m"))
    ez, tz = _float(raw.get("stateEstimate.z")), _float(raw.get("posCtl.targetZ"))
    return {
        "t_s": round(t_s, 3),
        "state": raw.get("control_state") or "",
        "keys": raw.get("keys") or "",
        "target": None if tx is None or ty is None or th is None
        else [round(tx, 4), round(ty, 4), round(th, 4)],
        "drift_m": _r(_float(raw.get("drift_m")), 4),
        # Off the height the firmware holds; both in the estimator's frame, so
        # no floor is needed (mission/review.py TraceRow.height_error_m).
        "height_error_m": _r(ez - tz, 4) if ez is not None and tz is not None else None,
    }


def gaps_in(times: list[float]) -> list[dict[str, float]]:
    """Stretches with no sample: longer than three periods is samples lost
    (dropped packets, a stalled link), not jitter — mission/review.py GAP_S."""
    return [{"from_s": round(a, 3), "to_s": round(b, 3)}
            for a, b in zip(times, times[1:], strict=False) if b - a > GAP_S]


def events_of(samples: list[dict[str, Any]], control: list[dict[str, Any]],
              gaps: list[dict[str, float]]) -> list[dict[str, Any]]:
    """What happened, in order and in words: the loop's state changing, keys
    pressed and released, holds begun and ended, base stations lost and
    regained, samples lost."""
    events: list[dict[str, Any]] = []

    def add(t_s: float, kind: str, text: str, point_id: str | None = None) -> None:
        events.append({"t_s": t_s, "kind": kind, "text": text, "point_id": point_id})

    state, keys, took_off = "", "", False
    for row in control:
        if row["state"] != state and row["state"]:
            words = _STATE_WORDS.get(row["state"], f"State: {row['state']}")
            if row["state"] == "flying" and not took_off:
                words, took_off = "Took off", True
            add(row["t_s"], "state", words)
            state = row["state"]
        if row["keys"] != keys:
            if row["keys"]:
                add(row["t_s"], "keys", f"Operator held {row['keys']}")
            else:
                add(row["t_s"], "keys", "Keys released")
            keys = row["keys"]

    holding: str | None = None
    lost_at: float | None = None          # when the base stations were last lost
    for row in samples:
        if row["point_id"] != holding:
            if holding:
                add(row["t_s"], "hold", f"{holding} hold ended", holding)
            if row["point_id"]:
                add(row["t_s"], "hold", f"Holding at {row['point_id']}", row["point_id"])
            holding = row["point_id"]
        # ONE EVENT PER STRETCH, at its start, with its length: on the lab's
        # flights reception flickers (lost and back within 0.2 s, several
        # times a flight — 2026-10-11), and a line per flicker buried the
        # stretch that mattered (4.7 s unmeasured over P1, flight d985c7a6).
        if row["positioned"] is False and lost_at is None:
            lost_at = row["t_s"]
        elif row["positioned"] is True and lost_at is not None:
            add(lost_at, "position", f"Base stations lost for {row['t_s'] - lost_at:.1f} s — "
                "the position was not measured, the drone flew on its own estimate")
            lost_at = None
    if lost_at is not None:
        add(lost_at, "position", "Base stations lost until the recording stops — "
            "the position was not measured")
    if holding and samples:
        add(samples[-1]["t_s"], "hold", f"{holding} hold ended — the recording stops", holding)

    for gap in gaps:
        add(gap["from_s"], "gap",
            f"No samples for {gap['to_s'] - gap['from_s']:.1f} s — data lost on the link")

    return sorted(events, key=lambda e: e["t_s"])


def load(root: Path, flight_id: str) -> Playback:
    """One flight from the files under the agent's data folder."""
    source = LocalFlightSource(root)
    try:
        csv_path = source._find_csv(flight_id)
    except FlightNotFound as e:
        raise PlaybackError(str(e)) from e

    flight_rows, cut_flight = _read(csv_path)
    trace_path = csv_path.parent / f"trace_{flight_id[:8]}.csv"
    trace_rows, cut_trace = _read(trace_path) if trace_path.exists() else ([], False)
    if not flight_rows:
        raise PlaybackError(f"Flight {flight_id} recorded no readings.")

    flight_t = [_seconds(r["recorded_at"]) for r in flight_rows]
    trace_t = [_seconds(r["recorded_at"]) for r in trace_rows]
    # The mission report's clock (review.load): the earlier first row.
    origin = min(flight_t[:1] + trace_t[:1])
    samples = [_sample(r, t - origin) for r, t in zip(flight_rows, flight_t, strict=True)]
    control = [_control(r, t - origin) for r, t in zip(trace_rows, trace_t, strict=True)]
    gaps = gaps_in([s["t_s"] for s in samples])
    end = max([s["t_s"] for s in samples[-1:]] + [c["t_s"] for c in control[-1:]])

    playback = Playback(
        flight_id=flight_id,
        started_at=flight_rows[0]["recorded_at"] if flight_t[0] == origin
        else trace_rows[0]["recorded_at"],
        duration_s=round(end, 3),
        temp_unit=flight_rows[0].get("temp_unit") or None,
        samples=samples, control=control, gaps=gaps,
        events=events_of(samples, control, gaps),
        truncated=cut_flight or cut_trace,
    )
    if playback.truncated:
        playback.notes.append(
            f"This flight is longer than playback holds: only its first "
            f"{MAX_ROWS // 600} minutes are shown.")
    if not trace_rows:
        playback.notes.append(
            "There is no control trace for this flight (one flown from the terminal writes "
            "none), so the commanded point, the keys and the loop's state are not shown.")

    session = source._find_session(flight_id)
    plan_path = session / "missions" / f"{flight_id}.json" if session else None
    if plan_path is not None and plan_path.exists():
        try:
            kept = json.loads(plan_path.read_text(encoding="utf-8"))
            playback.mission = Mission.from_dict(kept["mission"])
            playback.room = Room.from_dict(kept["room"]) if kept.get("room") else None
            playback.moves = list(kept.get("moves") or [])
        except (OSError, ValueError, KeyError, TypeError) as e:
            playback.notes.append(f"The plan this flight flew could not be read: {e}")
        if playback.mission is not None:
            try:
                playback.report = load_report(root, flight_id).to_dict()
            except ReportError as e:
                playback.notes.append(str(e))
    else:
        playback.notes.append(
            "This flight kept no plan (a Manual flight, or one flown from the terminal), "
            "so the map shows where the drone went over the default area, with no path.")
    return playback
