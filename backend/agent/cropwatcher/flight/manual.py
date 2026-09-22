"""Manual control loop — assisted, gentle, and landed gracefully.

The rule this file exists to enforce is unchanged: **the operator sends intent;
the agent generates the setpoint stream.** A design that sends one packet per
keypress breaks the first time a packet is late, because the Crazyflie
commander stops accepting control below roughly 10 Hz and the drone drops. The
app reports which keys are held; this loop turns that into setpoints at 50 Hz
on its own, and lands if the app goes quiet.

What changed from the first version, and why:

- **Assisted, not raw thrust.** Up/down used to add 900 thrust per tick —
  about 45,000 a second, zero to full in one second — and releasing the keys
  bled thrust off so the drone sank. Keys now move a *target height* gently
  (:data:`CLIMB_RATE_M_S`), sent as a hover setpoint, and the drone's own
  position controller holds that height when nothing is pressed.
- **Armed idle.** After Start, the props turn gently on the ground
  (:data:`IDLE_THRUST`, just above cflib's "10001 = next to no power") so the
  operator can see the drone is live before it lifts.
- **Graceful landing, not a thrust fade.** Land hands over to the high-level
  commander's landing, which descends under position control. Emergency stop
  is separate and deliberate — the app requires holding a button for it.

**Two control laws, chosen by whether the drone knows where it is.**

  assisted    base stations usable. W and S move a target *height*; the drone
              holds it, and releasing every key HOLDS THE SPOT — see below.
  unassisted  no base stations. The height comes from the BAROMETER (the
              firmware's complementary estimator) and is held with a z-distance
              setpoint: W and S move a target height gently, letting go holds
              it, and Land lowers the target to the floor at a fixed rate. The
              arrows tilt the drone, because there is no position to move to.

**Letting go holds the spot, not the speed.** Assisted flight used to send a
velocity of zero when no key was held, which asks the drone to stop — not to
stay. A drone told to stop drifts: every small error in the estimate, every
draught, every gust off its own propellers moves it, and nothing brings it
back. So when the arrows are released and the glide has come to rest, the
loop takes the position the drone is at and commands THAT, absolutely, until
the operator asks for something else. The firmware then flies back to it on
its own, which is what makes a hover look like a hover.

It needs a position to anchor to, so it only happens in assisted flight, and
only while one is being reported. Without one the loop falls back to the old
zero-velocity hover rather than guessing a coordinate.

The first unassisted law drove raw thrust. In the lab (2026-09-16) the slow
ramp through liftoff let the drone skid sideways on a leg and tumble, and
letting go of W did not hold anything. A barometer height is noisy — tens of
centimetres indoors — but it is a height, and the firmware can close the loop
on it where a person on a keyboard cannot.

Unassisted exists because the operator standing over the drone is allowed to
say it is fine to fly. It is offered only after the checks say assistance is
unavailable and the operator accepts that in as many words.

Deliberately independent of WebSockets and of cflib, so the safety behaviour
(heartbeat expiry, landing, stop) is testable without either.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from cropwatcher.safety.flight_guard import MAX_PLAUSIBLE_SPEED_M_S

log = logging.getLogger(__name__)

TICK_HZ = 50.0
TICK_S = 1.0 / TICK_HZ

# The app is expected to ping ~10x/second. Half a second of silence is several
# missed pings, not a hiccup.
HEARTBEAT_TIMEOUT_S = 0.5

# cflib's send_setpoint docs: thrust 10001 is "next to no power". A little
# above that turns the props gently without lift — far below hover thrust.
IDLE_THRUST = 11000

CLIMB_RATE_M_S = 0.15               # gentle rise and fall while W / S are held
LIFTOFF_HEIGHT_M = 0.05             # target above this means "flying"
TOUCHDOWN_HEIGHT_M = 0.05           # lowering below this lands
MAX_HEIGHT_M = 1.00
MOVE_SPEED_M_S = 0.20               # arrows, body frame
YAW_RATE_DEG_S = 30.0
LAND_S = 3.0

# ── glide ────────────────────────────────────────────────────────────────
#
# Nothing the keys command changes in a step. A key press used to set the climb
# speed instantly and a release stopped it instantly — a jolt at both ends that
# the height controller answered with the bounce seen in the lab traces
# (2026-09-17: motors slamming between 0 and full every 0.2–0.4 s). Every
# command now eases toward what the keys ask for at a bounded rate.
CLIMB_ACCEL_M_S2 = 0.30             # 0 → 0.15 m/s in 0.5 s; stops within ~4 cm
MOVE_ACCEL_M_S2 = 0.40              # assisted arrows: 0 → 0.20 m/s in 0.5 s
TILT_RATE_DEG_S = 12.0              # unassisted arrows: 0 → 5° in ~0.4 s
YAW_ACCEL_DEG_S2 = 90.0             # 0 → 30 °/s in ~0.3 s

# ── unassisted flight (barometer height hold) ────────────────────────────
#
# No base stations: the firmware estimates height from the barometer and holds
# a z-distance setpoint. Lower ceiling than assisted flight, because a baro
# height wanders by tens of centimetres and the operator has less margin.
MAX_UNASSISTED_HEIGHT_M = 0.80
MAX_TILT_DEG = 5.0                  # arrows: gentle, there is no position hold
# The generic z-distance packet and the legacy rpyt packet disagree on the sign
# of pitch (cfclient negates it for its height-hold mode). VERIFY IN THE LAB:
# if the up arrow moves the drone backwards, flip this.
PITCH_SIGN = -1.0
LAND_RATE_M_S = 0.25                # target lowered to the floor at this rate
TOUCHDOWN_HOLD_S = 0.6              # settle on the floor before the motors stop


class ControlState(StrEnum):
    IDLE = "idle"                   # disarmed, motors off
    ARMED = "armed"                 # props idling on the ground
    FLYING = "flying"
    LANDING = "landing"
    LANDED = "landed"               # down and disarmed; can arm again
    STOPPED = "stopped"             # emergency stop; needs a reset


class Commander(Protocol):
    """The subset of cflib's commander this loop needs."""

    def send_setpoint(self, roll: float, pitch: float, yaw_rate: float, thrust: int) -> None: ...

    def send_hover_setpoint(
        self, vx: float, vy: float, yawrate: float, zdistance: float
    ) -> None: ...

    def send_zdistance_setpoint(
        self, roll: float, pitch: float, yawrate: float, zdistance: float
    ) -> None: ...

    def send_position_setpoint(self, x: float, y: float, z: float, yaw: float) -> None: ...

    def send_notify_setpoint_stop(self, remain_valid_milliseconds: int = 0) -> None: ...

    def send_stop_setpoint(self) -> None: ...


@dataclass
class Intent:
    """What the operator is currently asking for.

    Held-key *state*, not an event stream. The app reports which controls are
    down; how often it reports has no bearing on how fast the drone is
    commanded.
    """

    up: bool = False
    down: bool = False
    forward: bool = False
    back: bool = False
    left: bool = False
    right: bool = False
    yaw_left: bool = False
    yaw_right: bool = False

    @classmethod
    def from_payload(cls, payload: dict) -> Intent:
        """Build from an app frame, ignoring anything unrecognised.

        Unknown keys are dropped rather than raising: a newer client sending an
        extra field must not knock the drone out of the air.
        """
        if not isinstance(payload, dict):
            raise ValueError("control frame must be an object")

        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: bool(v) for k, v in payload.items() if k in known})


@dataclass(frozen=True)
class Fix:
    """Where the drone says it is, in the estimator's own frame."""

    x: float
    y: float
    yaw_deg: float


#: Below this the eased velocity counts as stopped, and the spot is taken.
#: Anchoring while still gliding would fight the glide and lurch.
STOPPED_M_S = 0.02

#: Drift off the held spot that is worth saying out loud. Under this the
#: firmware is simply doing its job and there is nothing to report; over it,
#: something is winning against the position controller and the operator
#: should know before it becomes a geofence abort. The manual geofence is
#: +/-2.00 m, which is far too coarse to notice a hover sliding across a room.
DRIFT_NOTICE_M = 0.15


@dataclass
class ManualStats:
    ticks: int = 0
    heartbeat_timeouts: int = 0
    emergency_stops: int = 0
    rejected_frames: int = 0


class ManualController:
    """Runs a 50 Hz control loop from the operator's held-key intent."""

    def __init__(
        self,
        commander: Commander,
        *,
        ground_z: float,
        land: Callable[[float, float], None],
        assisted: bool = True,
        position: Callable[[], Fix | None] | None = None,
        heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S,
        tick_s: float = TICK_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        `ground_z` is the estimator z of the floor, captured by the checks.
        `land(z, duration_s)` is the high-level commander's landing.
        `assisted` is False when the drone has no usable position estimate: W
        and S then drive the throttle directly and the operator holds the
        height by eye, because there is no height for the drone to hold.
        """
        self._commander = commander
        self._ground_z = ground_z
        self._land = land
        self._assisted = assisted
        #: Where the drone reports it is, for holding a spot. None when
        #: nothing is reporting one — then the loop keeps to velocities.
        self._position = position
        self._anchor: Fix | None = None
        #: How far the drone is from the spot it is holding, metres. 0 when no
        #: spot is held. Read by the trace and by the app.
        self._drift_m = 0.0
        #: The last fix that was believed, with its timestamp — the jump test
        #: needs something to compare against.
        self._last_fix: tuple[float, Fix] | None = None
        self._touchdown_at: float | None = None
        # The eased commands. See "glide" above.
        self._climb_velocity = 0.0
        self._vx = 0.0
        self._vy = 0.0
        self._roll = 0.0
        self._pitch = 0.0
        self._yaw_rate = 0.0
        self._heartbeat_timeout = heartbeat_timeout_s
        self._tick_s = tick_s
        self._clock = clock

        self._lock = threading.Lock()
        self._intent = Intent()
        self._target_height = 0.0
        self._last_heartbeat = clock()
        self._last_tick = clock()
        self._state = ControlState.IDLE
        self._landing_until: float | None = None
        self._landing_started = False
        self._thread: threading.Thread | None = None
        self._running = False
        self.stats = ManualStats()

    # ── state ────────────────────────────────────────────────────────────

    @property
    def state(self) -> ControlState:
        with self._lock:
            return self._state

    @property
    def target_height(self) -> float:
        with self._lock:
            return self._target_height

    @property
    def assisted(self) -> bool:
        return self._assisted

    @property
    def intent(self) -> Intent:
        """The keys currently held, for the flight trace."""
        with self._lock:
            return self._intent

    @property
    def anchor(self) -> Fix | None:
        """The spot being held, for the flight trace. None while flying by key."""
        with self._lock:
            return self._anchor

    @property
    def drift_m(self) -> float:
        """How far the drone has been pushed off the spot it is holding.

        Zero while flying by key: there is no spot to be off. This is the
        number that says whether holding a spot is working.
        """
        with self._lock:
            return self._drift_m

    @property
    def climb_velocity(self) -> float:
        """The eased climb speed the height target is moving at, m/s."""
        with self._lock:
            return self._climb_velocity

    @property
    def ground_z(self) -> float:
        """The floor, in the estimator's frame. Barometric when unassisted."""
        return self._ground_z

    # ── operator input ───────────────────────────────────────────────────

    def arm(self) -> None:
        """Start: props idle on the ground. Refused after an emergency stop."""
        with self._lock:
            if self._state is ControlState.STOPPED:
                raise RuntimeError("emergency stop is active — run the checks again first")
            if self._state not in (ControlState.IDLE, ControlState.LANDED):
                return
            self._intent = Intent()
            self._target_height = 0.0
            self._reset_glide_locked()
            self._last_heartbeat = self._clock()
            self._last_tick = self._clock()
            self._state = ControlState.ARMED
        # The firmware locks thrust until it receives one setpoint with thrust
        # 0 (crtp_commander_rpyt). Without this every setpoint after it is
        # silently held at zero: the props never idle and the keys do nothing.
        # The lab's working scripts do the same (hop_test.py, keyboard_fly.py).
        self._commander.send_setpoint(0.0, 0.0, 0.0, 0)
        log.info("manual control: armed")

    def set_intent(self, intent: Intent) -> None:
        with self._lock:
            self._intent = intent
            self._last_heartbeat = self._clock()

    def heartbeat(self) -> None:
        """Refresh liveness without changing what the operator is asking for."""
        with self._lock:
            self._last_heartbeat = self._clock()

    def land(self) -> None:
        """Graceful landing when airborne; disarm when only idling."""
        with self._lock:
            state = self._state
            if state is ControlState.FLYING:
                self._begin_landing_locked()
                return
            if state is ControlState.ARMED:
                self._state = ControlState.IDLE
        if state is ControlState.ARMED:
            self._commander.send_stop_setpoint()
            log.info("manual control: disarmed on the ground")

    def emergency_stop(self) -> None:
        """Stop the motors now. Acts immediately, not on the next tick."""
        with self._lock:
            self._intent = Intent()
            self._state = ControlState.STOPPED
            self.stats.emergency_stops += 1
        self._commander.send_stop_setpoint()
        log.warning("manual control: EMERGENCY STOP")

    def reset(self) -> None:
        """Clear an emergency stop. The session calls this only after re-checking."""
        with self._lock:
            if self._state is ControlState.STOPPED:
                self._state = ControlState.IDLE

    # ── loop ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="manual-control")
        self._thread.start()

    def stop(self) -> None:
        """Shut the loop down. Lands first if airborne — never just stops sending."""
        if self.state is ControlState.FLYING:
            self.land()
            landing_s = (LAND_S if self._assisted
                         else MAX_UNASSISTED_HEIGHT_M / LAND_RATE_M_S + TOUCHDOWN_HOLD_S)
            deadline = time.monotonic() + landing_s + 1.0
            while self.state is ControlState.LANDING and time.monotonic() < deadline:
                time.sleep(0.05)
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self.state is not ControlState.LANDED:
            self._commander.send_stop_setpoint()

    def _run(self) -> None:
        """Tick on a fixed schedule, not a fixed sleep.

        Sleeping `tick_s` after each tick adds the tick's own cost and the OS
        timer slack to every period: measured at 38 Hz, not 50. Sleeping until
        the next deadline holds the rate, and resyncs rather than bursting if
        the loop falls a whole tick behind.
        """
        next_tick = time.monotonic()
        while self._running:
            self.tick()
            next_tick += self._tick_s
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -self._tick_s:
                next_tick = time.monotonic()

    def tick(self) -> None:
        """One control frame. Separated from the loop so tests can drive it."""
        send: Callable[[], None] | None = None
        with self._lock:
            now = self._clock()
            dt = min(max(now - self._last_tick, 0.0), 0.1)
            self._last_tick = now
            self.stats.ticks += 1
            state = self._state
            silent = now - self._last_heartbeat > self._heartbeat_timeout

            if state is ControlState.ARMED:
                if silent:
                    self.stats.heartbeat_timeouts += 1
                    self._state = ControlState.IDLE
                    log.warning("manual control: app went quiet while armed — disarming")
                    send = self._commander.send_stop_setpoint
                else:
                    intent = self._intent
                    self._glide_height_locked(CLIMB_RATE_M_S if intent.up else 0.0, dt)
                    if self._target_height > LIFTOFF_HEIGHT_M:
                        self._state = ControlState.FLYING
                        send = self._flight_setpoint_locked(intent, dt)
                    else:
                        send = lambda: self._commander.send_setpoint(0.0, 0.0, 0.0, IDLE_THRUST)  # noqa: E731

            elif state is ControlState.FLYING:
                if silent:
                    self.stats.heartbeat_timeouts += 1
                    log.warning("manual control: app went quiet — landing")
                    self._begin_landing_locked()
                else:
                    intent = self._intent
                    climb = (1 if intent.up else 0) - (1 if intent.down else 0)
                    self._glide_height_locked(climb * CLIMB_RATE_M_S, dt)
                    if intent.down and self._target_height <= TOUCHDOWN_HEIGHT_M:
                        self._begin_landing_locked()
                    else:
                        send = self._flight_setpoint_locked(intent, dt)

            if self._state is ControlState.LANDING:
                if self._assisted:
                    if self._landing_until is not None and now >= self._landing_until:
                        self._state = ControlState.LANDED
                        self._landing_until = None
                        send = self._commander.send_stop_setpoint
                    elif not self._landing_started:
                        self._landing_started = True
                        send = self._start_landing_commands
                else:
                    # Lower the target at a fixed rate — a controlled descent on
                    # the barometer, not a throttle cut — then settle and stop.
                    self._landing_started = True
                    self._glide_height_locked(-LAND_RATE_M_S, dt)
                    if self._target_height <= 0.0:
                        if self._touchdown_at is None:
                            self._touchdown_at = now
                        if now - self._touchdown_at >= TOUCHDOWN_HOLD_S:
                            self._state = ControlState.LANDED
                            self._touchdown_at = None
                            send = self._commander.send_stop_setpoint
                        else:
                            send = self._zdistance_setpoint_locked(Intent(), dt)
                    else:
                        send = self._zdistance_setpoint_locked(Intent(), dt)

        if send is not None:
            send()

    # ── helpers (lock held) ──────────────────────────────────────────────

    @staticmethod
    def _ease(current: float, target: float, max_step: float) -> float:
        return current + max(-max_step, min(max_step, target - current))

    def _reset_glide_locked(self) -> None:
        self._climb_velocity = self._vx = self._vy = 0.0
        self._roll = self._pitch = self._yaw_rate = 0.0
        self._release_anchor_locked()

    def _release_anchor_locked(self) -> None:
        self._anchor = None
        self._drift_m = 0.0
        self._last_fix = None

    def _believable_fix_locked(self) -> Fix | None:
        """The reported position, unless it moved faster than a drone can.

        A fix that jumps further between two ticks than the drone could
        possibly have flown is the ESTIMATOR moving, not the drone, and acting
        on it is the worst thing this loop can do: it would fly hard towards a
        place the drone already is. Measured in the lab on 2026-09-21 with
        stale base-station geometry — the estimate moved 21 cm in a single
        0.1 s step (2.1 m/s) while the drone sat still on the floor, with both
        stations received 96 % of the time. The arrows command 0.20 m/s.

        A rejected fix is not an error: the previous anchor stays, and the
        drone keeps flying to the spot it was already holding, which is
        exactly right if the estimate is the thing that moved.
        """
        if self._position is None:
            return None
        fix = self._position()
        if fix is None:
            self._last_fix = None
            return None
        now = self._clock()
        previous = self._last_fix
        if previous is not None:
            elapsed = now - previous[0]
            if elapsed > 0:
                moved = math.hypot(fix.x - previous[1].x, fix.y - previous[1].y)
                if moved / elapsed > MAX_PLAUSIBLE_SPEED_M_S:
                    log.warning(
                        "ignoring a position that jumped %.0f cm in %.0f ms — that is "
                        "the estimator, not the drone; check the base-station geometry",
                        moved * 100, elapsed * 1000,
                    )
                    return None
        self._last_fix = (now, fix)
        return fix

    def _glide_height_locked(self, desired_velocity: float, dt: float) -> None:
        """Move the height target at an eased climb speed, within the ceiling."""
        ceiling = MAX_HEIGHT_M if self._assisted else MAX_UNASSISTED_HEIGHT_M
        self._climb_velocity = self._ease(
            self._climb_velocity, desired_velocity, CLIMB_ACCEL_M_S2 * dt)
        target = self._target_height + self._climb_velocity * dt
        if target >= ceiling or target <= 0.0:
            # Stopping at a limit is a hard edge by nature; the speed there is at
            # most the climb rate, which the height controller absorbs.
            self._climb_velocity = 0.0
        self._target_height = min(ceiling, max(0.0, target))

    def _flight_setpoint_locked(self, intent: Intent, dt: float) -> Callable[[], None]:
        if self._assisted:
            return self._hover_setpoint_locked(intent, dt)
        return self._zdistance_setpoint_locked(intent, dt)

    def _hover_setpoint_locked(self, intent: Intent, dt: float) -> Callable[[], None]:
        forward = (1 if intent.forward else 0) - (1 if intent.back else 0)
        # cflib MotionCommander: left is +vy, turning left is +yawrate.
        left = (1 if intent.left else 0) - (1 if intent.right else 0)
        yaw = (1 if intent.yaw_left else 0) - (1 if intent.yaw_right else 0)
        self._vx = self._ease(self._vx, forward * MOVE_SPEED_M_S, MOVE_ACCEL_M_S2 * dt)
        self._vy = self._ease(self._vy, left * MOVE_SPEED_M_S, MOVE_ACCEL_M_S2 * dt)
        self._yaw_rate = self._ease(self._yaw_rate, yaw * YAW_RATE_DEG_S, YAW_ACCEL_DEG_S2 * dt)
        z = self._ground_z + self._target_height
        vx, vy, rate = self._vx, self._vy, self._yaw_rate

        asked_to_move = bool(forward or left or yaw)
        gliding = max(abs(vx), abs(vy), abs(rate) / YAW_RATE_DEG_S) > STOPPED_M_S
        if asked_to_move or gliding:
            # Under the operator's hand, or still coasting to a stop: a spot
            # taken now would be the wrong one, and holding it would fight
            # the glide.
            self._release_anchor_locked()
            return lambda: self._commander.send_hover_setpoint(vx, vy, rate, z)

        fix = self._believable_fix_locked()
        if self._anchor is None:
            self._anchor = fix
        anchor = self._anchor
        if anchor is None:
            # Nothing is reporting a position. Ask for stillness rather than
            # invent a coordinate to fly to.
            return lambda: self._commander.send_hover_setpoint(0.0, 0.0, 0.0, z)

        # How far the correction is from done. The setpoint below does not
        # change with it: an absolute position IS the strongest correction
        # this link can send, and the firmware already pushes harder the
        # further off it is, at 100 Hz. What the distance adds is knowing.
        if fix is not None:
            self._drift_m = math.hypot(fix.x - anchor.x, fix.y - anchor.y)
            if self._drift_m > DRIFT_NOTICE_M:
                log.warning(
                    "%.0f cm off the spot being held and still correcting", self._drift_m * 100)
        return lambda: self._commander.send_position_setpoint(
            anchor.x, anchor.y, z, anchor.yaw_deg)

    def _zdistance_setpoint_locked(self, intent: Intent, dt: float) -> Callable[[], None]:
        """Level attitude from the arrows, height held by the firmware on the
        barometer — the unassisted law. Tilt and yaw ease in and out."""
        forward = (1 if intent.forward else 0) - (1 if intent.back else 0)
        right = (1 if intent.right else 0) - (1 if intent.left else 0)
        # Turning left is a positive yaw rate (cflib MotionCommander.start_turn_left).
        yaw = (1 if intent.yaw_left else 0) - (1 if intent.yaw_right else 0)
        self._pitch = self._ease(
            self._pitch, forward * MAX_TILT_DEG * PITCH_SIGN, TILT_RATE_DEG_S * dt)
        # Positive roll is to the right in the firmware's setpoint frame.
        self._roll = self._ease(self._roll, right * MAX_TILT_DEG, TILT_RATE_DEG_S * dt)
        self._yaw_rate = self._ease(self._yaw_rate, yaw * YAW_RATE_DEG_S, YAW_ACCEL_DEG_S2 * dt)
        z = self._ground_z + self._target_height
        roll, pitch, rate = self._roll, self._pitch, self._yaw_rate
        return lambda: self._commander.send_zdistance_setpoint(roll, pitch, rate, z)

    def _begin_landing_locked(self) -> None:
        self._intent = Intent()
        self._state = ControlState.LANDING
        self._landing_started = False
        self._landing_until = self._clock() + LAND_S
        self._touchdown_at = None

    def _start_landing_commands(self) -> None:
        # Low-level setpoints hold priority over the high-level commander
        # until released (CLAUDE.md #2). Without this the landing command is
        # ignored and the drone keeps hovering at its last setpoint.
        self._commander.send_notify_setpoint_stop()
        self._land(self._ground_z, LAND_S)
        log.info("manual control: landing")
