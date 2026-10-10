"""The image model (stage 3, story 4.4): image.py and how the classifiers use it.

A real model needs labelled photos that do not exist yet, so these run a TINY
ONNX model built here — brighter frame, higher p_faulty — which exercises
everything except the learning: loading, the sha256 check, the input contract,
the threshold, and "fail small, say why".
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper  # noqa: E402

from cropwatcher.pipeline.contracts import (  # noqa: E402
    CleanResult,
    EnhancedFrame,
    EnhanceResult,
    FlightContext,
    Frame,
    FrameQuality,
    InspectionPoint,
    PointData,
    StageError,
)
from cropwatcher.pipeline.stages.classify.blocks import BlocksClassifier  # noqa: E402
from cropwatcher.pipeline.stages.classify.ground import GroundClassifier  # noqa: E402
from cropwatcher.pipeline.stages.classify.image import (  # noqa: E402
    CAMERA,
    ImageModel,
    ModelSpec,
    load_image_model,
    to_model_input,
)

START = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
ML_PREPROCESS = (Path(__file__).resolve().parents[4] / "ml" / "image-classifier"
                 / "preprocess.py")


def tiny_model(path: Path, *, side: int = 224, outputs: int = 2) -> str:
    """Logits [-m, m] x 4 with m the mean of the (normalised) input: a brighter
    frame is more faulty. Returns the file's sha256."""
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, side, side])
    y = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, outputs])
    nodes = [
        helper.make_node("ReduceMean", ["input"], ["m4"], axes=[1, 2, 3], keepdims=1),
        helper.make_node("Reshape", ["m4", "shape"], ["m"]),
        helper.make_node("Neg", ["m"], ["nm"]),
        helper.make_node("Concat", ["nm", "m"], ["pair"], axis=1),
        helper.make_node("Mul", ["pair", "gain"], ["logits"]),
    ]
    inits = [helper.make_tensor("shape", TensorProto.INT64, [2], [1, 1]),
             helper.make_tensor("gain", TensorProto.FLOAT, [1], [4.0])]
    graph = helper.make_graph(nodes, "tiny", [x], [y], inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_frame(path: Path, level: int) -> Path:
    ok, buf = cv2.imencode(".png", np.full((CAMERA[1], CAMERA[0]), level, np.uint8))
    assert ok
    buf.tofile(str(path))
    return path


def frame(seq: int, path: Path) -> Frame:
    return Frame(seq, START, float(seq), path, CAMERA[0], CAMERA[1], None, None, None)


def enhanced(f: Frame, *, usable: bool = True, path: Path | None = None) -> EnhancedFrame:
    q = FrameQuality(50.0, 100.0, 0.0, 0.0, usable, None if usable else "blurred")
    return EnhancedFrame(f, path, "identity", 1, quality=q)


@pytest.fixture
def models(tmp_path) -> Path:
    d = tmp_path / "models"
    d.mkdir()
    return d


@pytest.fixture
def spec(models) -> ModelSpec:
    sha = tiny_model(models / "tiny.onnx")
    return ModelSpec("tiny-brightness", "1", "tiny.onnx", sha, threshold=0.5)


# ── the model ────────────────────────────────────────────────────────────


def test_a_bright_frame_is_faulty_and_a_dark_one_is_normal(spec, models, tmp_path):
    model = ImageModel(spec, models)
    bright = model.label(enhanced(frame(1, write_frame(tmp_path / "b.png", 220))))
    dark = model.label(enhanced(frame(2, write_frame(tmp_path / "d.png", 30))))
    assert bright.label.value == "faulty" and bright.label.p_faulty > 0.5
    assert dark.label.value == "normal" and dark.label.p_faulty < 0.5
    assert bright.label.model == "tiny-brightness@1"
    assert (bright.seq, dark.seq) == (1, 2)


def test_the_threshold_decides_the_label(spec, models, tmp_path):
    f = enhanced(frame(1, write_frame(tmp_path / "f.png", 220)))
    strict = ImageModel(replace(spec, threshold=0.9999999), models)
    assert strict.label(f).label.value == "normal"


def test_the_same_frame_gives_the_same_p_faulty(spec, models, tmp_path):
    f = enhanced(frame(1, write_frame(tmp_path / "f.png", 150)))
    assert ImageModel(spec, models).label(f) == ImageModel(spec, models).label(f)


def test_a_missing_file_is_unknown_with_the_reason_not_an_exception(spec, models, tmp_path):
    (models / "tiny.onnx").unlink()
    v = ImageModel(spec, models).label(enhanced(frame(1, write_frame(tmp_path / "f.png", 90))))
    assert v.label.value == "unknown" and "missing" in v.label.reason


def test_a_changed_file_fails_its_sha256(spec, models, tmp_path):
    bad = replace(spec, sha256="0" * 64)
    v = ImageModel(bad, models).label(enhanced(frame(1, write_frame(tmp_path / "f.png", 90))))
    assert v.label.value == "unknown" and "sha256" in v.label.reason


@pytest.mark.parametrize("kwargs, why", [({"side": 112}, "input"), ({"outputs": 3}, "output")])
def test_a_model_with_the_wrong_shape_is_refused(models, tmp_path, kwargs, why):
    sha = tiny_model(models / "odd.onnx", **kwargs)
    odd = ModelSpec("odd", "1", "odd.onnx", sha)
    v = ImageModel(odd, models).label(enhanced(frame(1, write_frame(tmp_path / "f.png", 90))))
    assert v.label.value == "unknown" and why in v.label.reason


def test_an_unreadable_frame_is_unknown_and_the_next_one_still_labelled(spec, models, tmp_path):
    model = ImageModel(spec, models)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    v = model.label(enhanced(frame(1, broken)))
    assert v.label.value == "unknown" and v.label.reason == "frame unreadable"
    assert model.label(enhanced(frame(2, write_frame(tmp_path / "g.png", 220)))
                       ).label.value == "faulty"


def test_the_enhanced_copy_is_read_only_when_the_entry_says_so(spec, models, tmp_path):
    f = frame(1, write_frame(tmp_path / "orig.png", 30))            # dark original
    copy = write_frame(tmp_path / "copy.png", 220)                  # bright enhanced
    on_enhanced = ImageModel(replace(spec, frames="enhanced"), models)
    v = on_enhanced.label(enhanced(f, path=copy))
    assert v.label.value == "faulty" and v.source == "enhanced"
    assert ImageModel(spec, models).label(enhanced(f, path=copy)).label.value == "normal"
    missing = on_enhanced.label(enhanced(f, path=None))
    assert missing.label.value == "unknown" and "enhanced copy" in missing.label.reason


# ── the input contract ───────────────────────────────────────────────────


def test_the_input_is_1x3x224x224_float32_and_the_channels_agree():
    x = to_model_input(np.random.default_rng(0).integers(0, 256, (244, 324), dtype=np.uint8))
    assert x.shape == (1, 3, 224, 224) and x.dtype == np.float32
    assert np.array_equal(x[0, 0], x[0, 1]) and np.array_equal(x[0, 1], x[0, 2])


def test_the_stage_and_the_training_script_prepare_a_frame_identically():
    """Train/serve skew is silent and costs accuracy: hold the two together."""
    if not ML_PREPROCESS.is_file():
        pytest.skip("ml/image-classifier/preprocess.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("ml_preprocess", ML_PREPROCESS)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    img = np.random.default_rng(1).integers(0, 256, (244, 324), dtype=np.uint8)
    assert np.array_equal(to_model_input(img), mod.to_model_input(img))
    assert (mod.CAMERA, mod.MODEL_SIDE, mod.MEAN, mod.STD) == (
        CAMERA, 224, 0.449, 0.226)


# ── MODELS.json ──────────────────────────────────────────────────────────


def test_no_entry_means_no_model(models):
    (models / "MODELS.json").write_text("[]", encoding="utf-8")
    assert load_image_model(models) is None


def test_the_shipped_manifest_is_consistent():
    """Whatever MODELS.json lists must load: file present, sha256 right, shapes right.
    (It lists none today, and then there is nothing to check.)"""
    model = load_image_model()
    if model is not None:
        assert model._ready() is None


def test_an_entry_is_loaded_with_its_threshold(spec, models):
    entry = {"stage": "classify.image", "name": spec.name, "version": spec.version,
             "file": spec.file, "sha256": spec.sha256, "threshold": 0.7, "frames": "enhanced"}
    (models / "MODELS.json").write_text(json.dumps([entry]), encoding="utf-8")
    m = load_image_model(models)
    assert m is not None and m.spec.threshold == 0.7 and m.spec.frames == "enhanced"


def test_two_image_models_are_an_error(models):
    entry = {"stage": "classify.image", "name": "a", "version": "1", "file": "a", "sha256": "x"}
    (models / "MODELS.json").write_text(json.dumps([entry, entry]), encoding="utf-8")
    with pytest.raises(StageError):
        load_image_model(models)


# ── in the classifiers ───────────────────────────────────────────────────


def point(frames: tuple[Frame, ...]) -> PointData:
    return PointData(InspectionPoint("EMPTY", None, 0, 0, 0.4), (), frames)


@pytest.mark.parametrize("cls", [BlocksClassifier, GroundClassifier])
class TestInTheClassifiers:
    def run(self, cls, model, tmp_path, levels, unusable=()):
        frames = tuple(frame(i + 1, write_frame(tmp_path / f"{i}.png", lv))
                       for i, lv in enumerate(levels))
        ef = EnhanceResult(tuple(enhanced(f, usable=f.seq not in unusable) for f in frames))
        ctx = FlightContext("f", None, "C", None, START, tmp_path / "work")
        data = point(frames)
        return cls(model).classify(data, CleanResult((), ()), ef, ctx)

    def test_without_a_model_every_frame_is_unknown_no_image_model_yet(self, cls, tmp_path):
        r = self.run(cls, None, tmp_path, [220, 30])
        assert [v.label.reason for v in r.images] == ["no image model yet"] * 2

    def test_with_a_model_frames_are_labelled_in_order(self, cls, spec, models, tmp_path):
        r = self.run(cls, ImageModel(spec, models), tmp_path, [220, 30, 220])
        assert [v.seq for v in r.images] == [1, 2, 3]
        assert [v.label.value for v in r.images] == ["faulty", "normal", "faulty"]

    def test_an_unusable_frame_never_reaches_the_model(self, cls, spec, models, tmp_path):
        r = self.run(cls, ImageModel(spec, models), tmp_path, [220, 220], unusable={2})
        assert r.images[0].label.value == "faulty"
        assert r.images[1].label.value == "unknown"
        assert "unusable" in r.images[1].label.reason

    def test_a_broken_model_costs_the_frames_not_the_stage(self, cls, spec, models, tmp_path):
        (models / "tiny.onnx").unlink()
        r = self.run(cls, ImageModel(spec, models), tmp_path, [220])
        assert r.images[0].label.value == "unknown"
        assert r.sensors.reason          # the sensors still speak for themselves

    def test_the_version_names_the_model_only_when_there_is_one(self, cls, spec, models):
        assert cls().version == "1"
        assert cls(ImageModel(spec, models)).version == "1+tiny-brightness@1"
