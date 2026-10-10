"""The enhancer (stages/enhance/espcn.py) against dpp-enhance's acceptance
criteria. The contract's own rules run in test_conformance.py; these are the
ones particular to enhancing frames."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from cropwatcher.pipeline.contracts import (
    FlightContext,
    InspectionPoint,
    PointData,
    StageError,
)
from cropwatcher.pipeline.sources import LocalFlightSource
from cropwatcher.pipeline.stages.enhance import espcn
from cropwatcher.pipeline.stages.enhance.espcn import METHOD, EspcnEnhancer

FIXTURE = Path(__file__).parent / "fixtures" / "data"
MODELS = espcn.MODELS


@pytest.fixture(scope="module")
def flight():
    return LocalFlightSource(FIXTURE).load("372bbdc4-d323-42bb-9e6c-29ef02e3794c")


@pytest.fixture
def ctx(tmp_path, flight) -> FlightContext:
    return FlightContext(flight_id=flight.flight_id, session_id=flight.session_id,
                         temp_unit=flight.temp_unit, ground_z_m=None,
                         started_at=flight.started_at, workdir=tmp_path / "work")


@pytest.fixture
def point(flight) -> PointData:
    """Every frame of the fixture flight as one point."""
    frames = tuple(f for p in flight.points for f in p.frames)
    assert len(frames) >= 3
    return PointData(InspectionPoint("ALL", None, 0, 0, 0.4), (), frames)


def read(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)
    assert img is not None
    return img


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestOutput:
    def test_every_frame_is_enhanced_to_twice_its_size_in_8_bit_gray(self, point, ctx):
        result = EspcnEnhancer().enhance(point, ctx)
        assert [f.frame for f in result.frames] == list(point.frames)
        for f in result.frames:
            assert f.path == ctx.workdir / "enhanced" / f"{f.frame.seq:06d}.png"
            assert (f.method, f.scale, f.note) == (METHOD, 2, None)
            original, enhanced = read(f.frame.path), read(f.path)
            assert enhanced.dtype == np.uint8 and enhanced.ndim == 2
            assert enhanced.shape == (original.shape[0] * 2, original.shape[1] * 2)

    def test_the_originals_are_byte_identical_afterwards(self, point, ctx):
        before = [sha(f.path) for f in point.frames]
        EspcnEnhancer().enhance(point, ctx)
        assert [sha(f.path) for f in point.frames] == before

    def test_the_same_frames_give_the_same_bytes(self, point, ctx, tmp_path):
        first = [sha(f.path) for f in EspcnEnhancer().enhance(point, ctx).frames
                 if f.path is not None]
        again_ctx = dataclasses.replace(ctx, workdir=tmp_path / "again")
        again = [sha(f.path) for f in EspcnEnhancer().enhance(point, again_ctx).frames
                 if f.path is not None]
        assert first and first == again

    def test_the_method_is_what_the_evaluation_chose(self):
        assert METHOD == "espcn-x2+clahe-1.5+edge-0.6"


class TestFailingSmall:
    def test_no_frames_is_an_empty_result_and_needs_no_model(self, ctx, tmp_path):
        empty = PointData(InspectionPoint("EMPTY", None, 0, 0, 0.4), (), ())
        assert EspcnEnhancer(models=tmp_path / "nowhere").enhance(empty, ctx).frames == ()

    @pytest.mark.parametrize("damage", ["corrupt", "missing"])
    def test_a_bad_frame_gets_a_note_and_the_rest_are_enhanced(self, point, ctx, tmp_path,
                                                               damage):
        bad = tmp_path / "bad.png"
        if damage == "corrupt":
            bad.write_bytes(b"not a png")
        frames = list(point.frames)
        frames[1] = dataclasses.replace(frames[1], path=bad)
        data = dataclasses.replace(point, frames=tuple(frames))

        result = EspcnEnhancer().enhance(data, ctx).frames
        assert len(result) == len(frames)
        assert result[1].path is None and result[1].note
        assert (result[1].method, result[1].scale) == ("identity", 1)
        assert all(f.path is not None for i, f in enumerate(result) if i != 1)

    def test_a_missing_model_stops_the_stage(self, point, ctx, tmp_path):
        with pytest.raises(StageError, match="missing"):
            EspcnEnhancer(models=tmp_path).enhance(point, ctx)

    def test_a_model_that_is_not_the_one_in_MODELS_json_stops_the_stage(self, point, ctx,
                                                                         tmp_path):
        shutil.copy(MODELS / "MODELS.json", tmp_path / "MODELS.json")
        (tmp_path / espcn.MODEL_FILE).write_bytes(b"something else")
        with pytest.raises(StageError, match="sha256"):
            EspcnEnhancer(models=tmp_path).enhance(point, ctx)


class TestModelsJson:
    """dpp-contract, MODEL FILES: every model file has a complete entry, under 20 MB."""

    def entries(self) -> list[dict[str, str]]:
        return list(json.loads((MODELS / "MODELS.json").read_text()))

    def test_every_entry_is_complete_and_matches_its_file(self):
        for entry in self.entries():
            for key in ("name", "version", "file", "sha256", "source", "license"):
                assert entry.get(key), f"{entry.get('file')}: no {key}"
            path = MODELS / entry["file"]
            assert sha(path) == entry["sha256"]
            assert path.stat().st_size < 20e6

    def test_every_model_file_has_an_entry(self):
        named = {e["file"] for e in self.entries()}
        files = {p.name for p in MODELS.iterdir() if p.is_file() and p.name != "MODELS.json"}
        assert files <= named
