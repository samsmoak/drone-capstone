"""Choose scene@1's threshold (SCENE_CHANGE) on the lab's REAL frames.

  1. STEADY — every pair of consecutive readable frames the drone took from the
     same place (within scene.NEAR_M, at most scene.MAX_GAP_S apart): the
     scores a view gets when nothing is deliberately changed. People do walk
     through the lab, so the tail is not all noise — the percentiles say how
     much of it there is.
  2. PLANTED — a sample of those pairs with the second frame altered:
       occluder 15 % / 30 %   a dark shape across the lower frame (someone
                              stepping in front of the drone)
       light 20 %             a bright patch (a door, a lamp)
       exposure × 1.5         the whole frame brighter — must NOT count: the
                              camera's own gain, not the scene
     Found = score ≥ the threshold.

    cd backend/agent && .venv/bin/python ../../ml/scene-eval/evaluate.py \\
        "<data folder>" [--sample 600] [--seed 0]
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "agent"))

import cv2  # noqa: E402

from cropwatcher.pipeline.stages.classify import scene  # noqa: E402

THRESHOLDS = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60)


def _n(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def pairs(root: Path):
    for index in sorted((root / "sessions").glob("*/frames.csv")):
        rows = list(csv.DictReader(index.open()))
        prev = None
        for r in rows:
            t = _n(r.get("t_s"))
            pos = (_n(r.get("x_m")), _n(r.get("y_m")), _n(r.get("z_m")))
            path = index.parent / r["file"]
            if t is None or None in pos or not path.exists():
                prev = None
                continue
            if prev is not None:
                pt, ppos, ppath = prev
                if t - pt <= scene.MAX_GAP_S and math.dist(pos, ppos) <= scene.NEAR_M:
                    yield ppath, path
            prev = (t, pos, path)


def prepared_from(img: np.ndarray) -> np.ndarray:
    tmp = Path("/tmp/scene-eval.png")
    cv2.imwrite(str(tmp), img)
    out = scene._prepared(str(tmp))
    assert out is not None
    return out


def plant(img: np.ndarray, kind: str) -> np.ndarray:
    h, w = img.shape
    out = img.astype(np.float32).copy()
    if kind.startswith("occluder"):
        share = 0.15 if kind.endswith("15") else 0.30
        cw = int(w * math.sqrt(share))
        ch = int(h * math.sqrt(share))
        x0, y0 = (w - cw) // 2, h - ch
        out[y0:, x0:x0 + cw] = 12.0
    elif kind == "light20":
        cw, ch = int(w * math.sqrt(0.2)), int(h * math.sqrt(0.2))
        out[:ch, :cw] = 245.0
    elif kind == "exposure":
        out = out * 1.5
    return np.clip(out, 0, 255).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    steady: list[float] = []
    kept: list[tuple[Path, Path]] = []
    turned = 0
    for a, b in pairs(args.root):
        pa, pb = scene._prepared(str(a)), scene._prepared(str(b))
        if pa is None or pb is None or pa.shape != pb.shape:
            continue
        sc = scene.score(pa, pb)
        if sc is None:
            turned += 1
            continue
        steady.append(sc)
        kept.append((a, b))
    s = sorted(steady)
    if not s:
        print("no comparable pairs")
        return
    pct = {p: s[min(len(s) - 1, int(p / 100 * len(s)))] for p in (50, 90, 99, 99.5, 99.9)}
    print(f"TURNED  {turned} pairs looked somewhere else (shift > MAX_SHIFT): not scored")
    print(f"STEADY  {len(s)} pairs from the same place: p50 {pct[50]:.3f}, p90 {pct[90]:.3f}, "
          f"p99 {pct[99]:.3f}, p99.5 {pct[99.5]:.3f}, p99.9 {pct[99.9]:.3f}, max {s[-1]:.3f}")
    for th in THRESHOLDS:
        print(f"        ≥ {th:.2f}: {sum(v >= th for v in s)} of {len(s)} steady pairs "
              f"({100 * sum(v >= th for v in s) / len(s):.2f} %)")

    rng = random.Random(args.seed)
    sample = rng.sample(kept, min(args.sample, len(kept)))
    kinds = ("occluder15", "occluder30", "light20", "exposure")
    scores: dict[str, list[float]] = {k: [] for k in kinds}
    for a, b in sample:
        base = scene._prepared(str(a))
        img = cv2.imread(str(b), cv2.IMREAD_GRAYSCALE)
        if base is None or img is None:
            continue
        for k in kinds:
            sc = scene.score(base, prepared_from(plant(img, k)))
            scores[k].append(sc if sc is not None else 0.0)
    print(f"PLANTED {len(sample)} pairs")
    for th in THRESHOLDS:
        found = "  ".join(f"{k} {sum(v >= th for v in scores[k])}/{len(scores[k])}"
                          for k in kinds)
        print(f"        ≥ {th:.2f}: {found}")


if __name__ == "__main__":
    main()
