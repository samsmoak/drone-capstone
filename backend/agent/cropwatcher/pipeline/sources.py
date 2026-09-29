"""Where a flight comes from — the pipeline's input port, and its adapter for
this laptop.

LocalFlightSource reads what the agent already wrote, and nothing else:

    flights/<date>/flight_<first 8 of the id>_<time>.csv   the readings
    sessions/<session id>/meta.json                        which session flew it
    sessions/<session id>/frames.csv, frames/               the camera frames
    sessions/<session id>/missions/<flight id>.json         the plan flown, if any

FRAMES ARE RECORDED PER SESSION, NOT PER FLIGHT — the camera runs for the whole
session. So a flight's frames are the session's frames taken between its first
and last reading.

GROUPING BY INSPECTION POINT. Rows and frames carry point_id while the mission
controller was holding there (story 3.5). A flight with a mission gives one
PointData per inspection point, from exactly those rows and frames; readings
taken in transit belong to no point and are not analysed. A flight with no
mission is a single point, "flight", holding everything.

A later cloud worker gets its own adapter (Supabase Storage in, the same
LoadedFlight out) — the stages never know the difference.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from cropwatcher.pipeline.contracts import (
    WHOLE_FLIGHT,
    Frame,
    InspectionPoint,
    PointData,
    Reading,
)

log = logging.getLogger(__name__)

#: CSV columns that are words, not measurements.
TEXT_COLUMNS = frozenset({"index", "recorded_at", "flight_id", "mode", "thermal_state",
                          "event", "temp_unit", "point_id"})


class FlightNotFound(LookupError):
    """No readings for that flight on this computer."""


@dataclass(frozen=True)
class LoadedFlight:
    flight_id: str
    session_id: str | None
    temp_unit: Literal["C", "F"]
    ground_z_m: float | None
    started_at: datetime
    points: tuple[PointData, ...]
    #: Readings that belonged to no inspection point (transit, takeoff).
    unassigned_readings: int = 0


class FlightSource(Protocol):
    def load(self, flight_id: str) -> LoadedFlight: ...


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


class LocalFlightSource:
    """A flight recorded by the agent on this laptop."""

    def __init__(self, data_root: Path) -> None:
        self.root = data_root

    def load(self, flight_id: str) -> LoadedFlight:
        csv_path = self._find_csv(flight_id)
        rows = list(self._rows(csv_path))
        if not rows:
            raise FlightNotFound(f"Flight {flight_id} has no readings in {csv_path.name}.")
        started = _time(rows[0]["recorded_at"])
        ended = _time(rows[-1]["recorded_at"])
        unit = rows[0].get("temp_unit") or "C"
        if unit not in ("C", "F"):
            raise FlightNotFound(f"Flight {flight_id} records temperatures in {unit!r}, "
                                 f"which is not C or F.")

        readings = [(row.get("point_id") or None, self._reading(row, started)) for row in rows]
        session = self._find_session(flight_id)
        frames = self._frames(session, started, ended) if session else []
        plan = self._plan(session, flight_id) if session else None

        points: tuple[PointData, ...]
        if plan is None:
            point = InspectionPoint(WHOLE_FLIGHT, None, 0.0, 0.0, 0.0)
            points = (PointData(point, tuple(r for _, r in readings),
                                tuple(f for _, f in frames)),)
            unassigned = 0
        else:
            points = tuple(
                PointData(p, tuple(r for pid, r in readings if pid == p.id),
                          tuple(f for pid, f in frames if pid == p.id))
                for p in plan)
            unassigned = sum(1 for pid, _ in readings if pid is None)

        return LoadedFlight(
            flight_id=flight_id, session_id=session.name if session else None,
            temp_unit="F" if unit == "F" else "C", ground_z_m=None, started_at=started,
            points=points, unassigned_readings=unassigned,
        )

    # ── finding things ───────────────────────────────────────────────────

    def _find_csv(self, flight_id: str) -> Path:
        for path in sorted((self.root / "flights").glob(f"*/flight_{flight_id[:8]}_*.csv")):
            # Eight characters can collide; the rows name the whole id.
            with path.open(newline="", encoding="utf-8") as f:
                first = next(csv.DictReader(f), None)
            if first is not None and first.get("flight_id") == flight_id:
                return path
        raise FlightNotFound(f"No readings for flight {flight_id} on this computer.")

    def _find_session(self, flight_id: str) -> Path | None:
        for meta_path in (self.root / "sessions").glob("*/meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if any(f.get("id") == flight_id for f in meta.get("flights") or []):
                return meta_path.parent
        log.info("flight %s belongs to no session folder here; no frames", flight_id)
        return None

    @staticmethod
    def _rows(path: Path) -> Iterator[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as f:
            yield from csv.DictReader(f)

    @staticmethod
    def _reading(row: dict[str, str], started: datetime) -> Reading:
        at = _time(row["recorded_at"])
        return Reading(
            index=int(float(row["index"])), recorded_at=at,
            t_s=(at - started).total_seconds(),
            values={k: _number(v) for k, v in row.items() if k not in TEXT_COLUMNS},
        )

    def _frames(self, session: Path, started: datetime,
                ended: datetime) -> list[tuple[str | None, Frame]]:
        index = session / "frames.csv"
        if not index.exists():
            return []
        found: list[tuple[str | None, Frame]] = []
        for row in self._rows(index):
            try:
                at = _time(row["recorded_at"])
                if not started <= at <= ended:
                    continue
                found.append((row.get("point_id") or None, Frame(
                    seq=int(row["seq"]), recorded_at=at, t_s=(at - started).total_seconds(),
                    path=session / row["file"], width=int(row["width"]),
                    height=int(row["height"]), x_m=_number(row.get("x_m")),
                    y_m=_number(row.get("y_m")), z_m=_number(row.get("z_m")))))
            except (KeyError, ValueError):
                log.warning("skipping an unreadable row of %s", index)
        return sorted(found, key=lambda pair: pair[1].seq)

    @staticmethod
    def _plan(session: Path, flight_id: str) -> tuple[InspectionPoint, ...] | None:
        """The inspection points of the mission this flight flew, in order."""
        path = session / "missions" / f"{flight_id}.json"
        if not path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return tuple(
                InspectionPoint(str(p["id"]), p.get("label"), float(p["x_m"]),
                                float(p["y_m"]), float(p["z_m"]))
                for p in data["mission"]["points"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            log.warning("the plan flown by %s could not be read (%s); treating the "
                        "flight as one point", flight_id, e)
            return None
