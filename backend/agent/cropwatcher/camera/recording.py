"""Every camera frame of a session, written to disk first — then uploaded.

WHY FILES FIRST. The same rule as the flight CSV (CLAUDE.md, flight invariant
6): a local write cannot fail, a flight cannot be re-run, and the upload is
best-effort. So a session's frames land in its own folder as they arrive, and
the window reads them back from there — what the operator watches IS what was
saved and what will upload.

    <session folder>/frames/000001.png      one file per frame, as received
    <session folder>/frames.csv             one row per frame (the index)

    seq, recorded_at, t_s, file, width, height, bytes, x_m, y_m, z_m, upload

x/y/z are the drone's estimate at the moment the frame arrived, so every image
says where it was taken. `upload` is 1 for the frames chosen to go to Supabase:
EVERY frame is kept on the laptop; UPLOAD_FPS of them a second go up (decided
2026-09-24: 2 a second — about 27-55 MB per 10 minutes at ~45 KB a frame,
instead of ~100 MB for all ~3.7 a second).

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

from cropwatcher.sync.outbox import Kind, Outbox

log = logging.getLogger(__name__)

#: Frames a second chosen for upload. Every frame is still kept on disk.
UPLOAD_FPS = 2.0

INDEX_NAME = "frames.csv"
FRAMES_DIR = "frames"
COLUMNS = ["seq", "recorded_at", "t_s", "file", "width", "height", "bytes",
           "x_m", "y_m", "z_m", "upload"]

_EXT = {"image/png": "png", "image/jpeg": "jpg"}

Position = Callable[[], tuple[float, float, float] | None]


@dataclass(frozen=True)
class RecordedFrame:
    seq: int
    t_s: float
    recorded_at: str
    file: str
    content_type: str
    upload: bool

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "t_s": round(self.t_s, 3), "recorded_at": self.recorded_at,
                "upload": self.upload}


class FrameRecording:
    """One session's frames. Thread-safe: frames arrive on the camera's thread,
    the window reads on the API's."""

    def __init__(
        self,
        session_id: str,
        folder: Path,
        *,
        position: Position = lambda: None,
        upload_fps: float = UPLOAD_FPS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.folder = folder
        self.frames_dir = folder / FRAMES_DIR
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = folder / INDEX_NAME
        self._position = position
        self._upload_every = 1.0 / upload_fps
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._frames: list[RecordedFrame] = []
        self._next_upload_t = 0.0
        self.write_errors = 0
        with self.index_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNS)

    # ── writing ──────────────────────────────────────────────────────────

    def add(self, data: bytes, content_type: str, width: int, height: int) -> RecordedFrame | None:
        """Write one frame and its index row. None if the disk refused it —
        the stream carries on; a lost frame is not worth stopping for."""
        t = self._clock() - self._started
        with self._lock:
            seq = len(self._frames) + 1
            upload = t >= self._next_upload_t
            if upload:
                # Pace from the frame actually chosen, so a stall does not
                # bunch the next picks together.
                self._next_upload_t = t + self._upload_every
            name = f"{seq:06d}.{_EXT.get(content_type, 'bin')}"
            at = datetime.now(UTC).isoformat()
            pos = self._position()
            try:
                (self.frames_dir / name).write_bytes(data)
                with self.index_path.open("a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([
                        seq, at, f"{t:.3f}", f"{FRAMES_DIR}/{name}", width, height, len(data),
                        *(("", "", "") if pos is None else (f"{p:.3f}" for p in pos)),
                        int(upload),
                    ])
            except OSError:
                self.write_errors += 1
                log.warning("could not record camera frame %d", seq)
                if upload:
                    self._next_upload_t = t      # let the next frame take its slot
                return None
            frame = RecordedFrame(seq, t, at, name, content_type, upload)
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

    def after(self, seq: int, limit: int) -> list[RecordedFrame]:
        with self._lock:
            return self._frames[max(seq, 0):max(seq, 0) + limit]

    def path(self, frame: RecordedFrame) -> Path:
        return self.frames_dir / frame.file

    def summary(self) -> dict[str, Any]:
        latest = self.latest()
        return {
            "recording": True, "session_id": self.session_id, "count": self.count,
            "latest_seq": latest.seq if latest else 0,
            "latest_t_s": round(latest.t_s, 3) if latest else None,
            "upload_fps": round(1.0 / self._upload_every, 3),
            "write_errors": self.write_errors,
        }


class Recorder:
    """The agent-level switch: which session, if any, frames go to."""

    def __init__(self, outbox: Outbox, position: Position = lambda: None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._outbox = outbox
        self._position = position
        self._clock = clock
        self._lock = threading.Lock()
        self.current: FrameRecording | None = None

    def start(self, session_id: str, folder: Path) -> FrameRecording:
        recording = FrameRecording(session_id, folder, position=self._position,
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
