"""THE PLAN THAT WILL FLY — a mission fitted to the space the drone can fly in.

Samuel (2026-10-01): the plan the operator drew, and below it the plan that
will actually be executed, "relative to the available space". ONE function
makes the second from the first, and BOTH the Check step's preview and
Session.run_mission use it — a preview computed anywhere else could show one
thing while the drone flew another.

    1. from_start   the start is the drone (Mission.from_start, unchanged)
    2. the space    the room's fence, clipped to the coverage (where the
                    position can be trusted — coverage.py). Both are convex
                    or the fence is clipped to a convex outline, so the
                    result is one polygon.
    3. the fit      every inspection point outside that space — or too close
                    to its edge or an obstacle, or outside the height band —
                    is MOVED to the nearest spot that is fine, and the move
                    is recorded. Points already fine are NEVER touched: they
                    mark equipment, and scaling the whole plan would move the
                    good ones too (D1 in docs/plans/2026-10-01-…).
    4. validated    exactly as any mission (validate.py), against that space.

What it cannot fix stays a problem in words: a start (the drone) outside the
space — move the drone; a leg that crosses an obstacle — the fit moves points,
it does not re-route legs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from cropwatcher.mission.plan.coverage import clip_to_convex
from cropwatcher.mission.plan.floorplan import PlanError, Room
from cropwatcher.mission.plan.geofence import Geofence, GeofenceError
from cropwatcher.mission.plan.mission import InspectionPoint, Mission
from cropwatcher.mission.plan.shapes import Point
from cropwatcher.mission.plan.validate import Problem, validate_mission

#: How far the fit searches for a fine spot, and how finely. A point needing a
#: bigger move than this is not "the plan, fitted" — it is a different plan.
SEARCH_RADIUS_M = 3.0
SEARCH_STEP_M = 0.02
SEARCH_ANGLES = 72


@dataclass(frozen=True)
class Move:
    point_id: str
    before: tuple[float, float, float]
    after: tuple[float, float, float]

    @property
    def distance_m(self) -> float:
        return math.dist(self.before, self.after)

    def to_dict(self) -> dict[str, Any]:
        return {"point_id": self.point_id,
                "from": [round(v, 4) for v in self.before],
                "to": [round(v, 4) for v in self.after],
                "distance_m": round(self.distance_m, 4)}


@dataclass(frozen=True)
class FlyingPlan:
    """What Start will fly, and why it differs from the plan as drawn."""

    mission: Mission
    #: The room with its fence clipped to where the position can be trusted.
    room: Room
    moves: tuple[Move, ...]
    problems: tuple[Problem, ...]
    #: Points that could not be fitted within SEARCH_RADIUS_M.
    unfitted: tuple[str, ...]


def flying_space(room: Room, outer: Geofence) -> Room:
    """The room with its fence clipped to `outer` (the coverage, or the
    agent's default area until coverage is measured). Unchanged when the
    fence already lies inside it."""
    if outer.contains_fence(room.geofence):
        return room
    clipped = clip_to_convex(room.geofence.vertices, outer.vertices)
    try:
        fence = Geofence.polygon(clipped, z_min=room.geofence.z_min, z_max=room.geofence.z_max)
    except GeofenceError:
        raise PlanError("The room's fence and the space the drone's position can be trusted "
                        "in do not overlap. Measure the coverage again, or redraw the fence "
                        "where the base stations reach.") from None
    return replace(room, geofence=fence)


def plan_to_fly(mission: Mission, room: Room, *, outer: Geofence,
                start: Point | None) -> FlyingPlan:
    """The plan Start will fly: from the drone, fitted to the space, validated."""
    from_drone = mission.from_start(start) if start is not None else mission
    space = flying_space(room, outer)
    fence = space.geofence
    points: list[InspectionPoint] = []
    moves: list[Move] = []
    unfitted: list[str] = []
    for p in from_drone.points:
        z = min(max(p.z_m, fence.z_min), fence.z_max)
        xy = p.xy if _fine(p.xy, space) else _nearest_fine(p.xy, space)
        if xy is None:
            unfitted.append(p.id)
            xy = p.xy
        if xy != p.xy or z != p.z_m:
            moves.append(Move(p.id, (p.x_m, p.y_m, p.z_m), (xy[0], xy[1], z)))
            p = replace(p, x_m=xy[0], y_m=xy[1], z_m=z)
        points.append(p)
    fitted = replace(from_drone, points=tuple(points))
    problems = validate_mission(fitted, space, outer=outer)
    return FlyingPlan(fitted, space, tuple(moves), tuple(problems), tuple(unfitted))


def _fine(xy: Point, room: Room) -> bool:
    """The same point rules validate.py applies: inside, clear of the edge and
    of every obstacle by the room's clearance."""
    fence, clearance = room.geofence, room.clearance_m
    if not fence.contains(*xy) or fence.edge_distance(*xy) < clearance:
        return False
    return all(o.distance_to_point(xy) >= clearance for o in room.obstacles)


def _nearest_fine(xy: Point, room: Room) -> Point | None:
    """The nearest fine spot, searched ring by ring outwards."""
    steps = round(SEARCH_RADIUS_M / SEARCH_STEP_M)
    for k in range(1, steps + 1):
        r = k * SEARCH_STEP_M
        best: Point | None = None
        for a in range(SEARCH_ANGLES):
            t = 2 * math.pi * a / SEARCH_ANGLES
            c = (round(xy[0] + r * math.cos(t), 4), round(xy[1] + r * math.sin(t), 4))
            if _fine(c, room) and (best is None or math.dist(c, xy) < math.dist(best, xy)):
                best = c
        if best is not None:
            return best
    return None
