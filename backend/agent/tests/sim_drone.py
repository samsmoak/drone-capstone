"""A drone in software, flown by the REAL manual flight system.

Not a mock of ManualController: the real one, over a FakeCommander and a
FakeClock, exactly as tests/test_manual.py's Rig drives it. What this adds is
a body that MOVES — the position the estimator reports follows the position
setpoints the loop sends — so a mission scenario proves the mission controller
AND the tuned flight system together, on one clock, with no thread.

HOW IT MOVES
    While airborne, the drone's true (x, y, z) follows the last setpoint with
    a first-order lag (time constant lag_s), plus a steady x-y drift (wind).
    z is in the estimator's frame, like the setpoints: the floor is ground_z,
    not 0 (CLAUDE.md invariant 4), so a point's height above the floor is
    z - ground_z. The estimator reports the position at the stream's 10 Hz
    (telemetry/stream.py PERIOD_MS), with optional Gaussian noise on every
    axis from a seeded generator, so the same seed always gives the same
    flight. `position` is the Fix the loop reads (x, y, yaw); `position_z`
    is the height the estimator reports beside it.

    Landing is the firmware's high-level land: it comes down where it is, so
    the x-y setpoint is pinned to the drone's position when landing begins
    and the height setpoint drops to the floor.
    landed_at is where it touched down — or, after an emergency stop in the
    air, where it fell.

THE THINGS THAT GO WRONG, each a real path the flight system already has:
    stall()             the drone stops following (snagged, a dead motor)
    push(dx, dy)        a gust, at a believable speed (the loop rejects
                        estimator jumps faster than MAX_PLAUSIBLE_SPEED_M_S)
    hold_key(intent)    the operator takes over
    guard_lands()       what the in-flight guard does: land()
    emergency_stop()    the motors stop now
    window_goes_quiet() heartbeats stop: the dead-man lands it

The shape is the one agreed in mission-verification.txt, PART 1.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

from cropwatcher.flight.manual import TICK_S, ControlState, Fix, Intent, ManualController
from cropwatcher.mission.controller.mission_controller import TICK_S as CONTROLLER_TICK_S
from cropwatcher.telemetry.stream import PERIOD_MS
from tests.fakes import FakeClock, FakeCommander

#: The manual flight system's 50 Hz loop.
MANUAL_TICK_S = TICK_S
#: How often a scenario ticks a mission: the controller's own rate, never a copy.
MISSION_TICK_S = CONTROLLER_TICK_S
#: How often the estimator reports a position: the telemetry stream's rate.
ESTIMATE_S = PERIOD_MS / 1000.0
#: A believable gust: well under MAX_PLAUSIBLE_SPEED_M_S (2.0 m/s), the speed
#: past which the loop discards a fix as the estimator jumping.
PUSH_SPEED_M_S = 0.5

_AIRBORNE = (ControlState.FLYING, ControlState.LANDING)


def follow(position: tuple[float, float], setpoint: tuple[float, float], dt: float,
           lag_s: float) -> tuple[float, float]:
    """One step of a first-order lag: after lag_s of a held setpoint the
    position has covered 1 - 1/e (63 %) of the way, whatever dt is."""
    k = 1.0 - math.exp(-dt / lag_s) if lag_s > 0 else 1.0
    return (position[0] + (setpoint[0] - position[0]) * k,
            position[1] + (setpoint[1] - position[1]) * k)


class SimDrone:
    """A Crazyflie on a FakeClock, flown by the real ManualController."""

    def __init__(self, *, start: Fix, ground_z: float = 1.0, assisted: bool = True,
                 lag_s: float = 0.5, noise_m: float = 0.0,
                 drift_m_s: tuple[float, float] = (0.0, 0.0), seed: int = 0) -> None:
        self.clock = FakeClock()
        self.cmd = FakeCommander()
        self.lag_s = lag_s
        self.noise_m = noise_m
        self.drift_m_s = drift_m_s
        self._rng = random.Random(seed)
        self._true = (start.x, start.y)
        self.ground_z = ground_z
        self._true_z = ground_z                # on the floor
        self._setpoint_z: float | None = None
        self._yaw = start.yaw_deg
        self._setpoint: tuple[float, float] | None = None
        self._body_velocity = (0.0, 0.0)       # a hover setpoint, before any fix
        self._seen = 0                         # commands already applied
        self._stalled = False
        self._quiet = False
        self._push_left = (0.0, 0.0)
        self._ticks = 0
        self._was_airborne = False
        self._landing_spot: tuple[float, float] | None = None
        self._estimate_at = -math.inf
        self._watchers: list[Callable[[], None]] = []
        #: The high-level land calls the loop made: (ground z, duration).
        self.lands: list[tuple[float, float]] = []
        #: Where it touched down (or fell), once it has.
        self.landed_at: tuple[float, float] | None = None
        #: What the estimator reports now. Updated at ESTIMATE_S.
        self.position: Fix = start
        self.position_z: float = ground_z
        #: The last height commanded, in the estimator's frame (the firmware's
        #: posCtl.targetZ), or None before any.
        self.target_z: float | None = None
        self.ctl = ManualController(
            self.cmd, ground_z=ground_z, land=lambda z, d: self.lands.append((z, d)),
            assisted=assisted, clock=self.clock,
            position=(lambda: self.position) if assisted else None,
            heading=lambda: self._yaw,
        )

    # ── the session's part ───────────────────────────────────────────────

    def arm(self) -> None:
        """What the session does before a mission: arm. The session also calls
        start(), which runs the loop on a thread; here step() is the loop."""
        self.ctl.arm()

    @property
    def true_xy(self) -> tuple[float, float]:
        """Where the drone really is — what noise and the estimator hide."""
        return self._true

    @property
    def true_height(self) -> float:
        """How high the drone really is above the floor."""
        return self._true_z - self.ground_z

    def watch(self, observer: Callable[[], None]) -> None:
        """Call `observer` after every manual tick — to sample, say,
        current_point_id at the rate the loop runs."""
        self._watchers.append(observer)

    # ── time ─────────────────────────────────────────────────────────────

    def step(self, seconds: float, mission: object | None = None) -> None:
        """Advance the one clock in MANUAL_TICK_S steps: heartbeat (unless the
        window has gone quiet), the loop's tick, the drone moving — and
        mission.tick() every MISSION_TICK_S when a mission is given."""
        every = round(MISSION_TICK_S / MANUAL_TICK_S)
        for _ in range(round(seconds / MANUAL_TICK_S)):
            self._one_tick()
            if mission is not None and self._ticks % every == 0:
                mission.tick()                  # type: ignore[attr-defined]
            for observer in self._watchers:
                observer()

    def run_until(self, mission: object | None, done: Callable[[], bool], *,
                  limit_s: float) -> float:
        """Step until done() is true and return the simulated seconds it took.
        Fails the test at limit_s: no scenario can hang."""
        began = self.clock()
        while not done():
            if self.clock() - began >= limit_s:
                raise AssertionError(
                    f"not done after {limit_s:.1f} s of simulated flight "
                    f"(the loop is {self.ctl.state})")
            self.step(MANUAL_TICK_S, mission)
        return self.clock() - began

    # ── what goes wrong ──────────────────────────────────────────────────

    def stall(self) -> None:
        """The drone stops following its setpoint: a stuck drone."""
        self._stalled = True

    def push(self, dx: float, dy: float) -> None:
        """Move the drone by (dx, dy) at PUSH_SPEED_M_S — a gust. The position
        controller pulls it back as it goes, so the drone ends up displaced by
        less than (dx, dy)."""
        self._push_left = (self._push_left[0] + dx, self._push_left[1] + dy)

    def hold_key(self, intent: Intent) -> None:
        """The operator holds keys (Intent() releases them)."""
        self.ctl.set_intent(intent)

    def guard_lands(self) -> None:
        """What the in-flight guard does on a breach or a low battery."""
        self.ctl.land()

    def emergency_stop(self) -> None:
        self.ctl.emergency_stop()

    def window_goes_quiet(self) -> None:
        """Heartbeats stop, as when the operator's window closes or hangs."""
        self._quiet = True

    # ── the body ─────────────────────────────────────────────────────────

    def _one_tick(self) -> None:
        self.clock.advance(MANUAL_TICK_S)
        self._ticks += 1
        if not self._quiet:
            self.ctl.heartbeat()
        if self.clock() - self._estimate_at >= ESTIMATE_S - 1e-9:
            self._estimate_at = self.clock()
            self._report()
        self.ctl.tick()
        self._apply_commands()
        state = self.ctl.state
        if state is ControlState.LANDING and self._setpoint is not self._landing_spot:
            # The firmware's land comes down where the drone is.
            self._setpoint = self._landing_spot = self._true
            self._setpoint_z = self.ground_z
        if state in _AIRBORNE:
            self._move(MANUAL_TICK_S)
        # Compared across ticks, not within one: an emergency stop or a land()
        # changes the state between ticks, from another caller.
        if self._was_airborne and state not in _AIRBORNE and self.landed_at is None:
            self.landed_at = self._true
        if state not in _AIRBORNE:
            self._true_z = self.ground_z           # on the floor, or fallen to it
        self._was_airborne = state in _AIRBORNE

    def _apply_commands(self) -> None:
        for command in self.cmd.commands[self._seen:]:
            if command[0] == "position":
                self._setpoint = (command[1], command[2])
                self._setpoint_z = self.target_z = command[3]
                self._yaw = command[4]
            elif command[0] == "hover":
                self._body_velocity = (command[1], command[2])
                self._setpoint_z = self.target_z = command[4]
            elif command[0] == "zdistance":
                self._setpoint_z = self.target_z = command[4]
        self._seen = len(self.cmd.commands)

    def _move(self, dt: float) -> None:
        x, y = self._true
        if not self._stalled:
            if self._setpoint is not None:
                x, y = follow((x, y), self._setpoint, dt, self.lag_s)
            else:
                # No position yet, so a velocity in the drone's own frame.
                vx, vy = self._body_velocity
                c, s = math.cos(math.radians(self._yaw)), math.sin(math.radians(self._yaw))
                x, y = x + (vx * c - vy * s) * dt, y + (vx * s + vy * c) * dt
            x, y = x + self.drift_m_s[0] * dt, y + self.drift_m_s[1] * dt
            if self._setpoint_z is not None:
                self._true_z = follow((self._true_z, 0.0), (self._setpoint_z, 0.0), dt,
                                      self.lag_s)[0]
        left = math.hypot(*self._push_left)
        if left > 0:
            step = min(left, PUSH_SPEED_M_S * dt)
            ux, uy = self._push_left[0] / left, self._push_left[1] / left
            x, y = x + ux * step, y + uy * step
            self._push_left = (self._push_left[0] - ux * step, self._push_left[1] - uy * step)
        self._true = (x, y)

    def _report(self) -> None:
        x, y, z = self._true[0], self._true[1], self._true_z
        if self.noise_m > 0:
            x += self._rng.gauss(0.0, self.noise_m)
            y += self._rng.gauss(0.0, self.noise_m)
            z += self._rng.gauss(0.0, self.noise_m)
        self.position = Fix(x, y, self._yaw)
        self.position_z = z
