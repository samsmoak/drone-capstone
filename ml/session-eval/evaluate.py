"""Choose the GROUND classifier's settings on REAL sessions (ground@1,
backend/agent/cropwatcher/pipeline/stages/classify/ground.py): how often a
normal session raises an event on the ground (want ~never), and whether a
planted one is found.

For every session on the laptop with samples.csv:
  0. TIMING — the period between samples, and the longest run of identical
     values (what the cleaner's gap and stuck limits must allow at 1 Hz).
  1. NORMAL — clean it (the agent's cleaner, at 1 Hz) and classify its ground
     stretches as recorded. The corpus holds no known heat source, so every
     event is a false alarm (or a real event nobody planned — listed).
  2. WANDER — how far the blocks of normal ground stretches wander from their
     fit: what the physical minimums must stay above.
  3. PLANTED — the same session with one event added to the raw samples, in a
     ground stretch long enough to hold it with normal readings around it:
       a temperature BUMP (rise EDGE s, hold HOLD s, fall EDGE s) of 1, 2, 3
       or 5 °C on baro.temp — something warm beside the drone;
       a pressure STEP of 0.3 or 0.5 hPa held HOLD s.
     Found = an event of that signal and direction overlapping the window.

    cd backend/agent && .venv/bin/python ../../ml/session-eval/evaluate.py \\
        "<data folder>" [--grid] [--seed 0]
"""

from __future__ import annotations

import argparse
import collections
import csv
import itertools
import math
import random
import shutil
import statistics
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "agent"))

from cropwatcher.pipeline.contracts import FlightContext  # noqa: E402
from cropwatcher.pipeline.sources import LocalSessionSource, SessionNotFound  # noqa: E402
from cropwatcher.pipeline.stages.classify import blocks, ground  # noqa: E402
from cropwatcher.pipeline.stages.classify.pelt import pelt  # noqa: E402
from cropwatcher.pipeline.stages.clean.robust import RobustCleaner  # noqa: E402

BUMPS_C = (1.0, 2.0, 3.0, 5.0)
STEPS_HPA = (0.3, 0.5)
EDGE, HOLD = 10, 20                     # samples (s at 1 Hz)
#: Planted only in stretches this long: the event plus normal readings each side.
MIN_PLANT = 2 * (2 * EDGE + HOLD)


def _t(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def timing(root: Path) -> None:
    periods: list[float] = []
    runs: dict[str, list[int]] = {"baro.temp": [], "baro.pressure": []}
    n = rows_total = 0
    for f in sorted((root / "sessions").glob("*/samples.csv")):
        rows = [r for r in csv.DictReader(f.open()) if r.get("recorded_at")]
        if len(rows) < 30:
            continue
        n += 1
        rows_total += len(rows)
        t = [_t(r["recorded_at"]) for r in rows]
        periods += [b - a for a, b in zip(t, t[1:], strict=False)]
        for col, acc in runs.items():
            best = cur = 1
            prev = None
            for r in rows:
                v = r.get(col)
                cur = cur + 1 if v and v == prev else 1
                best = max(best, cur)
                prev = v
            acc.append(best)
    q = sorted(periods)
    print(f"TIMING  {n} sessions, {rows_total} samples: period median "
          f"{statistics.median(q):.3f} s, p99 {q[int(.99 * len(q))]:.3f}, "
          f"p99.9 {q[int(.999 * len(q))]:.3f}, max {q[-1]:.1f}")
    for col, acc in runs.items():
        print(f"        longest identical run of {col}: {max(acc)}")


def prepare(source: LocalSessionSource, sid: str, rows_override: Path | None = None):
    """Clean and fit every ground stretch of a session: (signal, residual,
    sigma, runs, indexes) per stretch, plus the stretches themselves."""
    src = LocalSessionSource(rows_override) if rows_override else source
    s = src.load(sid)
    ctx = FlightContext(sid, sid, "C", None, s.started_at, Path(tempfile.gettempdir()),
                        scope="session", period_s=1.0)
    clean = RobustCleaner().clean(s.whole, ctx)
    readings = s.whole.readings
    out = []
    stretches = ground.ground_stretches(readings)
    for stretch in stretches:
        for series in (blocks._temperature(readings, stretch, clean, "C"),
                       ground._pressure(readings, stretch, clean, 30)):
            if isinstance(series, str):
                continue
            fit = blocks.fit_cooling(series.t, series.y) if series.signal == "temperature" \
                else blocks.fit_line(series.t, series.y)
            r = series.y - fit.expected
            out.append((series.signal, r, blocks.noise(r),
                        blocks._runs(series.positions, readings, ground.GROUND_RUN_GAP_S),
                        np.array([readings[int(i)].index for i in series.positions]),
                        len(stretch)))
    return out, [(int(readings[int(st[0])].index), int(readings[int(st[-1])].index))
                 for st in stretches]


def events(prep, pen: float, min_block: int, z: float, minimum: dict[str, float],
           min_stretch: int):
    found = []
    for signal, r_all, sigma, runs, idx_all, stretch_len in prep:
        if stretch_len < min_stretch or sigma <= 0:
            continue
        threshold = max(z * sigma, minimum[signal])
        for run in runs:
            r = r_all[run]
            if len(r) < min_block:
                continue
            idx = idx_all[run]
            flagged, start = [], 0
            for end in pelt(r, pen * sigma ** 2 * math.log(max(len(r), 2)), min_block):
                level = float(r[start:end].mean())
                if abs(level) >= threshold:
                    flagged.append((start, end, level))
                start = end
            for a, b, _p in blocks._merge(flagged):
                found.append((signal, int(idx[a]), int(idx[b - 1]), float(r[a:b].mean())))
    return found


def wander(prep, pen: float, min_block: int) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {"temperature": [], "pressure": []}
    for signal, r_all, sigma, runs, _idx, _n in prep:
        if sigma <= 0:
            continue
        for run in runs:
            r = r_all[run]
            if len(r) < min_block:
                continue
            start = 0
            for end in pelt(r, pen * sigma ** 2 * math.log(max(len(r), 2)), min_block):
                out[signal].append(abs(float(r[start:end].mean())))
                start = end
    return out


def plant_copy(root: Path, sid: str, first: int, kind: str, size: float) -> Path:
    """A copy of the session folder with the event planted at sample `first`
    (1-based seq). Returns the copy's data root."""
    tmp = Path(tempfile.mkdtemp(prefix="plant-"))
    dst = tmp / "sessions" / sid
    dst.mkdir(parents=True)
    for name in ("samples.csv", "meta.json"):
        if (root / "sessions" / sid / name).exists():
            shutil.copy(root / "sessions" / sid / name, dst / name)
    rows = list(csv.DictReader((dst / "samples.csv").open()))
    fields = list(rows[0])
    col = "baro.temp" if kind == "bump" else "baro.pressure"
    length = 2 * EDGE + HOLD if kind == "bump" else HOLD
    for k in range(length):
        i = first - 1 + k
        if i >= len(rows) or not rows[i].get(col):
            continue
        if kind == "bump":
            lift = size * min(k / EDGE, 1.0, (length - 1 - k) / EDGE)
        else:
            lift = size
        rows[i][col] = repr(float(rows[i][col]) + lift)
    with (dst / "samples.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return tmp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    root: Path = args.root
    timing(root)
    source = LocalSessionSource(root)
    sids = sorted(p.parent.name for p in (root / "sessions").glob("*/samples.csv"))
    prepared = {}
    for sid in sids:
        try:
            prepared[sid] = prepare(source, sid)
        except SessionNotFound:
            continue
    lengths = sorted(n for prep, _ in prepared.values() for *_, n in prep[:1])
    stretch_lengths = sorted(b - a + 1 for _, st in prepared.values() for a, b in st)
    print(f"GROUND  {len(prepared)} sessions, {len(stretch_lengths)} ground stretches; "
          f"length median {statistics.median(stretch_lengths) if stretch_lengths else 0} s, "
          f"≥30 s: {sum(n >= 30 for n in stretch_lengths)}, ≥60 s: "
          f"{sum(n >= 60 for n in stretch_lengths)}, ≥{MIN_PLANT} s: "
          f"{sum(n >= MIN_PLANT for n in stretch_lengths)}")
    del lengths

    w = collections.defaultdict(list)
    for prep, _ in prepared.values():
        for k, v in wander(prep, blocks.PEN, ground.MIN_GROUND_BLOCK).items():
            w[k] += v
    for k in ("temperature", "pressure"):
        v = sorted(w[k])
        if v:
            unit = "°C" if k == "temperature" else "hPa"
            print(f"WANDER  {k}: {len(v)} blocks; |mean| p50 {v[len(v) // 2]:.3f}, p99 "
                  f"{v[int(.99 * len(v))]:.3f}, max {v[-1]:.3f} {unit}")

    rng = random.Random(args.seed)
    plants = []
    for sid, (_prep, stretches) in prepared.items():
        for a, b in stretches:
            if b - a + 1 >= MIN_PLANT:
                first = rng.randint(a + EDGE + HOLD // 2, b - (2 * EDGE + HOLD) - HOLD // 2)
                for size in BUMPS_C:
                    plants.append((sid, first, "bump", size))
                for size in STEPS_HPA:
                    plants.append((sid, first, "step", size))
                break
    planted_prep = {}
    for sid, first, kind, size in plants:
        tmp = plant_copy(root, sid, first, kind, size)
        try:
            planted_prep[(sid, first, kind, size)] = prepare(source, sid, tmp)[0]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"PLANTED {len(plants)} events in {len({p[0] for p in plants})} sessions")

    grid = itertools.product((6.0, 8.0, 16.0), (10, 15, 20), (30, 45, 60),
                             (0.6, 0.8, 1.0), (0.15, 0.2, 0.3)) if args.grid else \
        [(blocks.PEN, ground.MIN_GROUND_BLOCK, ground.MIN_GROUND_READINGS,
          ground.MIN_GROUND_EVENT_C, ground.MIN_GROUND_EVENT_HPA)]
    for pen, mb, ms, mc, mh in grid:
        minimum = {"temperature": mc, "pressure": mh}
        false = [(sid, e) for sid, (prep, _) in prepared.items()
                 for e in events(prep, pen, mb, blocks.Z_EVENT, minimum, ms)]
        hit = collections.Counter()
        tried = collections.Counter()
        for (sid, first, kind, size), prep in planted_prep.items():
            length = 2 * EDGE + HOLD if kind == "bump" else HOLD
            signal = "temperature" if kind == "bump" else "pressure"
            tried[(kind, size)] += 1
            if any(s == signal and lv > 0 and a <= first + length - 1 and b >= first
                   for s, a, b, lv in events(prep, pen, mb, blocks.Z_EVENT, minimum, ms)):
                hit[(kind, size)] += 1
        found = " ".join(f"{k}{s:g}:{hit[(k, s)]}/{tried[(k, s)]}"
                         for k, s in sorted(tried))
        print(f"PEN {pen:4.1f} block {mb:2d} stretch {ms:2d} min {mc:.2f}°C/{mh:.2f}hPa | "
              f"false {len(false):3d} | {found}")
        if not args.grid:
            for sid, (signal, a, b, lv) in false:
                print(f"    normal-session event: {sid[:8]} {signal} samples {a}–{b} "
                      f"{lv:+.3f}")


if __name__ == "__main__":
    main()
