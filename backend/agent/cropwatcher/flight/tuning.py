"""Flight-controller tuning applied for a manual flight, and put back after.

Evidence (lab traces, 2026-09-17, two barometer flights, 177 + 265 samples):

- **The motors hammered.** About 15% of samples had a motor pinned at 0 or full
  while the drone was being commanded, cycling every 0.2–0.4 s. That is the
  "bounce" the operator saw, and — because a saturated motor has no authority
  left for yaw — the steady 20–35 °/s spin that made forward, sideways and
  rotate look broken.
- **The vertical-speed estimate is noise on the barometer.** At rest, motors
  off, it read ±0.5–0.8 m/s. The firmware's vertical-velocity PID multiplies
  that by `velCtlPid.vzKp` (25 on this firmware's defaults) and turns it into
  thrust — thousands of units of it, every cycle.
- **This drone does not hover where the firmware assumes.** Unsaturated airborne
  motor output averaged 48,400 and 49,100 across the two flights. The firmware
  starts from `posCtlPid.thrustBase` = 36,000 (a stock 2.1) and leaves the
  integrator to find the other ~13,000 — wind-up, then overshoot.

So a manual flight sets the base thrust to the measured hover and, on the
barometer only, softens the height loop. Every value is **read from the drone
first** and scaled from what it reports, and the exact originals are written back
when the flight ends. Parameters the firmware does not publish are skipped, not
guessed. Parameter writes live in RAM only: a power cycle also restores the
firmware defaults.

These are starting values from two flights, to be refined from the flight traces
(`flights/<date>/trace_*.csv`), not a finished tune.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

#: Mean unsaturated motor output while airborne, lab traces 2026-09-17.
MEASURED_HOVER_THRUST = 48_500


class Kind(StrEnum):
    SET = "set"          # write this value
    SCALE = "scale"      # multiply what the drone reports


@dataclass(frozen=True)
class Adjustment:
    name: str
    kind: Kind
    value: float
    why: str


#: Every manual flight: start the height loop from where this drone hovers.
BASE_PROFILE: tuple[Adjustment, ...] = (
    Adjustment("posCtlPid.thrustBase", Kind.SET, MEASURED_HOVER_THRUST,
               "measured hover thrust; the default assumes a lighter stock drone"),
)

#: Barometer flights only: stop amplifying a noisy vertical-speed estimate.
BAROMETER_PROFILE: tuple[Adjustment, ...] = (
    Adjustment("velCtlPid.vzKp", Kind.SCALE, 0.40, "vertical-speed P reacts to baro noise"),
    Adjustment("velCtlPid.vzKi", Kind.SCALE, 0.30, "integral wind-up drove the oscillation"),
    Adjustment("posCtlPid.zKp", Kind.SCALE, 0.75, "softer height correction"),
    Adjustment("posCtlPid.zKi", Kind.SCALE, 0.50, "less wind-up on a wandering height"),
)


@dataclass(frozen=True)
class Applied:
    name: str
    before: str
    after: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "before": self.before, "after": self.after}


def _toc_element(param: Any, name: str) -> Any | None:
    group, _, field = name.partition(".")
    toc = getattr(getattr(param, "toc", None), "toc", {}) or {}
    return toc.get(group, {}).get(field)


def _format(value: float, ctype: str) -> str:
    """By the parameter's declared type, never by how the old value looked: a
    float gain reported as "2" must not have 1.5 rounded back to "2", and a
    uint16 refuses "48500.0"."""
    if "float" in ctype or "double" in ctype:
        return f"{value:.6g}"
    return str(int(round(value)))


class FlightTuning:
    """Applies profiles to a Crazyflie's parameters and restores them exactly."""

    def __init__(self, param: Any) -> None:
        self._param = param
        self._originals: dict[str, str] = {}

    @property
    def active(self) -> bool:
        return bool(self._originals)

    def apply(self, *profiles: tuple[Adjustment, ...]) -> list[Applied]:
        applied: list[Applied] = []
        if self._param is None:
            return applied
        for profile in profiles:
            for adj in profile:
                element = _toc_element(self._param, adj.name)
                if element is None:
                    log.info("tuning: %s is not published by this firmware — skipped", adj.name)
                    continue
                try:
                    before = str(self._param.get_value(adj.name))
                    current = float(before)
                    target = adj.value if adj.kind is Kind.SET else current * adj.value
                    after = _format(target, str(getattr(element, "ctype", "")))
                    self._param.set_value(adj.name, after)
                except Exception:
                    log.exception("tuning: could not adjust %s — left as it was", adj.name)
                    continue
                self._originals.setdefault(adj.name, before)
                applied.append(Applied(adj.name, before, after))
                log.info("tuning: %s %s -> %s (%s)", adj.name, before, after, adj.why)
        return applied

    def restore(self) -> None:
        """Write back exactly what the drone reported before. Safe to call twice."""
        for name, value in self._originals.items():
            try:
                self._param.set_value(name, value)
            except Exception:
                log.warning("tuning: could not restore %s (a power cycle restores it)", name)
        self._originals.clear()
