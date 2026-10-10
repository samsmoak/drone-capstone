"""The espcn-clahe@1 candidate's image steps: ESPCN ×2, CLAHE 1.5, then an
edge-only sharpen — the method this evaluation picked (RESULTS.txt).

Kevin wrote these as the agent's enhancer (#103, pipeline/stages/enhance/
espcn.py). The agent ships clahe@1 instead (docs/features/pipeline/
enhance.txt): ESPCN ×2 tied bicubic on these frames (RESULTS.txt), so it
added a contrib OpenCV build and a model file for no detail. The steps live
here, unchanged, so the evaluation still runs and still scores exactly the
method it describes.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

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
