"""Score a cleaner on real flights with planted faults — the acceptance numbers
of docs/handoffs/sprint-1/undone/dpp-clean.txt, and the comparison that let
robust@1 replace hampel@1 (MEASUREMENTS.txt).

For each flight: plant faults (plant_faults.py), load the result the way the
pipeline does (LocalFlightSource), clean it as one point, and report

  caught        planted faults flagged with the right column AND kind (want 100 %)
  false flags   unplanted values flagged, over every checked value (want <= 1 %)
                — temperature and pressure only, the columns both cleaners check.
                A gap the recording itself proves (a skipped index, lost time)
                is not false: it is there.
  ramp flags    flags inside the planted hand-warmer ramp (want 0)
  ms            time to clean the flight as one point, on this machine

and, for robust@1's position and battery checks, a second planting
(plant_extras): caught, and the flags those columns raise on the real flight.

    cd backend/agent && .venv/bin/python ../../ml/sensor-faults/evaluate.py \\
        [--cleaner robust|hampel] [--seeds 0-4] <flight.csv or folder> [...]
"""

from __future__ import annotations

import argparse
import collections
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# The agent beside this script, not whichever checkout the venv was installed
# from: a score must describe the code it sits next to.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "agent"))

from plant_faults import (  # noqa: E402
    TEMPERATURES,
    Planted,
    plant,
    plant_extras,
    read,
    real_gaps,
    write,
)

from cropwatcher.pipeline.contracts import Cleaner, FlightContext, ReadingFlag  # noqa: E402
from cropwatcher.pipeline.sources import LocalFlightSource  # noqa: E402
from cropwatcher.pipeline.stages.clean.robust import SENSOR_COLUMNS, RobustCleaner  # noqa: E402

#: The planting needs this many rows (plant_faults.plant raises below it).
MIN_ROWS = 287


def cleaner_named(name: str) -> Cleaner:
    if name == "robust":
        return RobustCleaner()
    if name == "hampel":
        # hampel@1 left the agent when robust@1 replaced it (2026-10-09); it is
        # scored from the commit that last held it, for the comparison only.
        from hampel_v1 import HampelCleaner
        return HampelCleaner()
    raise SystemExit(f"unknown cleaner {name!r}: robust or hampel")


@dataclass(frozen=True)
class Score:
    planted: int
    caught: int
    missed: tuple[tuple[int, str, str], ...]        # index, column, kind
    false_flags: tuple[ReadingFlag, ...]
    checked_values: int
    ramp_flags: tuple[ReadingFlag, ...]
    ms: float
    flags: tuple[ReadingFlag, ...]                  # everything the cleaner flagged

    @property
    def false_rate(self) -> float:
        return len(self.false_flags) / self.checked_values if self.checked_values else 0.0


def _clean(planted: Planted, cleaner: Cleaner,
           workdir: Path | None) -> tuple[tuple[ReadingFlag, ...], int, float]:
    with tempfile.TemporaryDirectory() as tmp:
        root = workdir or Path(tmp)
        write(planted, root)
        flight = LocalFlightSource(root).load(planted.rows[0]["flight_id"])
        point = flight.whole
        ctx = FlightContext(flight.flight_id, None, flight.temp_unit, None,
                            flight.started_at, root / "work")
        start = time.perf_counter()
        result = cleaner.clean(point, ctx)
        ms = (time.perf_counter() - start) * 1000
    checked = sum(1 for r in point.readings for c in r.values if c in SENSOR_COLUMNS)
    return result.flags, checked, ms


def evaluate(rows: list[dict[str, str]], seed: int = 0, workdir: Path | None = None,
             cleaner: Cleaner | None = None) -> Score:
    cleaner = cleaner or RobustCleaner()
    planted = plant(rows, seed)
    flags, checked, ms = _clean(planted, cleaner, workdir)

    truth = {(i, c or None): k for i, c, k in planted.truth}
    for gap in real_gaps(rows):
        truth.setdefault((gap, None), "gap")
    planted_truth = {(i, c or None) for i, c, _ in planted.truth}
    got = {(f.index, f.column): f for f in flags}
    missed = tuple((i, c or "", k) for (i, c), k in truth.items()
                   if (i, c) in planted_truth and ((i, c) not in got or got[(i, c)].kind != k))
    false_flags = tuple(f for key, f in got.items()
                        if key not in truth and (f.column is None or f.column in SENSOR_COLUMNS))
    # The ramp is planted in the TEMPERATURES; a flag there is the rule broken.
    ramp = tuple(f for f in flags for first, last, _ in planted.events
                 if first <= f.index <= last and f.column in TEMPERATURES
                 and (f.index, f.column) not in truth)
    return Score(len(planted_truth), len(planted_truth) - len(missed), missed, false_flags,
                 checked, ramp, ms, flags)


@dataclass(frozen=True)
class ExtraScore:
    planted: int
    caught: int
    missed: tuple[tuple[int, str, str], ...]
    real_flags: collections.Counter[tuple[str, str]]   # (column, kind) on unplanted values


def evaluate_extras(rows: list[dict[str, str]], seed: int = 0,
                    cleaner: Cleaner | None = None) -> ExtraScore:
    cleaner = cleaner or RobustCleaner()
    planted = plant_extras(rows, seed)
    flags, _, _ = _clean(planted, cleaner, None)
    truth = {(i, c): k for i, c, k in planted.truth}
    got = {(f.index, f.column): f for f in flags}
    missed = tuple((i, c, k) for (i, c), k in truth.items()
                   if (i, c) not in got or got[(i, c)].kind != k)
    real = collections.Counter((f.column or "", f.kind) for key, f in got.items()
                               if key not in truth and f.column not in SENSOR_COLUMNS
                               and f.column is not None)
    return ExtraScore(len(truth), len(truth) - len(missed), missed, real)


def _flights(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        found += sorted(path.glob("*/flight_*.csv")) if path.is_dir() else [path]
    return found


def _seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(text)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", nargs="+", type=Path,
                        help="real flight CSVs, or a data folder's flights/")
    parser.add_argument("--cleaner", default="robust")
    parser.add_argument("--seeds", default="0")
    parser.add_argument("--quiet", action="store_true", help="totals only")
    args = parser.parse_args()
    cleaner = cleaner_named(args.cleaner)
    total = collections.Counter[str]()
    extras_real = collections.Counter[tuple[str, str]]()
    kinds = collections.Counter[tuple[str, str]]()
    for path in _flights(args.csv):
        rows = read(path)
        if len(rows) < MIN_ROWS:
            total["skipped (too short to plant)"] += 1
            continue
        total["flights"] += 1
        for seed in _seeds(args.seeds):
            try:
                s = evaluate(rows, seed, cleaner=cleaner)
            except ValueError:          # this seed's planting needs more rows
                total["seed runs too short"] += 1
                continue
            total["planted"] += s.planted
            total["caught"] += s.caught
            total["false"] += len(s.false_flags)
            total["checked"] += s.checked_values
            total["ramp"] += len(s.ramp_flags)
            total["ms"] += round(s.ms)
            total["runs"] += 1
            for f in s.false_flags:
                kinds[(f.column or "row", f.kind)] += 1
            if not args.quiet:
                print(f"{path.name} seed {seed}: caught {s.caught}/{s.planted} · false flags "
                      f"{len(s.false_flags)}/{s.checked_values} ({s.false_rate:.2%}) · "
                      f"ramp flags {len(s.ramp_flags)} · {s.ms:.1f} ms")
                for miss in s.missed:
                    print(f"  MISSED   {miss}")
                for flag in (*s.false_flags, *s.ramp_flags):
                    print(f"  FLAGGED  {flag.index} {flag.column} {flag.kind}: {flag.reason}")
            if args.cleaner == "robust":
                e = evaluate_extras(rows, seed, cleaner)
                total["extra planted"] += e.planted
                total["extra caught"] += e.caught
                extras_real.update(e.real_flags)
    runs = max(total["runs"], 1)
    print(f"\n{args.cleaner}: {total['flights']} flights × {len(_seeds(args.seeds))} seeds "
          f"({total['skipped (too short to plant)']} too short)")
    print(f"  caught       {total['caught']}/{total['planted']} "
          f"({total['caught'] / max(total['planted'], 1):.2%})")
    print(f"  false flags  {total['false']}/{total['checked']} "
          f"({total['false'] / max(total['checked'], 1):.3%})  {kinds.most_common(6)}")
    print(f"  ramp flags   {total['ramp']}")
    print(f"  mean time    {total['ms'] / runs:.1f} ms per flight")
    if args.cleaner == "robust":
        print(f"  position/battery caught {total['extra caught']}/{total['extra planted']}")
        print(f"  position/battery flags on the real flights (all seeds): "
              f"{extras_real.most_common(8)}")


if __name__ == "__main__":
    main()
