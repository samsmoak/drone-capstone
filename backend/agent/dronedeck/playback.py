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

TWO SOURCES, ONE BUILDER (2026-10-11). load() reads this laptop's files;
load_cloud() reads the same three things from Supabase — public.telemetry,
public.flight_traces and public.flight_plans (migration 20261011000019,
uploaded by sync/flight_playback.py) — so any signed-in person's flight plays
back on any computer. Both hand rows to _build(), so a flight looks the same
whichever copy it came from; tests/test_playback.py proves it. The API tries
this laptop first (instant, complete, offline) and Supabase for the rest.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dronedeck.mission.plan.floorplan import Room
from dronedeck.mission.plan.mission import Mission
from dronedeck.mission.review import (
    GAP_S,
    StampRow,
    TraceRow,
    _float,
    _seconds,
    review,
)
from dronedeck.pipeline.sources import FlightNotFound, LocalFlightSource

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


class PlaybackCloud(Protocol):
    """What load_cloud asks of the cloud client (sync/cloud.py SupabaseCloud)."""

    def read_telemetry(self, flight_id: str, limit: int) -> list[dict[str, Any]]: ...
    def read_flight_traces(self, flight_id: str, limit: int) -> list[dict[str, Any]]: ...
    def read_flight_plan(self, flight_id: str) -> dict[str, Any] | None: ...


#: Where a row came from, as the API and the page say it.
THIS_COMPUTER = "this_computer"
SUPABASE = "supabase"


@dataclass(frozen=True)
class FlightFiles:
    """A flight's files on this laptop: the CSV always; the trace and the plan
    as flown when the flight wrote them."""
    csv: Path
    trace: Path | None
    plan: Path | None


def files_of(root: Path, flight_id: str) -> FlightFiles:
    """Where this laptop keeps a flight's files — found the way the data
    pipeline and the mission report find them (pipeline/sources.py). The one
    rule, used by playback and by the upload (sync/flight_playback.py)."""
    source = LocalFlightSource(root)
    try:
        csv_path = source._find_csv(flight_id)
    except FlightNotFound as e:
        raise PlaybackError(str(e)) from e
    trace = csv_path.parent / f"trace_{flight_id[:8]}.csv"
    session = source._find_session(flight_id)
    plan = session / "missions" / f"{flight_id}.json" if session else None
    return FlightFiles(csv_path, trace if trace.exists() else None,
                       plan if plan is not None and plan.exists() else None)


@dataclass
class Playback:
    flight_id: str
    source: str                                     # THIS_COMPUTER or SUPABASE
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


#: A row from either source: a CSV's cells (text) or a database row (numbers).
Cells = Mapping[str, Any]


def _num(value: Any) -> float | None:
    """A number from a CSV cell or a database value; None if there is none."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    return _float(value if isinstance(value, str) else None)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _positioned(raw: Cells) -> bool | None:
    """Whether a base station was received for this row: the position was
    measured, not the IMU coasting. None in a file older than the column."""
    received = _num(raw.get("lighthouse_received"))
    return None if received is None else received > 0


def _sample(raw: Cells, t_s: float) -> dict[str, Any]:
    vx, vy = _num(raw.get("vx_m_s")), _num(raw.get("vy_m_s"))
    return {
        "t_s": round(t_s, 3),
        "x_m": _r(_num(raw.get("x_m")), 4),
        "y_m": _r(_num(raw.get("y_m")), 4),
        "z_m": _r(_num(raw.get("z_m")), 4),
        "positioned": _positioned(raw),
        "yaw_deg": _r(_num(raw.get("yaw_deg")), 1),
        "roll_deg": _r(_num(raw.get("roll_deg")), 1),
        "pitch_deg": _r(_num(raw.get("pitch_deg")), 1),
        "speed_m_s": _r(math.hypot(vx, vy), 3) if vx is not None and vy is not None else None,
        "vz_m_s": _r(_num(raw.get("vz_m_s")), 3),
        "battery_v": _r(_num(raw.get("battery_v")), 3),
        "temp": _r(_num(raw.get("corrected_temp")), 2),
        "pressure_hpa": _r(_num(raw.get("station_pressure_hpa")), 2),
        "thrust": _r(_num(raw.get("thrust")), 0),
        "point_id": _text(raw.get("point_id")),
    }


def _height_error(raw: Cells) -> float | None:
    """Off the height the firmware holds: stateEstimate.z − posCtl.targetZ, both
    in the estimator's frame, so no floor is needed (review.py TraceRow).

    COMPUTED FROM THE TWO READINGS WHENEVER THEY ARE THERE — from either
    source. The database row's own height_error_m column is a float8, and
    PostgREST returns those with 15 significant digits, so on a real lab
    flight (fdd57690, 2026-10-11) the report's hold-height figures differed
    in the 15th digit from the files'; the readings themselves travel in the
    row's jsonb `values`, which keeps every digit."""
    ez, tz = _num(raw.get("stateEstimate.z")), _num(raw.get("posCtl.targetZ"))
    if ez is not None and tz is not None:
        return ez - tz
    return _num(raw.get("height_error_m"))


def _target(raw: Cells) -> tuple[float, float, float] | None:
    tx, ty = _num(raw.get("target_x_m")), _num(raw.get("target_y_m"))
    th = _num(raw.get("target_height_m"))
    return None if tx is None or ty is None or th is None else (tx, ty, th)


def _control(raw: Cells, t_s: float) -> dict[str, Any]:
    target = _target(raw)
    return {
        "t_s": round(t_s, 3),
        "state": _text(raw.get("control_state")) or "",
        "keys": _text(raw.get("keys")) or "",
        "target": None if target is None else [round(v, 4) for v in target],
        "drift_m": _r(_num(raw.get("drift_m")), 4),
        "height_error_m": _r(_height_error(raw), 4),
    }


def _trace_row(raw: Cells, t_s: float) -> TraceRow:
    """The mission report's view of a trace row (review.py trace_rows), from
    either source."""
    ex, ey = _num(raw.get("stateEstimate.x")), _num(raw.get("stateEstimate.y"))
    return TraceRow(t_s=t_s, state=_text(raw.get("control_state")) or "",
                    keys=_text(raw.get("keys")) or "", target=_target(raw),
                    estimate=None if ex is None or ey is None else (ex, ey),
                    drift_m=_num(raw.get("drift_m")) or 0.0,
                    height_error_m=_height_error(raw))


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


def _build(flight_id: str, source: str, flight_rows: Sequence[Cells], trace_rows: Sequence[Cells],
           truncated: bool, kept: dict[str, Any] | None,
           plan_error: str | None = None) -> Playback:
    """One flight from its rows, whichever copy they came from."""
    if not flight_rows:
        raise PlaybackError(f"Flight {flight_id} recorded no readings.")
    flight_t = [_seconds(str(r["recorded_at"])) for r in flight_rows]
    trace_t = [_seconds(str(r["recorded_at"])) for r in trace_rows]
    # The mission report's clock (review.load): the earlier first row.
    origin = min(flight_t[:1] + trace_t[:1])
    samples = [_sample(r, t - origin) for r, t in zip(flight_rows, flight_t, strict=True)]
    control = [_control(r, t - origin) for r, t in zip(trace_rows, trace_t, strict=True)]
    gaps = gaps_in([s["t_s"] for s in samples])
    end = max([s["t_s"] for s in samples[-1:]] + [c["t_s"] for c in control[-1:]])

    playback = Playback(
        flight_id=flight_id, source=source,
        started_at=str(flight_rows[0]["recorded_at"]) if flight_t[0] == origin
        else str(trace_rows[0]["recorded_at"]),
        duration_s=round(end, 3),
        temp_unit=_text(flight_rows[0].get("temp_unit")),
        samples=samples, control=control, gaps=gaps,
        events=events_of(samples, control, gaps),
        truncated=truncated,
    )
    if truncated:
        playback.notes.append(
            f"This flight is longer than playback holds: only its first "
            f"{MAX_ROWS // 600} minutes are shown.")
    if not trace_rows:
        playback.notes.append(
            "There is no control trace for this flight (one flown from the terminal writes "
            "none, and a flight from another computer has none until that computer uploads "
            "it), so the commanded point, the keys and the loop's state are not shown.")

    if plan_error:
        playback.notes.append(f"The plan this flight flew could not be read: {plan_error}")
    elif kept is not None:
        try:
            playback.mission = Mission.from_dict(kept["mission"])
            playback.room = Room.from_dict(kept["room"]) if kept.get("room") else None
            playback.moves = list(kept.get("moves") or [])
        except (ValueError, KeyError, TypeError) as e:
            playback.notes.append(f"The plan this flight flew could not be read: {e}")
    else:
        playback.notes.append(
            "This flight kept no plan (a Manual flight, one flown from the terminal, or a "
            "mission whose computer has not uploaded it yet), so the map shows where the "
            "drone went over the default area, with no path.")

    if playback.mission is not None:
        # The mission report, from the same rows on the same clock — what
        # review.load computes from the files (tests/test_playback.py).
        traces = [_trace_row(r, t - origin) for r, t in zip(trace_rows, trace_t, strict=True)]
        stamps = [StampRow(t - origin, _text(r.get("point_id")))
                  for r, t in zip(flight_rows, flight_t, strict=True)]
        playback.report = review(playback.mission, traces or None, stamps,
                                 flight_id=flight_id).to_dict()
    return playback


def load(root: Path, flight_id: str) -> Playback:
    """One flight from the files under the agent's data folder."""
    files = files_of(root, flight_id)
    flight_rows, cut_flight = _read(files.csv)
    trace_rows, cut_trace = _read(files.trace) if files.trace else ([], False)
    kept: dict[str, Any] | None = None
    plan_error: str | None = None
    if files.plan is not None:
        try:
            kept = json.loads(files.plan.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            plan_error = str(e)
    return _build(flight_id, THIS_COMPUTER, list(flight_rows), list(trace_rows),
                  cut_flight or cut_trace, kept, plan_error)


def load_cloud(cloud: PlaybackCloud, flight_id: str) -> Playback:
    """One flight from Supabase: anyone's, flown on any computer. Telemetry is
    there for every uploaded flight; the trace and the plan only once the
    computer that flew it has uploaded them (sync/flight_playback.py)."""
    flight_rows = cloud.read_telemetry(flight_id, MAX_ROWS + 1)
    trace_rows = cloud.read_flight_traces(flight_id, MAX_ROWS + 1)
    truncated = len(flight_rows) > MAX_ROWS or len(trace_rows) > MAX_ROWS
    if not flight_rows:
        raise PlaybackError(f"Flight {flight_id} has no readings in Supabase yet.")
    return _build(flight_id, SUPABASE, flight_rows[:MAX_ROWS], trace_rows[:MAX_ROWS],
                  truncated, cloud.read_flight_plan(flight_id))


#: Where a flight is played from, for the API: this laptop's files when it has
#: them, else Supabase when signed in. `cloud_for` returns the signed-in client
#: or None.
def load_any(root: Path, flight_id: str,
             cloud_for: Callable[[], PlaybackCloud | None]) -> Playback:
    try:
        return load(root, flight_id)
    except PlaybackError as here:
        cloud = cloud_for()
        if cloud is None:
            raise PlaybackError(
                f"{here} Sign in to play flights recorded on other computers.") from None
        return load_cloud(cloud, flight_id)


# ── the list: this laptop's flights and Supabase's, each once ─────────────

#: How many flights the list holds: the newest first. Enough for a semester of
#: lab days; the list is a picker, not an archive browser.
LIST_LIMIT = 300


def _local_flights(sessions: list[dict[str, Any]], root: Path) -> dict[str, dict[str, Any]]:
    """Every flight in this laptop's session records (history.py), with who flew
    it — the session's operator — and whether its plan as flown is here."""
    found: dict[str, dict[str, Any]] = {}
    for session in sessions:
        for flight in session.get("flights") or []:
            fid = str(flight.get("id") or "")
            if not fid:
                continue
            plan = root / "sessions" / str(session["id"]) / "missions" / f"{fid}.json"
            found[fid] = {
                "id": fid, "session_id": session["id"],
                "started_at": flight.get("started_at"), "ended_at": flight.get("ended_at"),
                "mode": flight.get("mode"), "program": flight.get("program"),
                "outcome": flight.get("outcome"), "abort_reason": flight.get("abort_reason"),
                "operator_email": session.get("operator_email"),
                "operator_name": session.get("operator_name"),
                "has_plan": plan.exists(),
            }
    return found


def list_flights(root: Path, sessions: list[dict[str, Any]],
                 cloud_rows: list[dict[str, Any]] | None,
                 upload_state: Callable[[str], str | None],
                 *, mode: str | None = None, limit: int = LIST_LIMIT) -> list[dict[str, Any]]:
    """This laptop's flights and Supabase's, merged on the flight id, newest
    first. A flight on this laptop plays from here (instant, complete,
    offline) even when Supabase has it too; every other one plays from
    Supabase — anyone's, and this account's from another computer or after
    the files here were deleted.

    `upload_state(flight_id)` says how far this laptop's upload has got —
    "uploading" while its records are pending, "uploaded" once sent, None for
    a flight this laptop never queued."""
    here = _local_flights(sessions, root)
    there = {str(r["id"]): r for r in (cloud_rows or [])}
    merged: list[dict[str, Any]] = []
    for fid in here.keys() | there.keys():
        local, cloud = here.get(fid), there.get(fid)
        row = dict(local or cloud or {})
        if local and cloud:
            # The laptop's record is the one played; Supabase fills what the
            # laptop may not know (an older session record without a name).
            for key in ("operator_email", "operator_name", "mode", "program", "outcome"):
                row[key] = row.get(key) or cloud.get(key)
            row["has_plan"] = bool(local.get("has_plan") or cloud.get("has_plan"))
        row["on_this_computer"] = local is not None
        row["in_supabase"] = cloud is not None
        row["source"] = THIS_COMPUTER if local is not None else SUPABASE
        row["upload"] = upload_state(fid) if local is not None else None
        if mode and row.get("mode") != mode:
            continue
        merged.append(row)
    merged.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return merged[:limit]
