"""The firmware supervisor's verdict on whether the motors may run.

After a tumble the Crazyflie supervisor marks itself crashed and holds every
motor at zero until it is told to recover. The agent did not know this: on
2026-09-17 a flight tumbled (roll 175°), the session went straight back to
"fly again", and the next flight reported "flying" for 19 seconds with thrust
0 and all four motors at 0. Nothing in the agent read the supervisor's state.

The bits are the firmware's own (supervisor.h), as cflib 0.1.33 names them in
``cflib.crazyflie.supervisor``. They are read from ``supervisor.info`` on the
telemetry stream, which the drone already publishes at 10 Hz, so asking costs
no extra radio traffic.

    crashed   recoverable: a crash-recovery request clears it, if upright
    tumbled   the drone is not upright; recovery waits until it is
    locked    not recoverable in flight software — the drone needs a restart

Pure: the callables are injected, so the recovery sequence is tested without a
drone.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

CAN_BE_ARMED = 1 << 0
IS_ARMED = 1 << 1
CAN_FLY = 1 << 3
IS_FLYING = 1 << 4
IS_TUMBLED = 1 << 5
IS_LOCKED = 1 << 6
IS_CRASHED = 1 << 7

RECOVERY_TIMEOUT_S = 3.0
RECOVERY_POLL_S = 0.2


class MotorState(StrEnum):
    READY = "ready"                 # nothing holding the motors
    RECOVERED = "recovered"         # was crashed; recovery cleared it
    UNKNOWN = "unknown"             # this firmware does not publish supervisor.info
    TUMBLED = "tumbled"             # not upright — stand it up
    CRASHED = "crashed"             # recovery was asked for and did not clear it
    LOCKED = "locked"               # needs a power cycle


@dataclass(frozen=True)
class MotorCheck:
    state: MotorState
    bits: int | None

    @property
    def ok(self) -> bool:
        return self.state in (MotorState.READY, MotorState.RECOVERED, MotorState.UNKNOWN)

    @property
    def message(self) -> str:
        return MESSAGES[self.state]


MESSAGES: dict[MotorState, str] = {
    MotorState.READY: "The drone is ready to arm.",
    MotorState.RECOVERED: "The drone had locked its motors after the last crash — recovered.",
    MotorState.UNKNOWN: "This firmware does not report its supervisor state; not checked.",
    MotorState.TUMBLED: (
        "The drone reports it is not upright. Stand it level on a flat surface, then try again."
    ),
    MotorState.CRASHED: (
        "The drone is still holding its motors after the crash. Switch it off and on, "
        "then try again."
    ),
    MotorState.LOCKED: (
        "The drone has locked its motors and needs a restart. Switch it off and on, "
        "then try again."
    ),
}


def ensure_motors_unlocked(
    read_bits: Callable[[], int | None],
    request_recovery: Callable[[], None] | None,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_s: float = RECOVERY_TIMEOUT_S,
) -> MotorCheck:
    """Read the supervisor; recover from a crash if that is all that is wrong."""
    bits = read_bits()
    if bits is None:
        return MotorCheck(MotorState.UNKNOWN, None)
    if bits & IS_LOCKED:
        return MotorCheck(MotorState.LOCKED, bits)
    if not bits & (IS_CRASHED | IS_TUMBLED):
        return MotorCheck(MotorState.READY, bits)

    if request_recovery is not None:
        request_recovery()
    deadline = clock() + timeout_s
    while clock() < deadline:
        sleep(RECOVERY_POLL_S)
        current = read_bits()
        if current is None:
            continue
        bits = current
        if bits & IS_LOCKED:
            return MotorCheck(MotorState.LOCKED, bits)
        if not bits & (IS_CRASHED | IS_TUMBLED):
            return MotorCheck(MotorState.RECOVERED, bits)
    state = MotorState.TUMBLED if bits & IS_TUMBLED else MotorState.CRASHED
    return MotorCheck(state, bits)
