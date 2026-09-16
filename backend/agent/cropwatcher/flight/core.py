"""The flight core.

One place that knows how to talk to a Crazyflie. Every caller — CLI, REST,
WebSocket, mission queue — goes through this, passing parameters as arguments.

This exists because the previous implementation had no such layer: parameters
reached the flight scripts by writing text into their ``input()`` prompts over
stdin, so every caller had to impersonate a human at a terminal, and four
scripts each re-implemented connect / reset / capture-origin / fly / log.

Altitudes here are **metres above the ground captured at takeoff**, never raw
``stateEstimate.z``. Lighthouse z=0 is wherever the rig was calibrated from; the
measured floor ranged 0.85–1.40 m across sessions in the same room. Commanding
an absolute 1.0 m once produced a 15 cm hop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from cropwatcher.flight import preflight
from cropwatcher.flight.preflight import PreflightReport

log = logging.getLogger(__name__)

DEFAULT_URI = "radio://0/80/2M"

TAKEOFF_TIME_S = 2.0
LAND_TIME_S = 2.5
GOTO_DEFAULT_DURATION_S = 3.0


@dataclass(frozen=True)
class Waypoint:
    """A target position, metres, relative to the takeoff ground reference."""

    x: float
    y: float
    z: float
    label: str | None = None


class FlightError(RuntimeError):
    pass


def scan(uri: str = DEFAULT_URI) -> list[str]:
    """Return URIs of reachable drones. Empty if the radio or drone is absent."""
    cflib.crtp.init_drivers()
    return [found[0] for found in cflib.crtp.scan_interfaces()]


@contextmanager
def connect(uri: str = DEFAULT_URI) -> Iterator[SyncCrazyflie]:
    """Open a link, guaranteeing motors are stopped on every exit path."""
    cflib.crtp.init_drivers()
    if not cflib.crtp.scan_interfaces():
        raise FlightError("no drone found — radio plugged in, battery connected, powered on?")

    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache="./.cache")) as scf:
        try:
            yield scf
        finally:
            _cut_motors(scf)


class Flight:
    """An armed flight session. Obtain one via :func:`session`.

    Every altitude argument is metres above the ground reference captured during
    preflight, so callers never deal with the lighthouse frame's offset.
    """

    def __init__(self, scf: SyncCrazyflie, report: PreflightReport) -> None:
        self._scf = scf
        self._cf = scf.cf
        self._hlc = scf.cf.high_level_commander
        self.report = report
        self.ground_z = report.ground_z_m
        self._airborne = False

    # ── commands ─────────────────────────────────────────────────────────

    def takeoff(self, height_m: float, duration_s: float = TAKEOFF_TIME_S) -> None:
        self._hlc.takeoff(self.ground_z + height_m, duration_s)
        time.sleep(duration_s)
        self._airborne = True

    def goto(self, wp: Waypoint, duration_s: float = GOTO_DEFAULT_DURATION_S) -> None:
        if not self._airborne:
            raise FlightError("goto before takeoff")
        self._hlc.go_to(wp.x, wp.y, self.ground_z + wp.z, 0.0, duration_s)
        time.sleep(duration_s)

    def hold(self, seconds: float) -> None:
        time.sleep(seconds)

    def land(self, duration_s: float = LAND_TIME_S) -> None:
        self._hlc.land(self.ground_z, duration_s)
        time.sleep(duration_s)
        self._airborne = False

    # ── telemetry ────────────────────────────────────────────────────────

    def position(self) -> tuple[float, float, float]:
        """Current position, metres, relative to the ground reference."""
        row = preflight.sample(self._scf, [
            ("stateEstimate.x", "float"),
            ("stateEstimate.y", "float"),
            ("stateEstimate.z", "float"),
        ], n=1)[0]
        return (
            row["stateEstimate.x"],
            row["stateEstimate.y"],
            row["stateEstimate.z"] - self.ground_z,
        )

    def battery(self) -> float:
        # cflib log rows are untyped dicts, so coerce at this boundary rather
        # than letting Any leak into callers.
        return float(preflight.sample(self._scf, [("pm.vbat", "float")], n=1)[0]["pm.vbat"])

    def voltage_critical(self) -> bool:
        return self.battery() < preflight.CRITICAL_VBAT


@contextmanager
def session(
    uri: str = DEFAULT_URI,
    *,
    hold_seconds: float = 0.0,
    require_positioning: bool = True,
    force: bool = False,
) -> Iterator[Flight]:
    """Connect, run every preflight gate, and yield an armed :class:`Flight`.

    Lands and cuts motors on exit, including on exception — a raised error must
    never leave the drone hovering.
    """
    with connect(uri) as scf:
        _configure(scf.cf)
        report = preflight.run(
            scf,
            hold_seconds,
            require_positioning=require_positioning,
            force=force,
        )
        log.info(
            "preflight ok — %.2f V, %d base stations, ground z=%+.3f m (spread %.1f cm)",
            report.vbat, report.base_stations, report.ground_z_m,
            report.estimate_spread_m * 100,
        )

        flight = Flight(scf, report)
        try:
            yield flight
        finally:
            try:
                if flight._airborne:
                    flight.land()
            except Exception:
                log.exception("landing failed during cleanup")


def _configure(cf) -> None:
    """Estimator, controller, and commander priority."""
    cf.param.set_value("stabilizer.estimator", "2")   # Kalman
    cf.param.set_value("commander.enHighLevel", "1")

    # Mellinger tracks a position setpoint noticeably better than the default
    # PID, which overshoots and keeps climbing. Measured: PID overshot a 0.15 m
    # target by 53%; Mellinger settled within 8 cm of 0.5 m.
    try:
        cf.param.set_value("stabilizer.controller", "2")
    except Exception:
        log.warning("Mellinger controller unavailable, staying on PID")

    # If anything used the low-level commander this power cycle, it holds
    # setpoint priority and the high-level commander is silently ignored —
    # takeoff() returns fine and the motors stay at exactly 0.
    try:
        cf.commander.send_notify_setpoint_stop()
    except Exception:
        log.debug("send_notify_setpoint_stop unsupported on this firmware")

    time.sleep(0.2)


def _cut_motors(scf: SyncCrazyflie) -> None:
    """Stop the motors on every path out. Never assume the link is alive."""
    try:
        for _ in range(5):
            scf.cf.commander.send_setpoint(0, 0, 0, 0)
            time.sleep(0.02)
        scf.cf.commander.send_stop_setpoint()
        scf.cf.high_level_commander.stop()
    except Exception:
        log.debug("could not cut motors — link probably already down")
