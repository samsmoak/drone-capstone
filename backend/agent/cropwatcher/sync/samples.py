"""A session's own vitals, uploaded (supabase migration 20261006000013).

The session keeps one sample a second from Start to End session
(history.SessionLog → sessions/<id>/samples.csv), flying or not. Until
2026-10-06 that file never left the laptop, so a session with no flight showed
nothing on the web; the web app's Sessions tab reads public.session_samples.

The CSV is the record (CLAUDE.md invariant 6: write first, upload after); this
reads it from a cursor, in batches, so an interrupted upload resumes exactly
where it stopped and a re-sent batch changes nothing (primary key session_id,
seq).
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cropwatcher.safety.flight_guard import position_trusted
from cropwatcher.telemetry.stream import Snapshot

SAMPLES_NAME = "samples.csv"
#: Rows per insert: well under PostgREST's request limits, few round trips.
BATCH = 500

#: public.session_samples column ← the stream variable it is read from.
COLUMNS: Mapping[str, str] = MappingProxyType({
    "x_m": "stateEstimate.x", "y_m": "stateEstimate.y", "z_m": "stateEstimate.z",
    "battery_v": "pm.vbat", "raw_temp": "baro.temp", "station_pressure_hpa": "baro.pressure",
    "roll_deg": "stabilizer.roll", "pitch_deg": "stabilizer.pitch", "yaw_deg": "stabilizer.yaw",
    "thrust": "stabilizer.thrust",
})


def _number(text: str | None) -> float | None:
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def row_for(session_id: str, seq: int, cells: Mapping[str, str]) -> dict[str, Any]:
    """One samples.csv row as a public.session_samples row."""
    values = {k: v for k, v in ((k, _number(c)) for k, c in cells.items()
                                if k not in ("recorded_at", "mode", "height_m"))
              if v is not None}
    received = values.get("lighthouse.bsReceive")
    row: dict[str, Any] = {
        "session_id": session_id, "seq": seq,
        "recorded_at": cells.get("recorded_at"),
        "mode": cells.get("mode") or None,
        "height_m": _number(cells.get("height_m")),
        "positioned": position_trusted(Snapshot(MappingProxyType(values), None)),
        "lighthouse_received": None if received is None else int(received),
        "values": values,
    }
    for column, name in COLUMNS.items():
        row[column] = values.get(name)
    return row


def batches(folder: Path, session_id: str, after_seq: int,
            size: int = BATCH) -> Iterator[list[dict[str, Any]]]:
    """Rows after `after_seq` (1-based, header excluded), `size` at a time."""
    path = folder / SAMPLES_NAME
    if not path.exists():
        return
    with path.open(newline="") as f:
        batch: list[dict[str, Any]] = []
        for seq, cells in enumerate(csv.DictReader(f), start=1):
            if seq <= after_seq or not cells.get("recorded_at"):
                continue
            batch.append(row_for(session_id, seq, cells))
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch
