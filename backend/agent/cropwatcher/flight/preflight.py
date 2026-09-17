"""Preflight measurements: the battery model, settling, and the estimator reset.

The checklist an operator watches lives in :mod:`cropwatcher.flight.checks`;
this module holds the measured constants and the primitives it is built from.

The governing rule: **the drone is the authority.** Where the firmware publishes
its own verdict, read that instead of re-deriving it from a threshold we invented.
An invented 3.70 V arming threshold refused flights the drone would have allowed,
repeatedly, while ``sys.canfly`` sat there with the real answer.
"""

from __future__ import annotations

import time

from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.syncLogger import SyncLogger

# The estimate must hold this still before we trust it as a ground reference.
# Sampling too early after a Kalman reset produced a reference 0.14 m wrong,
# which put the takeoff target below the floor and the drone never left ground.
SETTLE_TOLERANCE_M = 0.02
SETTLE_WINDOW = 6
SETTLE_TIMEOUT_S = 15.0

# Hover current drags the pack down hard: 3.77 V resting sagged to ~3.30 V
# within three seconds. Land before the cells are damaged.
CRITICAL_VBAT = 3.10

# Capacity model, from the same measurements. Endurance is a capacity question,
# not a voltage-threshold one — a linear volts-per-second rule demands more than
# 4.2 V past about 25 s, which no LiPo can supply.
VBAT_EMPTY = 3.30
VBAT_FULL = 4.20
ENDURANCE_AT_FULL_S = 240.0
USABLE_FRACTION = 0.8


def sample(scf: SyncCrazyflie, variables: list[tuple[str, str]], n: int = 5,
           period_ms: int = 100) -> list[dict]:
    """Read `n` samples of the given log variables."""
    cfg = LogConfig(name="sample", period_in_ms=period_ms)
    for name, kind in variables:
        cfg.add_variable(name, kind)

    out: list[dict] = []
    with SyncLogger(scf, cfg) as logger:
        for i, (_, data, _) in enumerate(logger):
            out.append(data)
            if i >= n - 1:
                break
    return out


def estimate_endurance_s(vbat: float) -> float:
    """Rough seconds of hover left, from resting voltage."""
    frac = (vbat - VBAT_EMPTY) / (VBAT_FULL - VBAT_EMPTY)
    return max(0.0, frac) * ENDURANCE_AT_FULL_S


def wait_for_stable_z(
    scf: SyncCrazyflie,
    tolerance_m: float = SETTLE_TOLERANCE_M,
    window: int = SETTLE_WINDOW,
    timeout_s: float = SETTLE_TIMEOUT_S,
) -> tuple[float | None, float]:
    """Return (ground_z, spread) once the estimate stops moving.

    The Kalman estimate keeps converging for seconds after a reset, so a fixed
    sleep is not enough — it silently returns a mid-convergence value. Watch a
    sliding window instead and accept only once the spread is under tolerance.

    Returns ``(None, best_spread)`` if it never settles, so the caller can
    report *how far off* it was rather than just failing.
    """
    recent: list[float] = []
    best: float | None = None
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        z = sample(scf, [("stateEstimate.z", "float")], n=1)[0]["stateEstimate.z"]
        recent.append(z)
        if len(recent) > window:
            recent.pop(0)

        if len(recent) == window:
            spread = max(recent) - min(recent)
            best = spread if best is None else min(best, spread)
            if spread < tolerance_m:
                return sum(recent) / len(recent), spread

        time.sleep(0.15)

    return None, (best if best is not None else float("inf"))


def reset_estimator(cf) -> None:
    """Reset the Kalman filter. Keep the drone still while this runs."""
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.15)
    cf.param.set_value("kalman.resetEstimation", "0")
    time.sleep(2.0)
