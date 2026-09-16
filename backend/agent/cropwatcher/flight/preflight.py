"""Preflight gates.

Every check here exists because skipping it cost real debugging time during
bring-up. They run before any command that could spin a motor.

The governing rule: **the drone is the authority.** Where the firmware publishes
its own verdict, read that instead of re-deriving it from a threshold we invented.
An invented 3.70 V arming threshold refused flights the drone would have allowed,
repeatedly, while ``sys.canfly`` sat there with the real answer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

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


class PreflightFailure(StrEnum):
    NO_POSITIONING = "no_positioning_deck"
    NO_BASE_STATIONS = "no_base_stations"
    FIRMWARE_REFUSES = "firmware_refuses_to_arm"
    ESTIMATE_UNSTABLE = "position_estimate_unstable"
    INSUFFICIENT_ENDURANCE = "insufficient_endurance"


class PreflightError(RuntimeError):
    def __init__(self, reason: PreflightFailure, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class PreflightReport:
    vbat: float
    can_fly: bool
    base_stations: int
    ground_z_m: float
    estimate_spread_m: float
    endurance_s: float


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


def run(scf: SyncCrazyflie, hold_seconds: float, *, require_positioning: bool = True,
        force: bool = False) -> PreflightReport:
    """Run every gate. Raises :class:`PreflightError` on the first failure.

    `force` skips the *advisory* gates (endurance, stability) but never the
    physical ones — no positioning deck means no position feedback, and no
    amount of insistence changes that.
    """
    cf = scf.cf
    time.sleep(1.0)

    # 1. Positioning hardware. Ask the drone, never infer from a parts list.
    if require_positioning:
        lighthouse = str(cf.param.get_value("deck.bcLighthouse4", timeout=3))
        if lighthouse != "1":
            raise PreflightError(
                PreflightFailure.NO_POSITIONING,
                "deck.bcLighthouse4=0 — no position feedback, refusing to fly",
            )

    rows = sample(scf, [
        ("pm.vbat", "float"),
        ("sys.canfly", "uint8_t"),
        ("lighthouse.bsAvailable", "uint16_t"),
    ])
    vbat = sum(r["pm.vbat"] for r in rows) / len(rows)
    can_fly = bool(rows[-1]["sys.canfly"])
    stations = bin(int(rows[-1]["lighthouse.bsAvailable"])).count("1")

    # 2. Base stations must actually be visible, deck or no deck.
    if require_positioning and stations == 0:
        raise PreflightError(
            PreflightFailure.NO_BASE_STATIONS,
            "no lighthouse base stations visible",
        )

    # 3. The firmware's own verdict. Do not second-guess it with a voltage guess.
    if not can_fly and not force:
        raise PreflightError(
            PreflightFailure.FIRMWARE_REFUSES,
            f"sys.canfly=0 at {vbat:.2f} V — the supervisor will not arm the "
            f"motors whatever we send. Charge, then power-cycle the drone.",
        )

    # 4. Enough charge for the requested hold.
    endurance = estimate_endurance_s(vbat)
    budget = endurance * USABLE_FRACTION
    if hold_seconds > budget and not force:
        raise PreflightError(
            PreflightFailure.INSUFFICIENT_ENDURANCE,
            f"{hold_seconds:.0f}s hold needs ~{hold_seconds / USABLE_FRACTION:.0f}s "
            f"of endurance; this cell has roughly {endurance:.0f}s",
        )

    # 5. Settled position estimate, after resetting the estimator.
    reset_estimator(cf)
    ground_z, spread = wait_for_stable_z(scf)
    if ground_z is None:
        if not force:
            raise PreflightError(
                PreflightFailure.ESTIMATE_UNSTABLE,
                f"estimate never settled — best spread {spread * 100:.1f} cm, "
                f"needs under {SETTLE_TOLERANCE_M * 100:.0f} cm. The drone is "
                f"being moved, or the lighthouse geometry is poor here.",
            )
        ground_z = sum(
            r["stateEstimate.z"] for r in sample(scf, [("stateEstimate.z", "float")], n=8)
        ) / 8

    return PreflightReport(
        vbat=vbat,
        can_fly=can_fly,
        base_stations=stations,
        ground_z_m=ground_z,
        estimate_spread_m=spread,
        endurance_s=endurance,
    )


def reset_estimator(cf) -> None:
    """Reset the Kalman filter. Keep the drone still while this runs."""
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.15)
    cf.param.set_value("kalman.resetEstimation", "0")
    time.sleep(2.0)
