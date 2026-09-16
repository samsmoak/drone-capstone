"""Manual control loop.

The rule this file exists to enforce: **the browser sends intent; the agent
generates the setpoint stream.** A design that sends one packet per keypress
breaks the first time a packet is late, because the Crazyflie commander stops
accepting control below roughly 10 Hz and the drone drops.

So the browser says "forward is held" and this loop repeats that setpoint at
50 Hz on its own. If the browser goes quiet — closed tab, dead Wi-Fi, frozen
page — the heartbeat lapses and the drone lands itself.

Deliberately independent of WebSockets and of cflib, so the dangerous parts
(heartbeat expiry, thrust decay, panic) can be tested without either.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

log = logging.getLogger(__name__)

TICK_HZ = 50.0
TICK_S = 1.0 / TICK_HZ

# The browser is expected to ping ~10x/second. Half a second of silence is
# several missed pings, not a hiccup.
HEARTBEAT_TIMEOUT_S = 0.5

THRUST_MAX = 50000
THRUST_STEP = 900          # per tick while climbing
THRUST_DECAY = 350         # per tick when the operator is not asking to climb

ANGLE_DEG = 12.0
YAW_RATE_DEG_S = 70.0


class ControlState(StrEnum):
    IDLE = "idle"
    FLYING = "flying"
    LANDING = "landing"
    STOPPED = "stopped"


class Commander(Protocol):
    """The subset of cflib's commander this loop needs."""

    def send_setpoint(self, roll: float, pitch: float, yaw_rate: float, thrust: int) -> None: ...

    def send_stop_setpoint(self) -> None: ...


@dataclass
class Intent:
    """What the operator is currently asking for.

    Held-key *state*, not an event stream. The browser reports which controls
    are down; how often it reports has no bearing on how fast the drone is
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
        """Build from a browser frame, ignoring anything unrecognised.

        Unknown keys are dropped rather than raising: a newer client sending an
        extra field must not knock the drone out of the air.
        """
        if not isinstance(payload, dict):
            raise ValueError("control frame must be an object")

        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: bool(v) for k, v in payload.items() if k in known})


@dataclass
class ManualStats:
    ticks: int = 0
    heartbeat_timeouts: int = 0
    panics: int = 0
    rejected_frames: int = 0


class ManualController:
    """Runs a 50 Hz control loop from the operator's held-key intent."""

    def __init__(
        self,
        commander: Commander,
        *,
        heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S,
        tick_s: float = TICK_S,
        clock=time.monotonic,
    ) -> None:
        self._commander = commander
        self._heartbeat_timeout = heartbeat_timeout_s
        self._tick_s = tick_s
        self._clock = clock

        self._lock = threading.Lock()
        self._intent = Intent()
        self._thrust = 0.0
        self._last_heartbeat = clock()
        self._state = ControlState.IDLE
        self._thread: threading.Thread | None = None
        self._running = False
        self.stats = ManualStats()

    # ── state ────────────────────────────────────────────────────────────

    @property
    def state(self) -> ControlState:
        with self._lock:
            return self._state

    @property
    def thrust(self) -> int:
        with self._lock:
            return int(self._thrust)

    # ── operator input ───────────────────────────────────────────────────

    def set_intent(self, intent: Intent) -> None:
        with self._lock:
            self._intent = intent
            self._last_heartbeat = self._clock()
            if self._state is ControlState.IDLE:
                self._state = ControlState.FLYING

    def heartbeat(self) -> None:
        """Refresh liveness without changing what the operator is asking for."""
        with self._lock:
            self._last_heartbeat = self._clock()

    def panic(self) -> None:
        """Cut motors immediately. Checked before anything else each tick."""
        with self._lock:
            self._thrust = 0.0
            self._intent = Intent()
            self._state = ControlState.STOPPED
            self.stats.panics += 1
        self._commander.send_stop_setpoint()
        log.warning("manual control: PANIC — motors cut")

    def land(self) -> None:
        """Decay thrust to zero and stop."""
        with self._lock:
            self._intent = Intent()
            self._state = ControlState.LANDING

    # ── loop ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="manual-control")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._commander.send_stop_setpoint()

    def _run(self) -> None:
        while self._running:
            self.tick()
            time.sleep(self._tick_s)

    def tick(self) -> None:
        """One control frame. Separated from the loop so tests can drive it."""
        with self._lock:
            if self._state is ControlState.STOPPED:
                return

            now = self._clock()
            silent_for = now - self._last_heartbeat

            if silent_for > self._heartbeat_timeout and self._state is ControlState.FLYING:
                # The operator is gone. Do not hold the drone at power waiting
                # for them to come back.
                self._state = ControlState.LANDING
                self.stats.heartbeat_timeouts += 1
                log.warning(
                    "manual control: no heartbeat for %.2fs — landing", silent_for
                )

            intent = self._intent
            landing = self._state is ControlState.LANDING

            if landing:
                self._thrust = max(0.0, self._thrust - THRUST_DECAY)
                roll = pitch = yaw = 0.0
                if self._thrust <= 0.0:
                    self._state = ControlState.STOPPED
            else:
                if intent.up:
                    self._thrust = min(THRUST_MAX, self._thrust + THRUST_STEP)
                elif intent.down:
                    self._thrust = max(0.0, self._thrust - THRUST_STEP)
                else:
                    # Thrust bleeds off when nobody is asking to climb, so
                    # letting go of the keyboard brings the drone down rather
                    # than leaving it pinned at power.
                    self._thrust = max(0.0, self._thrust - THRUST_DECAY)

                pitch = ANGLE_DEG if intent.forward else -ANGLE_DEG if intent.back else 0.0
                roll = ANGLE_DEG if intent.right else -ANGLE_DEG if intent.left else 0.0
                yaw = (
                    YAW_RATE_DEG_S if intent.yaw_right
                    else -YAW_RATE_DEG_S if intent.yaw_left
                    else 0.0
                )

            thrust = int(self._thrust)
            stopped = self._state is ControlState.STOPPED
            self.stats.ticks += 1

        self._commander.send_setpoint(roll, pitch, yaw, thrust)
        if stopped:
            self._commander.send_stop_setpoint()
