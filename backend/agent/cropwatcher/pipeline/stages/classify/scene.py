"""Scene change — what the camera can honestly add to a finding (story 4.4,
scene@1).

THE CAMERA CANNOT SEE HEAT. It is a 324 × 244 grayscale camera; a warm pump
looks exactly like a cold one. What it can see is whether its VIEW CHANGED
while a reading departed: a person stepping in front of the drone, a cabinet
door opening, a light going on. That corroborates that something physical
happened then — it never decides that it did, and a steady view never
contradicts a reading (the owner, 2026-10-09: "the telemetry is the source of
truth; an image only supports it").

THE MEASURE. Each readable frame is compared with the previous readable frame
taken from about the same place (within NEAR_M, at most MAX_GAP_S earlier):
both are shrunk to a quarter size, blurred, and standardised (zero mean, unit
spread, so a change of exposure alone does not count). The second is then
ALIGNED to the first by phase correlation — a drone turning a few degrees in
place shifts the whole view, which is not something new in it (the lab's
0.35–0.45 "steady" pairs were exactly that, 2026-10-09) — and the score is
the mean absolute difference over the part both frames see. A shift of more
than MAX_SHIFT of the frame is the drone looking somewhere else: no score. A
frame with no comparable predecessor — the drone moved, or it is the first —
has no score, and says why.

SCENE_CHANGE, the score at which a view "changed", is measured on the lab's
frames (ml/scene-eval/MEASUREMENTS.txt): above every score of a drone sitting
still with nothing happening.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from cropwatcher.pipeline.contracts import EnhancedFrame, ViewChange

#: Two frames are "from the same place" within this distance, m.
NEAR_M = 0.05
#: ...and this close in time, s (the camera records two a second).
MAX_GAP_S = 1.5
#: Frames are compared at a quarter of the camera's size.
SHRINK = 4
#: Gaussian blur, px at the shrunk size: sensor noise is not a change.
BLUR_SIGMA = 1.0
#: More than this share of the frame's width or height between two aligned
#: frames, and the drone was looking somewhere else.
MAX_SHIFT = 0.25
#: The score at which the view changed (ml/scene-eval/MEASUREMENTS.txt).
SCENE_CHANGE = 0.45


def _prepared(path: str) -> np.ndarray | None:
    import cv2

    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    small: np.ndarray = cv2.resize(
        img, (max(1, img.shape[1] // SHRINK), max(1, img.shape[0] // SHRINK)),
        interpolation=cv2.INTER_AREA).astype(np.float32)
    small = cv2.GaussianBlur(small, (0, 0), BLUR_SIGMA)
    spread = float(small.std())
    if spread < 1e-3:
        return np.zeros_like(small)
    return (small - float(small.mean())) / spread


def align(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """The parts of `a` and `b` that see the same place, `b` shifted onto `a`;
    None when the shift is more than MAX_SHIFT (a different view)."""
    import cv2

    (dx, dy), _ = cv2.phaseCorrelate(a.astype(np.float64), b.astype(np.float64))
    h, w = a.shape
    if abs(dx) > MAX_SHIFT * w or abs(dy) > MAX_SHIFT * h:
        return None
    sx, sy = int(round(dx)), int(round(dy))
    # b(x + dx, y + dy) ≈ a(x, y): the overlap, with a margin of one pixel.
    ax0, ax1 = max(0, -sx) + 1, min(w, w - sx) - 1
    ay0, ay1 = max(0, -sy) + 1, min(h, h - sy) - 1
    if ax1 - ax0 < w // 2 or ay1 - ay0 < h // 2:
        return None
    return a[ay0:ay1, ax0:ax1], b[ay0 + sy:ay1 + sy, ax0 + sx:ax1 + sx]


def score(a: np.ndarray, b: np.ndarray) -> float | None:
    """Mean |difference| of the aligned overlap; None when the views do not
    overlap enough to compare."""
    aligned = align(a, b)
    if aligned is None:
        return None
    pa, pb = aligned
    return float(np.mean(np.abs(pa - pb)))


def measure(frames: Sequence[EnhancedFrame]) -> tuple[ViewChange, ...]:
    """One ViewChange per frame, in order. Unreadable or unusable frames are
    skipped as comparisons and say so."""
    out: list[ViewChange] = []
    previous: tuple[EnhancedFrame, np.ndarray] | None = None
    for e in frames:
        f = e.frame
        if e.quality is not None and not e.quality.usable:
            out.append(ViewChange(f.seq, None, None, "unusable frame"))
            continue
        img = _prepared(str(f.path))
        if img is None:
            out.append(ViewChange(f.seq, None, None, "unreadable frame"))
            continue
        if previous is None:
            out.append(ViewChange(f.seq, None, None, "nothing earlier to compare with"))
        else:
            pf, pimg = previous
            dt = f.t_s - pf.frame.t_s
            moved = _moved(pf, e)
            if dt > MAX_GAP_S:
                out.append(ViewChange(f.seq, None, pf.frame.seq,
                                       f"{dt:.1f} s after the frame before it"))
            elif moved is None:
                out.append(ViewChange(f.seq, None, pf.frame.seq, "position not measured"))
            elif moved > NEAR_M:
                out.append(ViewChange(f.seq, None, pf.frame.seq,
                                       f"the drone moved {moved * 100:.0f} cm"))
            elif img.shape != pimg.shape:
                out.append(ViewChange(f.seq, None, pf.frame.seq, "a different frame size"))
            else:
                raw = score(pimg, img)
                if raw is None:
                    out.append(ViewChange(f.seq, None, pf.frame.seq,
                                           "the camera turned to a different view"))
                else:
                    s = round(raw, 4)
                    out.append(ViewChange(f.seq, s, pf.frame.seq,
                                          "the view changed" if s >= SCENE_CHANGE
                                          else "the view held steady",
                                          changed=s >= SCENE_CHANGE))
        previous = (e, img)
    return tuple(out)


def _moved(a: EnhancedFrame, b: EnhancedFrame) -> float | None:
    pa, pb = (a.frame.x_m, a.frame.y_m, a.frame.z_m), (b.frame.x_m, b.frame.y_m, b.frame.z_m)
    if any(v is None for v in (*pa, *pb)):
        return None
    return math.dist(pa, pb)  # type: ignore[arg-type]
