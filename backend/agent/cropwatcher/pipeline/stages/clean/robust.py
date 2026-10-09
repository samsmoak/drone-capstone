"""The cleaner — stage 1, story 4.2: flag only the values that come from a
misbehaving sensor or estimator, and leave a real event alone.

It FLAGS and never edits or deletes: the contract hands the readings back
unchanged, and the stages after this one skip what is flagged. A value keeps
the first flag that fits, in this order:

  missing       None or NaN.
  out_of_range  Outside what the sensor (or the room's positioning) can
                measure at all.
  untrusted     A position the drone did not measure: no base station was
                received for that row, so x, y, z are the IMU coasting.
  stuck         The exact same value for STUCK_SAMPLES valid readings in a row,
                on a column straight off the sensor — counted ACROSS a gap: a
                frozen sensor that lost a row is still frozen.
  implausible   A change between two readings no drone can make: a position
                moving faster than the flight guard believes possible, a
                battery jumping by more than any real load step.
  spike         A Hampel identifier: off the rolling median by more than
                K × max(1.4826 × MAD, the column's noise floor).
  gap           Time lost between two readings (the whole row, column None,
                on the first reading after the gap).

WHAT REPLACED hampel@1, AND WHY (ml/sensor-faults/MEASUREMENTS.txt has the
numbers). On 66 real flights hampel@1 raised 332 false flags and 139 inside
the planted hand-warmer ramps; 294 of the false flags were corrected_temp
"spikes" at a thermal_state change, with raw_temp clean. They were the
CORRECTION ENGINE stepping its offset when the state switched (telemetry/
correction.py: the board's offset is scaled per state) — a held step that
lasts less than half a window, which a median calls a spike. So:

  corrected_temp is not judged on its own values. It is raw_temp minus the
  engine's offset, so (1) it inherits raw_temp's spike and stuck flags — a
  value computed from a bad one is bad — and (2) the OFFSET (raw − corrected)
  is checked for spikes against the neighbours IN THE SAME THERMAL STATE: it
  may step when the state changes, and only then. (A flight with no raw_temp
  column has nothing to hold it against; then it is judged on its own values.)

There is still NO RATE-OF-CHANGE RULE on temperature or pressure. A real heat
event is a sustained rise, which moves the median with it; a rate rule would
flag exactly what the pipeline exists to find.

Every number here cites ml/sensor-faults/MEASUREMENTS.txt.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from cropwatcher.pipeline.contracts import (
    CleanResult,
    FlagKind,
    FlightContext,
    PointData,
    Reading,
    ReadingFlag,
)
from cropwatcher.safety.flight_guard import MAX_PLAUSIBLE_SPEED_M_S

#: Telemetry period: 10 Hz (MEASUREMENTS.txt, "Timing": median 0.100 s).
EXPECTED_PERIOD_S = 0.1
#: A gap is more than 2.5 periods between readings: twice the worst jitter
#: measured (0.120 s) (MEASUREMENTS.txt, "Timing").
GAP_S = 2.5 * EXPECTED_PERIOD_S
#: Hampel window: 11 readings, 1.1 s centred on the value (MEASUREMENTS.txt, "Spike").
WINDOW = 11
#: Hampel threshold, in scaled MADs (MEASUREMENTS.txt, "Spike").
K = 3.0
#: Fewer valid values in the window than this and the median is not trusted.
MIN_WINDOW = 5
#: Stuck: the longest run of identical values in 158 real flights is 2
#: (MEASUREMENTS.txt, "Stuck"); 10 readings is one second of a value that
#: should be moving.
STUCK_SAMPLES = 10
#: Turns a MAD into a standard deviation for normally distributed noise.
MAD_TO_SIGMA = 1.4826
#: The engine's offset moves at most 0.076 °C between two readings in the same
#: thermal state (158 flights, MEASUREMENTS.txt, "Offset"): a floor of 0.05 °C
#: puts the threshold at ≥ 0.15 °C, twice that.
OFFSET_FLOOR_C = 0.05
#: Same-state neighbours needed to judge the offset at all.
MIN_SAME_STATE = 2
#: Lighthouse V2 reaches a few metres; no position in a lab room is 20 m out.
POSITION_LIMIT_M = 20.0
#: A battery reading outside 2.5–4.4 V is not a one-cell LiPo; the corpus
#: ranges 2.79–4.19 V (the low end is sag under full thrust).
BATTERY_LOW_V = 2.5
BATTERY_HIGH_V = 4.4
#: The largest real battery step between two readings is 0.78 V (a throttle
#: step); 1.0 V in 0.1 s is not a load change.
BATTERY_STEP_V = 1.0
#: An implausible value is compared with the last good one only this far back;
#: after that the estimate has settled somewhere new and becomes the reference.
PLAUSIBLE_HORIZON_S = 0.5

# A SESSION'S SAMPLES COME ONCE A SECOND, not ten times (FlightContext.period_s).
# The gap limit is 2.5 periods at either rate — measured on 141 real sessions
# (30 591 readings): median period 1.002 s, 99.9 % under 1.44 s
# (ml/session-eval/MEASUREMENTS.txt, "Timing"). The plausibility horizon is at
# least 2.5 periods too, or a 1 Hz reading would never have a neighbour close
# enough to be compared with. Counted limits (WINDOW, STUCK_SAMPLES) stay in
# readings: no value repeats more than twice in a row at 1 Hz either.


def gap_limit_s(period_s: float) -> float:
    """More than this between two readings is time lost."""
    return 2.5 * period_s


def plausible_horizon_s(period_s: float) -> float:
    return max(PLAUSIBLE_HORIZON_S, 2.5 * period_s)

#: How a check records a flag: index, column (None = whole row), kind, reason.
Flag = Callable[[int, str | None, FlagKind, str], None]

#: The order in the module docstring: a value keeps the first flag that fits.
PRIORITY: dict[FlagKind, int] = {"missing": 0, "out_of_range": 1, "untrusted": 2, "stuck": 3,
                                 "implausible": 4, "spike": 5, "gap": 6}

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class Column:
    """A sensor column checked on its own values. Limits are in °C for a
    temperature, in the column's unit otherwise; temperatures are converted
    per flight."""

    name: str
    low: float
    high: float
    noise_floor: float          # the smallest scaled MAD the spike check uses
    temperature: bool
    stuck_check: bool           # only meaningful on a value straight off the sensor


# The BMP388's own limits — Bosch BMP388 datasheet, BST-BMP388-DS001, section 1
# ("Specification"): pressure 300 to 1250 hPa, operating temperature -40 to
# +85 °C. A value outside them was not measured by that chip.
RAW_TEMP = Column("raw_temp", -40.0, 85.0, 0.05, temperature=True, stuck_check=True)
CORRECTED_TEMP = Column("corrected_temp", -40.0, 85.0, 0.05, temperature=True,
                        stuck_check=False)
PRESSURE = Column("station_pressure_hpa", 300.0, 1250.0, 0.03, temperature=False,
                  stuck_check=True)
SENSORS = (RAW_TEMP, PRESSURE)
POSITION = ("x_m", "y_m", "z_m")
BATTERY = "battery_v"

#: The columns scored like hampel@1's (ml/sensor-faults/evaluate.py).
SENSOR_COLUMNS = (RAW_TEMP.name, CORRECTED_TEMP.name, PRESSURE.name)


class RobustCleaner:
    name = "robust"
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

        period = ctx.period_s if ctx.period_s > 0 else EXPECTED_PERIOD_S
        horizon = plausible_horizon_s(period)
        segments = _segments(readings, flag, gap_limit_s(period))
        present = {c for r in readings for c in r.values}
        bad: dict[str, set[int]] = {}
        for column in SENSORS:
            if column.name in present:
                bad[column.name] = _check_sensor(column, readings, segments, ctx.temp_unit, flag)
        if CORRECTED_TEMP.name in present and RAW_TEMP.name in present:
            _check_corrected(readings, segments, ctx.temp_unit, flag, found,
                             bad[RAW_TEMP.name])
        elif CORRECTED_TEMP.name in present:
            # No sensor value to hold it against: judged on its own values.
            _check_sensor(CORRECTED_TEMP, readings, segments, ctx.temp_unit, flag)
        if all(c in present for c in POSITION):
            _check_position(readings, flag, horizon)
        if BATTERY in present:
            _check_battery(readings, flag, horizon)

        flags = sorted(found.values(), key=lambda f: (f.index, f.column or ""))
        return CleanResult(readings=readings, flags=tuple(flags))


# ── helpers ──────────────────────────────────────────────────────────────


def _value(r: Reading, column: str) -> float:
    v = r.values.get(column)
    return float("nan") if v is None else float(v)


def _segments(readings: Sequence[Reading], flag: Flag, gap_s: float = GAP_S) -> list[range]:
    """Positions of each stretch with no lost time between, flagging the first
    reading after every gap. A spike window never reaches across lost time."""
    starts = [0]
    for i in range(1, len(readings)):
        prev, cur = readings[i - 1], readings[i]
        dt = cur.t_s - prev.t_s
        lost = cur.index - prev.index - 1
        if dt > gap_s or lost > 0:
            if lost > 0:
                rows = f"reading {prev.index + 1}" if lost == 1 else \
                    f"readings {prev.index + 1}–{cur.index - 1}"
                reason = (f"{rows} missing between {prev.index} and {cur.index} "
                          f"({dt:.2f} s apart): rows were lost.")
            else:
                reason = (f"{dt:.2f} s between readings {prev.index} and {cur.index} "
                          f"(limit {gap_s:.2f} s): telemetry stopped arriving.")
            flag(cur.index, None, "gap", reason)
            starts.append(i)
    ends = [*starts[1:], len(readings)]
    return [range(a, b) for a, b in zip(starts, ends, strict=True)]


def _limits(column: Column, unit: str) -> tuple[float, float, float, str]:
    low, high, floor = column.low, column.high, column.noise_floor
    if column.temperature and unit == "F":
        # Limits are absolute temperatures: × 9/5 + 32. The floor is a
        # difference: × 9/5 only (the same trap as telemetry/row.py).
        low, high, floor = low * 9 / 5 + 32, high * 9 / 5 + 32, floor * 9 / 5
    sym = ("°F" if unit == "F" else "°C") if column.temperature else "hPa"
    return low, high, floor, sym


def _hampel(values: FloatArray, segments: Sequence[range],
            floor: float) -> tuple[NDArray[np.bool_], FloatArray, FloatArray]:
    """Per position: is it a spike, its window median, and the threshold used.
    Windows are centred and never cross a segment boundary (lost time)."""
    n = len(values)
    spike = np.zeros(n, dtype=bool)
    median = np.full(n, np.nan)
    limit = np.full(n, np.nan)
    half = WINDOW // 2
    for seg in segments:
        part = values[seg.start:seg.stop]
        padded = np.pad(part, (half, half), constant_values=np.nan)
        win = sliding_window_view(padded, WINDOW)
        enough = (~np.isnan(win)).sum(axis=1) >= MIN_WINDOW
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # all-NaN windows
            med = np.nanmedian(win, axis=1)
            mad = np.nanmedian(np.abs(win - med[:, None]), axis=1)
        scale = np.maximum(MAD_TO_SIGMA * mad, floor)
        off = np.abs(part - med)
        hit = enough & ~np.isnan(part) & (off > K * scale)
        spike[seg.start:seg.stop] = hit
        median[seg.start:seg.stop] = med
        limit[seg.start:seg.stop] = K * scale
    return spike, median, limit


def _stuck_runs(values: FloatArray) -> list[NDArray[np.intp]]:
    """Runs of identical valid values, at least STUCK_SAMPLES long. NaNs are
    skipped, not counted, and gaps do not break a run."""
    valid = np.flatnonzero(~np.isnan(values))
    runs: list[NDArray[np.intp]] = []
    start = 0
    for end in range(1, len(valid) + 1):
        if end < len(valid) and values[valid[end]] == values[valid[start]]:
            continue
        if end - start >= STUCK_SAMPLES:
            runs.append(valid[start:end])
        start = end
    return runs


# ── checks ───────────────────────────────────────────────────────────────


def _check_sensor(column: Column, readings: Sequence[Reading], segments: Sequence[range],
                  unit: str, flag: Flag) -> set[int]:
    """missing, out_of_range, stuck, spike on a sensor column. Returns every
    position whose value is not usable — what corrected_temp's offset check
    must leave out (and inherits, where the flag was stuck or spike)."""
    name = column.name
    low, high, floor, sym = _limits(column, unit)
    values = np.array([_value(r, name) for r in readings])
    inherited: set[int] = set()
    for i, v in enumerate(values):
        if math.isnan(v):
            flag(readings[i].index, name, "missing", f"{name} was not recorded.")
            inherited.add(i)
        elif not low <= v <= high:
            flag(readings[i].index, name, "out_of_range",
                 f"{name} {v:.2f} {sym} is outside what the sensor can measure "
                 f"({low:.0f} to {high:.0f} {sym}).")
            values[i] = np.nan
            inherited.add(i)

    if column.stuck_check:
        for run in _stuck_runs(values):
            held = (f"held at exactly {values[run[0]]:.3f} {sym} for {len(run)} readings "
                    f"({len(run) * EXPECTED_PERIOD_S:.1f} s; limit {STUCK_SAMPLES})")
            for at in (int(i) for i in run):
                flag(readings[at].index, name, "stuck",
                     f"{name} {held}: the sensor stopped updating.")
                inherited.add(at)
            values[run] = np.nan             # a stuck value is no neighbour

    spike, median, limit = _hampel(values, segments, floor)
    span = WINDOW * EXPECTED_PERIOD_S
    for at in (int(i) for i in np.flatnonzero(spike)):
        x = values[at]
        flag(readings[at].index, name, "spike",
             f"{name} {x:.2f} {sym} is {abs(x - median[at]):.2f} {sym} off the {span:.1f} s "
             f"median (limit {limit[at]:.2f} {sym}): a spike.")
        inherited.add(at)
    return inherited


def _check_corrected(readings: Sequence[Reading], segments: Sequence[range], unit: str,
                     flag: Flag, found: dict[tuple[int, str | None], ReadingFlag],
                     raw_bad: set[int]) -> None:
    """corrected_temp = raw_temp − the engine's offset (telemetry/correction.py).

    Its own missing and out_of_range; raw_temp's stuck and spike inherited; and
    the OFFSET checked for spikes against same-state neighbours, so a step the
    engine takes when thermal_state switches is not a spike."""
    name = CORRECTED_TEMP.name
    low, high, _, sym = _limits(CORRECTED_TEMP, unit)
    floor = OFFSET_FLOOR_C * (9 / 5 if unit == "F" else 1.0)
    raw = np.array([_value(r, RAW_TEMP.name) for r in readings])
    corrected = np.array([_value(r, name) for r in readings])
    for i, v in enumerate(corrected):
        if math.isnan(v):
            flag(readings[i].index, name, "missing", f"{name} was not recorded.")
        elif not low <= v <= high:
            flag(readings[i].index, name, "out_of_range",
                 f"{name} {v:.2f} {sym} is outside what the sensor can measure "
                 f"({low:.0f} to {high:.0f} {sym}).")
            corrected[i] = np.nan

    for i in sorted(raw_bad):
        source = found.get((readings[i].index, RAW_TEMP.name))
        if source is not None and source.kind in ("stuck", "spike"):
            flag(readings[i].index, name, source.kind,
                 f"{name} is computed from raw_temp, which was flagged {source.kind} here.")

    offset = raw - corrected
    raw_ok = np.array([i not in raw_bad for i in range(len(readings))])
    offset[~raw_ok] = np.nan
    states = [r.text.get("thermal_state", "") for r in readings]
    half = WINDOW // 2
    for seg in segments:
        for i in seg:
            d = offset[i]
            if math.isnan(d):
                continue
            lo, hi = max(seg.start, i - half), min(seg.stop, i + half + 1)
            same = [offset[j] for j in range(lo, hi)
                    if j != i and states[j] == states[i] and not math.isnan(offset[j])]
            if len(same) < MIN_SAME_STATE:
                continue
            ref = float(np.median(same))
            scale = max(MAD_TO_SIGMA * float(np.median(np.abs(np.array(same) - ref))), floor)
            if abs(d - ref) > K * scale:
                flag(readings[i].index, name, "spike",
                     f"{name} {corrected[i]:.2f} {sym} is {abs(d - ref):.2f} {sym} off the "
                     f"correction engine's offset for {states[i] or 'its state'} (limit "
                     f"{K * scale:.2f} {sym}), while raw_temp held: the correction "
                     f"spiked.")


def _check_position(readings: Sequence[Reading], flag: Flag,
                    horizon_s: float = PLAUSIBLE_HORIZON_S) -> None:
    """untrusted (no base station), out_of_range, implausible (faster than the
    flight guard believes a drone can move)."""
    good: tuple[float, float, float, float] | None = None       # t, x, y, z
    for r in readings:
        xyz = [_value(r, c) for c in POSITION]
        if any(math.isnan(v) for v in xyz):
            for c, v in zip(POSITION, xyz, strict=True):
                if math.isnan(v):
                    flag(r.index, c, "missing", f"{c} was not recorded.")
            continue
        received = r.values.get("lighthouse_received")
        if received is not None and not math.isnan(received) and received <= 0:
            for c in POSITION:
                flag(r.index, c, "untrusted",
                     f"{c}: no base station was received for this reading, so the "
                     f"position is the drone's estimate coasting, not a measurement.")
            continue
        far = [(c, v) for c, v in zip(POSITION, xyz, strict=True) if abs(v) > POSITION_LIMIT_M]
        if far:
            for c, v in far:
                flag(r.index, c, "out_of_range",
                     f"{c} {v:.2f} m is further than any base station reaches "
                     f"(limit ±{POSITION_LIMIT_M:.0f} m).")
            continue
        x, y, z = xyz
        if good is not None:
            t0, x0, y0, z0 = good
            dt = r.t_s - t0
            if 0 < dt <= horizon_s:
                speed = math.dist((x, y, z), (x0, y0, z0)) / dt
                if speed > MAX_PLAUSIBLE_SPEED_M_S:
                    for c in POSITION:
                        flag(r.index, c, "implausible",
                             f"the position moved {math.dist((x, y, z), (x0, y0, z0)):.2f} m "
                             f"in {dt:.2f} s ({speed:.1f} m/s; limit "
                             f"{MAX_PLAUSIBLE_SPEED_M_S:.1f} m/s): the estimate jumped.")
                    continue
        good = (r.t_s, x, y, z)


def _check_battery(readings: Sequence[Reading], flag: Flag,
                   horizon_s: float = PLAUSIBLE_HORIZON_S) -> None:
    """missing, out_of_range, implausible (a step no load change makes). Never
    stuck: pm.vbat repeats for up to 28 readings in a real flight."""
    good: tuple[float, float] | None = None                       # t, volts
    for r in readings:
        v = _value(r, BATTERY)
        if math.isnan(v):
            flag(r.index, BATTERY, "missing", f"{BATTERY} was not recorded.")
            continue
        if not BATTERY_LOW_V <= v <= BATTERY_HIGH_V:
            flag(r.index, BATTERY, "out_of_range",
                 f"{BATTERY} {v:.2f} V is not a one-cell battery's voltage "
                 f"({BATTERY_LOW_V:.1f} to {BATTERY_HIGH_V:.1f} V).")
            continue
        if good is not None and 0 < r.t_s - good[0] <= horizon_s \
                and abs(v - good[1]) > BATTERY_STEP_V:
            flag(r.index, BATTERY, "implausible",
                 f"{BATTERY} jumped {v - good[1]:+.2f} V in {r.t_s - good[0]:.2f} s (limit "
                 f"{BATTERY_STEP_V:.1f} V): not a load change.")
            continue
        good = (r.t_s, v)
