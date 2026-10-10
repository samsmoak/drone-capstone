"""Turn the dataset's photos into what the classify stage will see, and report.

    ml/image-classifier/.venv/Scripts/python ml/image-classifier/preprocess.py
    ... preprocess.py --check      # report only, write nothing

THE STAGE SEES 324 x 244, 8-bit grayscale (the AI deck's frames, possibly
CLAHE-enhanced by clahe@1). So every photo is brought to that format, and the
model's 1x3x224x224 input is made FROM it — a model trained on anything finer
would learn detail the drone never delivers.

  data/raw/<file>  ->  data/processed/<file>.png   324 x 244, grayscale

SCREENSHOTS carry the viewer's crosshair, which a model could learn instead of
the equipment. A source that is not already 324 x 244 is treated as a
screenshot: the reticle's thin lines at the centre are inpainted away before
shrinking. A real deck frame (324 x 244) is never touched except to be
copied. Check the result by eye: --preview writes before/after crops.

Each processed frame is also measured with the enhancer's own limits
(enhance/clahe.py measure_quality), so an unusable photo is known now rather
than discovered as "unknown — frame unusable" at flight time.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend" / "agent"))
from cropwatcher.pipeline.stages.enhance.clahe import measure_quality  # noqa: E402

MANIFEST = HERE / "manifests" / "images.csv"
RAW = HERE / "data" / "raw"
PROCESSED = HERE / "data" / "processed"
PREVIEW = HERE / "data" / "preview"

#: The camera's frame, as (width, height).
CAMERA = (324, 244)
#: The model's input side, px.
MODEL_SIDE = 224
#: ImageNet statistics (the backbone's pretraining), applied to the gray value.
MEAN, STD = 0.449, 0.226

#: The reticle: arms within this many px of the centre, this thick, at the
#: SOURCE's scale of 828 px wide (scaled for other sizes).
RETICLE_REACH = 44
RETICLE_HALF_WIDTH = 4
#: A pixel this far from its neighbourhood's median, on an arm, is the reticle.
RETICLE_DELTA = 18

Gray = NDArray[np.uint8]


def remove_reticle(gray: Gray) -> Gray:
    """Inpaint the crosshair's thin arms at the centre; the rest is untouched."""
    h, w = gray.shape
    k = w / 828.0
    reach, half = int(RETICLE_REACH * k) + 1, max(1, int(round(RETICLE_HALF_WIDTH * k)))
    cx, cy = w // 2, h // 2
    arms = np.zeros_like(gray, dtype=bool)
    arms[cy - half:cy + half + 1, cx - reach:cx + reach + 1] = True   # horizontal arm
    arms[cy - reach:cy + reach + 1, cx - half:cx + half + 1] = True   # vertical arm
    side = int(round(15 * k)) | 1
    background = cv2.medianBlur(gray, max(3, side))
    differs = np.abs(gray.astype(np.int16) - background.astype(np.int16)) > RETICLE_DELTA
    mask = (arms & differs).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    if not mask.any():
        return gray
    out: Gray = cv2.inpaint(gray, mask, 3, cv2.INPAINT_TELEA)
    return out


def _read(path: Path) -> Gray | None:
    """Read through bytes: cv2.imread fails on Windows paths holding characters
    like the narrow no-break space macOS puts before "PM" in screenshot names."""
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    return None if image is None else np.asarray(image, dtype=np.uint8)


def _write(path: Path, image: Gray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"cannot encode {path}")
    encoded.tofile(str(path))


def to_camera_format(path: Path) -> tuple[Gray, bool]:
    """The photo as the stage would see it, and whether it was a screenshot."""
    image = _read(path)
    if image is None:
        raise ValueError(f"cannot read {path}")
    gray: Gray = np.asarray(image, dtype=np.uint8)
    if (gray.shape[1], gray.shape[0]) == CAMERA:
        return gray, False
    gray = remove_reticle(gray)
    out: Gray = cv2.resize(gray, CAMERA, interpolation=cv2.INTER_AREA)
    return out, True


def to_model_input(frame: Gray) -> NDArray[np.float32]:
    """1 x 3 x 224 x 224 float32: the frame squashed square, normalised, the one
    gray channel repeated three times. This is the model's input contract —
    stages/classify/image.py must do exactly this."""
    square = cv2.resize(frame, (MODEL_SIDE, MODEL_SIDE), interpolation=cv2.INTER_AREA)
    x = (square.astype(np.float32) / 255.0 - MEAN) / STD
    return np.repeat(x[None, None, :, :], 3, axis=1).astype(np.float32)


def _preview(source: Path, before: Gray, after: Gray, name: str) -> None:
    PREVIEW.mkdir(parents=True, exist_ok=True)
    h, w = before.shape
    crop = before[h // 2 - 70:h // 2 + 70, w // 2 - 70:w // 2 + 70]
    cleaned = remove_reticle(before)[h // 2 - 70:h // 2 + 70, w // 2 - 70:w // 2 + 70]
    pair = np.hstack([crop, cleaned])
    _write(PREVIEW / f"{name}.png", cv2.resize(pair, None, fx=3, fy=3,
                                               interpolation=cv2.INTER_NEAREST))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    ap.add_argument("--preview", action="store_true",
                    help="write before/after crops of the reticle to data/preview/")
    args = ap.parse_args()

    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("the manifest is empty")
        return 1

    unusable = 0
    for n, r in enumerate(rows):
        src = RAW / r["file"]
        frame, screenshot = to_camera_format(src)
        q = measure_quality(frame)
        unusable += not q.usable
        if not args.check:
            dst = (PROCESSED / r["file"]).with_suffix(".png")
            dst.parent.mkdir(parents=True, exist_ok=True)
            _write(dst, frame)
        if args.preview and screenshot:
            raw = _read(src)
            assert raw is not None
            _preview(src, raw, frame, f"{n + 1:03d}")
        print(f"{n + 1:3d}  {r['label']:6s}  {'screenshot' if screenshot else 'deck frame':10s}"
              f"  sharp {q.sharpness:6.0f}  mean {q.brightness:5.0f}"
              f"  white {q.bright_share:4.0%}  "
              f"{'ok' if q.usable else 'UNUSABLE — ' + str(q.reason)}")
    print(f"\n{len(rows)} photos, {unusable} the stage would call unusable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
