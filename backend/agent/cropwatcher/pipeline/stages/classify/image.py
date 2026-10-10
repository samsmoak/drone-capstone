"""The image model — stage 3, story 4.4: is what the camera saw faulty?

AN ONNX FILE, listed in pipeline/models/MODELS.json with `"stage":
"classify.image"`, trained in ml/image-classifier/. With no such entry
`load_image_model()` returns None and every frame stays "unknown — no image
model yet": a stage that guessed would write confident nonsense into every
result (stub.py).

WHAT "FAULTY" MEANS is written in docs/features/pipeline/classify.txt, and is
the dataset's definition, not this file's.

THE INPUT CONTRACT is the model's, and `to_model_input` must stay identical to
ml/image-classifier/preprocess.py (a test holds them together): the frame as
the camera delivers it — 324 × 244, 8-bit grayscale — squashed to 224 × 224,
normalised, the one channel repeated three times. A model trained on anything
else would be wrong here by construction. OUTPUT: 1 × 2 logits, [normal,
faulty]; p_faulty is the softmax of the second, and the label is faulty at or
above the entry's `threshold`.

THE ENTRY'S `frames` says which image the model was trained on: "original"
(default) or "enhanced" (clahe@1's copy). A model never reads the other one.

FAIL SMALL, SAY WHY. A frame the model cannot label — unreadable, a bad file,
a model that failed to load — is "unknown" with the reason, and the sensors'
analysis goes on without it. Nothing here raises into the runner.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from cropwatcher.pipeline.contracts import (
    EnhancedFrame,
    ImageVerdict,
    Label,
    LabelValue,
    StageError,
)

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
STAGE = "classify.image"

#: The camera's frame, (width, height) — every frame is brought to this first.
CAMERA = (324, 244)
#: The model's input side, px.
MODEL_SIDE = 224
#: The backbone's pretraining statistics, applied to the gray value.
MEAN, STD = 0.449, 0.226

Gray = NDArray[np.uint8]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    version: str
    file: str
    sha256: str
    threshold: float = 0.5
    frames: str = "original"            # "original" | "enhanced"

    @property
    def tag(self) -> str:
        return f"{self.name}@{self.version}"


def to_model_input(frame: Gray) -> NDArray[np.float32]:
    """1 × 3 × 224 × 224 float32 from a 324 × 244 gray frame."""
    camera = frame
    if (frame.shape[1], frame.shape[0]) != CAMERA:
        camera = np.asarray(cv2.resize(frame, CAMERA, interpolation=cv2.INTER_AREA),
                            dtype=np.uint8)
    square = cv2.resize(camera, (MODEL_SIDE, MODEL_SIDE), interpolation=cv2.INTER_AREA)
    x = (square.astype(np.float32) / 255.0 - MEAN) / STD
    return np.repeat(x[None, None, :, :], 3, axis=1).astype(np.float32)


def _read_gray(path: Path) -> Gray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    return None if image is None else np.asarray(image, dtype=np.uint8)


class ImageModel:
    """One ONNX image classifier. Loaded on first use, once; a model that will
    not load is remembered, and every frame then says why."""

    def __init__(self, spec: ModelSpec, models_dir: Path = MODELS_DIR) -> None:
        self.spec = spec
        self._path = models_dir / spec.file
        self._session: Any = None
        self._input = ""
        self._error: str | None = None

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def version(self) -> str:
        return self.spec.version

    def _load(self) -> None:
        """Raises StageError with words for the operator."""
        if not self._path.is_file():
            raise StageError(f"image model file {self.spec.file} is missing")
        digest = hashlib.sha256(self._path.read_bytes()).hexdigest()
        if digest != self.spec.sha256:
            raise StageError(f"image model file {self.spec.file} does not match its "
                             "sha256 in MODELS.json")
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 1          # the same input, the same output
            session = ort.InferenceSession(str(self._path), options,
                                           providers=["CPUExecutionProvider"])
        except Exception as e:  # noqa: BLE001 — any load failure is the same to the operator
            raise StageError(f"image model {self.spec.tag} could not be loaded: {e}") from e
        shape = session.get_inputs()[0].shape
        if list(shape[1:]) != [3, MODEL_SIDE, MODEL_SIDE]:
            raise StageError(f"image model {self.spec.tag} takes input {shape}, "
                             f"not 1x3x{MODEL_SIDE}x{MODEL_SIDE}")
        out = session.get_outputs()[0].shape
        if not out or out[-1] != 2:
            raise StageError(f"image model {self.spec.tag} gives output {out}, "
                             "not 1x2 logits [normal, faulty]")
        self._session = session
        self._input = session.get_inputs()[0].name

    def _ready(self) -> str | None:
        """None when the model is loaded, else why it is not."""
        if self._session is not None:
            return None
        if self._error is None:
            try:
                self._load()
            except StageError as e:
                self._error = str(e)
                log.warning("image model unavailable: %s", e)
        return self._error

    def p_faulty(self, frame: Gray) -> float:
        why = self._ready()
        if why is not None:
            raise StageError(why)
        logits = np.asarray(self._session.run(None, {self._input: to_model_input(frame)})[0],
                            dtype=np.float64).reshape(-1)
        shifted = logits - logits.max()
        p = np.exp(shifted) / np.exp(shifted).sum()
        return float(p[1])

    def label(self, e: EnhancedFrame) -> ImageVerdict:
        """One verdict for one frame; never raises."""
        tag = self.spec.tag
        enhanced = self.spec.frames == "enhanced"
        source: Literal["original", "enhanced"] = "enhanced" if enhanced else "original"

        def unknown(reason: str) -> ImageVerdict:
            return ImageVerdict(e.frame.seq, "original", Label("unknown", None, tag, reason))

        path = e.path if enhanced else e.frame.path
        if path is None:
            return unknown("the enhanced copy this model reads is missing")
        gray = _read_gray(path)
        if gray is None:
            return unknown("frame unreadable")
        try:
            p = self.p_faulty(gray)
        except StageError as err:
            return unknown(str(err))
        except Exception as err:  # noqa: BLE001 — one bad frame must not stop the rest
            log.warning("image model failed on frame %d: %s", e.frame.seq, err)
            return unknown(f"the image model failed on this frame: {err}")
        value: LabelValue = "faulty" if p >= self.spec.threshold else "normal"
        return ImageVerdict(e.frame.seq, source, Label(value, round(p, 4), tag))


def load_image_model(models_dir: Path = MODELS_DIR) -> ImageModel | None:
    """The image model listed in MODELS.json, or None when there is none."""
    manifest = models_dir / "MODELS.json"
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    mine = [x for x in entries if x.get("stage") == STAGE]
    if not mine:
        return None
    if len(mine) > 1:
        raise StageError(f"MODELS.json lists {len(mine)} image models; the stage uses one")
    x = mine[0]
    spec = ModelSpec(name=x["name"], version=x["version"], file=x["file"], sha256=x["sha256"],
                     threshold=float(x.get("threshold", 0.5)), frames=x.get("frames", "original"))
    return ImageModel(spec, models_dir)
