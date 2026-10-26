"""A session's camera frames: to disk first, read back from disk, uploaded from
a cursor. No camera and no cloud — both are faked here."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from dronedeck.camera.deck import DeckStream
from dronedeck.camera.recording import (
    COLUMNS,
    INDEX_NAME,
    FrameRecording,
    NotRecording,
    Recorder,
    frames_to_upload,
)
from dronedeck.sync.cloud import CloudError
from dronedeck.sync.outbox import Kind, Outbox
from dronedeck.sync.syncer import Syncer
from tests.test_camera_deck import image, reader
from tests.test_sync import FakeCloud


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def rows(folder: Path) -> list[dict[str, str]]:
    with (folder / INDEX_NAME).open(newline="") as f:
        return list(csv.DictReader(f))


class TestFrameRecording:
    def test_each_frame_is_a_file_and_an_index_row(self, tmp_path):
        rec = FrameRecording("s1", tmp_path, position=lambda: (0.1, -0.2, 0.5))
        rec.add(b"png-1", "image/png", 324, 244)
        rec.add(b"png-2", "image/png", 324, 244)
        assert (tmp_path / "frames" / "000001.png").read_bytes() == b"png-1"
        index = rows(tmp_path)
        assert list(index[0]) == COLUMNS
        assert [r["seq"] for r in index] == ["1", "2"]
        assert (index[0]["x_m"], index[0]["y_m"], index[0]["z_m"]) == ("0.100", "-0.200", "0.500")
        assert index[0]["width"] == "324" and index[0]["bytes"] == "5"

    def test_no_position_leaves_the_cells_empty_not_zero(self, tmp_path):
        """Zero is a place; an unknown position must not read as one."""
        rec = FrameRecording("s1", tmp_path)
        rec.add(b"x", "image/png", 2, 1)
        assert rows(tmp_path)[0]["x_m"] == ""

    def test_two_a_second_are_marked_for_upload_and_every_frame_is_kept(self, tmp_path):
        clock = Clock()
        rec = FrameRecording("s1", tmp_path, clock=clock)
        for _ in range(20):                      # 20 frames over 5 s, ~4 a second
            rec.add(b"x", "image/png", 2, 1)
            clock.t += 0.25
        marked = [r for r in rows(tmp_path) if r["upload"] == "1"]
        assert len(rows(tmp_path)) == 20
        assert len(marked) == 10                 # 2 a second for 5 s

    def test_a_stall_does_not_bunch_the_next_uploads(self, tmp_path):
        clock = Clock()
        rec = FrameRecording("s1", tmp_path, clock=clock)
        rec.add(b"x", "image/png", 2, 1)         # t=0: upload
        clock.t = 7.0                            # 7 s stall
        rec.add(b"x", "image/png", 2, 1)         # upload
        clock.t = 7.1
        rec.add(b"x", "image/png", 2, 1)         # too soon after the last pick
        assert [r["upload"] for r in rows(tmp_path)] == ["1", "1", "0"]

    def test_auto_capture_off_writes_nothing_but_manual_still_saves(self, tmp_path):
        auto = {"on": False}
        rec = FrameRecording("s1", tmp_path, auto=lambda: auto["on"])
        assert rec.add(b"x", "image/png", 2, 1) is None
        manual = rec.add_manual(b"by-hand", "image/png", 2, 1)
        assert manual is not None and manual.source == "manual" and manual.upload
        index = rows(tmp_path)
        assert [(r["source"], r["why"], r["upload"]) for r in index] == [("manual", "manual", "1")]
        auto["on"] = True                      # switched on mid-session: at once
        assert rec.add(b"y", "image/png", 2, 1) is not None
        assert rec.summary()["manual"] == 1 and rec.summary()["auto"] is True

    def test_manual_captures_are_never_paced(self, tmp_path):
        rec = FrameRecording("s1", tmp_path, clock=Clock())   # the clock never moves
        for _ in range(3):
            assert rec.add_manual(b"m", "image/png", 2, 1) is not None
        assert [r["upload"] for r in rows(tmp_path)] == ["1", "1", "1"]

    def test_the_index_says_why_and_by_how_much(self, tmp_path):
        import cv2
        import numpy as np
        clock = Clock()
        rec = FrameRecording("s1", tmp_path, clock=clock)

        def png(level: int) -> bytes:
            return cv2.imencode(".png", np.full((244, 324), level, np.uint8))[1].tobytes()

        rec.add(png(100), "image/png", 324, 244)
        clock.t = 1.0
        rec.add(png(160), "image/png", 324, 244)
        index = rows(tmp_path)
        assert [r["why"] for r in index] == ["first", "change"]
        assert float(index[1]["change"]) == 60.0 and index[0]["change"] == ""

    def test_after_filters_by_source(self, tmp_path):
        rec = FrameRecording("s1", tmp_path)
        rec.add(b"a", "image/png", 2, 1)
        rec.add_manual(b"m", "image/png", 2, 1)
        assert [f.seq for f in rec.after(0, 10, "manual")] == [2]
        assert [f.seq for f in rec.after(0, 10)] == [1, 2]

    def test_read_back_by_number_and_latest(self, tmp_path):
        rec = FrameRecording("s1", tmp_path)
        for n in range(3):
            rec.add(f"f{n}".encode(), "image/png", 2, 1)
        assert rec.latest().seq == 3
        assert rec.path(rec.get(2)).read_bytes() == b"f1"
        assert rec.get(0) is None and rec.get(4) is None
        assert [f.seq for f in rec.after(1, 10)] == [2, 3]

    def test_a_disk_that_refuses_a_frame_does_not_stop_the_recording(self, tmp_path):
        rec = FrameRecording("s1", tmp_path)
        (tmp_path / "frames").chmod(0o500)
        try:
            assert rec.add(b"x", "image/png", 2, 1) is None
        finally:
            (tmp_path / "frames").chmod(0o700)
        assert rec.write_errors == 1
        assert rec.add(b"y", "image/png", 2, 1) is not None


class TestRecorder:
    def test_frames_only_go_to_disk_inside_a_session(self, tmp_path):
        recorder = Recorder(Outbox(tmp_path / "outbox"))
        recorder.on_frame(b"standby", "image/png", 2, 1)      # no session: shown, not kept
        recording = recorder.start("s1", tmp_path / "s1")
        recorder.on_frame(b"in-session", "image/png", 2, 1)
        recorder.stop()
        recorder.on_frame(b"after", "image/png", 2, 1)
        assert recording.count == 1

    def test_a_capture_by_hand_needs_a_session(self, tmp_path):
        recorder = Recorder(Outbox(tmp_path / "outbox"))
        with pytest.raises(NotRecording, match="Start a session"):
            recorder.capture_manual(b"x", "image/png", 2, 1)
        recording = recorder.start("s1", tmp_path / "s1")
        frame = recorder.capture_manual(b"x", "image/png", 2, 1)
        assert frame.source == "manual" and recording.count == 1

    def test_the_session_switch_reaches_the_recording(self, tmp_path):
        auto = {"on": True}
        recorder = Recorder(Outbox(tmp_path / "outbox"), auto=lambda: auto["on"])
        recording = recorder.start("s1", tmp_path / "s1")
        recorder.on_frame(b"x", "image/png", 2, 1)
        auto["on"] = False
        recorder.on_frame(b"y", "image/png", 2, 1)
        assert recording.count == 1

    def test_the_outbox_holds_one_record_for_the_session(self, tmp_path):
        outbox = Outbox(tmp_path / "outbox")
        recorder = Recorder(outbox)
        recorder.start("s1", tmp_path / "s1")
        for _ in range(5):
            recorder.on_frame(b"x", "image/png", 2, 1)
        recorder.stop()
        records = list(outbox.pending(Kind.FRAMES))
        assert [r.id for r in records] == ["s1"]
        assert records[0].payload["ended"] is True
        assert records[0].payload["count"] == 5

    def test_a_deck_stream_feeds_it(self, tmp_path):
        recorder = Recorder(Outbox(tmp_path / "outbox"))
        recording = recorder.start("s1", tmp_path / "s1")
        stream = DeckStream(start=False)
        stream.add_listener(recorder.on_frame)
        stream.pump(reader(image(4, 2, b"abcdefgh")))
        assert recording.count == 1
        assert recording.path(recording.latest()).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


class FrameCloud(FakeCloud):
    def __init__(self) -> None:
        super().__init__()
        self.uploaded: list[str] = []
        self.fail_after: int | None = None

    def upload_frame(self, object_path, path, content_type, *, replace=False):
        if self.fail_after is not None and len(self.uploaded) >= self.fail_after:
            raise CloudError("offline")
        self.uploaded.append(object_path)


def recorded(tmp_path, n: int, *, end: bool) -> tuple[Outbox, Path]:
    outbox = Outbox(tmp_path / "outbox")
    clock = Clock()
    recorder = Recorder(outbox, clock=clock)
    folder = tmp_path / "s1"
    recorder.start("s1", folder)
    for _ in range(n):
        recorder.on_frame(b"x", "image/png", 2, 1)
        clock.t += 0.5                           # every frame is an upload pick
    if end:
        recorder.stop()
    return outbox, folder


class TestUpload:
    def test_marked_frames_then_the_index_at_the_end(self, tmp_path):
        outbox, _ = recorded(tmp_path, 3, end=True)
        cloud = FrameCloud()
        Syncer(outbox, lambda: cloud)._send_frames(cloud)
        assert cloud.uploaded == ["s1/frames/000001.png", "s1/frames/000002.png",
                                  "s1/frames/000003.png", "s1/frames.csv"]
        assert list(outbox.pending(Kind.FRAMES)) == []

    def test_an_open_session_uploads_what_it_has_and_keeps_its_record(self, tmp_path):
        outbox, _ = recorded(tmp_path, 2, end=False)
        cloud = FrameCloud()
        Syncer(outbox, lambda: cloud)._send_frames(cloud)
        assert "s1/frames.csv" not in cloud.uploaded
        assert outbox.get(Kind.FRAMES, "s1")["uploaded_through"] == 2

    def test_an_interrupted_upload_resumes_where_it_stopped(self, tmp_path):
        outbox, _ = recorded(tmp_path, 4, end=True)
        cloud = FrameCloud()
        cloud.fail_after = 2
        with pytest.raises(CloudError):
            Syncer(outbox, lambda: cloud)._send_frames(cloud)
        assert outbox.get(Kind.FRAMES, "s1")["uploaded_through"] == 2
        cloud.fail_after = None
        Syncer(outbox, lambda: cloud)._send_frames(cloud)
        # Frames 1 and 2 were not sent twice.
        assert cloud.uploaded.count("s1/frames/000001.png") == 1
        assert cloud.uploaded[-1] == "s1/frames.csv"

    def test_the_cursor_reads_the_index_on_disk(self, tmp_path):
        _, folder = recorded(tmp_path, 3, end=True)
        assert [seq for seq, _, _ in frames_to_upload(folder, 1)] == [2, 3]
