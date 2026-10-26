"""Read the SYSTEM STATUS gauge in sensor images and flag DANGER (70-100 inclusive).

    python -m cropwatcher.pipeline.stages.classify.status_gauge "system status"
    ... status_gauge "system status" --sheet status.png   # annotated contact sheet
    ... status_gauge photo.png

Same method as pressure_gauge.py (reticle removal, dial cut-out, arrow-shaped needle,
needle extended to the tick ring), but the dial is a circle with its bottom cut off, so
the bezel is only checked over the upper arc. The scale is 0-100: 0-30 inclusive is ok,
30-70 exclusive is a warning, 70-100 inclusive is danger. A needle off the scale is
marked purple.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from cropwatcher.pipeline.stages.classify import pressure_gauge
from cropwatcher.pipeline.stages.classify.image import _read_gray as _read
from cropwatcher.pipeline.stages.classify.pressure_gauge import (
    PURPLE,
    SWEEP_DEG,
    YELLOW,
    _scale_angle,
    read_needle,
)
from cropwatcher.pipeline.stages.classify.reticle import remove_reticle

Gray = NDArray[np.uint8]

OK_MAX = 30.0                          # inclusive
DANGER_MIN = 70.0                      # inclusive
FULL_SCALE = 100.0
RANGE_TOLERANCE = 0.0                  # units of slack past 0 and 100
#: Of 12 wedges (0 = left, clockwise): the dial's intact upper arc.
TOP_SECTORS = range(0, 6)
BOTTOM_SECTORS = range(8, 10)          # the wedges straight down, where the dial is cut off
MIN_TOP_CONTRAST = 35                  # the arc must be clearly bezelled...
MIN_BELOW_CONTRAST = 15               # a bezelled dial must show where the status gauge should be
#: ...and the bottom must not be, or it is the full pressure dial.
MAX_BOTTOM_CONTRAST = 25
#: Status dial centre below the pressure dial's, in pressure radii.
BELOW_PRESSURE = 2.45
RADIUS_RATIO = 0.85                    # status dial radius over the pressure dial's
#: How far a detected circle may sit from that guess, in radii.
SEARCH_TOLERANCE = 0.35
#: Where the flat bottom edge can be, in radii below the centre.
CUT_SEARCH = (0.3, 0.9)
#: Columns to find it in, in radii either side: clear of the needle.
CUT_SIDES = (0.4, 0.65)
#: The needle's pivot sits this far below the dial centre, in radii.
HUB_DROP = 0.18
#: Needle darkness vs the face, tried in turn for faint needles.
DARK_RATIOS = (0.6, 0.75, 0.85)


@dataclass
class Reading:
    value: float | None                # None when there is no valid reading (see error)
    error: str | None = None           # why there is no reading
    raw: float | None = None           # the needle's reading before the range check
    circle: tuple[float, float, float] | None = None      # cx, cy, r in the source image
    tip: tuple[float, float] | None = None                # needle tip in the source image
    tail: tuple[float, float] | None = None               # needle stem end in the source image

    @property
    def danger(self) -> bool | None:
        return None if self.value is None else self.value >= DANGER_MIN

    @property
    def warning(self) -> bool | None:
        return None if self.value is None else OK_MAX < self.value < DANGER_MIN

    @property
    def label(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        if self.danger:
            return "DANGER"
        return "WARNING" if self.warning else "ok"


def _weakest_sector(gray: Gray, cx: float, cy: float, r: float, shown: range,
                    sectors: int = 12) -> float:
    """Face-minus-bezel brightness in the worst of the `shown` wedges around the circle."""
    h, w = gray.shape
    x0, x1 = max(0, int(cx - 1.4 * r)), min(w, int(cx + 1.4 * r) + 1)
    y0, y1 = max(0, int(cy - 1.4 * r)), min(h, int(cy + 1.4 * r) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx, dy = xx - cx, yy - cy
    dist = np.hypot(dx, dy)
    wedge = ((np.arctan2(dy, dx) + np.pi) / (2 * np.pi) * sectors).astype(int) % sectors
    patch = gray[y0:y1, x0:x1].astype(np.float32)
    worst = np.inf
    for k in range(sectors):
        if k not in shown:
            continue
        here = wedge == k
        face = here & (dist > 0.3 * r) & (dist < 0.8 * r)
        bezel = here & (dist > 1.1 * r) & (dist < 1.35 * r)
        if not face.any() or not bezel.any():
            return -np.inf                          # the circle runs off the image
        worst = min(worst, float(patch[face].mean() - patch[bezel].mean()))
    return worst


def _status_circles(gray: Gray) -> list[tuple[float, float, float]]:
    """Circles with a bright face and dark bezel over the top arc but not along the bottom.
    The pressure gauge is bezelled all round, so it is skipped."""
    h = gray.shape[0]
    blur = cv2.medianBlur(gray, 5)
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=h // 8,
                             param1=100, param2=22,
                             minRadius=max(15, h // 30), maxRadius=int(h * 0.6))
    circles = []
    for cx, cy, r in ([] if found is None else found[0][:60]):
        top = _weakest_sector(gray, float(cx), float(cy), float(r), TOP_SECTORS)
        bottom = _weakest_sector(gray, float(cx), float(cy), float(r), BOTTOM_SECTORS)
        if top > MIN_TOP_CONTRAST and bottom < MAX_BOTTOM_CONTRAST:
            circles.append((top * r, (float(cx), float(cy), float(r))))
    return [c for _, c in sorted(circles, reverse=True)]


def _below(circle: tuple[float, float, float]) -> tuple[float, float, float]:
    """Where the status gauge sits if `circle` is the pressure gauge above it."""
    cx, cy, r = circle
    return cx, cy + BELOW_PRESSURE * r, RADIUS_RATIO * r


def _pressure_dial(gray: Gray) -> tuple[float, float, float] | None:
    """The pressure gauge above the status gauge, if the picture has both: the gauge
    pressure_gauge finds, with a status-shaped dial in the place below it."""
    circle = pressure_gauge.find_dial(gray)
    if circle is None:
        return None
    below = _weakest_sector(gray, *_below(circle), TOP_SECTORS)
    return circle if below > MIN_BELOW_CONTRAST else None


def find_dial(gray: Gray) -> tuple[float, float, float] | None:
    """The status gauge. When the pressure gauge is in view, the status gauge is the one
    below it; otherwise it is the best status-shaped circle in the picture."""
    circles = _status_circles(gray)
    pressure = _pressure_dial(gray)
    if pressure is None:
        return circles[0] if circles else None
    guess = _below(pressure)
    for cx, cy, r in circles:
        if (np.hypot(cx - guess[0], cy - guess[1]) < SEARCH_TOLERANCE * guess[2]
                and abs(r - guess[2]) < SEARCH_TOLERANCE * guess[2]):
            return cx, cy, r
    return guess


def _cut_depth(gray: Gray, circle: tuple[float, float, float]) -> float:
    """How far below the dial centre the flat bottom edge sits, as a fraction of the radius:
    the steepest drop from bright face to dark panel in the columns either side of the needle."""
    cx, cy, r = circle
    size = pressure_gauge.DIAL_PX
    s = size / (2 * r)
    matrix = np.array([[s, 0, size / 2 - cx * s], [0, s, size / 2 - cy * s]])
    warped = cv2.warpAffine(gray, matrix, (size, size),
                            flags=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_REPLICATE)
    dial = cv2.GaussianBlur(warped, (0, 0), 2).astype(np.float32)
    c = size / 2
    near, far = CUT_SIDES
    cols = np.r_[int(c - far * c):int(c - near * c), int(c + near * c):int(c + far * c)]
    rows = dial[:, cols].mean(axis=1)
    lo, hi = int(c + CUT_SEARCH[0] * c), min(size - 4, int(c + CUT_SEARCH[1] * c))
    drop = [rows[y + 3] - rows[y - 3] for y in range(lo, hi)]
    return (lo + int(np.argmin(drop)) - c) / c


def _read_needle(gray: Gray, circle: tuple[float, float, float]):
    lowest = _cut_depth(gray, circle)
    for ratio in DARK_RATIOS:
        needle = read_needle(gray, circle, lowest, ratio)
        if needle is not None:
            angle, tip, tail = needle
            cx, cy, r = circle
            hub = np.array([cx, cy + HUB_DROP * r])
            # The head reaches far past the pivot and the stem barely does, so the end
            # farther from the pivot is the tip, whatever the arrow's shape says.
            if np.linalg.norm(np.array(tip) - hub) < np.linalg.norm(np.array(tail) - hub):
                tip, tail = tail, tip
            return angle, tip, tail
    return None


def read_gauge(gray: Gray) -> Reading:
    gray = remove_reticle(gray)
    circle = find_dial(gray)
    if circle is None:
        return Reading(None, "dial not found")
    needle = _read_needle(gray, circle)
    if needle is None:
        return Reading(None, "needle not found", circle=circle)
    _, tip, tail = needle
    angle = _scale_angle(circle, tip, tail)
    if angle is None:
        return Reading(None, "needle not found", circle=circle)
    raw = (angle + SWEEP_DEG) / (2 * SWEEP_DEG) * FULL_SCALE
    if not -RANGE_TOLERANCE <= raw <= FULL_SCALE + RANGE_TOLERANCE:
        return Reading(None, f"needle out of range ({raw:.0f})", raw, circle, tip, tail)
    return Reading(float(np.clip(raw, 0, FULL_SCALE)), None, raw, circle, tip, tail)


def annotate(gray: Gray, reading: Reading, label: str) -> NDArray[np.uint8]:
    img = np.asarray(cv2.cvtColor(remove_reticle(gray), cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    colour = (128, 128, 128)
    if reading.circle:
        cx, cy, r = reading.circle
        if reading.raw is not None and reading.value is None:
            colour = PURPLE                         # the needle is off the 0-100 scale
        else:
            colour = (0, 0, 255) if reading.danger else YELLOW if reading.warning else (0, 200, 0)
        cv2.circle(img, (int(cx), int(cy)), int(r), colour, 2)
        if reading.tip and reading.tail:
            cv2.line(img, (int(reading.tail[0]), int(reading.tail[1])),
                     (int(reading.tip[0]), int(reading.tip[1])), (255, 128, 0), 2)
    text = reading.label if reading.value is None else f"{reading.value:.0f} {reading.label}"
    cv2.putText(img, f"{label}: {text}", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 3)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path", type=Path, help="an image or a folder of images")
    ap.add_argument("--sheet", type=Path, help="write an annotated contact sheet here")
    args = ap.parse_args()

    files = sorted(args.path.glob("*.png")) if args.path.is_dir() else [args.path]
    tiles = []
    for i, f in enumerate(files):
        gray = _read(f)
        if gray is None:
            print(f"{i:3d}  cannot read {f.name}".encode("ascii", "replace").decode())
            continue
        reading = read_gauge(gray)
        value = " -- " if reading.value is None else f"{reading.value:4.0f}"
        print(f"{i:3d}  {value}  {reading.label}  {f.name}".encode("ascii", "replace").decode())
        if args.sheet:
            tiles.append(cv2.resize(annotate(gray, reading, str(i)), (414, 312)))
    if args.sheet and tiles:
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
        cv2.imencode(".png", sheet)[1].tofile(str(args.sheet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
