"""Score the cleaner on real flights with planted faults — the ticket's
acceptance numbers (docs/handoffs/sprint-1/undone/dpp-clean.txt, ACCEPTANCE).

For each flight: plant faults (plant_faults.py), load the result the way the
pipeline does (LocalFlightSource), clean it as one point, and report

  caught        planted faults flagged with the right column AND kind (want 100 %)
  false flags   unplanted values flagged, over every checked value (want <= 1 %)
  ramp flags    flags inside the planted hand-warmer ramp (want 0)
  ms            time to clean the flight as one point, on this machine

    cd backend/agent && .venv/bin/python ../../ml/sensor-faults/evaluate.py <flight.csv> [...]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from plant_faults import plant, read, write  # noqa: E402

from cropwatcher.pipeline.contracts import FlightContext, ReadingFlag  # noqa: E402
from cropwatcher.pipeline.sources import LocalFlightSource  # noqa: E402
from cropwatcher.pipeline.stages.clean.hampel import COLUMNS, HampelCleaner  # noqa: E402


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


def evaluate(rows: list[dict[str, str]], seed: int = 0, workdir: Path | None = None) -> Score:
    planted = plant(rows, seed)
    with tempfile.TemporaryDirectory() as tmp:
        root = workdir or Path(tmp)
        write(planted, root)
        flight = LocalFlightSource(root).load(planted.rows[0]["flight_id"])
        (point,) = flight.points                      # no mission: the whole flight
        ctx = FlightContext(flight.flight_id, None, flight.temp_unit, None,
                            flight.started_at, root / "work")
        start = time.perf_counter()
        result = HampelCleaner().clean(point, ctx)
        ms = (time.perf_counter() - start) * 1000

    truth = {(i, c or None): k for i, c, k in planted.truth}
    got = {(f.index, f.column): f for f in result.flags}
    missed = tuple((i, c or "", k) for (i, c), k in truth.items()
                   if (i, c) not in got or got[(i, c)].kind != k)
    false_flags = tuple(f for key, f in got.items() if key not in truth)
    names = {c.name for c in COLUMNS}
    checked = sum(1 for r in point.readings for c in r.values if c in names)
    ramp = tuple(f for f in result.flags for first, last, _ in planted.events
                 if first <= f.index <= last)
    return Score(len(truth), len(truth) - len(missed), missed, false_flags, checked,
                 ramp, ms, result.flags)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", nargs="+", type=Path, help="real flight CSVs")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    for path in args.csv:
        s = evaluate(read(path), args.seed)
        print(f"{path.name}: caught {s.caught}/{s.planted} · false flags "
              f"{len(s.false_flags)}/{s.checked_values} ({s.false_rate:.2%}) · "
              f"ramp flags {len(s.ramp_flags)} · {s.ms:.1f} ms")
        for miss in s.missed:
            print(f"  MISSED   {miss}")
        for flag in (*s.false_flags, *s.ramp_flags):
            print(f"  FLAGGED  {flag.index} {flag.column} {flag.kind}: {flag.reason}")


if __name__ == "__main__":
    main()
