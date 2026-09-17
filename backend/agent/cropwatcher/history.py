"""The session history kept on this laptop.

Every session leaves a folder the desktop app can read back, online or not:

    sessions/<session id>/meta.json     who, which drone, when, and a summary
    sessions/<session id>/samples.csv   every stream variable, once a second,
                                        for the WHOLE session — not only while
                                        a flight is recording

The outbox is the wrong place for this: it deletes records once Supabase has
them, and the operator's own history should not disappear because the upload
succeeded. The flight CSVs are the wrong place too: they cover flights only, and
a session's checks, idling and aborted takeoffs happen outside them.

**Auto and Manual are kept apart.** The mode can change between flights inside
one session, so it is recorded on every sample, not just on the session: a
filter on "Manual" then shows manual readings only, even from a session that
started in Auto. `modes` lists every mode a session used.

One sample a second keeps a long session small (about 1 MB an hour) while still
answering "what did the battery do between 14:02 and 14:09". The flight CSVs
keep the full 10 Hz record for the dashboard.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cropwatcher.paths import data_dir

log = logging.getLogger(__name__)

SAMPLE_PERIOD_S = 1.0
MAX_SAMPLES_RETURNED = 5000


def sessions_dir() -> Path:
    root = data_dir() / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class FlightSummary:
    id: str
    mode: str
    program: str | None
    started_at: str
    ended_at: str | None = None
    outcome: str | None = None
    abort_reason: str | None = None


@dataclass
class SessionSummary:
    """What the Control page's recent-sessions list shows at a glance."""

    samples: int = 0
    battery_start_v: float | None = None
    battery_end_v: float | None = None
    battery_min_v: float | None = None
    max_height_m: float | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None


@dataclass
class SessionMeta:
    id: str
    operator_id: str
    operator_email: str
    operator_name: str | None
    drone_hardware_id: str | None
    mode: str
    assisted: bool
    started_at: str
    ended_at: str | None = None
    end_reason: str | None = None
    #: Every mode this session was in at some point, in first-used order.
    modes: list[str] = field(default_factory=list)
    flights: list[FlightSummary] = field(default_factory=list)
    summary: SessionSummary = field(default_factory=SessionSummary)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SessionMeta:
        data = dict(raw)
        data["flights"] = [FlightSummary(**f) for f in data.get("flights", [])]
        data["summary"] = SessionSummary(**data.get("summary", {}))
        return cls(**data)

    @property
    def duration_s(self) -> float | None:
        if self.ended_at is None:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.ended_at)
        return (end - start).total_seconds()


class SessionLog:
    """One session's folder. Written as the session happens, never after."""

    def __init__(
        self,
        meta: SessionMeta,
        *,
        root: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        height_reference: Callable[[], float | None] = lambda: None,
    ) -> None:
        self.meta = meta
        self.folder = (root or sessions_dir()) / meta.id
        self.folder.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._height_reference = height_reference
        self._lock = threading.Lock()
        self._last_sample: float | None = None
        self._columns: list[str] | None = None
        self._file: Any = None
        self._writer: Any = None
        if meta.mode not in meta.modes:
            meta.modes.append(meta.mode)
        self._save()

    # ── meta ─────────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Atomic: a crash mid-write leaves the previous meta, never half of one."""
        target = self.folder / "meta.json"
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.meta.to_dict(), indent=2))
        os.replace(temp, target)

    def flight_started(self, flight_id: str, mode: str, program: str | None) -> None:
        with self._lock:
            self.meta.flights.append(
                FlightSummary(id=flight_id, mode=mode, program=program, started_at=_now_iso()))
            self._save()

    def flight_finished(self, flight_id: str, *, outcome: str | None,
                        abort_reason: str | None = None) -> None:
        with self._lock:
            for flight in self.meta.flights:
                if flight.id == flight_id:
                    flight.ended_at = _now_iso()
                    flight.outcome = outcome
                    flight.abort_reason = abort_reason
            self._save()

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.meta.mode = mode
            if mode not in self.meta.modes:
                self.meta.modes.append(mode)
            self._save()

    # ── samples ──────────────────────────────────────────────────────────

    def sample(self, snap: Any) -> None:
        """Called at the stream rate; keeps one sample per SAMPLE_PERIOD_S."""
        now = self._clock()
        with self._lock:
            if self._last_sample is not None and now - self._last_sample < SAMPLE_PERIOD_S:
                return
            self._last_sample = now
            values: Mapping[str, float] = dict(getattr(snap, "values", {}) or {})
            if not values:
                return
            if self._writer is None:
                self._columns = ["recorded_at", "mode", "height_m", *sorted(values)]
                self._file = (self.folder / "samples.csv").open("w", newline="")
                self._writer = csv.writer(self._file)
                self._writer.writerow(self._columns)

            reference = self._height_reference()
            z = values.get("stateEstimate.z")
            height = None if z is None or reference is None else round(z - reference, 3)
            assert self._columns is not None
            row = [_now_iso(), self.meta.mode, height, *(values.get(c) for c in self._columns[3:])]
            self._writer.writerow(row)
            self._file.flush()
            self._update_summary(values, height)

    def _update_summary(self, values: Mapping[str, float], height: float | None) -> None:
        s = self.meta.summary
        s.samples += 1
        vbat = values.get("pm.vbat")
        if vbat is not None:
            if s.battery_start_v is None:
                s.battery_start_v = round(vbat, 2)
            s.battery_end_v = round(vbat, 2)
            lowest = vbat if s.battery_min_v is None else min(s.battery_min_v, vbat)
            s.battery_min_v = round(lowest, 2)
        if height is not None:
            highest = height if s.max_height_m is None else max(s.max_height_m, height)
            s.max_height_m = round(highest, 3)
        temp = values.get("baro.temp")
        if temp is not None:
            s.temp_min_c = round(temp if s.temp_min_c is None else min(s.temp_min_c, temp), 2)
            s.temp_max_c = round(temp if s.temp_max_c is None else max(s.temp_max_c, temp), 2)
        # Meta on disk every ten samples: cheap, and a crash loses ten seconds.
        if s.samples % 10 == 1:
            self._save()

    # ── end ──────────────────────────────────────────────────────────────

    def close(self, reason: str) -> None:
        with self._lock:
            self.meta.ended_at = _now_iso()
            self.meta.end_reason = reason
            self._save()
            if self._file is not None:
                self._file.close()
                self._file, self._writer = None, None


# ── reading ──────────────────────────────────────────────────────────────


def _used(meta: SessionMeta, mode: str | None) -> bool:
    return mode is None or mode in (meta.modes or [meta.mode])


def list_sessions(
    limit: int = 20, *, mode: str | None = None, root: Path | None = None,
) -> list[dict[str, Any]]:
    """Newest first, optionally only sessions that were in `mode` at some point.

    A folder with an unreadable meta is skipped, not fatal.
    """
    folder = root or sessions_dir()
    metas: list[SessionMeta] = []
    for meta_file in folder.glob("*/meta.json"):
        try:
            metas.append(SessionMeta.from_dict(json.loads(meta_file.read_text())))
        except (OSError, ValueError, TypeError):
            log.warning("skipping unreadable session record %s", meta_file.parent.name)
    metas = [m for m in metas if _used(m, mode)]
    metas.sort(key=lambda m: m.started_at, reverse=True)
    return [_public(m) for m in metas[:limit]]


def read_session(session_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    meta_file = _session_folder(session_id, root) / "meta.json"
    if not meta_file.exists():
        return None
    return _public(SessionMeta.from_dict(json.loads(meta_file.read_text())))


def read_samples(
    session_id: str,
    variables: Iterable[str],
    *,
    mode: str | None = None,
    root: Path | None = None,
    limit: int = MAX_SAMPLES_RETURNED,
) -> list[dict[str, Any]]:
    """The requested columns, oldest first, optionally only readings taken in
    `mode`. Unknown variables come back None."""
    folder = _session_folder(session_id, root)
    path = folder / "samples.csv"
    if not path.exists():
        return []
    fallback_mode = None
    meta_file = folder / "meta.json"
    if meta_file.exists():
        fallback_mode = json.loads(meta_file.read_text()).get("mode")
    wanted = list(variables)
    rows: list[dict[str, Any]] = []
    with path.open(newline="") as f:
        for raw in csv.DictReader(f):
            row_mode = raw.get("mode") or fallback_mode
            if mode is not None and row_mode != mode:
                continue
            row: dict[str, Any] = {"recorded_at": raw.get("recorded_at"), "mode": row_mode}
            for name in wanted:
                row[name] = _number(raw.get(name))
            rows.append(row)
    # Evenly thinned, so a long session still spans its whole time range.
    if len(rows) > limit:
        step = len(rows) / limit
        rows = [rows[int(i * step)] for i in range(limit)]
    return rows


def _session_folder(session_id: str, root: Path | None) -> Path:
    # The id arrives from a URL: refuse anything that could walk out of the folder.
    if not session_id or any(c in session_id for c in "/\\."):
        raise ValueError("invalid session id")
    return (root or sessions_dir()) / session_id


def _number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _public(meta: SessionMeta) -> dict[str, Any]:
    data = meta.to_dict()
    data["duration_s"] = meta.duration_s
    return data
