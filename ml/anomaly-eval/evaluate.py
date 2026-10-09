"""Choose the classifier's block settings on REAL flights: how often a normal
flight raises an event (want ~never), and whether a planted one is found.

For every flight on the laptop with enough airborne readings:
  1. NORMAL — clean it (the agent's cleaner) and classify it as recorded. The
     corpus holds no known heat source, so every event here is a false alarm
     (or a real event nobody planned — they are listed to be looked at).
  2. PLANTED — the same flight with one event added to the raw readings:
       a temperature BUMP (rise 5 s, hold 5 s, fall 5 s) of 1, 2, 3 or 5 °C on
       raw_temp and corrected_temp — the drone passing something warm;
       a pressure STEP of 0.3 or 0.5 hPa held 5 s (0.5 s edges).
     Found = an event of that signal, that direction, overlapping the window.

Bumps are planted only in flights with at least MIN_AIRBORNE readings in the
air (60 s, a real mission's length): an event needs normal flight around it
to stand out against — one that fills most of a short flight cannot be told
from that flight's own baseline, by this method or any other that has no
reference but the flight itself.

The fits are done once per flight; PELT and the threshold are re-run per
setting, so the grid is cheap. It also prints how far the blocks of the
NORMAL flights wander — what the physical minimums must stay above.

    cd backend/agent && .venv/bin/python ../../ml/anomaly-eval/evaluate.py \\
        "<data folder>" [--grid] [--seed 0]
"""

from __future__ import annotations

import argparse
import collections
import csv
import itertools
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "agent"))

from cropwatcher.pipeline.contracts import (
    CleanResult,
    FlightContext,
    PointData,
)
from cropwatcher.pipeline.sources import LocalFlightSource
from cropwatcher.pipeline.stages.classify import blocks
from cropwatcher.pipeline.stages.classify.pelt import pelt

try:                                    # the agent's own cleaner, where it has one
    from cropwatcher.pipeline.stages.clean.robust import RobustCleaner as Cleaner
except ImportError:                     # pragma: no cover — a branch without it
    from cropwatcher.pipeline.stages.clean.stub import StubCleaner as Cleaner

BUMPS_C = (1.0, 2.0, 3.0, 5.0)
STEPS_HPA = (0.3, 0.5)
EDGE, HOLD = 50, 50                     # readings: 5 s up, 5 s held, 5 s down
MIN_AIRBORNE = 600                      # readings: 60 s in the air


@dataclass(frozen=True)
class Prepared:
    """One signal of one flight, fitted: everything PELT needs."""

    signal: str
    residual: np.ndarray
    sigma: float
    spread: float
    runs: list[slice]
    indexes: np.ndarray                 # Reading.index per value


def prepare(data: PointData, clean: CleanResult, ctx: FlightContext) -> list[Prepared]:
    airborne = blocks._airborne(data.readings)
    out = []
    for series in (blocks._temperature(data.readings, airborne, clean, ctx.temp_unit),
                   blocks._pressure(data.readings, airborne, clean)):
        if isinstance(series, str):
            continue
        fit = blocks.fit_cooling(series.t, series.y) if series.signal == "temperature" \
            else blocks.fit_line(series.t, series.y)
        r = series.y - fit.expected
        out.append(Prepared(series.signal, r, blocks.noise(r),
                            blocks.MAD_TO_SIGMA * blocks._mad(r),
                            blocks._runs(series.positions, data.readings),
                            np.array([data.readings[int(i)].index for i in series.positions])))
    return out


def events(p: Prepared, pen: float, min_block: int, z: float,
           minimum: float) -> list[tuple[int, int, float]]:
    """(first index, last index, level) of every event under these settings."""
    if p.sigma <= 0:
        return []
    found = []
    threshold = max(z * p.sigma, minimum)
    for run in p.runs:
        r = p.residual[run]
        if len(r) < min_block:
            continue
        idx = p.indexes[run]
        flagged = []
        start = 0
        for end in pelt(r, pen * p.sigma ** 2 * math.log(max(len(r), 2)), min_block):
            level = float(r[start:end].mean())
            if abs(level) >= threshold:
                flagged.append((start, end, level))
            start = end
        for a, b, _peak in blocks._merge(flagged):         # one event, as the stage does
            found.append((int(idx[a]), int(idx[b - 1]), float(r[a:b].mean())))
    return found


def plant(rows: list[dict[str, str]], first: int, kind: str, size: float) -> tuple[int, int]:
    """Add the event to rows in place; return its first and last index."""
    unit_f = rows[0].get("temp_unit") == "F"
    if kind == "bump":
        shape = [*(k / EDGE for k in range(EDGE)), *([1.0] * HOLD),
                 *(1 - k / EDGE for k in range(EDGE))]
        columns = ("raw_temp", "corrected_temp")
        amount = size * 9 / 5 if unit_f else size
    else:
        shape = [*(k / 5 for k in range(5)), *([1.0] * HOLD), *(1 - k / 5 for k in range(5))]
        columns = ("station_pressure_hpa",)
        amount = size
    for k, lift in enumerate(shape):
        for c in columns:
            rows[first + k][c] = repr(float(rows[first + k][c]) + amount * lift)
    return int(float(rows[first]["index"])), int(float(rows[first + len(shape) - 1]["index"]))


def load(rows: list[dict[str, str]], tmp: Path) -> tuple[PointData, FlightContext]:
    folder = tmp / "flights" / "x"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.csv"):
        old.unlink()
    path = folder / f"flight_{rows[0]['flight_id'][:8]}_planted.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    flight = LocalFlightSource(tmp).load(rows[0]["flight_id"])
    ctx = FlightContext(flight.flight_id, None, flight.temp_unit, None, flight.started_at,
                        tmp / "work")
    return flight.whole, ctx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tmp", type=Path, default=Path("/tmp/anomaly-eval"))
    args = parser.parse_args()
    rng = random.Random(args.seed)
    cleaner = Cleaner()
    print(f"cleaner: {cleaner.name}@{cleaner.version}")

    normal: list[tuple[str, list[Prepared]]] = []
    planted: list[tuple[str, str, float, tuple[int, int], list[Prepared]]] = []
    for path in sorted(args.data.glob("flights/*/flight_*.csv")):
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        if len(rows) < 100:
            continue
        data, ctx = load(rows, args.tmp)
        prepared = prepare(data, cleaner.clean(data, ctx), ctx)
        if not prepared:
            continue
        normal.append((path.name, prepared))
        airborne = blocks._airborne(data.readings)
        if len(airborne) < MIN_AIRBORNE:
            continue
        lo, hi = int(airborne[0]) + 20, int(airborne[-1]) - (2 * EDGE + HOLD) - 20
        if hi <= lo:
            continue
        for kind, sizes in (("bump", BUMPS_C), ("step", STEPS_HPA)):
            for size in sizes:
                copy = [dict(r) for r in rows]
                window = plant(copy, rng.randint(lo, hi), kind, size)
                pdata, pctx = load(copy, args.tmp)
                planted.append((path.name, kind, size, window,
                                prepare(pdata, cleaner.clean(pdata, pctx), pctx)))

    print(f"{len(normal)} flights analysed; {len(planted)} planted runs "
          f"({len(planted) // (len(BUMPS_C) + len(STEPS_HPA))} flights long enough)")

    def minimum(signal: str, min_c: float, min_hpa: float) -> float:
        return min_c if signal == "temperature" else min_hpa

    def wander(pen: float, min_block: int) -> None:
        """The largest |block mean| of each NORMAL flight, per signal."""
        for signal in ("temperature", "pressure"):
            tops = []
            for _, prepared in normal:
                for p in prepared:
                    if p.signal != signal or p.sigma <= 0:
                        continue
                    top = 0.0
                    for run in p.runs:
                        r = p.residual[run]
                        if len(r) < min_block:
                            continue
                        start = 0
                        for end in pelt(r, pen * p.sigma ** 2 * math.log(max(len(r), 2)),
                                        min_block):
                            top = max(top, abs(float(r[start:end].mean())))
                            start = end
                    tops.append(top)
            q = np.percentile(tops, [50, 90, 95, 99, 100]) if tops else []
            print(f"  {signal:11} largest block per normal flight: p50 {q[0]:.3f} · "
                  f"p90 {q[1]:.3f} · p95 {q[2]:.3f} · p99 {q[3]:.3f} · max {q[4]:.3f}"
                  if len(q) else f"  {signal}: none")

    def score(pen: float, min_block: int, z: float, min_c: float,
              min_hpa: float) -> tuple[dict[str, float], list[str]]:
        false = collections.Counter[str]()
        flights_with = collections.Counter[str]()
        listed = []
        for name, prepared in normal:
            for p in prepared:
                found = events(p, pen, min_block, z, minimum(p.signal, min_c, min_hpa))
                false[p.signal] += len(found)
                flights_with[p.signal] += bool(found)
                listed += [f"{name} {p.signal} {a}–{b} {lvl:+.3f}" for a, b, lvl in found]
        hits = collections.Counter[tuple[str, float]]()
        tries = collections.Counter[tuple[str, float]]()
        for _, kind, size, (a, b), prepared in planted:
            signal = "temperature" if kind == "bump" else "pressure"
            for p in prepared:
                if p.signal != signal:
                    continue
                tries[(kind, size)] += 1
                hits[(kind, size)] += any(
                    lvl > 0 and s <= b and e >= a
                    for s, e, lvl in events(p, pen, min_block, z,
                                            minimum(p.signal, min_c, min_hpa)))
        out = {f"false {s}": false[s] / max(len(normal), 1) for s in ("temperature", "pressure")}
        out |= {f"flights with a {s} event": flights_with[s] / max(len(normal), 1)
                for s in ("temperature", "pressure")}
        out |= {f"found {k} {v}": hits[(k, v)] / max(tries[(k, v)], 1) for k, v in tries}
        return out, listed

    print("\nWANDER (PEN 8, MIN_BLOCK 20):")
    wander(8.0, 20)
    if args.grid:
        print("\n  PEN  Z   min°C minhPa | false/flight T  P | found bump 1 2 3 5 °C | "
              "step 0.3 0.5 hPa")
        for pen, z, mc, mp in itertools.product((8, 16), (4, 6), (0.3, 0.5, 0.8, 1.0),
                                                (0.1, 0.15, 0.2, 0.3)):
            s, _ = score(pen, 20, z, mc, mp)
            print(f"  {pen:<4} {z:<3} {mc:<5} {mp:<6} | {s['false temperature']:.2f} "
                  f"{s['false pressure']:.2f} | " + " ".join(
                      f"{s.get(f'found bump {v}', 0):.2f}" for v in BUMPS_C) + " | " + " ".join(
                      f"{s.get(f'found step {v}', 0):.2f}" for v in STEPS_HPA))
    s, listed = score(blocks.PEN, blocks.MIN_BLOCK, blocks.Z_EVENT, blocks.MIN_EVENT_C,
                      blocks.MIN_EVENT_HPA)
    print(f"\nTHE SETTINGS IN blocks.py (PEN {blocks.PEN}, MIN_BLOCK {blocks.MIN_BLOCK}, "
          f"Z_EVENT {blocks.Z_EVENT}, MIN_EVENT_C {blocks.MIN_EVENT_C}, "
          f"MIN_EVENT_HPA {blocks.MIN_EVENT_HPA}):")
    for key, value in s.items():
        print(f"  {key:30} {value:.3f}")
    print("  events on the unplanted flights:")
    for line in listed[:40]:
        print(f"    {line}")


if __name__ == "__main__":
    main()
