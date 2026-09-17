"""Opening and closing a link to a Crazyflie.

The connection primitives. Everything that *flies* goes through
:class:`cropwatcher.flight.link.DroneLink`, which owns the checks, the telemetry
stream and the in-flight guards — there is deliberately no flight object here
any more, because the one that lived here slept through its waits without
watching anything and flew a drone into a wall.

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
