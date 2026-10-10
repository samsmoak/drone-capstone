"""Score every candidate on a prepared set.

    python score.py --set camera-frames
    python score.py --set photos --methods bicubic-x2,fsrcnn-x2

Writes data/runs/<set>/: each method's outputs (<method>/<id>.png), every
image's scores (scores.csv), each method's time (timings.csv) and the table
(summary.txt, also printed) that RESULTS.txt is written from. A run of some
methods replaces those methods' rows and keeps the rest, so the table always
covers every method scored so far.

WHAT EACH COLUMN MEANS
  PSNR, SSIM    against the truth (prepare.py, THE PROTOCOL), with the border
                and any crosshair left out. Δ is against bicubic at the same
                scale — the number that says whether a model earned its file.
  edges kept    fine detail on the truth's strongest edges (top 10 %),
                output ÷ truth. Below 1 blurs real detail; above 1 oversharpens.
  flat texture  fine detail where the truth is smooth (bottom 50 %), output ÷
                truth. ABOVE 1 IS DETAIL THAT IS NOT THERE — invented texture
                or amplified noise. The number dpp-enhance.txt asks for beside
                sharpness: on an inspection drone an invented crack is a false
                alarm.
  ms/frame      median, warm, on real 324×244 frames whatever the protocol —
                the size the stage will see. 20 frames = the contract's
                target (< 2 s).
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import statistics
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from common import FRAME_H, FRAME_W, RUNS, Item, load_set, metric_mask, shrink, write_png
from methods import METHODS, Method, pick
from skimage.metrics import structural_similarity


def pair(item: Item, img: np.ndarray, scale: int) -> tuple[np.ndarray, np.ndarray] | None:
    """(input, truth) for a method of this scale, or None if this image cannot be truth for it."""
    if item.protocol == "reference":
        tw, th = FRAME_W * scale, FRAME_H * scale
        if tw > img.shape[1] or th > img.shape[0]:
            return None
        return shrink(img, FRAME_W, FRAME_H), shrink(img, tw, th)
    truth = shrink(img, FRAME_W, FRAME_H)
    if scale == 1:
        return truth, truth
    return shrink(truth, FRAME_W // scale, FRAME_H // scale), truth


def high_pass(img: np.ndarray) -> np.ndarray:
    f = img.astype(np.float32)
    return np.abs(f - cv2.GaussianBlur(f, (0, 0), 1.0))


SCORE_KEYS = ["psnr", "ssim", "edges_kept", "flat_texture"]


def scores(truth: np.ndarray, out: np.ndarray, keep: np.ndarray) -> dict[str, float]:
    t, o = truth.astype(np.float64), out.astype(np.float64)
    mse = float(((t - o)[keep] ** 2).mean())
    _, ssim_map = structural_similarity(truth, out, data_range=255, full=True)
    hp_t, hp_o = high_pass(truth)[keep], high_pass(out)[keep]
    flat = hp_t <= np.percentile(hp_t, 50)
    edges = hp_t >= np.percentile(hp_t, 90)
    return {
        "psnr": 10 * np.log10(255**2 / mse) if mse > 0 else float("inf"),
        "ssim": float(ssim_map[keep].mean()),
        "edges_kept": float(hp_o[edges].mean() / max(hp_t[edges].mean(), 1e-6)),
        "flat_texture": float(hp_o[flat].mean() / max(hp_t[flat].mean(), 1e-6)),
    }


def time_per_frame(method: Method, frames: list[np.ndarray]) -> float:
    method.fn(frames[0])  # warm: model load and first-call allocation are not per-frame costs
    times = []
    for f in frames:
        t = time.perf_counter()
        method.fn(f)
        times.append(time.perf_counter() - t)
    return statistics.median(times)


def merge(
    path: Path, fresh: list[dict[str, object]], redone: set[str], ids: set[str]
) -> list[dict[str, str]]:
    """The rows already in `path` that this run did not redo, plus this run's.

    A run of some methods updates those methods and keeps every other one, so
    the table always covers everything scored so far. Rows for images no longer
    in the set (prepare.py was re-run) are dropped: they were scored on other
    inputs. Timing rows carry no image id and are kept regardless."""
    kept: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="") as fh:
            kept = [
                r
                for r in csv.DictReader(fh)
                if r["method"] not in redone and r.get("id", "") in ids | {""}
            ]
    return kept + [{k: str(v) for k, v in r.items()} for r in fresh]


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--set", required=True)
    ap.add_argument("--methods", default="all", help='"all" or comma-separated names (methods.py)')
    args = ap.parse_args()

    items = load_set(args.set)
    images = {i.id: i.image() for i in items}
    methods = pick(args.methods)
    run_dir = RUNS / args.set
    run_dir.mkdir(parents=True, exist_ok=True)
    cpu = f"{platform.processor() or platform.machine()} · {os.cpu_count()} threads"

    fresh: list[dict[str, object]] = []
    for m in methods:
        for item in items:
            p = pair(item, images[item.id], m.scale)
            if p is None:
                continue
            inp, truth = p
            out = m.fn(inp)
            write_png(run_dir / m.name / f"{item.id}.png", out)
            keep = metric_mask(truth.shape, item.mask, border=m.scale)
            fresh.append({"method": m.name, "id": item.id, **scores(truth, out, keep)})
        print(f"scored {m.name}")

    real_frames = [shrink(images[i.id], FRAME_W, FRAME_H) for i in items]
    fresh_times: list[dict[str, object]] = [
        {"method": m.name, "sec": time_per_frame(m, real_frames), "cpu": cpu} for m in methods
    ]

    redone, ids = {m.name for m in methods}, {i.id for i in items}
    rows = merge(run_dir / "scores.csv", fresh, redone, ids)
    times = merge(run_dir / "timings.csv", fresh_times, redone, ids)
    write_csv(run_dir / "scores.csv", rows, ["method", "id", *SCORE_KEYS])
    write_csv(run_dir / "timings.csv", times, ["method", "sec", "cpu"])

    by_method: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_method[r["method"]].append(r)
    sec_of = {r["method"]: float(r["sec"]) for r in times}
    # every method scored so far, in the registry's order; a renamed one is dropped
    shown = [m for m in METHODS if m.name in sec_of]

    def mean(name: str, key: str) -> float:
        return statistics.fmean(float(r[key]) for r in by_method[name])

    protocols = sorted({i.protocol for i in items})
    lines = [
        f"set {args.set}: {len(items)} images, protocol {'/'.join(protocols)}"
        f"{', crosshair masked' if any(i.mask for i in items) else ''}",
        f"cpu {' and '.join(sorted({r['cpu'] for r in times}))} · "
        f"opencv {cv2.__version__} ({cv2.getNumThreads()} threads)",
        "",
        f"{'method':36s} {'×':>2s} {'n':>3s} {'PSNR':>6s} {'ΔPSNR':>6s} {'SSIM':>6s} "
        f"{'ΔSSIM':>7s} {'edges':>6s} {'flat':>6s} {'ms/fr':>7s} {'20 fr':>6s} {'MB':>5s}",
        f"{'':36s} {'':>2s} {'':>3s} {'dB':>6s} {'dB':>6s} {'':>6s} {'':>7s} "
        f"{'kept':>6s} {'textr':>6s} {'':>7s} {'s':>6s} {'':>5s}",
    ]
    for m in shown:
        sec = sec_of[m.name]
        if not by_method[m.name]:
            lines.append(
                f"{m.name:36s} {m.scale:>2d}   — no image can be truth at ×{m.scale} "
                f"· {sec * 1000:7.1f} ms/frame"
            )
            continue
        base = f"bicubic-x{m.scale}"
        psnr, ssim = mean(m.name, "psnr"), mean(m.name, "ssim")
        has_base = bool(by_method.get(base)) and m.scale > 1
        dpsnr = f"{psnr - mean(base, 'psnr'):+6.2f}" if has_base else f"{'':>6s}"
        dssim = f"{ssim - mean(base, 'ssim'):+7.4f}" if has_base else f"{'':>7s}"
        lines.append(
            f"{m.name:36s} {m.scale:>2d} {len(by_method[m.name]):>3d} "
            f"{psnr:6.2f} {dpsnr} {ssim:6.4f} {dssim} "
            f"{mean(m.name, 'edges_kept'):6.2f} {mean(m.name, 'flat_texture'):6.2f} "
            f"{sec * 1000:7.1f} {sec * 20:6.2f} {m.model_mb():5.2f}"
        )

    summary = "\n".join(lines)
    (run_dir / "summary.txt").write_text(summary + "\n")
    print()
    print(summary)


if __name__ == "__main__":
    main()
