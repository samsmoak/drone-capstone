"""Read the pressure gauge in sensor images and flag DANGER (400-600 kPa inclusive).

    python -m cropwatcher.pipeline.stages.classify.pressure_gauge pressurePhotos
    ... pressure_gauge pressurePhotos --sheet out.png   # annotated contact sheet
    ... pressure_gauge photo.png

Geometric baseline, no training: remove the reticle, find the dial (the largest
bright disc), cut it out at a fixed size, find the dark arrow-shaped needle, turn
its angle into kPa, and compare with the fault band.

The dial sweeps 270 degrees: 0 kPa at -135 deg from straight up, 600 kPa at +135.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from cropwatcher.pipeline.stages.classify.image import _read_gray as _read
from cropwatcher.pipeline.stages.classify.reticle import remove_reticle

Gray = NDArray[np.uint8]

FAULT_MIN, FAULT_MAX = 400.0, 600.0     # inclusive
WARN_MIN, WARN_MAX = 200.0, 400.0       # exclusive: the middle third of the scale
#: Half the dial's sweep, from straight up (0 kPa at -120, 600 at +120).
SWEEP_DEG = 120.0
#: Where the scale's ticks sit, as a fraction of the dial radius.
TICK_RING = 0.85
FULL_SCALE = 600.0
RANGE_TOLERANCE = 0.0                  # kPa of slack past 0 and 600
MIN_BEZEL_CONTRAST = 10               # grey levels, face over bezel, in every sector
PURPLE = (200, 0, 170)                 # BGR, for a needle outside 0-600
YELLOW = (0, 215, 255)                 # BGR, for the warning band
DIAL_PX = 256                          # the dial is resampled to this many px across


@dataclass
class Reading:
    kpa: float | None                  # None when there is no valid reading (see error)
    error: str | None = None           # why there is no reading
    raw_kpa: float | None = None       # the needle's reading before the range check
    circle: tuple[float, float, float] | None = None      # cx, cy, r in the source image
    tip: tuple[float, float] | None = None                # needle tip in the source image
    tail: tuple[float, float] | None = None               # needle stem end in the source image

    @property
    def faulty(self) -> bool | None:
        return None if self.kpa is None else FAULT_MIN <= self.kpa <= FAULT_MAX

    @property
    def warning(self) -> bool | None:
        return None if self.kpa is None else WARN_MIN < self.kpa < WARN_MAX

    @property
    def label(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        if self.faulty:
            return "DANGER"
        return "WARNING" if self.warning else "ok"


def _weakest_sector(gray: Gray, cx: float, cy: float, r: float, sectors: int = 12) -> float:
    """Face-minus-bezel brightness in the worst of `sectors` wedges around the circle.

    A real dial has a dark bezel all the way round; a bright patch that merely has
    one circular edge (the foil panel) is dark on one side only and scores low."""
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
        here = wedge == k
        face = here & (dist > 0.3 * r) & (dist < 0.8 * r)
        bezel = here & (dist > 1.1 * r) & (dist < 1.35 * r)
        if not face.any() or not bezel.any():
            return -np.inf                          # the circle runs off the image
        worst = min(worst, float(patch[face].mean() - patch[bezel].mean()))
    return worst


def find_dial(gray: Gray) -> tuple[float, float, float] | None:
    """The pressure gauge: the largest circle with a bright face and a dark bezel all round."""
    h = gray.shape[0]
    blur = cv2.medianBlur(gray, 5)
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=h // 8,
                             param1=100, param2=35,
                             minRadius=max(15, h // 30), maxRadius=int(h * 0.6))
    if found is None:
        return None
    best, best_score = None, 0.0
    for cx, cy, r in found[0][:15]:
        weakest = _weakest_sector(gray, float(cx), float(cy), float(r))
        if weakest > MIN_BEZEL_CONTRAST and weakest * r > best_score:
            best, best_score = (float(cx), float(cy), float(r)), weakest * r
    return best


Point = tuple[float, float]


def read_needle(gray: Gray, circle: tuple[float, float, float], lowest: float = 1.0,
                dark_ratio: float = 0.6) -> tuple[float, Point, Point] | None:
    """Return (angle in degrees clockwise from straight up, tip and tail in source px).

    `lowest` is how far below the dial centre to look, as a fraction of the radius; a dial
    with a printed label or a cut-off bottom passes less than 1 to keep that out of the search.
    `dark_ratio` is how much darker than the face a pixel must be to count as needle."""
    cx, cy, r = circle
    s = DIAL_PX / (2 * r)
    matrix = np.array([[s, 0, DIAL_PX / 2 - cx * s], [0, s, DIAL_PX / 2 - cy * s]])
    dial = cv2.warpAffine(gray, matrix, (DIAL_PX, DIAL_PX),
                          flags=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)
    c = DIAL_PX / 2
    yy, xx = np.mgrid[0:DIAL_PX, 0:DIAL_PX]
    dist = np.hypot(xx - c, yy - c)
    inside = (dist < 0.72 * c) & (yy - c < lowest * c)      # leave the tick ring and bezel out

    face = float(np.median(dial[dist < 0.9 * c]))
    dark = ((dial < face * dark_ratio) & inside).astype(np.uint8)
    blob = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, blob)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark)
    if count < 2:
        return None
    needle = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[needle, cv2.CC_STAT_AREA] < 0.02 * DIAL_PX ** 2:
        return None
    ys, xs = np.nonzero(labels == needle)
    pts = np.column_stack([xs, ys]).astype(np.float64)
    pts -= pts.mean(axis=0)
    axis = np.linalg.eigh(np.cov(pts.T))[1][:, -1]          # the arrow's long axis
    along, across = pts @ axis, pts @ np.array([-axis[1], axis[0]])
    # The arrowhead is far wider than the stem: it sits where the needle is widest.
    spread = (along - along.min()) / (along.max() - along.min() + 1e-9)
    bins = np.minimum((spread * 10).astype(int), 9)
    widths = np.array([np.ptp(across[bins == k]) if (bins == k).sum() > 3 else 0.0
                       for k in range(10)])
    if np.argmax(widths) < 5:
        axis, along = -axis, -along
    centre = np.array([xs.mean(), ys.mean()])
    tip = centre + axis * along.max()
    tail = centre + axis * along.min()
    angle = float(np.degrees(np.arctan2(axis[0], -axis[1])))

    def to_source(p: NDArray[np.float64]) -> Point:
        return (float((p[0] - DIAL_PX / 2) / s + cx), float((p[1] - DIAL_PX / 2) / s + cy))

    return angle, to_source(tip), to_source(tail)


def _scale_angle(circle: tuple[float, float, float], tip: tuple[float, float],
                 tail: tuple[float, float]) -> float | None:
    """Where the needle points on the scale: extend the arrow through its tip to the tick
    ring and take that spot's angle around the dial centre, clockwise from straight up.

    The arrow pivots on a hub below the dial centre, so neither its own axis angle nor the
    tip's angle around the centre matches what a person reads off the printed scale."""
    cx, cy, r = circle
    centre, tip_p = np.array([cx, cy]), np.array(tip)
    direction = tip_p - np.array(tail)
    direction /= np.linalg.norm(direction)
    offset = tip_p - centre
    b = float(offset @ direction)
    disc = b * b - (float(offset @ offset) - (TICK_RING * r) ** 2)
    if disc < 0:
        return None
    hit = tip_p + (-b + np.sqrt(disc)) * direction
    return float(np.degrees(np.arctan2(hit[0] - cx, cy - hit[1])))


def read_gauge(gray: Gray) -> Reading:
    gray = remove_reticle(gray)
    circle = find_dial(gray)
    if circle is None:
        return Reading(None, "dial not found")
    needle = read_needle(gray, circle)
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
        if reading.raw_kpa is not None and reading.kpa is None:
            colour = PURPLE                         # the needle is off the 0-600 scale
        else:
            colour = (0, 0, 255) if reading.faulty else YELLOW if reading.warning else (0, 200, 0)
        cv2.circle(img, (int(cx), int(cy)), int(r), colour, 2)
        if reading.tip and reading.tail:
            cv2.line(img, (int(reading.tail[0]), int(reading.tail[1])),
                     (int(reading.tip[0]), int(reading.tip[1])), (255, 128, 0), 2)
    text = reading.label if reading.kpa is None else f"{reading.kpa:.0f} {reading.label}"
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
        kpa = "  -- " if reading.kpa is None else f"{reading.kpa:5.0f}"
        print(f"{i:3d}  {kpa} kPa  {reading.label}  {f.name}".encode("ascii", "replace").decode())
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
