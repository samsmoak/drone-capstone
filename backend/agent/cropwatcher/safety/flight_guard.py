"""Is it safe to fly, and is it safe to keep flying?

Two questions, one module, both answered from the live telemetry stream.

**Before flight** — :func:`assess_positioning`. The lab crash of 2026-09-16 is
why this exists. Preflight counted ``lighthouse.bsAvailable`` (base stations the
drone holds *geometry* for: 4) and reported "4 base stations" while
``lighthouse.bsReceive`` — stations actually being received — was empty. The
drone flew on dead reckoning: at rest its x/y estimate wandered 8.9 m, and in
the air it flew sideways into the room. Readiness is now judged on reception,
per-station calibration and geometry, and the filter's own uncertainty.

**During flight** — :class:`FlightGuard`. The hover loop printed an estimate
that fell to −5.2 m below the floor and kept holding. Every sample is now
checked, and the answer is one of three:

- ``OK``   keep going
- ``LAND`` graceful landing — the estimate is still trustworthy enough to fly it
- ``STOP`` stop the motors — the estimate itself is gone, so a "landing" would
  steer by a position that does not exist. That is what flew the drone into
  the room. A short drop from hover height is the lesser harm.

The thresholds below are *safety policy*, not firmware facts, and are named so
they can be tuned from flight data. Where the firmware publishes its own
verdict (``pm.state`` low power, the supervisor's tumble flag) that is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cropwatcher.telemetry.stream import Snapshot

# ── positioning readiness ────────────────────────────────────────────────

# The kit has two base stations; positioning with one works but degrades.
MIN_USABLE_STATIONS = 2
# Filter position variance, m². 0.0025 m² is a 5 cm standard deviation. The
# crash reading at rest was ~4.4 m².
MAX_READY_VARIANCE_M2 = 0.0025

# ── in-flight policy ─────────────────────────────────────────────────────

# Above this the estimate is too uncertain to LOCK a position to, even though
# the flight may continue. 0.01 m² is a 10 cm standard deviation. The drone
# publishes its own confidence, so manual position hold reads that rather than
# guessing from how far the number moved (flight/manual.py, flight/link.py).
# It sits between the 5 cm wanted at rest before arming and the 50 cm at which
# the estimate stops being a position at all.
MAX_HOLD_VARIANCE_M2 = 0.01

MAX_DRIFT_M = 0.30                  # sideways from the takeoff point, hold programs
MAX_HEIGHT_ERROR_M = 0.25           # from the target height, hold programs
HEIGHT_ERROR_GRACE_S = 1.0          # must persist this long (climb overshoot)
RECEPTION_LOST_GRACE_S = 0.5        # Kalman coasts on the IMU briefly
LOW_VOLTAGE_GRACE_S = 1.0           # a sag under a throttle step is not "empty"
STALE_TELEMETRY_S = 0.5
# Beyond these the estimate is not a position — it is the accelerometer
# integrating. The crash trace fell ~1 m per sample at 4 Hz.
MAX_PLAUSIBLE_SPEED_M_S = 2.0
MAX_FLIGHT_VARIANCE_M2 = 0.25       # 50 cm standard deviation
BELOW_FLOOR_M = -0.30
ABOVE_CEILING_MARGIN_M = 0.50

CRITICAL_VBAT = 3.10                # measured floor, see flight/preflight.py

# `pm.state` values published by the firmware (pm.h: PMStates).
PM_LOW_POWER = 3
PM_SHUTDOWN = 4

# `supervisor.info` bit for "tumbled" (firmware supervisor.h). The firmware
# already cuts the motors when it sets this; the guard reports it.
SUPERVISOR_TUMBLED_BIT = 5


def station_ids(bitmask: float | None) -> tuple[int, ...]:
    if bitmask is None:
        return ()
    value = int(bitmask)
    return tuple(i for i in range(16) if value >> i & 1)


@dataclass(frozen=True)
class PositioningStatus:
    received: tuple[int, ...]
    calibrated: tuple[int, ...]
    with_geometry: tuple[int, ...]
    stored: tuple[int, ...]
    variance_m2: tuple[float | None, float | None, float | None]

    @property
    def usable(self) -> tuple[int, ...]:
        """Received, and both calibration and geometry are valid."""
        return tuple(
            s for s in self.received if s in self.calibrated and s in self.with_geometry
        )

    @property
    def received_without_geometry(self) -> tuple[int, ...]:
        return tuple(s for s in self.received if s not in self.usable)

    @property
    def ready(self) -> bool:
        return not self.problems()

    def problems(self) -> list[str]:
        """Why positioning is not ready, in words an operator can act on."""
        out: list[str] = []
        if not self.received:
            out.append(
                "No base station signal is reaching the drone. Check both base "
                "stations are on (front LED solid green), the drone is upright, "
                "and nothing blocks the line of sight."
            )
        elif self.received_without_geometry:
            ids = ", ".join(str(s) for s in self.received_without_geometry)
            out.append(
                f"Base station(s) {ids} are received but have no valid calibration "
                f"or geometry. Re-run geometry estimation in cfclient."
            )
        if self.received and len(self.usable) < MIN_USABLE_STATIONS:
            out.append(
                f"Only {len(self.usable)} usable base station(s); "
                f"{MIN_USABLE_STATIONS} are needed. One may be blocked or off."
            )
        variances = [v for v in self.variance_m2 if v is not None]
        if len(variances) < 3:
            out.append("The position filter's uncertainty is not available.")
        elif max(variances) > MAX_READY_VARIANCE_M2:
            worst_cm = max(variances) ** 0.5 * 100
            out.append(
                f"Position is uncertain by about {worst_cm:.0f} cm; it must be "
                f"under {MAX_READY_VARIANCE_M2 ** 0.5 * 100:.0f} cm. Keep the drone "
                f"still and wait for the base stations to lock on."
            )
        return out


def assess_positioning(snap: Snapshot) -> PositioningStatus:
    return PositioningStatus(
        received=station_ids(snap.get("lighthouse.bsReceive")),
        calibrated=station_ids(snap.get("lighthouse.bsCalVal")),
        with_geometry=station_ids(snap.get("lighthouse.bsGeoVal")),
        stored=station_ids(snap.get("lighthouse.bsAvailable")),
        variance_m2=(
            snap.get("kalman.varPX"),
            snap.get("kalman.varPY"),
            snap.get("kalman.varPZ"),
        ),
    )


# ── in-flight guard ──────────────────────────────────────────────────────


class Action(StrEnum):
    OK = "ok"
    LAND = "land"
    STOP = "stop"


class Reason(StrEnum):
    NONE = "none"
    TUMBLED = "tumbled"
    POSITION_LOST = "position_lost"
    RECEPTION_LOST = "reception_lost"
    BATTERY_LOW = "battery_low"
    DRIFT = "drift"
    HEIGHT_ERROR = "height_error"
    OUTSIDE_FENCE = "outside_fence"
    TELEMETRY_STALE = "telemetry_stale"


@dataclass(frozen=True)
class Verdict:
    action: Action
    reason: Reason = Reason.NONE
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.action is Action.OK


OK = Verdict(Action.OK)


@dataclass(frozen=True)
class GuardContext:
    """What this flight is supposed to be doing, fixed at takeoff."""

    ground_z: float
    fence_half_extent_m: float
    max_height_m: float
    # Hold programs only. Manual flight moves on purpose, so drift and height
    # error do not apply there — reception, battery, fence and plausibility do.
    takeoff_xy: tuple[float, float] | None = None
    target_height_m: float | None = None
    #: False when the drone has no usable position estimate.
    #:
    #: Every position-derived guard then reads the accelerometer integrating,
    #: not a position: drift, fence, height error, plausibility and reception
    #: would all fire on noise, and "landing" would steer by a number that means
    #: nothing. They are switched off, deliberately and visibly, and the
    #: operator flying by eye is the guard. What still runs: tumble, battery,
    #: stale telemetry — and the heartbeat, which lands on a quiet window.
    assisted: bool = True


class FlightGuard:
    """Checks each telemetry sample against the flight's context.

    Stateful only for the grace periods, so a single noisy sample never aborts
    a flight and a persistent fault always does.
    """

    def __init__(self, context: GuardContext) -> None:
        self.context = context
        self._reception_lost_since: float | None = None
        self._height_error_since: float | None = None
        self._low_voltage_since: float | None = None
        self._hold_armed_at: float | None = None

    def arm_hold_checks(self, now: float) -> None:
        """Start drift/height checks — call once the takeoff climb completes."""
        self._hold_armed_at = now

    def _battery_verdict(self, snap: Snapshot, now: float) -> Verdict:
        """Low battery ends the operation, in both modes and both assist levels.

        The firmware's own `pm.state` is the authority; the voltage is a second
        opinion with a grace period, because a sag under a throttle step is not
        an empty battery.
        """
        pm_state = snap.get("pm.state")
        if pm_state is not None and int(pm_state) in (PM_LOW_POWER, PM_SHUTDOWN):
            return Verdict(
                Action.LAND, Reason.BATTERY_LOW,
                "The drone reports low battery — ending the operation and landing.",
            )
        vbat = snap.get("pm.vbat")
        if vbat is not None and vbat < CRITICAL_VBAT:
            if self._low_voltage_since is None:
                self._low_voltage_since = now
            if now - self._low_voltage_since > LOW_VOLTAGE_GRACE_S:
                return Verdict(
                    Action.LAND, Reason.BATTERY_LOW,
                    f"Battery at {vbat:.2f} V — ending the operation and landing.",
                )
        else:
            self._low_voltage_since = None
        return OK

    def check(self, snap: Snapshot, now: float) -> Verdict:
        ctx = self.context
        age = snap.age_s(now)
        if age is None or age > STALE_TELEMETRY_S:
            return Verdict(
                Action.LAND, Reason.TELEMETRY_STALE,
                "Lost contact with the drone's telemetry — landing.",
            )

        info = snap.get("supervisor.info")
        if info is not None and int(info) >> SUPERVISOR_TUMBLED_BIT & 1:
            return Verdict(
                Action.STOP, Reason.TUMBLED,
                "The drone reports it has tumbled — motors stopped.",
            )

        # Everything below the battery reads the position estimate. Without base
        # stations there is no estimate to read, so those guards are off and the
        # operator flying by eye is the guard — the checks said so and the
        # operator accepted it. Battery and tumble still apply either way.
        if not ctx.assisted:
            return self._battery_verdict(snap, now)

        x = snap.get("stateEstimate.x")
        y = snap.get("stateEstimate.y")
        z = snap.get("stateEstimate.z")
        if x is None or y is None or z is None:
            return Verdict(Action.STOP, Reason.POSITION_LOST, "No position estimate.")
        height = z - ctx.ground_z

        speeds = [abs(v) for v in (snap.get("stateEstimate.vx"), snap.get("stateEstimate.vy"),
                                   snap.get("stateEstimate.vz")) if v is not None]
        variances = [v for v in (snap.get("kalman.varPX"), snap.get("kalman.varPY"))
                     if v is not None]
        if (
            (speeds and max(speeds) > MAX_PLAUSIBLE_SPEED_M_S)
            or height < BELOW_FLOOR_M
            or height > ctx.max_height_m + ABOVE_CEILING_MARGIN_M
            or (variances and max(variances) > MAX_FLIGHT_VARIANCE_M2)
        ):
            return Verdict(
                Action.STOP, Reason.POSITION_LOST,
                f"Position estimate is no longer believable (height {height:+.2f} m) — "
                f"motors stopped rather than steering by it.",
            )

        received = snap.get("lighthouse.bsReceive")
        if received is not None and int(received) == 0:
            if self._reception_lost_since is None:
                self._reception_lost_since = now
            if now - self._reception_lost_since > RECEPTION_LOST_GRACE_S:
                return Verdict(
                    Action.LAND, Reason.RECEPTION_LOST,
                    "Base station signal lost — landing while the estimate still holds.",
                )
        else:
            self._reception_lost_since = None

        battery = self._battery_verdict(snap, now)
        if not battery.ok:
            return battery

        if abs(x) > ctx.fence_half_extent_m or abs(y) > ctx.fence_half_extent_m:
            return Verdict(
                Action.LAND, Reason.OUTSIDE_FENCE,
                f"Outside the geofence at ({x:+.2f}, {y:+.2f}) m — landing.",
            )

        if self._hold_armed_at is not None and ctx.takeoff_xy is not None:
            dx, dy = x - ctx.takeoff_xy[0], y - ctx.takeoff_xy[1]
            drift = (dx * dx + dy * dy) ** 0.5
            if drift > MAX_DRIFT_M:
                return Verdict(
                    Action.LAND, Reason.DRIFT,
                    f"Drifted {drift * 100:.0f} cm from the takeoff point — landing.",
                )

        if self._hold_armed_at is not None and ctx.target_height_m is not None:
            if abs(height - ctx.target_height_m) > MAX_HEIGHT_ERROR_M:
                if self._height_error_since is None:
                    self._height_error_since = now
                if now - self._height_error_since > HEIGHT_ERROR_GRACE_S:
                    return Verdict(
                        Action.LAND, Reason.HEIGHT_ERROR,
                        f"Holding {height:.2f} m instead of {ctx.target_height_m:.2f} m — landing.",
                    )
            else:
                self._height_error_since = None

        return OK
