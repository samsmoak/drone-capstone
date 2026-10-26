"""Remove the viewer's crosshair from one image, using preprocess.py's logic.

    python -m cropwatcher.pipeline.stages.classify.reticle photo.png
    ... reticle photo.png -o cleaned.png
    ... reticle photo.png --compare     # also write a before/after crop

Writes <name>_noreticle.png next to the input unless -o is given. The image is
read as 8-bit grayscale and is NOT resized, so the output is the same size as the
input. remove_reticle() and its constants are copied from
ml/image-classifier/preprocess.py; keep them in step if that file changes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

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
    marked = (arms & differs).astype(np.uint8) * 255
    mask = np.asarray(cv2.dilate(marked, np.ones((3, 3), np.uint8)), dtype=np.uint8)
    if not mask.any():
        return gray
    return np.asarray(cv2.inpaint(gray, mask, 3, cv2.INPAINT_TELEA), dtype=np.uint8)


def _read(path: Path) -> Gray | None:
    """Read through bytes: cv2.imread fails on Windows paths holding characters
    like the narrow no-break space macOS puts before "PM" in screenshot names."""
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    return None if image is None else np.asarray(image, dtype=np.uint8)


def _write(path: Path, image: Gray) -> None:
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"cannot encode {path}")
    encoded.tofile(str(path))


def _say(text: str) -> None:
    """Print without dying on a Windows console that cannot show a filename."""
    enc = sys.stdout.encoding or "utf-8"
    print(text.encode(enc, "replace").decode(enc))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image", type=Path, help="the image to clean")
    ap.add_argument("-o", "--output", type=Path,
                    help="where to write the result (default: <name>_noreticle.png)")
    ap.add_argument("--compare", action="store_true",
                    help="also write <name>_compare.png: 3x before/after crop of the centre")
    args = ap.parse_args()

    gray = _read(args.image)
    if gray is None:
        _say(f"cannot read {args.image}")
        return 1

    cleaned = remove_reticle(gray)
    out_path = args.output or args.image.with_name(f"{args.image.stem}_noreticle.png")
    _write(out_path, cleaned)

    changed = int(np.count_nonzero(gray != cleaned))
    _say(f"{args.image.name}: {gray.shape[1]} x {gray.shape[0]}, "
          f"{changed} px changed"
          f"{'' if changed else ' (no reticle found)'} -> {out_path}")

    if args.compare:
        h, w = gray.shape
        r = min(70, h // 2, w // 2)
        box = (slice(h // 2 - r, h // 2 + r), slice(w // 2 - r, w // 2 + r))
        pair = np.hstack([gray[box], cleaned[box]])
        compare_path = out_path.with_name(f"{args.image.stem}_compare.png")
        big = np.asarray(cv2.resize(pair, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST),
                         dtype=np.uint8)
        _write(compare_path, big)
        _say(f"before | after crop -> {compare_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
