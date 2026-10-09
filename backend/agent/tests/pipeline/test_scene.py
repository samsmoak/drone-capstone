"""scene@1 — whether the camera's view changed (stages/classify/scene.py), and
how a finding uses it: a change inside the stretch supports it; a steady view
cannot tell; nothing ever contradicts a reading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from cropwatcher.pipeline.contracts import (
    ClassifyResult,
    EnhancedFrame,
    EnhanceResult,
    Event,
    Frame,
    Label,
)
from cropwatcher.pipeline.stages.classify import scene
from cropwatcher.pipeline.stages.interpret.findings import _frames

T0 = datetime(2026, 10, 9, 18, 0, tzinfo=UTC)


def scenery(seed: int = 1) -> np.ndarray:
    """A textured grayscale view: blurred noise, like a room at 324 × 244."""
    rng = np.random.default_rng(seed)
    base = rng.random((244, 324)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 6)
    base = (base - base.min()) / (base.max() - base.min())
    return (base * 180 + 30).astype(np.uint8)


def frame(tmp: Path, seq: int, img: np.ndarray, t: float, x: float = 0.0) -> EnhancedFrame:
    path = tmp / f"{seq:06d}.png"
    cv2.imwrite(str(path), img)
    f = Frame(seq, T0 + timedelta(seconds=t), t, path, 324, 244, x, 0.0, 1.0)
    return EnhancedFrame(f, None, "identity", 1)


def shifted(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    return np.roll(np.roll(img, dy, axis=0), dx, axis=1)


def occluded(img: np.ndarray, share: float = 0.3) -> np.ndarray:
    out = img.copy()
    h, w = out.shape
    cw, ch = int(w * share ** 0.5), int(h * share ** 0.5)
    out[h - ch:, (w - cw) // 2:(w - cw) // 2 + cw] = 12
    return out


class TestTheMeasure:
    def test_the_same_view_held_steady(self, tmp_path):
        img = scenery()
        views = scene.measure([frame(tmp_path, 1, img, 0.0), frame(tmp_path, 2, img, 0.5)])
        assert views[0].score is None and "nothing earlier" in views[0].note
        assert views[1].score == pytest.approx(0.0, abs=1e-3)
        assert not views[1].changed and views[1].against == 1

    def test_a_drone_turning_a_little_is_not_a_change(self, tmp_path):
        img = scenery()
        views = scene.measure([frame(tmp_path, 1, img, 0.0),
                               frame(tmp_path, 2, shifted(img, 12, -6), 0.5)])
        assert views[1].score is not None and not views[1].changed

    def test_someone_stepping_in_front_is_a_change(self, tmp_path):
        img = scenery()
        views = scene.measure([frame(tmp_path, 1, img, 0.0),
                               frame(tmp_path, 2, occluded(img), 0.5)])
        assert views[1].changed and views[1].score >= scene.SCENE_CHANGE

    def test_the_cameras_own_exposure_is_not_a_change(self, tmp_path):
        img = scenery()
        brighter = np.clip(img.astype(np.float32) * 1.25, 0, 255).astype(np.uint8)
        views = scene.measure([frame(tmp_path, 1, img, 0.0), frame(tmp_path, 2, brighter, 0.5)])
        assert not views[1].changed

    def test_a_drone_that_moved_is_not_compared(self, tmp_path):
        img = scenery()
        views = scene.measure([frame(tmp_path, 1, img, 0.0),
                               frame(tmp_path, 2, occluded(img), 0.5, x=0.4)])
        assert views[1].score is None and "moved 40 cm" in views[1].note

    def test_frames_too_far_apart_in_time_are_not_compared(self, tmp_path):
        img = scenery()
        views = scene.measure([frame(tmp_path, 1, img, 0.0), frame(tmp_path, 2, img, 9.0)])
        assert views[1].score is None


def event(t0: float, t1: float) -> Event:
    return Event("temperature", "C", 10, 50, t0, t1, "rise", 31.0, 29.0, 2.0, 40.0, 2.5, 0.1,
                 (), 0.0, 0.0, 1.0)


def classified(views) -> ClassifyResult:
    from cropwatcher.pipeline.contracts import ImageVerdict

    unknown = Label("unknown", None, "blocks@1", "no image model yet")
    return ClassifyResult(tuple(ImageVerdict(v.seq, "original", unknown) for v in views),
                          Label("faulty", None, "blocks@1"), views=tuple(views))


class TestWhatAFindingSays:
    def test_a_change_inside_the_stretch_supports_it(self, tmp_path):
        img = scenery()
        frames = [frame(tmp_path, 1, img, 1.0), frame(tmp_path, 2, img, 1.5),
                  frame(tmp_path, 3, occluded(img), 2.0)]
        views = scene.measure(frames)
        seqs, support, note = _frames(event(1.5, 4.0), EnhanceResult(tuple(frames)),
                                      classified(views))
        assert support == "supports" and seqs == (1, 2, 3)
        assert "frame 3" in note and "Look at the frames" in note

    def test_a_steady_view_cannot_tell_and_never_contradicts(self, tmp_path):
        img = scenery()
        frames = [frame(tmp_path, 1, img, 1.0), frame(tmp_path, 2, img, 1.5)]
        views = scene.measure(frames)
        _, support, note = _frames(event(1.0, 3.0), EnhanceResult(tuple(frames)),
                                   classified(views))
        assert support == "cannot_tell"
        assert "held steady" in note and "does not see heat" in note

    def test_a_moving_drone_cannot_tell_either(self, tmp_path):
        img = scenery()
        frames = [frame(tmp_path, 1, img, 1.0), frame(tmp_path, 2, occluded(img), 1.5, x=0.5)]
        views = scene.measure(frames)
        _, support, note = _frames(event(1.0, 3.0), EnhanceResult(tuple(frames)),
                                   classified(views))
        assert support == "cannot_tell" and "could not be compared" in note
