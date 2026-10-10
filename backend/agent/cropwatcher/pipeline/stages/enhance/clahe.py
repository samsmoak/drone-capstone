"""The enhancer — stage 2, story 4.3: clearer frames, and how usable each one is.

THE FRAMES' PROBLEM IS CONTRAST, NOT RESOLUTION. The AI deck records 324×244
8-bit grayscale, and the lab's frames are dark and low-contrast (ml/enhance-
eval/RESULTS.txt). CLAHE — contrast-limited adaptive histogram equalisation —
stretches contrast tile by tile, with a limit so flat areas are not blown into
grain. It moves pixel values; it never draws a pixel that was not there, which
a super-resolution network can (an invented crack is a false alarm on an
inspection drone). An upscaler can still be swapped in behind the same
contract if Kevin's evaluation (ml/upscaling-eval/) shows it adds real
detail.

NO COLOUR. The frames hold none; colourising would guess it.

QUALITY is measured on the ORIGINAL, never the enhanced copy:
  sharpness     variance of the Laplacian — low means motion blur or focus
  brightness    mean pixel, 0..255
  dark_share    pixels at 0..5 — crushed to black
  bright_share  pixels at 250..255 — blown to white
A frame outside the limits is still enhanced and kept, but marked unusable
with the reason, so nothing downstream reads it as evidence. Every limit cites
ml/enhance-eval/RESULTS.txt.

The original is never touched: the copy goes to ctx.workdir/enhanced/<seq>.png.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from numpy.typing import NDArray

from cropwatcher.pipeline.contracts import (
    EnhancedFrame,
    EnhanceResult,
    FlightContext,
    FrameQuality,
    PointData,
)

log = logging.getLogger(__name__)

#: CLAHE's contrast limit and tile grid (RESULTS.txt, "Settings").
CLIP_LIMIT = 2.0
TILE_GRID = (4, 4)
#: Below this variance of the Laplacian a frame is blurred (RESULTS.txt, "Quality").
MIN_SHARPNESS = 25.0
#: A mean pixel below this is too dark to read (RESULTS.txt, "Quality").
MIN_BRIGHTNESS = 15.0
#: More than this share crushed to black, or blown to white, is unreadable.
MAX_CLIPPED_SHARE = 0.5
DARK_LEVEL = 5
BRIGHT_LEVEL = 250

Image = NDArray[np.uint8]


def measure_quality(image: Image) -> FrameQuality:
    """How usable a grayscale frame is, by the limits above."""
    sharpness = float(cv2.Laplacian(image, cv2.CV_64F).var())
    brightness = float(image.mean())
    dark = float((image <= DARK_LEVEL).mean())
    bright = float((image >= BRIGHT_LEVEL).mean())
    reasons = []
    if brightness < MIN_BRIGHTNESS:
        reasons.append(f"too dark: mean {brightness:.0f} of 255 (limit {MIN_BRIGHTNESS:.0f})")
    if dark > MAX_CLIPPED_SHARE:
        reasons.append(f"too dark: {dark:.0%} of pixels black")
    if bright > MAX_CLIPPED_SHARE:
        reasons.append(f"overexposed: {bright:.0%} of pixels white")
    if sharpness < MIN_SHARPNESS:
        reasons.append(f"blurred: sharpness {sharpness:.0f} (limit {MIN_SHARPNESS:.0f})")
    return FrameQuality(sharpness=sharpness, brightness=brightness, dark_share=dark,
                        bright_share=bright, usable=not reasons,
                        reason="; ".join(reasons) or None)


class ClaheEnhancer:
    name = "clahe"
    version = "1"

    def __init__(self) -> None:
        self._clahe = cv2.createCLAHE(clipLimit=CLIP_LIMIT, tileGridSize=TILE_GRID)

    def enhance(self, data: PointData, ctx: FlightContext) -> EnhanceResult:
        folder = ctx.workdir / "enhanced"
        out: list[EnhancedFrame] = []
        for frame in data.frames:
            read = cv2.imread(str(frame.path), cv2.IMREAD_GRAYSCALE)
            if read is None:
                out.append(EnhancedFrame(frame, None, "identity", 1,
                                         note="the frame could not be read as an image"))
                continue
            image: Image = np.asarray(read, dtype=np.uint8)
            quality = measure_quality(image)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{frame.seq:06d}.png"
            if not cv2.imwrite(str(target), self._clahe.apply(image)):
                log.warning("could not write the enhanced copy of frame %d", frame.seq)
                out.append(EnhancedFrame(frame, None, "identity", 1,
                                         note="the enhanced copy could not be written",
                                         quality=quality))
                continue
            out.append(EnhancedFrame(frame, target, "clahe", 1, quality=quality))
        return EnhanceResult(tuple(out))
