"""Which way the arrow keys move the drone — never the way its nose points.

THE PROBLEM THIS SOLVES (the owner, 2026-09-30). The arrows used to be in the
drone's own frame: ↑ moved it wherever its nose pointed. A drone set down at
-116° (flight-log.txt) or turned with A/D moved "forward" somewhere the
operator did not expect, and after half a turn ↑ came towards them. A
quadcopter can move in any direction without turning, so the nose never
needs to decide where the keys go.

THE ARROWS NOW MOVE THE DRONE IN ONE OF THESE FRAMES, and the operator picks
the first two:

  operator   ↑ away from the operator, ↓ back towards them, ← / → around
             them — to their left and right as they face the drone. It stays
             right when the drone flies behind them and they turn to face it,
             whatever the drone's heading. Needs the drone's position and the
             operator's spot. This is ArduPilot's Super Simple mode and DJI's
             Home Lock, with base stations where they use GPS. THE DEFAULT.
  room       ↑ is the room's forward: +x, the direction `cropwatcher
             geometry` asked the operator to face the drone along ("the
             direction you want to call forward"). Fixed; never turns.

and two it falls back to, said out loud in the app:

  room       from operator, when the drone is within NEAR_OPERATOR_M of the
             operator's spot — there "away" has no clear direction.
  takeoff    ↑ is the way the nose pointed at takeoff, however it turns after.
             When there is no position (no base stations, or not reported
             yet): ArduPilot's Simple mode, DJI's Course Lock. If that is the
             wrong way, Shift + the arrow it went corrects it in the air
             (NoseFacing, turn_nose) — for that flight only.
  nose       the old behaviour, only when not even a heading is reported.

WITHOUT A POSITION, NOTHING KNOWS WHERE THE OPERATOR IS. The drone has a
heading (the gyro, relative to power-on; there is no compass on a Crazyflie
2.1) and nothing else: no position, and no idea of the operator. So "away from
you" cannot be measured — it can only be TOLD, once, and then KEPT through
every turn by the heading. It stays right while the operator faces the way they
did at takeoff; turning round to follow a drone behind them needs a position
(the operator frame), or a correction in the air.

Headings follow the Crazyflie's convention, which the estimator reports:
degrees counter-clockwise from +x, so 0° is +x and 90° is +y. "Left" is 90°
counter-clockwise of forward, as cflib's +vy is.

Pure: no clock, no lock, no drone — manual.py calls resolve() every tick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class KeyFrame(StrEnum):
    """What the operator chose."""

    OPERATOR = "operator"
    ROOM = "room"


class ActiveFrame(StrEnum):
    """What the arrows are actually doing this tick."""

    OPERATOR = "operator"
    ROOM = "room"
    TAKEOFF = "takeoff"
    NOSE = "nose"


class NoseFacing(StrEnum):
    """Which way the drone's nose pointed at takeoff, as the operator stands.

    Only used with no position (the takeoff frame): it is what turns "the way
    the nose pointed" into "away from the operator". With a position the
    operator frame measures "away" directly and this is not needed.
    """

    AWAY = "away"                       # the nose pointed where the operator faces
    LEFT = "left"                       # ...to the operator's left
    RIGHT = "right"                     # ...to the operator's right
    TOWARDS = "towards"                 # ...back at the operator


#: Where the operator's forward is, relative to the nose at takeoff, degrees
#: counter-clockwise. The nose at the operator's LEFT is 90° counter-clockwise
#: of their forward, so their forward is the nose turned 90° CLOCKWISE: -90.
NOSE_TO_FORWARD_DEG: dict[NoseFacing, float] = {
    NoseFacing.AWAY: 0.0,
    NoseFacing.LEFT: -90.0,
    NoseFacing.RIGHT: 90.0,
    NoseFacing.TOWARDS: 180.0,
}


def turn_nose(nose: NoseFacing, went: NoseFacing,
              pressed: NoseFacing = NoseFacing.AWAY) -> NoseFacing:
    """Correct where up points from what the operator SAW, in the air.

    The arrow `pressed` (up: AWAY, down: TOWARDS, left, right) was flown under
    `nose` and the drone went `went` of them. That key moves the drone along
    its own direction off the current forward F; it should have gone
    `pressed`, it went `went`, so the true forward is F turned by the
    difference of the two offsets. For up (pressed AWAY) that is `went`'s
    offset alone: went LEFT means F is 90° counter-clockwise of the true
    forward, so the true forward is F turned 90° clockwise — the offset LEFT
    stands for. Turning round to face a drone behind you: up came at you,
    TOWARDS, 180°.
    """
    total = (NOSE_TO_FORWARD_DEG[nose] + NOSE_TO_FORWARD_DEG[went]
             - NOSE_TO_FORWARD_DEG[pressed]) % 360.0
    for facing, offset in NOSE_TO_FORWARD_DEG.items():
        if offset % 360.0 == total:
            return facing
    raise AssertionError(f"offsets are multiples of 90°, got {total}")  # pragma: no cover


def _wrap_deg(degrees: float) -> float:
    """Fold a heading into [-180, 180)."""
    return (degrees + 180.0) % 360.0 - 180.0


class Reason(StrEnum):
    """Why the active frame is not the chosen one."""

    NEAR_OPERATOR = "near_operator"     # within NEAR_OPERATOR_M of the spot
    NO_POSITION = "no_position"         # no base stations / not reported yet
    NO_HEADING = "no_heading"           # not even a heading to hold a direction


#: Closer than this to the operator's spot, "away from you" has no clear
#: direction — at 10 cm a sideways drift of 5 cm swings it by 30°. The arrows
#: use the room's directions until the drone is FAR_OPERATOR_M out again: the
#: gap between the two is hysteresis, so a drone hovering at the boundary does
#: not flip frames on every tick.
NEAR_OPERATOR_M = 0.50
FAR_OPERATOR_M = 0.60

#: The room's forward: +x in the Lighthouse frame, which `cropwatcher geometry`
#: defines as the direction the operator faced the drone along.
ROOM_FORWARD_DEG = 0.0


@dataclass(frozen=True)
class FrameStatus:
    """What the arrows mean right now — for the loop and for the app."""

    chosen: KeyFrame
    active: ActiveFrame
    reason: Reason | None
    #: The room-frame direction ↑ moves the drone, degrees; None for NOSE.
    forward_deg: float | None
    #: The operator's spot, and where it came from: "marked" (the operator
    #: said "I'm here") or "takeoff" (where this flight lifted off, as
    #: ArduPilot's home is where it armed). None when neither exists.
    operator: tuple[float, float] | None
    operator_source: str | None
    #: Whether the drone is inside the near-operator circle — kept so the
    #: hysteresis has something to remember.
    near: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen": str(self.chosen), "active": str(self.active),
            "reason": None if self.reason is None else str(self.reason),
            "forward_deg": None if self.forward_deg is None else round(self.forward_deg, 1),
            "operator": None if self.operator is None else [round(v, 3) for v in self.operator],
            "operator_source": self.operator_source,
        }


def resolve(
    chosen: KeyFrame,
    *,
    drone_xy: tuple[float, float] | None,
    operator_xy: tuple[float, float] | None,
    operator_source: str | None,
    takeoff_heading_deg: float | None,
    was_near: bool = False,
    nose: NoseFacing = NoseFacing.AWAY,
) -> FrameStatus:
    """Decide the frame the arrows move in, for where things are now."""
    def status(active: ActiveFrame, reason: Reason | None, forward: float | None,
               near: bool = False) -> FrameStatus:
        return FrameStatus(chosen, active, reason, forward, operator_xy, operator_source, near)

    if drone_xy is None:
        # No position: nothing to be "away from", and no room to be in. Keep
        # the operator's forward as it was at takeoff: the nose's heading then,
        # turned by where the operator said the nose pointed.
        if takeoff_heading_deg is None:
            return status(ActiveFrame.NOSE, Reason.NO_HEADING, None)
        forward = _wrap_deg(takeoff_heading_deg + NOSE_TO_FORWARD_DEG[nose])
        return status(ActiveFrame.TAKEOFF, Reason.NO_POSITION, forward)

    if chosen is KeyFrame.ROOM or operator_xy is None:
        # Room chosen — or operator chosen with no spot yet, which only
        # happens before the drone has lifted off: the room is the honest
        # fallback, and it needs no reason beyond the missing spot.
        return status(ActiveFrame.ROOM, None, ROOM_FORWARD_DEG)

    dx, dy = drone_xy[0] - operator_xy[0], drone_xy[1] - operator_xy[1]
    distance = math.hypot(dx, dy)
    near = distance < (FAR_OPERATOR_M if was_near else NEAR_OPERATOR_M)
    if near:
        return status(ActiveFrame.ROOM, Reason.NEAR_OPERATOR, ROOM_FORWARD_DEG, near=True)
    return status(ActiveFrame.OPERATOR, None, math.degrees(math.atan2(dy, dx)))


def keys_to_room(forward: float, left: float, forward_deg: float) -> tuple[float, float]:
    """A (forward, left) key vector as a room-frame (x, y) vector, when ↑
    means the room direction `forward_deg`."""
    heading = math.radians(forward_deg)
    cos_h, sin_h = math.cos(heading), math.sin(heading)
    return (forward * cos_h - left * sin_h, forward * sin_h + left * cos_h)


def room_to_body(x: float, y: float, heading_deg: float) -> tuple[float, float]:
    """A room-frame (x, y) vector as (forward, left) in the frame of a drone
    whose nose points `heading_deg` — the inverse of keys_to_room."""
    heading = math.radians(heading_deg)
    cos_h, sin_h = math.cos(heading), math.sin(heading)
    return (x * cos_h + y * sin_h, -x * sin_h + y * cos_h)
