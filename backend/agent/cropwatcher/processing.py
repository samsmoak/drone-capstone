"""Processing recorded flights through the data pipeline, one at a time, in a
process of its own — the DPP switch on the Control page.

WHEN. The operator chooses per session: on by default in Auto (a mission's
whole point is its verdicts), off by default in Manual, and changeable either
way. The choice is read when a flight BEGINS and recorded on it, so switching
mid-flight never leaves a flight half-decided. When a flight marked for
processing ends — its CSV already closed and on disk (CLAUDE.md invariant 6:
write first) — it is queued here.

WHERE. `cropwatcher process --flight <id>`, the same command a developer runs,
started as a CHILD PROCESS at a lower priority. Never in the agent's own
process: the pipeline's CPU work beside the 50 Hz flight loop would compete
for Python's one interpreter lock (features/pipeline/data-pipeline.txt), and a
stage that crashes or hangs must never take the radio with it. The frozen
desktop agent is the whole CLI with freeze_support() first
(packaging/sidecar.py), so the same command works there.

WHAT COMES OUT. results/<flight id>/result.json, written by the pipeline. This
module only tracks each job — queued, running, done, failed with a reason — and
reports every change to its listener (the session: the app, and the flight's
line in the session history). Nothing here reads or judges a verdict.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

#: A flight's id goes into a path (results/<id>/) and onto a command line.
FLIGHT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: An inspection point's id too (results/<flight>/live/<point>.json).
POINT_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
#: Longest a single flight may take. The stubs finish in well under a second;
#: the real stages will be slower, but a job still running after this is stuck.
TIMEOUT_S = 15 * 60
#: How many recent jobs the app is shown.
KEEP_JOBS = 20


class JobState:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


#: What a job processes: one flight, a session around its flights, or — while a
#: mission flies — the flight so far, for one inspection point's verdict
#: (story 4.9). A live job goes ahead of everything waiting: it is wanted now.
FLIGHT, SESSION, LIVE = "flight", "session", "live"
KINDS = (FLIGHT, SESSION, LIVE)


def job_key(flight_id: str, point_id: str | None = None) -> str:
    """How a job is found: the id, or "<flight>#<point>" for a live job."""
    return f"{flight_id}#{point_id}" if point_id else flight_id


@dataclass
class Job:
    #: The flight's id — or, for a session job (kind "session"), the session's.
    flight_id: str
    state: str = JobState.QUEUED
    queued_at: str = ""
    finished_at: str | None = None
    #: Why it failed, in words; None otherwise.
    error: str | None = None
    kind: str = FLIGHT
    #: A live job's inspection point.
    point_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cli(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "cropwatcher.cli", *args]


def default_command(flight_id: str) -> list[str]:
    """The pipeline command for one flight, frozen or from source."""
    return _cli("process", "--flight", flight_id)


def default_session_command(session_id: str) -> list[str]:
    """The pipeline command for a session around its flights."""
    return _cli("process", "--session", session_id)


def default_live_command(flight_id: str, point_id: str) -> list[str]:
    """The pipeline command for one point's verdict while the flight goes on."""
    return _cli("process", "--flight", flight_id, "--live-point", point_id)


def _lower_priority(process: subprocess.Popen[bytes]) -> None:
    """Behind the flight loop, not beside it. Best effort: a failure here
    changes how fast a result arrives, never whether."""
    with contextlib.suppress(Exception):
        if hasattr(os, "setpriority"):
            os.setpriority(os.PRIO_PROCESS, process.pid, 10)


def _last_line(text: bytes) -> str:
    lines = [line.strip() for line in text.decode("utf-8", "replace").splitlines()
             if line.strip()]
    return lines[-1][:300] if lines else ""


class ProcessingQueue:
    """Flights waiting to be processed, run one after another on one thread."""

    def __init__(self, *, on_change: Callable[[Job], None] | None = None,
                 command: Callable[[str], list[str]] = default_command,
                 session_command: Callable[[str], list[str]] = default_session_command,
                 live_command: Callable[[str, str], list[str]] = default_live_command,
                 timeout_s: float = TIMEOUT_S) -> None:
        self._on_change = on_change
        self._command = command
        self._session_command = session_command
        self._live_command = live_command
        self._timeout_s = timeout_s
        self._jobs: dict[str, Job] = {}
        self._listeners: dict[str, Callable[[Job], None]] = {}
        self._lock = threading.Lock()
        #: (priority, order, key): live first, then in the order submitted;
        #: a key of None stops the worker.
        self._waiting: queue.PriorityQueue[tuple[int, int, str | None]] = queue.PriorityQueue()
        self._order = 0
        self._running: subprocess.Popen[bytes] | None = None
        self._worker: threading.Thread | None = None
        self._closed = False

    # ── the queue ────────────────────────────────────────────────────────

    def submit(self, flight_id: str, *, on_change: Callable[[Job], None] | None = None,
               kind: str = FLIGHT, point_id: str | None = None) -> Job:
        """Queue a flight (or, with kind "session", a session; with kind
        "live", one point of a flight in the air). Queuing one already queued
        or running changes nothing; one that finished is run again (its result
        is replaced)."""
        if kind not in KINDS:
            raise ValueError(f"{kind!r} is not a kind of job")
        if not FLIGHT_ID.match(flight_id or ""):
            raise ValueError(f"{flight_id!r} is not a {kind} id")
        if (kind == LIVE) != bool(point_id) or (point_id and not POINT_ID.match(point_id)):
            raise ValueError("a live job needs a point id, and only a live job has one")
        key = job_key(flight_id, point_id)
        with self._lock:
            if self._closed:
                raise RuntimeError("the processing queue is closed")
            existing = self._jobs.get(key)
            if existing is not None and existing.state in (JobState.QUEUED, JobState.RUNNING):
                return existing
            job = Job(flight_id=flight_id, queued_at=_now(), kind=kind, point_id=point_id)
            self._jobs[key] = job
            if on_change is not None:
                self._listeners[key] = on_change
            self._trim()
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="processing",
                                                daemon=True)
                self._worker.start()
        with self._lock:
            self._order += 1
            order = self._order
        self._waiting.put((0 if kind == LIVE else 1, order, key))
        self._changed(job)
        return job

    def job(self, flight_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(flight_id)

    def jobs(self) -> list[dict[str, Any]]:
        """Newest first."""
        with self._lock:
            return [j.to_dict() for j in reversed(self._jobs.values())]

    def close(self) -> None:
        """Stop taking work and end the flight being processed. Called when the
        agent shuts down; a flight not finished is simply processed again the
        next time someone asks."""
        with self._lock:
            self._closed = True
            running = self._running
        self._waiting.put((-1, 0, None))
        if running is not None:
            with contextlib.suppress(Exception):
                running.kill()

    def wait_idle(self, timeout_s: float = 10.0) -> bool:
        """For tests: True once nothing is queued or running."""
        import time
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                busy = any(j.state in (JobState.QUEUED, JobState.RUNNING)
                           for j in self._jobs.values())
            if not busy:
                return True
            time.sleep(0.01)
        return False

    # ── the worker ───────────────────────────────────────────────────────

    def _work(self) -> None:
        while True:
            _, _, key = self._waiting.get()
            if key is None:
                return
            with self._lock:
                job = self._jobs.get(key)
                if job is None or job.state != JobState.QUEUED:
                    continue
                job.state = JobState.RUNNING
            self._changed(job)
            flight_id = job.flight_id
            error = self._run(flight_id, job.kind, job.point_id)
            with self._lock:
                job.state = JobState.FAILED if error else JobState.DONE
                job.error = error
                job.finished_at = _now()
            if error:
                log.warning("processing %s %s failed: %s", job.kind, flight_id, error)
            else:
                log.info("processed %s %s", job.kind, flight_id)
            self._changed(job)

    def _run(self, flight_id: str, kind: str = FLIGHT,
             point_id: str | None = None) -> str | None:
        """Run the pipeline on one flight, session or live point. None when it
        succeeded, else why not."""
        flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        if kind == LIVE and point_id:
            argv = self._live_command(flight_id, point_id)
        else:
            argv = (self._session_command if kind == SESSION else self._command)(flight_id)
        try:
            process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, creationflags=flags)
        except OSError as e:
            return f"The pipeline could not be started: {e.strerror or e}."
        with self._lock:
            self._running = process
        _lower_priority(process)
        try:
            out, err = process.communicate(timeout=self._timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return f"The pipeline took longer than {self._timeout_s / 60:.0f} minutes and " \
                   f"was stopped."
        finally:
            with self._lock:
                self._running = None
        if process.returncode == 0:
            return None
        said = _last_line(out) or _last_line(err)
        return said or f"The pipeline stopped with code {process.returncode}."

    def _changed(self, job: Job) -> None:
        with self._lock:
            listener = self._listeners.get(job_key(job.flight_id, job.point_id))
        for notify in (self._on_change, listener):
            if notify is None:
                continue
            try:
                notify(job)
            except Exception:
                log.exception("a processing listener failed")

    def _trim(self) -> None:
        """Keep the last KEEP_JOBS; never drop one that is still to run."""
        while len(self._jobs) > KEEP_JOBS:
            oldest = next((fid for fid, j in self._jobs.items()
                           if j.state in (JobState.DONE, JobState.FAILED)), None)
            if oldest is None:
                return
            del self._jobs[oldest]
            self._listeners.pop(oldest, None)
