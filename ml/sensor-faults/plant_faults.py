"""Plant known sensor faults into a real flight CSV, so the cleaner can be
scored against a ground truth (docs/handoffs/sprint-1/undone/dpp-clean.txt, step 2).

Writes, for each input flight:
  <out>/flights/planted/flight_<id>_planted.csv  the flight with faults planted,
                         named and laid out so LocalFlightSource finds it
  …_planted.truth.csv    index,column,kind — every planted fault
  …_planted.events.csv   first,last,what — REAL events planted (the hand-warmer
                         ramp). Not faults: the cleaner must leave them alone.

Faults are planted one after another with a margin between them, so no fault
sits inside another's Hampel window. Magnitudes are written in °C / hPa and
converted to the flight's own unit.

    cd backend/agent && .venv/bin/python ../../ml/sensor-faults/plant_faults.py \\
        <flight.csv> [...] --out <dir> [--seed 0]
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from pathlib import Path

#: Rows between two planted faults: more than half the cleaner's 11-reading
#: window, so one fault is never another's neighbour.
MARGIN = 8
STUCK_ROWS = 15
#: A hand warmer under the box: +5 °C over 10 s (100 readings), then held.
RAMP_C = 5.0
RAMP_ROWS = 100
RAMP_HOLD_ROWS = 30

TEMPERATURES = ("raw_temp", "corrected_temp")


@dataclass
class Planted:
    rows: list[dict[str, str]]
    truth: list[tuple[int, str, str]] = field(default_factory=list)   # index, column, kind
    events: list[tuple[int, int, str]] = field(default_factory=list)  # first, last, what


def plant(rows: list[dict[str, str]], seed: int = 0) -> Planted:
    """Plant one of every fault the cleaner looks for, then a hand-warmer ramp."""
    if not rows:
        raise ValueError("an empty flight has nowhere to plant a fault")
    rng = random.Random(seed)
    fahrenheit = rows[0].get("temp_unit") == "F"
    rows = [dict(r) for r in rows]
    drop: set[int] = set()
    out = Planted(rows)

    def temp_delta(c: float) -> float:
        return c * 9 / 5 if fahrenheit else c

    def temp_abs(c: float) -> float:
        return c * 9 / 5 + 32 if fahrenheit else c

    def index(pos: int) -> int:
        return int(float(rows[pos]["index"]))

    def spike(pos: int, column: str) -> None:
        size = rng.uniform(2.0, 4.0) * rng.choice((-1, 1))
        if column in TEMPERATURES:
            size = temp_delta(size)
        rows[pos][column] = repr(float(rows[pos][column]) + size)
        out.truth.append((index(pos), column, "spike"))

    def missing(pos: int, column: str, text: str) -> None:
        rows[pos][column] = text
        out.truth.append((index(pos), column, "missing"))

    def out_of_range(pos: int, column: str, value: float) -> None:
        rows[pos][column] = repr(value)
        out.truth.append((index(pos), column, "out_of_range"))

    def stuck(pos: int, column: str) -> None:
        held = rows[pos][column]
        for p in range(pos, pos + STUCK_ROWS):
            rows[p][column] = held
            out.truth.append((index(p), column, "stuck"))
            if column == "raw_temp":     # the cleaner flags what is computed from it
                out.truth.append((index(p), "corrected_temp", "stuck"))

    def lose(pos: int, count: int) -> None:
        drop.update(range(pos, pos + count))
        out.truth.append((index(pos + count), "", "gap"))

    plan = [
        (1, lambda p: spike(p, "raw_temp")),
        (1, lambda p: spike(p, "corrected_temp")),
        (1, lambda p: spike(p, "station_pressure_hpa")),
        (1, lambda p: missing(p, "raw_temp", "nan")),
        (1, lambda p: missing(p, "station_pressure_hpa", "")),
        (1, lambda p: out_of_range(p, "raw_temp", temp_abs(150.0))),
        (1, lambda p: out_of_range(p, "station_pressure_hpa", 0.0)),
        (STUCK_ROWS, lambda p: stuck(p, "raw_temp")),
        (STUCK_ROWS, lambda p: stuck(p, "station_pressure_hpa")),
        (2, lambda p: lose(p, 1)),          # one row lost: only the index shows it
        (4, lambda p: lose(p, 3)),
    ]
    pos = MARGIN
    for length, put in plan:
        pos += rng.randint(0, 3)
        put(pos)
        pos += length + MARGIN

    first = pos
    needed = first + RAMP_ROWS + RAMP_HOLD_ROWS
    if needed > len(rows):
        raise ValueError(f"flight too short: {len(rows)} rows, planting needs {needed}")
    rise = temp_delta(RAMP_C)
    for p in range(first, len(rows)):
        lift = rise * min((p - first) / RAMP_ROWS, 1.0)
        for column in TEMPERATURES:
            rows[p][column] = repr(float(rows[p][column]) + lift)
    unit = "°F" if fahrenheit else "°C"
    out.events.append((index(first), index(len(rows) - 1),
                       f"hand-warmer ramp: +{rise:.1f} {unit} over "
                       f"{RAMP_ROWS / 10:.0f} s, then held"))

    out.rows = [r for p, r in enumerate(rows) if p not in drop]
    return out


def write(planted: Planted, out_dir: Path) -> Path:
    """Write the planted flight where, and as, LocalFlightSource looks for it
    (flights/*/flight_<first 8 of the id>_*.csv); return the CSV."""
    folder = out_dir / "flights" / "planted"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"flight_{planted.rows[0]['flight_id'][:8]}_planted"
    path = folder / f"{name}.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(planted.rows[0]))
        writer.writeheader()
        writer.writerows(planted.rows)
    with (folder / f"{name}.truth.csv").open("w", newline="") as f:
        csv.writer(f).writerows([("index", "column", "kind"), *planted.truth])
    with (folder / f"{name}.events.csv").open("w", newline="") as f:
        csv.writer(f).writerows([("first", "last", "what"), *planted.events])
    return path


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", nargs="+", type=Path, help="real flight CSVs")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    for path in args.csv:
        planted = plant(read(path), args.seed)
        written = write(planted, args.out)
        print(f"{written}: {len(planted.truth)} planted values, {len(planted.events)} real event")


if __name__ == "__main__":
    main()
