"""Flying with the guards watching.

:class:`GuardedFlight` is the only way the agent moves a drone autonomously.
Every command that takes time — takeoff, hold, landing — waits in
:meth:`GuardedFlight.watch`, which checks each telemetry sample with the
:class:`FlightGuard` and acts on its verdict at once:

- ``LAND`` → graceful landing, then :class:`FlightAborted`
- ``STOP`` → motors stopped, then :class:`FlightAborted`

The same wait is where operator requests land: :meth:`request_land` (the Land
button) and :meth:`request_stop` (the hold-to-activate Emergency stop) are safe
to call from any thread.

This replaces a hover loop that slept, printed an estimate falling to −5.2 m
below the floor, and kept holding.

High-level commander rules from bring-up still apply (CLAUDE.md #2): the
session's connect step sends ``send_notify_setpoint_stop()`` before any of this
runs, and every altitude here is metres above the ground captured by the checks
(CLAUDE.md #4).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cropwatcher.flight.checks import ReadyReport
from cropwatcher.safety.flight_guard import CRITICAL_VBAT, Action, FlightGuard, Reason, Verdict
from cropwatcher.telemetry.stream import Snapshot

log = logging.getLogger(__name__)

TAKEOFF_S = 2.5
LAND_S = 3.0
WATCH_PERIOD_S = 0.05                  # 20 Hz — telemetry arrives at 10 Hz
POST_LAND_SETTLE_S = 0.3


class Phase(StrEnum):
    GROUNDED = "grounded"
    TAKING_OFF = "taking_off"
    HOLDING = "holding"
    LANDING = "landing"
    STOPPED = "stopped"


OPERATOR_LAND = Verdict(Action.LAND, Reason.NONE, "Landing requested by the operator.")
OPERATOR_STOP = Verdict(Action.STOP, Reason.NONE, "Emergency stop by the operator.")


class FlightAborted(RuntimeError):
    """The flight ended early. The drone is already landed or stopped."""

    def __init__(self, verdict: Verdict) -> None:
        super().__init__(verdict.message)
        self.verdict = verdict


@dataclass(frozen=True)
class PhaseEvent:
    phase: Phase
    detail: str = ""


class GuardedFlight:
    def __init__(
        self,
        cf: Any,
        snapshot: Callable[[], Snapshot],
        guard: FlightGuard,
        report: ReadyReport,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_phase: Callable[[PhaseEvent], None] | None = None,
    ) -> None:
        self._cf = cf
        self._hlc = cf.high_level_commander
        self._snapshot = snapshot
        self.guard = guard
        self.report = report
        self._clock = clock
        self._sleep = sleep
        self._on_phase = on_phase

        self._lock = threading.Lock()
        self._requested: Verdict | None = None
        self.phase = Phase.GROUNDED
        self.abort: Verdict | None = None

    # ── operator requests (any thread) ───────────────────────────────────

    def request_land(self) -> None:
        with self._lock:
            if self._requested is None or self._requested.action is Action.LAND:
                self._requested = OPERATOR_LAND

    def request_stop(self) -> None:
        with self._lock:
            self._requested = OPERATOR_STOP
        # Act now as well as in the watch loop: an emergency stop must not wait
        # for the next tick, and the loop may be blocked on a slow link.
        self._stop_motors()

    # ── commands ─────────────────────────────────────────────────────────

    @property
    def airborne(self) -> bool:
        return self.phase in (Phase.TAKING_OFF, Phase.HOLDING, Phase.LANDING)

    def takeoff(self, height_m: float, duration_s: float = TAKEOFF_S) -> None:
        self._set_phase(Phase.TAKING_OFF, f"to {height_m:.2f} m")
        self._hlc.takeoff(self.report.ground_z_m + height_m, duration_s)
        self.watch(duration_s)
        self.guard.arm_hold_checks(self._clock())

    def hold(self, seconds: float) -> None:
        self._set_phase(Phase.HOLDING, f"{seconds:.0f} s")
        self.watch(seconds)

    def goto(self, wp: Any, duration_s: float = 3.0) -> None:
        """Fly to a waypoint. x/y are absolute Lighthouse metres; z is above ground.

        ``Flight.goto`` sent ``go_to(wp.x, wp.y, ground_z + wp.z)`` and the
        planner depends on that frame — see docs/frontend mission planner.
        """
        if not self.airborne:
            raise RuntimeError("goto before takeoff")
        self._set_phase(Phase.HOLDING, f"to {wp.label or 'waypoint'}")
        self._hlc.go_to(wp.x, wp.y, self.report.ground_z_m + wp.z, 0.0, duration_s)
        self.watch(duration_s)

    def position(self) -> tuple[float, float, float]:
        """Latest estimate: x, y absolute; z above the ground reference."""
        snap = self._snapshot()
        return (
            snap.get("stateEstimate.x") or 0.0,
            snap.get("stateEstimate.y") or 0.0,
            (snap.get("stateEstimate.z") or 0.0) - self.report.ground_z_m,
        )

    def voltage_critical(self) -> bool:
        """For mission code. The guard already lands on low battery mid-wait."""
        vbat = self._snapshot().get("pm.vbat")
        return vbat is not None and vbat < CRITICAL_VBAT

    def land(self, duration_s: float = LAND_S) -> None:
        """Graceful landing. Only a STOP can interrupt it."""
        if self.phase in (Phase.LANDING, Phase.STOPPED, Phase.GROUNDED):
            return
        self._set_phase(Phase.LANDING)
        self._hlc.land(self.report.ground_z_m, duration_s)
        self._watch_landing(duration_s)
        self._finish_landing()

    # ── the watch ────────────────────────────────────────────────────────

    def watch(self, seconds: float) -> None:
        """Wait `seconds`, acting on every guard verdict and operator request."""
        end = self._clock() + seconds
        while self._clock() < end:
            verdict = self._next_verdict()
            if verdict.action is Action.STOP:
                self._abort_stop(verdict)
            if verdict.action is Action.LAND:
                self.abort = verdict
                log.warning("flight aborted: %s", verdict.message)
                self.land()
                raise FlightAborted(verdict)
            self._sleep(WATCH_PERIOD_S)

    def _watch_landing(self, seconds: float) -> None:
        end = self._clock() + seconds
        while self._clock() < end:
            verdict = self._next_verdict()
            if verdict.action is Action.STOP:
                self._abort_stop(verdict)
            self._sleep(WATCH_PERIOD_S)

    def _next_verdict(self) -> Verdict:
        with self._lock:
            requested = self._requested
        if requested is not None and requested.action is Action.STOP:
            return requested
        verdict = self.guard.check(self._snapshot(), self._clock())
        if verdict.action is Action.STOP:
            return verdict
        if requested is not None and self.phase is not Phase.LANDING:
            return requested
        return verdict

    def _abort_stop(self, verdict: Verdict) -> None:
        self.abort = verdict
        log.error("motors stopped: %s", verdict.message)
        self._stop_motors()
        self._set_phase(Phase.STOPPED, verdict.message)
        raise FlightAborted(verdict)

    def _finish_landing(self) -> None:
        try:
            self._hlc.stop()
        except Exception:
            log.debug("high-level stop failed after landing")
        self._sleep(POST_LAND_SETTLE_S)
        self._set_phase(Phase.GROUNDED, "landed")

    def _stop_motors(self) -> None:
        try:
            self._cf.commander.send_stop_setpoint()
            self._hlc.stop()
        except Exception:
            log.exception("could not send stop — link may be down")

    def _set_phase(self, phase: Phase, detail: str = "") -> None:
        self.phase = phase
        if self._on_phase is not None:
            try:
                self._on_phase(PhaseEvent(phase, detail))
            except Exception:
                log.exception("phase callback failed")
