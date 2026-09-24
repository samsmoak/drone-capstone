"""Getting local records to Supabase, eventually and exactly once.

The laptop is the one that must push: no server can reach into it, the same
constraint as the radio. So this runs whenever it can — during a flight, when a
flight ends, at sign-in, and every minute while anything is unsent — and the
desktop app stays in the tray until it reports nothing pending.

Order matters, because records reference each other: drones, then sessions,
then flights, then each flight's telemetry and log file. Audit events have no
foreign keys precisely so they can go first and never wait for anything.

Nothing is ever sent twice into a duplicate: ids are generated on the laptop,
records upsert on their id, and telemetry upserts on ``(flight_id, index)``
after asking the server for the highest row it already holds.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args, get_type_hints

from cropwatcher.camera.recording import INDEX_NAME, frames_to_upload
from cropwatcher.sync.cloud import Cloud, CloudError
from cropwatcher.sync.outbox import Kind, Outbox
from cropwatcher.telemetry.row import TelemetryRow

log = logging.getLogger(__name__)

AUDIT_BATCH = 100
TELEMETRY_BATCH = 500
SYNC_INTERVAL_S = 60.0

# Column → type, from the one row schema shared by the CSV and Postgres.
#
# Resolved with get_type_hints, not the raw annotations: `from __future__ import
# annotations` makes those plain strings, and comparing a string to `int` never
# matches — every column came back as text, so `index + 1` concatenated.
def _column_types() -> dict[str, type]:
    types: dict[str, type] = {}
    for name, hint in get_type_hints(TelemetryRow).items():
        args = [a for a in get_args(hint) if a is not type(None)]
        resolved = args[0] if args else hint
        if resolved in (int, float, str):
            types[name] = resolved
    return types


_TYPES = _column_types()


def parse_csv_row(raw: dict[str, str]) -> dict[str, Any]:
    """One CSV line back into the types Postgres expects."""
    row: dict[str, Any] = {}
    for column, value in raw.items():
        if value == "" or value is None:
            row[column] = None
            continue
        kind = _TYPES.get(column, str)
        if kind is int:
            row[column] = int(float(value))
        elif kind is float:
            row[column] = float(value)
        else:
            row[column] = value
    return row


def read_rows_after(csv_path: Path, after_index: int | None) -> Iterator[dict[str, Any]]:
    """Rows from the flight's CSV with an index above `after_index`."""
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            index = raw.get("index")
            if index in (None, ""):
                continue
            if after_index is not None and int(float(index)) <= after_index:
                continue
            yield parse_csv_row(raw)


@dataclass
class SyncStatus:
    """What the operator sees before they close the app."""

    pending_flights: int = 0
    pending_events: int = 0
    uploading: str | None = None
    last_error: str | None = None
    last_success_at: float | None = None

    @property
    def everything_sent(self) -> bool:
        return self.pending_flights == 0 and self.pending_events == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending_flights": self.pending_flights,
            "pending_events": self.pending_events,
            "uploading": self.uploading,
            "last_error": self.last_error,
            "everything_sent": self.everything_sent,
        }


class Syncer:
    def __init__(
        self,
        outbox: Outbox,
        cloud_for: Callable[[], Cloud | None],
        *,
        on_status: Callable[[SyncStatus], None] | None = None,
        interval_s: float = SYNC_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`cloud_for` returns the signed-in client, or None when signed out."""
        self._outbox = outbox
        self._cloud_for = cloud_for
        self._on_status = on_status
        self._interval = interval_s
        self._sleep = sleep
        self.status = SyncStatus()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

    # ── loop ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is None:
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True, name="sync")
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def trigger(self) -> None:
        """Sync now — called at flight end, sign-in and End session."""
        self._wake.set()

    def _run(self) -> None:
        while self._running:
            try:
                self.sync_once()
            except Exception:
                log.exception("sync pass failed; will retry")
            self._wake.wait(self._interval)
            self._wake.clear()

    # ── one pass ─────────────────────────────────────────────────────────

    def sync_once(self) -> SyncStatus:
        with self._lock:
            cloud = self._cloud_for()
            if cloud is None:
                self._refresh_counts(offline=True)
                return self.status
            try:
                self._send_audit(cloud)
                self._send_drones(cloud)
                self._send_sessions(cloud)
                self._send_flights(cloud)
                self._send_frames(cloud)
                self.status.last_error = None
                self.status.last_success_at = time.time()
            except CloudError as e:
                # Expected when offline: everything stays on disk for next time.
                self.status.last_error = str(e)
                log.info("sync incomplete: %s", e)
            finally:
                self.status.uploading = None
                self._refresh_counts()
            return self.status

    def _refresh_counts(self, offline: bool = False) -> None:
        self.status.pending_flights = self._outbox.count_pending(Kind.FLIGHT)
        self.status.pending_events = self._outbox.count_pending(Kind.AUDIT)
        if offline:
            self.status.last_error = "Not signed in — records are saved on this computer."
        if self._on_status is not None:
            try:
                self._on_status(self.status)
            except Exception:
                log.exception("sync status callback failed")

    # ── each kind ────────────────────────────────────────────────────────

    def _send_audit(self, cloud: Cloud) -> None:
        batch: list[dict[str, Any]] = []
        ids: list[str] = []
        for record in self._outbox.pending(Kind.AUDIT):
            batch.append({k: v for k, v in record.payload.items() if not k.startswith("_")})
            ids.append(record.id)
            if len(batch) >= AUDIT_BATCH:
                break
        if not batch:
            return
        cloud.insert_audit(batch)
        for event_id in ids:
            self._outbox.remove(Kind.AUDIT, event_id)

    def _send_drones(self, cloud: Cloud) -> None:
        for record in self._outbox.pending(Kind.DRONE):
            payload = record.payload
            drone_id = cloud.upsert_drone(
                payload["hardware_id"], payload.get("name") or payload["hardware_id"],
                payload.get("uri", ""),
            )
            self._outbox.update(
                Kind.DRONE, record.id,
                lambda payload, drone_id=drone_id: payload.update(
                    {"drone_id": drone_id, "_sent": True}),
            )

    def _send_sessions(self, cloud: Cloud) -> None:
        for record in self._outbox.pending(Kind.SESSION):
            row = self._row(record.payload)
            row["drone_id"] = self._drone_id(record.payload.get("drone_hardware_id"))
            cloud.upsert_session(row)
            # Only finished sessions are done; an open one is re-sent as it changes.
            if record.payload.get("ended_at"):
                self._outbox.mark_sent(Kind.SESSION, record.id)

    def _send_flights(self, cloud: Cloud) -> None:
        for record in self._outbox.pending(Kind.FLIGHT):
            payload = record.payload
            flight_id = record.id
            row = self._row(payload, drop={
                "csv_path", "csv_object", "csv_uploaded", "rows_written", "drone_hardware_id"})
            row["drone_id"] = self._drone_id(payload.get("drone_hardware_id"))
            cloud.upsert_flight(row)

            csv_path = Path(payload.get("csv_path", ""))
            if not csv_path.exists():
                log.warning("flight %s has no CSV on disk; sending the record only", flight_id)
                if payload.get("ended_at"):
                    self._outbox.mark_sent(Kind.FLIGHT, flight_id)
                continue

            self.status.uploading = flight_id
            sent_to = cloud.max_telemetry_index(flight_id)
            batch: list[dict[str, Any]] = []
            for telemetry_row in read_rows_after(csv_path, sent_to):
                batch.append(telemetry_row)
                if len(batch) >= TELEMETRY_BATCH:
                    cloud.insert_telemetry(batch)
                    sent_to = batch[-1]["index"]
                    batch = []
            if batch:
                cloud.insert_telemetry(batch)
                sent_to = batch[-1]["index"]

            if not payload.get("ended_at"):
                continue        # still flying: rows keep coming

            object_path = payload.get("csv_object") or f"{flight_id}.csv.gz"
            if not payload.get("csv_uploaded"):
                cloud.upload_flight_csv(object_path, csv_path)
                self._outbox.update(
                    Kind.FLIGHT, flight_id,
                    lambda payload, object_path=object_path: payload.update(
                        {"csv_uploaded": True, "csv_object": object_path}),
                )
                # The server can finish the import even if this laptop closes now.
                cloud.request_backfill(flight_id, object_path)

            expected = payload.get("rows_written")
            complete = expected is None or (sent_to is not None and sent_to + 1 >= expected)
            if complete:
                self._outbox.mark_sent(Kind.FLIGHT, flight_id)
            else:
                log.info("flight %s: %s of %s rows uploaded", flight_id,
                         (sent_to or -1) + 1, expected)

    def _send_frames(self, cloud: Cloud) -> None:
        """A session's recorded frames, from its cursor on (camera/recording.py).

        Only frames frames.csv marks for upload; the cursor advances after each
        one lands, so an interrupted pass resumes exactly where it stopped. The
        index goes last, once the session has ended — replacing any earlier
        copy — and only then is the record sent.
        """
        for record in self._outbox.pending(Kind.FRAMES):
            payload = record.payload
            session_id = record.id
            folder = Path(payload.get("folder", ""))
            if not folder.exists():
                log.warning("session %s has no frames folder; nothing to upload", session_id)
                self._outbox.mark_sent(Kind.FRAMES, session_id)
                continue
            self.status.uploading = f"frames {session_id[:8]}"
            cursor = int(payload.get("uploaded_through", 0))
            for seq, path, content_type in frames_to_upload(folder, cursor):
                cloud.upload_frame(f"{session_id}/{path.parent.name}/{path.name}",
                                   path, content_type)
                self._outbox.update(Kind.FRAMES, session_id,
                                    lambda p, seq=seq: p.__setitem__("uploaded_through", seq))
            if not payload.get("ended"):
                continue        # still recording: more frames will come
            cloud.upload_frame(f"{session_id}/{INDEX_NAME}", folder / INDEX_NAME, "text/csv",
                               replace=True)
            self._outbox.mark_sent(Kind.FRAMES, session_id)

    # ── helpers ──────────────────────────────────────────────────────────

    def _drone_id(self, hardware_id: str | None) -> str | None:
        if not hardware_id:
            return None
        record = self._outbox.get(Kind.DRONE, hardware_id)
        return (record or {}).get("drone_id")

    @staticmethod
    def _row(payload: dict[str, Any], drop: set[str] | None = None) -> dict[str, Any]:
        """The server-facing columns: local bookkeeping and locals-only fields out."""
        skip = {"drone_hardware_id"} | (drop or set())
        return {k: v for k, v in payload.items() if not k.startswith("_") and k not in skip}
