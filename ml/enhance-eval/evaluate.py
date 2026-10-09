"""Choose the enhancer's settings, and the frame-quality limits, on REAL frames.

Samples frames recorded by the AI deck (sessions/*/frames/*.png in the agent's
data folder), measures each original's quality, runs CLAHE at several
settings, and prints the numbers RESULTS.txt quotes. Writes a before/after
sheet to --out (never committed: the repository is public, the frames are the
lab's).

    cd backend/agent && .venv/bin/python ../../ml/enhance-eval/evaluate.py \\
        --data "<data folder>" --n 400 --out /tmp/enhance-eval
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "agent"))

from cropwatcher.pipeline.stages.enhance.clahe import (  # noqa: E402
    CLIP_LIMIT,
    TILE_GRID,
    measure_quality,
)

SETTINGS = [(1.5, 8), (2.0, 8), (3.0, 8), (2.0, 4), (3.0, 4)]


def entropy(img: np.ndarray) -> float:
    hist = np.bincount(img.ravel(), minlength=256).astype(float)
    p = hist[hist > 0] / hist.sum()
    return float(-(p * np.log2(p)).sum())


def flat_noise(img: np.ndarray, mask: np.ndarray) -> float:
    """Pixel noise where the ORIGINAL is smooth: what an enhancer adds there is
    grain, not detail (Kevin's "flat texture" idea, ml/upscaling-eval)."""
    lap = cv2.Laplacian(img, cv2.CV_64F)
    return float(lap[mask].std()) if mask.any() else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--n", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    frames = sorted(args.data.glob("sessions/*/frames/*.png"))
    rng = random.Random(args.seed)
    sample = rng.sample(frames, min(args.n, len(frames)))
    print(f"{len(frames)} frames recorded; {len(sample)} sampled")

    qualities = [measure_quality(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)) for p in sample]
    for name in ("sharpness", "brightness", "dark_share", "bright_share"):
        vals = sorted(getattr(q, name) for q in qualities)
        pct = [vals[int(len(vals) * f)] for f in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95)]
        print(f"  {name:13} p1 {pct[0]:.4g} · p5 {pct[1]:.4g} · p25 {pct[2]:.4g} · "
              f"p50 {pct[3]:.4g} · p75 {pct[4]:.4g} · p95 {pct[5]:.4g}")
    unusable = [q for q in qualities if not q.usable]
    print(f"  unusable by the current limits: {len(unusable)} "
          f"({len(unusable) / len(qualities):.1%}): "
          f"{sorted({q.reason.split(':')[0] for q in unusable if q.reason})}")

    print("\n  setting        contrast×   entropy +bits   flat grain×   ms/frame")
    for clip, tile in SETTINGS:
        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
        gains, ents, grains, ms = [], [], [], []
        for path in sample:
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            start = time.perf_counter()
            out = clahe.apply(img)
            ms.append((time.perf_counter() - start) * 1000)
            grad = cv2.Laplacian(cv2.GaussianBlur(img, (5, 5), 0), cv2.CV_64F)
            flat = np.abs(grad) < np.percentile(np.abs(grad), 30)
            gains.append(out.std() / max(img.std(), 1e-6))
            ents.append(entropy(out) - entropy(img))
            grains.append(flat_noise(out, flat) / max(flat_noise(img, flat), 1e-6))
        print(f"  clip {clip:<3} {tile}×{tile}     {statistics.median(gains):.2f}        "
              f"{statistics.median(ents):+.2f}          {statistics.median(grains):.2f}"
              f"          {statistics.median(ms):.2f}")

    args.out.mkdir(parents=True, exist_ok=True)
    clahe = cv2.createCLAHE(clipLimit=CLIP_LIMIT, tileGridSize=TILE_GRID)
    rows = []
    for path in sample[:8]:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        rows.append(np.hstack([img, np.full((img.shape[0], 4), 255, np.uint8), clahe.apply(img)]))
    cv2.imwrite(str(args.out / "before-after.png"), np.vstack(rows))
    print(f"\n  sheet: {args.out / 'before-after.png'} (left original, right the enhancer's CLAHE)")


if __name__ == "__main__":
    main()
