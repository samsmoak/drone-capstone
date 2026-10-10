"""The enhancer — stage 2, story 4.3: a clearer copy of every camera frame,
written beside the original and never in place of it.

Three steps, in this order, on each 8-bit grayscale frame:

  ESPCN ×2      a small super-resolution network (OpenCV dnn_superres):
                324×244 → 648×488.
  CLAHE 1.5     local contrast, 8×8 tiles — most of the visible gain.
  edge sharpen  unsharp at 0.6, weighted by edge strength: full on real
                edges, none where the gradient is noise.

Chosen by ml/upscaling-eval/RESULTS.txt, which scored every candidate and
says why this one won. That evaluation imports the functions below rather
than keeping its own copy, so what was measured is what runs here.

THE ENHANCED IMAGE CAN SHOW WHAT IS NOT IN THE SCENE. CLAHE lifts sensor
noise into faint grain on smooth surfaces, and no step can recover detail the
camera did not capture. It is never the only evidence for a verdict, and
wherever it is shown it is labelled as enhanced
(docs/features/pipeline/image-enhancement.txt).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from cropwatcher.pipeline.contracts import (
    EnhancedFrame,
    EnhanceResult,
    FlightContext,
    Frame,
    PointData,
    StageError,
)

log = logging.getLogger(__name__)

MODELS = Path(__file__).resolve().parents[2] / "models"
MODEL_FILE = "ESPCN_x2.pb"

SCALE = 2
CLAHE_CLIP, CLAHE_TILES = 1.5, (8, 8)
UNSHARP_SIGMA = 1.0
EDGE_AMOUNT = 0.6
# The edge weight ramps from EDGE_LO to EDGE_HI, in grey levels per pixel
# (Sobel ÷ 8 on a 1-px blur). Measured 2026-10-09 on ESPCN ×2 + CLAHE 2.0 of the
# camera frames: 90 % of flat-area pixels are under 3.5, half of edge pixels
# over 11.5.
EDGE_LO, EDGE_HI = 3.0, 8.0

METHOD = f"espcn-x{SCALE}+clahe-{CLAHE_CLIP}+edge-{EDGE_AMOUNT}"


# ── the steps — ml/upscaling-eval/methods.py imports these ─────────────────


def load_model(path: Path) -> cv2.dnn_superres.DnnSuperResImpl:
    sr = cv2.dnn_superres.DnnSuperResImpl.create()
    sr.readModel(str(path))
    sr.setModel("espcn", SCALE)
    return sr


def upscale(sr: cv2.dnn_superres.DnnSuperResImpl, img: np.ndarray) -> np.ndarray:
    """ESPCN was trained on the luma of colour photos. OpenCV converts BGR to
    YCrCb and runs the network on Y; a gray frame repeated to BGR has flat
    chroma, so Y is the whole answer."""
    out = sr.upsample(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    return cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)


def clahe(img: np.ndarray, clip: float = CLAHE_CLIP) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=clip, tileGridSize=CLAHE_TILES).apply(img)


def edge_sharpen(img: np.ndarray, amount: float = EDGE_AMOUNT) -> np.ndarray:
    """Unsharp masking weighted by edge strength, so noise on a smooth surface
    is not sharpened into texture."""
    f = img.astype(np.float32)
    blur = cv2.GaussianBlur(f, (0, 0), UNSHARP_SIGMA)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
    weight = np.clip((np.hypot(gx, gy) - EDGE_LO) / (EDGE_HI - EDGE_LO), 0, 1)
    out: np.ndarray = np.clip(f + amount * weight * (f - blur) + 0.5, 0, 255).astype(np.uint8)
    return out


def enhance_image(sr: cv2.dnn_superres.DnnSuperResImpl, img: np.ndarray) -> np.ndarray:
    """An 8-bit grayscale frame in; the same, SCALE times as wide, out."""
    return edge_sharpen(clahe(upscale(sr, img)))


# ── the stage ──────────────────────────────────────────────────────────────


def model_entry(models: Path, file: str) -> dict[str, str]:
    try:
        entries = json.loads((models / "MODELS.json").read_text())
    except (OSError, ValueError) as e:
        raise StageError(f"the enhancer cannot read MODELS.json: {e}") from e
    for entry in entries:
        if entry.get("file") == file:
            return dict(entry)
    raise StageError(f"MODELS.json has no entry for {file}")


class EspcnEnhancer:
    name = "espcn-clahe"
    version = "1"

    def __init__(self, models: Path = MODELS) -> None:
        self._models = models
        self._sr: cv2.dnn_superres.DnnSuperResImpl | None = None

    def check(self) -> None:
        """Load the model now; raise StageError if it is missing or altered.
        The agent's selftest calls this on the frozen binary."""
        self._model()

    def _model(self) -> cv2.dnn_superres.DnnSuperResImpl:
        """Loaded once, and only when a point has frames. A missing or altered
        model file stops the stage, so the runner uses the originals."""
        if self._sr is None:
            path = self._models / MODEL_FILE
            if not path.exists():
                raise StageError(f"the enhancer's model file is missing: {path}")
            want = model_entry(self._models, MODEL_FILE)["sha256"]
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            if got != want:
                raise StageError(f"{MODEL_FILE} is not the file MODELS.json names "
                                 f"(sha256 {got[:12]}…, expected {want[:12]}…)")
            self._sr = load_model(path)
        return self._sr

    def enhance(self, data: PointData, ctx: FlightContext) -> EnhanceResult:
        if not data.frames:
            return EnhanceResult(frames=())
        sr = self._model()
        out_dir = ctx.workdir / "enhanced"
        out_dir.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        frames = tuple(self._one(sr, f, out_dir) for f in data.frames)
        log.info("point %s: enhanced %d of %d frames in %.2f s", data.point.id,
                 sum(f.path is not None for f in frames), len(frames),
                 time.perf_counter() - start)
        return EnhanceResult(frames=frames)

    def _one(self, sr: cv2.dnn_superres.DnnSuperResImpl, frame: Frame,
             out_dir: Path) -> EnhancedFrame:
        """One frame. A frame that cannot be enhanced says why, and the rest
        carry on — one bad file must not cost the point its other frames."""
        try:
            img = cv2.imdecode(np.fromfile(frame.path, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                log.warning("frame %d not enhanced: not a readable image", frame.seq)
                return self._skipped(frame, "the frame file is not a readable image")
            out = enhance_image(sr, img)
            ok, png = cv2.imencode(".png", out)
            if not ok:
                log.warning("frame %d not enhanced: PNG encoding failed", frame.seq)
                return self._skipped(frame, "the enhanced image could not be encoded")
            path = out_dir / f"{frame.seq:06d}.png"
            path.write_bytes(png.tobytes())
        except (OSError, cv2.error) as e:
            log.warning("frame %d not enhanced", frame.seq, exc_info=True)
            return self._skipped(frame, f"enhancement failed: {type(e).__name__}: {e}")
        return EnhancedFrame(frame=frame, path=path, method=METHOD, scale=SCALE)

    @staticmethod
    def _skipped(frame: Frame, note: str) -> EnhancedFrame:
        return EnhancedFrame(frame=frame, path=None, method="identity", scale=1,
                             note=f"{note} — the original frame is used")
