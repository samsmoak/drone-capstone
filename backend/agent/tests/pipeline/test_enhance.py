"""The enhancer (stage 2, story 4.3), clahe@1: a clearer copy of every frame,
the original untouched, and each frame's quality measured on the original.

The contract's own rules (one per frame, in order, files only in the workdir,
originals byte-identical, deterministic) run in test_conformance.py; these are
the enhancer's."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from cropwatcher.pipeline.contracts import FlightContext, Frame, InspectionPoint, PointData
from cropwatcher.pipeline.stages.enhance.clahe import (
    MIN_BRIGHTNESS,
    MIN_SHARPNESS,
    ClaheEnhancer,
    measure_quality,
)

START = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)


def scene(seed: int = 0) -> np.ndarray:
    """A dark, low-contrast frame with edges in it, like the lab's."""
    rng = np.random.default_rng(seed)
    img = np.full((244, 324), 55, np.uint8)
    img[60:180, 40:280] = 68
    img[100:140, 120:200] = 48
    noise = rng.normal(0, 2.0, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def frames_of(tmp_path: Path, images: list[np.ndarray]) -> PointData:
    folder = tmp_path / "frames"
    folder.mkdir()
    frames = []
    for seq, img in enumerate(images, start=1):
        path = folder / f"{seq:06d}.png"
        cv2.imwrite(str(path), img)
        frames.append(Frame(seq, START, seq * 0.5, path, 324, 244, None, None, None))
    return PointData(InspectionPoint("flight", None, 0, 0, 0), (), tuple(frames))


def ctx(tmp_path: Path) -> FlightContext:
    return FlightContext("f", None, "C", None, START, tmp_path / "work")


def test_every_frame_gets_an_enhanced_copy_with_more_contrast(tmp_path):
    data = frames_of(tmp_path, [scene(0), scene(1)])
    result = ClaheEnhancer().enhance(data, ctx(tmp_path))
    for e in result.frames:
        assert e.path == tmp_path / "work" / "enhanced" / f"{e.frame.seq:06d}.png"
        assert (e.method, e.scale) == ("clahe", 1)
        original = cv2.imread(str(e.frame.path), cv2.IMREAD_GRAYSCALE)
        enhanced = cv2.imread(str(e.path), cv2.IMREAD_GRAYSCALE)
        assert enhanced.shape == original.shape            # grayscale in, grayscale out
        assert enhanced.std() > original.std()


def test_the_original_is_byte_identical_after(tmp_path):
    data = frames_of(tmp_path, [scene()])
    before = hashlib.sha256(data.frames[0].path.read_bytes()).hexdigest()
    ClaheEnhancer().enhance(data, ctx(tmp_path))
    assert hashlib.sha256(data.frames[0].path.read_bytes()).hexdigest() == before


def test_an_unreadable_frame_says_so_and_the_rest_carry_on(tmp_path):
    data = frames_of(tmp_path, [scene(), scene(1)])
    data.frames[0].path.write_bytes(b"not a png")
    first, second = ClaheEnhancer().enhance(data, ctx(tmp_path)).frames
    assert first.path is None and first.note and "could not be read" in first.note
    assert second.path is not None and second.quality is not None


def test_no_frames_is_an_empty_result(tmp_path):
    empty = PointData(InspectionPoint("flight", None, 0, 0, 0), (), ())
    assert ClaheEnhancer().enhance(empty, ctx(tmp_path)).frames == ()


def test_a_readable_scene_is_usable():
    quality = measure_quality(scene())
    assert quality.usable and quality.reason is None
    assert quality.sharpness >= MIN_SHARPNESS and quality.brightness >= MIN_BRIGHTNESS


@pytest.mark.parametrize(("image", "words"), [
    (np.zeros((244, 324), np.uint8), "too dark"),
    (np.full((244, 324), 255, np.uint8), "overexposed"),
    (np.full((244, 324), 90, np.uint8), "blurred"),        # nothing in it: no edges
])
def test_an_unreadable_frame_is_marked_unusable_with_why(image, words):
    quality = measure_quality(image)
    assert not quality.usable
    assert quality.reason and words in quality.reason


def test_quality_is_measured_on_the_original_not_the_copy(tmp_path):
    data = frames_of(tmp_path, [np.zeros((244, 324), np.uint8)])
    (e,) = ClaheEnhancer().enhance(data, ctx(tmp_path)).frames
    assert e.quality is not None and not e.quality.usable
