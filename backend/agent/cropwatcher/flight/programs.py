"""Preset programs the operator can run in Auto mode.

A program is a short, fixed flight with a name, a duration the battery must
cover, and a result. Only one exists so far — the hover test — because it is
the flight that proves a setup before anything more ambitious is tried.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from cropwatcher.flight.control import LAND_S, TAKEOFF_S, FlightAborted, GuardedFlight
from cropwatcher.safety.flight_guard import Action, Reason

log = logging.getLogger(__name__)


class Outcome(StrEnum):
    COMPLETED = "completed"
    LANDED_BY_OPERATOR = "landed_by_operator"
    LANDED_BY_GUARD = "landed_by_guard"
    STOPPED = "stopped"


@dataclass(frozen=True)
class HoverTest:
    """Take off straight up, hold a steady height, land where it started."""

    height_m: float = 0.30
    hold_s: float = 10.0

    key = "hover-test"
    label = "Hover test"

    def __post_init__(self) -> None:
        if not 0.1 <= self.height_m <= 1.0:
            raise ValueError("hover height must be between 0.10 and 1.00 m")
        if not 1.0 <= self.hold_s <= 60.0:
            raise ValueError("hold must be between 1 and 60 s")

    def duration_s(self) -> float:
        return TAKEOFF_S + self.hold_s + LAND_S

    def describe(self) -> str:
        return f"Take off to {self.height_m:.2f} m, hold {self.hold_s:.0f} s, land."


@dataclass(frozen=True)
class ProgramResult:
    outcome: Outcome
    reason: Reason
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"outcome": str(self.outcome), "reason": str(self.reason), "message": self.message}


def run_hover_test(flight: GuardedFlight, program: HoverTest) -> ProgramResult:
    """Fly the hover test. Always leaves the drone landed or stopped."""
    try:
        flight.takeoff(program.height_m)
        flight.hold(program.hold_s)
        flight.land()
        return ProgramResult(Outcome.COMPLETED, Reason.NONE, "Hover test completed and landed.")
    except FlightAborted as e:
        verdict = e.verdict
        if verdict.action is Action.STOP:
            outcome = Outcome.STOPPED
        elif verdict.reason is Reason.NONE:
            outcome = Outcome.LANDED_BY_OPERATOR
        else:
            outcome = Outcome.LANDED_BY_GUARD
        return ProgramResult(outcome, verdict.reason, verdict.message)
    except Exception:
        # Anything unexpected: never leave it in the air.
        log.exception("hover test failed unexpectedly")
        try:
            flight.land()
        except Exception:
            flight.request_stop()
        raise
