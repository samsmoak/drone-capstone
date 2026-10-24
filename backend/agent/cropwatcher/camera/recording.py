"""Every camera frame of a session, written to disk first — then uploaded.

WHY FILES FIRST. The same rule as the flight CSV (CLAUDE.md, flight invariant
6): a local write cannot fail, a flight cannot be re-run, and the upload is
best-effort. So a session's frames land in its own folder as they arrive, and
the window reads them back from there — what the operator watches IS what was
saved and what will upload.

    <session folder>/frames/000001.png      one file per frame, as received
    <session folder>/frames.csv             one row per frame (the index)

    seq, recorded_at, t_s, file, width, height, bytes, x_m, y_m, z_m, upload,
    point_id, source, why, change

x/y/z are the drone's estimate at the moment the frame arrived, so every image
says where it was taken. point_id is the inspection point the mission
controller was HOLDING at that moment, and empty otherwise (story 3.5).
`upload` is 1 for the frames CAPTURED — the ones that go to Supabase and fill
the galleries. EVERY frame is kept on the laptop; which are captured is the
auto-capture rule (capture.py, 2026-10-24): a frame that differs from the last
captured one, at most 2 a second (the pacing decided 2026-09-24 for upload
size), the first few similar ones, every frame while a point is held, and one
in each long still stretch. `why` says which; `change` is the measured
difference from the last captured frame. `source` is "auto", or "manual" for
a frame the operator captured by hand — always uploaded, never paced.

AUTO-CAPTURE OFF (the session's switch, 2026-10-24, Samuel: "when off it
doesnt mean the camera goes black the camera is on but just that the frames are
not stored"): nothing is written automatically. The camera stays live; manual
captures are still saved.

ONLY IN A SESSION. Standby shows the camera live and records nothing — the
same line the vitals follow (sessions-and-modes.txt).

UPLOAD IS ONE OUTBOX RECORD PER SESSION (Kind.FRAMES) with a cursor —
"uploaded through seq N" — exactly as flight telemetry resumes from its last
row. One record per frame would be ~1,200 files per ten minutes in an outbox
that never deletes a sent record.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cropwatcher.camera.capture import MANUAL, MIN_INTERVAL_S, CaptureRule, small_grey
from cropwatcher.sync.outbox import Kind, Outbox

log = logging.getLogger(__name__)

INDEX_NAME = "frames.csv"
FRAMES_DIR = "frames"
COLUMNS = ["seq", "recorded_at", "t_s", "file", "width", "height", "bytes",
           "x_m", "y_m", "z_m", "upload", "point_id", "source", "why", "change"]

_EXT = {"image/png": "png", "image/jpeg": "jpg"}

Position = Callable[[], tuple[float, float, float] | None]
#: Which inspection point is being held, if any (story 3.5) — see session.py.
PointId = Callable[[], str | None]
#: Whether the session records frames automatically (its auto-capture switch).
Auto = Callable[[], bool]


def _no_point() -> str | None:
    return None


@dataclass(frozen=True)
class RecordedFrame:
    seq: int
    t_s: float
    recorded_at: str
    file: str
    content_type: str
    upload: bool
    #: "auto", or "manual" — captured by hand.
    source: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "t_s": round(self.t_s, 3), "recorded_at": self.recorded_at,
                "upload": self.upload, "source": self.source}


class FrameRecording:
    """One session's frames. Thread-safe: frames arrive on the camera's thread,
    the window reads on the API's."""

    def __init__(
        self,
        session_id: str,
        folder: Path,
        *,
        position: Position = lambda: None,
        point_id: PointId = _no_point,
        auto: Auto = lambda: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.folder = folder
        self.frames_dir = folder / FRAMES_DIR
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = folder / INDEX_NAME
        self._position = position
        self._point_id = point_id
        self._auto = auto
        self._rule = CaptureRule()
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._frames: list[RecordedFrame] = []
        self.write_errors = 0
        with self.index_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNS)

    # ── writing ──────────────────────────────────────────────────────────

    def add(self, data: bytes, content_type: str, width: int, height: int) -> RecordedFrame | None:
        """Write one frame from the camera and its index row, and decide
        whether it is captured. None if auto-capture is off (nothing is
        written) or the disk refused it — the stream carries on; a lost frame
        is not worth stopping for."""
        if not self._auto():
            return None
        # Decoded outside the lock: the API's reads must not wait on it.
        image = small_grey(data)
        t = self._clock() - self._started
        point = self._current_point()
        with self._lock:
            decision = self._rule.decide(t, image, holding_point=bool(point))
            frame = self._write(data, content_type, width, height, t, point,
                                upload=decision.captured, source="auto",
                                why=decision.why or "", change=decision.change)
            if frame is not None and decision.captured and decision.why is not None:
                self._rule.commit(t, image, decision.why)
            return frame

    def add_manual(self, data: bytes, content_type: str, width: int,
                   height: int) -> RecordedFrame | None:
        """A frame the operator captured by hand: always written, always
        uploaded, whatever auto-capture says. None if the disk refused it."""
        t = self._clock() - self._started
        point = self._current_point()
        with self._lock:
            return self._write(data, content_type, width, height, t, point,
                               upload=True, source=MANUAL, why=MANUAL, change=None)

    def _current_point(self) -> str:
        try:
            return self._point_id() or ""
        except Exception:
            return ""

    def _write(self, data: bytes, content_type: str, width: int, height: int, t: float,
               point: str, *, upload: bool, source: str, why: str,
               change: float | None) -> RecordedFrame | None:
        """The file, then its row. Under the lock: seq is the list's length."""
        seq = len(self._frames) + 1
        name = f"{seq:06d}.{_EXT.get(content_type, 'bin')}"
        at = datetime.now(UTC).isoformat()
        pos = self._position()
        try:
            (self.frames_dir / name).write_bytes(data)
            with self.index_path.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    seq, at, f"{t:.3f}", f"{FRAMES_DIR}/{name}", width, height, len(data),
                    *(("", "", "") if pos is None else (f"{p:.3f}" for p in pos)),
                    int(upload), point, source, why,
                    "" if change is None else f"{change:.2f}",
                ])
        except OSError:
            self.write_errors += 1
            log.warning("could not record camera frame %d", seq)
            return None
        frame = RecordedFrame(seq, t, at, name, content_type, upload, source)
        self._frames.append(frame)
        return frame

    # ── reading ──────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._frames)

    def latest(self) -> RecordedFrame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def get(self, seq: int) -> RecordedFrame | None:
        with self._lock:
            return self._frames[seq - 1] if 1 <= seq <= len(self._frames) else None

    def after(self, seq: int, limit: int, source: str | None = None) -> list[RecordedFrame]:
        """Frames after `seq`, up to `limit` — of one source, when asked."""
        with self._lock:
            frames = self._frames[max(seq, 0):]
        if source is not None:
            frames = [f for f in frames if f.source == source]
        return frames[:limit]

    def path(self, frame: RecordedFrame) -> Path:
        return self.frames_dir / frame.file

    def summary(self) -> dict[str, Any]:
        with self._lock:
            frames = list(self._frames)
        latest = frames[-1] if frames else None
        return {
            "recording": True, "session_id": self.session_id, "count": len(frames),
            "latest_seq": latest.seq if latest else 0,
            "latest_t_s": round(latest.t_s, 3) if latest else None,
            "upload_fps": round(1.0 / MIN_INTERVAL_S, 3),
            "write_errors": self.write_errors,
            "auto": self._auto(),
            "captured": sum(1 for f in frames if f.upload),
            "manual": sum(1 for f in frames if f.source == MANUAL),
        }


class Recorder:
    """The agent-level switch: which session, if any, frames go to."""

    def __init__(self, outbox: Outbox, position: Position = lambda: None,
                 clock: Callable[[], float] = time.monotonic,
                 point_id: PointId = _no_point, auto: Auto = lambda: True) -> None:
        self._outbox = outbox
        self._position = position
        self._point_id = point_id
        self._auto = auto
        self._clock = clock
        self._lock = threading.Lock()
        self.current: FrameRecording | None = None

    def start(self, session_id: str, folder: Path) -> FrameRecording:
        recording = FrameRecording(session_id, folder, position=self._position,
                                   point_id=self._point_id, auto=self._auto,
                                   clock=self._clock)
        self._outbox.put(Kind.FRAMES, session_id, {
            "session_id": session_id, "folder": str(folder),
            "started_at": datetime.now(UTC).isoformat(),
            "uploaded_through": 0, "ended": False, "index_uploaded": False,
        })
        with self._lock:
            self.current = recording
        log.info("recording camera frames for session %s", session_id)
        return recording

    def stop(self) -> None:
        with self._lock:
            recording, self.current = self.current, None
        if recording is None:
            return
        self._outbox.update(Kind.FRAMES, recording.session_id,
                            lambda p: p.update({"ended": True, "count": recording.count}))
        log.info("recorded %d camera frames", recording.count)

    def on_frame(self, data: bytes, content_type: str, width: int, height: int) -> None:
        with self._lock:
            recording = self.current
        if recording is not None:
            recording.add(data, content_type, width, height)

    def capture_manual(self, data: bytes, content_type: str, width: int,
                       height: int) -> RecordedFrame:
        """Save one frame by hand into the session's recording. A session is
        required — standby records nothing, by hand or otherwise."""
        with self._lock:
            recording = self.current
        if recording is None:
            raise NotRecording("Start a session first: captures are saved into a session.")
        frame = recording.add_manual(data, content_type, width, height)
        if frame is None:
            raise NotRecording("The frame could not be saved — the laptop's disk refused it.")
        log.info("captured frame %d by hand", frame.seq)
        return frame


class NotRecording(Exception):
    """A capture was asked for and could not be saved; the message says why."""


def read_index(folder: Path, source: str | None = None) -> list[dict[str, Any]]:
    """A session's frames as frames.csv lists them, oldest first — of one
    source, when asked. For a session that has ended (the history pages);
    a running one is read from memory (FrameRecording). A row from before
    `source` existed is "auto": nothing could be captured by hand then."""
    index = folder / INDEX_NAME
    if not index.exists():
        return []
    out: list[dict[str, Any]] = []
    with index.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                seq, t_s = int(row["seq"]), float(row["t_s"])
            except (KeyError, ValueError):
                continue
            kind = row.get("source") or "auto"
            if source is not None and kind != source:
                continue
            out.append({"seq": seq, "t_s": round(t_s, 3), "recorded_at": row.get("recorded_at"),
                        "upload": row.get("upload") == "1", "source": kind,
                        "point_id": row.get("point_id") or None})
    return out


def frame_file(folder: Path, seq: int) -> tuple[Path, str] | None:
    """One recorded frame's file and content type, by number, or None. The
    name comes from the index, never from the request."""
    index = folder / INDEX_NAME
    if not index.exists():
        return None
    with index.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("seq") == str(seq):
                file = folder / row["file"]
                if not file.is_file():
                    return None
                return file, "image/jpeg" if file.suffix == ".jpg" else "image/png"
    return None


def frames_to_upload(folder: Path, after_seq: int) -> Iterator[tuple[int, Path, str]]:
    """(seq, file, content type) for each frame marked for upload after
    `after_seq`, read from frames.csv — the record on disk, not memory, so an
    agent that restarted uploads exactly what the index says."""
    index = folder / INDEX_NAME
    if not index.exists():
        return
    with index.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                seq = int(row["seq"])
            except (KeyError, ValueError):
                continue
            if seq <= after_seq or row.get("upload") != "1":
                continue
            file = folder / row["file"]
            ctype = "image/jpeg" if file.suffix == ".jpg" else "image/png"
            yield seq, file, ctype
