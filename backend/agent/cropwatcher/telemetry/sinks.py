"""Where telemetry rows go.

Flight code calls ``sink.write(row)`` and never imports Supabase, CSV or
anything else. That indirection is what lets the CSV write be unconditional
while the network upload is best-effort.

**A local write cannot fail; a flight cannot be re-run.** If the network drops
mid-flight, that flight's data is gone forever unless it already hit the disk.
So the CSV is the record of truth and Supabase is a copy, never the reverse.
"""

from __future__ import annotations

import csv
import logging
import queue
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


class TelemetrySink(Protocol):
    """Anywhere a telemetry row can go."""

    def write(self, row: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class CsvSink:
    """Append rows to a timestamped CSV under a date folder.

    Path shape matches the original project so existing analysis still works::

        <root>/<YYYY-MM-DD>/flight_<YYYY-MM-DD_HH-MM-SS>.csv

    The header is taken from the first row written, so the schema is whatever
    the correction engine actually produced rather than a list kept in sync by
    hand.
    """

    def __init__(self, root: Path | str = "organized_flights", prefix: str = "flight") -> None:
        now = datetime.now()
        folder = Path(root) / now.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)

        stem = f"{prefix}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
        path = folder / f"{stem}.csv"
        counter = 1
        while path.exists():
            path = folder / f"{stem}_{counter}.csv"
            counter += 1

        self.path = path
        self._file = path.open("w", newline="", encoding="utf-8")
        self._writer: csv.DictWriter | None = None
        self._lock = threading.Lock()
        log.info("logging telemetry to %s", path)

    def write(self, row: dict[str, Any]) -> None:
        with self._lock:
            if self._writer is None:
                self._writer = csv.DictWriter(self._file, fieldnames=list(row.keys()))
                self._writer.writeheader()
            self._writer.writerow(row)
            # Flush every row: a crash or brownout must not cost the tail of a
            # flight sitting in a buffer.
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()


class LiveUploadSink:
    """Batch rows to Supabase during the flight, on a background thread.

    Never blocks the flight loop and never raises into it — a failed batch is
    logged and dropped, because the CSV already holds the data and the sync
    re-sends whatever the server is missing once it can (see sync/syncer.py).
    Rows are batched rather than inserted one at a time; at 10 Hz, per-row
    inserts would be 10 round trips a second for no benefit.
    """

    def __init__(
        self,
        send: Callable[[list[dict[str, Any]]], None],
        batch_size: int = 50,
        flush_interval_s: float = 5.0,
    ) -> None:
        self._send = send
        self._batch_size = batch_size
        self._flush_interval = flush_interval_s

        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="live-upload")
        self._thread.start()

    def write(self, row: dict[str, Any]) -> None:
        self._queue.put(row)

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=10.0)

    def _run(self) -> None:
        batch: list[dict[str, Any]] = []
        while True:
            try:
                row = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                self._flush(batch)
                batch = []
                continue

            if row is None:                       # close() sentinel
                self._flush(batch)
                return

            batch.append(row)
            if len(batch) >= self._batch_size:
                self._flush(batch)
                batch = []

    def _flush(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        try:
            self._send(batch)
        except Exception:
            # Deliberately swallowed. The CSV has the data, and the sync fills
            # the gap; losing the flight is what cannot be recovered.
            log.info("live upload failed for %d rows; the sync will send them", len(batch))


class FanOutSink:
    """Write to several sinks. One failing never stops the others."""

    def __init__(self, sinks: Sequence[TelemetrySink]) -> None:
        self._sinks = list(sinks)

    def write(self, row: dict[str, Any]) -> None:
        for sink in self._sinks:
            try:
                sink.write(row)
            except Exception:
                log.exception("sink %s failed on write", type(sink).__name__)

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:
                log.exception("sink %s failed on close", type(sink).__name__)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
