"""The cleaner — stage 1, story 4.2: Flag only the values that come from a
misbehaving sensor, and leave a real event alone.

It FLAGS and never edits or deletes: the contract hands the readings back
unchanged, and the stages after this one skip what is flagged. 

The five checks are listed below and erroneous values take the first flag that
fits:

  missing       None or NaN.
  out_of_range  Outside what the BMP388 can measure at all.
  stuck         The exact same value for STUCK_SAMPLES readings in a row, on a
                column that comes straight off the sensor.
  spike         A Hampel filter: off the rolling median by more than
                K × max(1.4826 × MAD, the column's noise floor).
  gap           Time lost between two readings (whole row, column None, on the
                first reading after the gap).

There is deliberately NO rate-of-change rule. A real heat event is a sustained
rise, and the correction engine steps corrected_temp by 4.6 °C when the
drone takes off (row 27 of the pipeline fixture) and holds it: both move the
rolling median with them, so Hampel leaves them alone, where a rate rule
would flag exactly what the pipeline exists to find.

NOTE: Every number here cites ml/sensor-faults/MEASUREMENTS.txt. The spike and stuck
numbers are PROVISIONAL — measured on one flight, the pipeline fixture — until
three or more flights confirm them (docs/handoffs/sprint-1/undone/dpp-clean.txt).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from cropwatcher.pipeline.contracts import (
    CleanResult,
    FlagKind,
    FlightContext,
    PointData,
    Reading,
    ReadingFlag,
)

#: Telemetry period: 10 Hz (MEASUREMENTS.txt, "Timing": median 0.100 s).
EXPECTED_PERIOD_S = 0.1
#: A gap is more than 2.5 periods between readings. The largest real interval
#: measured is 0.120 s, so 0.25 s is twice the worst jitter seen (MEASUREMENTS.txt).
GAP_S = 2.5 * EXPECTED_PERIOD_S
#: Hampel window: 11 readings, 1.1 s centred on the value (MEASUREMENTS.txt, "Spike").
WINDOW = 11
#: Hampel threshold, in scaled MADs (MEASUREMENTS.txt, "Spike").
K = 3.0
#: Fewer valid neighbours than this and the median is not trusted: no spike check.
MIN_WINDOW = 5
#: Stuck: the longest run of identical values measured is 2 (MEASUREMENTS.txt,
#: "Stuck"); 10 readings is one second of a value that should be moving.
STUCK_SAMPLES = 10
#: How a check records a flag: index, column (None = whole row), kind, reason.
Flag = Callable[[int, str | None, FlagKind, str], None]

#: Turns a MAD into a standard deviation for normally distributed noise.
MAD_TO_SIGMA = 1.4826
#: The order in the module docstring: a value keeps the first flag that fits,
#: whichever column's check raised it.
PRIORITY: dict[FlagKind, int] = {"missing": 0, "out_of_range": 1, "stuck": 2, "spike": 3, "gap": 4}


@dataclass(frozen=True)
class Column:
    """A column this stage checks. Limits are in °C for a temperature, in the
    column's own unit otherwise; temperatures are converted per flight."""

    name: str
    low: float
    high: float
    noise_floor: float          # the smallest scaled MAD the spike check uses
    temperature: bool
    stuck_check: bool           # only meaningful on a value straight off the sensor


# The BMP388's own limits — Bosch BMP388 datasheet, BST-BMP388-DS001, section 1
# ("Specification"): pressure 300 to 1250 hPa, operating temperature -40 to
# +85 °C. A value outside them was not measured by that chip.
COLUMNS = (
    Column("raw_temp", -40.0, 85.0, 0.05, temperature=True, stuck_check=True),
    Column("corrected_temp", -40.0, 85.0, 0.05, temperature=True, stuck_check=False),
    Column("station_pressure_hpa", 300.0, 1250.0, 0.03, temperature=False,
           stuck_check=True),
)

#: corrected_temp is computed from raw_temp (telemetry/correction.py): when
#: raw_temp is stuck, the value computed from it is not a measurement either.
DERIVED_FROM = {"raw_temp": "corrected_temp"}


class HampelCleaner:
    name = "hampel"
    version = "1"

    def clean(self, data: PointData, ctx: FlightContext) -> CleanResult:
        readings = data.readings
        if not readings:
            return CleanResult(readings=readings, flags=())

        found: dict[tuple[int, str | None], ReadingFlag] = {}

        def flag(index: int, column: str | None, kind: FlagKind, reason: str) -> None:
            key, new = (index, column), ReadingFlag(index, column, kind, reason)
            if key not in found or PRIORITY[kind] < PRIORITY[found[key].kind]:
                found[key] = new

        segments = _segments(readings, flag)
        present = {c for r in readings for c in r.values}
        for column in COLUMNS:
            if column.name in present:
                _check_column(column, segments, ctx.temp_unit, flag)

        flags = sorted(found.values(), key=lambda f: (f.index, f.column or ""))
        return CleanResult(readings=readings, flags=tuple(flags))


# ── checks ───────────────────────────────────────────────────────────────


def _segments(readings: Sequence[Reading], flag: Flag) -> list[list[Reading]]:
    """Split at every gap, flagging the first reading after it. A window never
    reaches across lost time."""
    segments: list[list[Reading]] = [[readings[0]]]
    for prev, cur in zip(readings, readings[1:], strict=False):
        dt = cur.t_s - prev.t_s
        lost = cur.index - prev.index - 1
        if dt > GAP_S or lost > 0:
            if lost > 0:
                rows = f"reading {prev.index + 1}" if lost == 1 else \
                    f"readings {prev.index + 1}–{cur.index - 1}"
                reason = (f"{rows} missing between {prev.index} and {cur.index} "
                          f"({dt:.2f} s apart): rows were lost.")
            else:
                reason = (f"{dt:.2f} s between readings {prev.index} and {cur.index} "
                          f"(limit {GAP_S:.2f} s): telemetry stopped arriving.")
            flag(cur.index, None, "gap", reason)
            segments.append([])
        segments[-1].append(cur)
    return segments


def _check_column(column: Column, segments: list[list[Reading]], unit: str, flag: Flag) -> None:
    name = column.name
    sym = ("°F" if unit == "F" else "°C") if column.temperature else "hPa"
    low, high, floor = column.low, column.high, column.noise_floor
    if column.temperature and unit == "F":
        # Limits are absolute temperatures: × 9/5 + 32. The floor is a
        # difference: × 9/5 only (the same trap as telemetry/row.py).
        low, high, floor = low * 9 / 5 + 32, high * 9 / 5 + 32, floor * 9 / 5

    for segment in segments:
        values = np.full(len(segment), np.nan)
        for i, r in enumerate(segment):
            v = r.values.get(name)
            if v is None or math.isnan(v):
                flag(r.index, name, "missing", f"{name} was not recorded.")
            elif not low <= v <= high:
                flag(r.index, name, "out_of_range",
                     f"{name} {v:.2f} {sym} is outside what the sensor can measure "
                     f"({low:.0f} to {high:.0f} {sym}).")
            else:
                values[i] = v

        if column.stuck_check:
            _stuck(name, segment, values, sym, flag)
        _spikes(name, segment, values, floor, sym, flag)


def _stuck(name: str, segment: list[Reading], values: np.ndarray, sym: str, flag: Flag) -> None:
    """A run of identical values. Missing and out-of-range readings (NaN here)
    are skipped, not counted: a frozen sensor that drops one value is still
    frozen."""
    valid = np.flatnonzero(~np.isnan(values))
    start = 0
    for end in range(1, len(valid) + 1):
        if end < len(valid) and values[valid[end]] == values[valid[start]]:
            continue
        run = valid[start:end]
        if len(run) >= STUCK_SAMPLES:
            held = (f"held at exactly {values[run[0]]:.3f} {sym} for {len(run)} readings "
                    f"({len(run) * EXPECTED_PERIOD_S:.1f} s; limit {STUCK_SAMPLES})")
            derived = DERIVED_FROM.get(name)
            for r in (segment[i] for i in run):
                flag(r.index, name, "stuck", f"{name} {held}: the sensor stopped updating.")
                if derived and derived in r.values:
                    flag(r.index, derived, "stuck",
                         f"{derived} is computed from {name}, which was {held}.")
            values[run] = np.nan              # a stuck value is no neighbour
        start = end


def _spikes(name: str, segment: list[Reading], values: np.ndarray, floor: float,
            sym: str, flag: Flag) -> None:
    half = WINDOW // 2
    span = WINDOW * EXPECTED_PERIOD_S
    for i, r in enumerate(segment):
        x = values[i]
        if math.isnan(x):
            continue
        window = values[max(0, i - half):i + half + 1]
        window = window[~np.isnan(window)]
        if len(window) < MIN_WINDOW:
            continue
        median = float(np.median(window))
        scale = max(MAD_TO_SIGMA * float(np.median(np.abs(window - median))), floor)
        off = abs(x - median)
        if off > K * scale:
            flag(r.index, name, "spike",
                 f"{name} {x:.2f} {sym} is {off:.2f} {sym} off the {span:.1f} s median "
                 f"(limit {K * scale:.2f} {sym}): a spike.")
