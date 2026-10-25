"""What playback needs beyond telemetry, uploaded (supabase migration
20261011000019): a flight's plan AS FLOWN and its 10 Hz control trace.

Both are files the laptop wrote first (CLAUDE.md invariant 6) — the plan in
sessions/<id>/missions/<flight>.json, the trace beside the flight CSV — and
until 2026-10-11 neither left it, so another computer could replay where a
drone went (public.telemetry) but not the plan it flew or what the loop was
doing (docs/features/desktop/mission-playback.txt).

ONE OUTBOX RECORD PER FLIGHT (Kind.PLAYBACK), queued when the flight ends and,
for flights flown before this existed, when the agent starts
(queue_past_flights). The record holds only the flight id and a cursor: the
files are found when it is sent, the same way playback and the pipeline find
them (playback.files_of), so there is one rule for where a flight's files are.
The trace goes up in batches from the cursor, so an interrupted pass resumes
exactly where it stopped and a re-sent batch changes nothing (primary key
flight_id, seq; ignore-duplicates). Copied from sync/samples.py.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dronedeck.sync.outbox import Kind, Outbox

#: Rows per insert: well under PostgREST's request limits, few round trips.
BATCH = 500

#: The trace columns that have their own column in public.flight_traces; every
#: other one goes in `values`, so nothing recorded is dropped.
_OWN = ("recorded_at", "control_state", "keys", "target_x_m", "target_y_m",
        "target_height_m", "drift_m")


def _number(text: str | None) -> float | None:
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def plan_row(flight_id: str, kept: dict[str, Any]) -> dict[str, Any]:
    """A plan-as-flown file (session._keep_plan_flown) as a public.flight_plans row."""
    return {"flight_id": flight_id, "mission": kept["mission"],
            "room": kept.get("room") or None, "moves": list(kept.get("moves") or [])}


def read_plan(path: Path) -> dict[str, Any]:
    kept: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return kept


def trace_row(flight_id: str, seq: int, cells: dict[str, str]) -> dict[str, Any]:
    """One trace CSV row (telemetry/trace.py) as a public.flight_traces row."""
    ez, tz = _number(cells.get("stateEstimate.z")), _number(cells.get("posCtl.targetZ"))
    values: dict[str, float | str] = {
        k: v for k, v in ((k, _number(c)) for k, c in cells.items() if k not in _OWN)
        if v is not None}
    tuning = cells.get("tuning")
    if tuning:
        values["tuning"] = tuning          # text: the gains changed at takeoff
    return {
        "flight_id": flight_id, "seq": seq,
        "recorded_at": cells.get("recorded_at"),
        "control_state": cells.get("control_state") or None,
        "keys": cells.get("keys") or None,
        "target_x_m": _number(cells.get("target_x_m")),
        "target_y_m": _number(cells.get("target_y_m")),
        "target_height_m": _number(cells.get("target_height_m")),
        "drift_m": _number(cells.get("drift_m")),
        "height_error_m": None if ez is None or tz is None else ez - tz,
        "values": values,
    }


def trace_batches(path: Path, flight_id: str, after_seq: int,
                  size: int | None = None) -> Iterator[list[dict[str, Any]]]:
    """Trace rows after `after_seq` (1-based, header excluded), `size` (BATCH,
    read when called) at a time."""
    size = size or BATCH
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as f:
        batch: list[dict[str, Any]] = []
        for seq, cells in enumerate(csv.DictReader(f), start=1):
            if seq <= after_seq or not cells.get("recorded_at"):
                continue
            batch.append(trace_row(flight_id, seq, cells))
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch


def queue(outbox: Outbox, flight_id: str) -> None:
    """Queue a flight's plan and trace for upload — once: a flight already
    queued (sent or not) keeps its record and its cursor."""
    if outbox.get(Kind.PLAYBACK, flight_id) is not None:
        return
    outbox.put(Kind.PLAYBACK, flight_id, {
        "flight_id": flight_id, "occurred_at": datetime.now(UTC).isoformat(),
        "plan_sent": False, "uploaded_through": 0,
    })


def queue_past_flights(outbox: Outbox) -> list[str]:
    """Every ended flight this laptop recorded that has no playback record yet:
    the flights flown before the upload existed. Run when the agent starts;
    cheap after the first time (one file check per flight)."""
    queued: list[str] = []
    for flight_id, payload in outbox.records(Kind.FLIGHT):
        if payload.get("ended_at") and outbox.get(Kind.PLAYBACK, flight_id) is None:
            queue(outbox, flight_id)
            queued.append(flight_id)
    return queued
