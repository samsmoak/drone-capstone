"""Every check a mission passes before it can fly.

The layers nest, and each is checked against the one outside it:

    Lighthouse coverage   where the position can be trusted (measured)
      └ geofence          the room's hard boundary
          └ obstacles     what the drone must keep clear of
          └ home, the inspection points, and every LEG between them

Legs matter as much as points: two points can both sit in clear floor with a
bench between them, and in an L-shaped room a leg can leave the fence with
both of its ends inside. Legs include home → first point and, when returning,
last point → home — the leg out of the takeoff spot is the easiest to forget.

The result is a list of Problems, not an exception: the editor shows every one
at once, beside the point it concerns. `errors` block flying; `warnings` are
said out loud and do not.

THE EDITOR KEEPS NO COPY of these checks: it posts every draft to
/missions/validate and shows what comes back. This is the one authority — it
runs as the plan is edited, when it is saved, at the Check step from the
drone's own position, and again before anything arms.

WHAT IS FLOWN IS WHAT IS CHECKED: the points up to the end point (if one is
set) and the legs between them. Points after the end point are kept in the
plan but not flown, so they are not held to the flying rules.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cropwatcher.mission.plan.floorplan import Room
from cropwatcher.mission.plan.geofence import Geofence
from cropwatcher.mission.plan.mission import MAX_HOLD_S, MIN_HOLD_S, Mission


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    severity: Severity = Severity.ERROR
    #: The inspection point, "home" (the start), or a leg ("P1 → P2") it concerns; None for
    #: the mission or the room as a whole.
    where: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "severity": str(self.severity), "where": self.where}


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.severity is Severity.ERROR]


def outer_bound(room: Room | None, *, default_half_extent_m: float) -> Geofence:
    """The largest area anything in a room may occupy — THE ROOM'S MAP.

    The drone and its Lighthouse deck do not see walls or objects (this drone
    carries no distance sensor); what they establish is where the drone's
    position can be trusted. That measured coverage is the map every fence,
    obstacle and path must fit inside. Until it has been measured, the agent's
    default flying area stands in, and validate_room says so.
    """
    if room is not None and room.coverage is not None:
        return room.coverage
    return Geofence.square(default_half_extent_m)


def validate_room(room: Room, *, outer: Geofence) -> list[Problem]:
    """The room on its own: the fence inside the outer bound, obstacles inside
    the fence. `outer` is the room's measured coverage when it has one, and the
    agent's default fence otherwise."""
    problems: list[Problem] = []
    if room.coverage is None:
        problems.append(Problem(
            "coverage_not_measured",
            "This room's Lighthouse coverage has not been measured, so the fence is "
            "checked against the agent's default flying area instead. Measure it before "
            "trusting the edges of the room.",
            Severity.WARNING))
    if not outer.contains_fence(room.geofence):
        problems.append(Problem(
            "fence_outside_coverage",
            "Part of the geofence is outside the area the drone's position can be "
            "trusted in. Pull the fence in."))
    for obstacle in room.obstacles:
        if not all(room.geofence.contains(*p) for p in obstacle.reference_points()):
            problems.append(Problem(
                "obstacle_outside_fence",
                f"Obstacle {obstacle.name} is partly outside the geofence — it cannot "
                f"affect the flight there, so check it is where you meant.",
                Severity.WARNING, where=obstacle.id))
    return problems


def validate_mission(mission: Mission, room: Room, *, outer: Geofence) -> list[Problem]:
    """The mission in its room. Every problem found, in flying order."""
    problems = validate_room(room, outer=outer)
    fence = room.geofence
    clearance = room.clearance_m

    if mission.room_id != room.id:
        problems.append(Problem("wrong_room", f"This mission belongs to room "
                                              f"{mission.room_id}, not {room.id}."))
        return problems

    if not mission.points:
        problems.append(Problem("no_points", "Add at least one inspection point."))

    if mission.end_point_id is not None and mission.end_point_id not in mission.point_ids:
        problems.append(Problem(
            "end_point", f"The end point {mission.end_point_id} is not one of this "
            f"mission's points. Choose another end point, or clear it.",
            where=mission.end_point_id))

    duplicates = [pid for pid, n in Counter(mission.point_ids).items() if n > 1]
    for pid in duplicates:
        problems.append(Problem("duplicate_point_id",
                                f"Two inspection points share the id {pid}. Each needs its "
                                f"own — every reading taken there is stamped with it.",
                                where=pid))

    if not fence.contains_height(mission.cruise_height_m):
        problems.append(Problem(
            "cruise_height", f"Cruise height {mission.cruise_height_m:.2f} m is outside the "
            f"room's permitted {fence.z_min:.2f}–{fence.z_max:.2f} m."))

    # Home and every point: inside, clear of the fence edge, clear of obstacles
    # — beside one, or over one that has a height (obstacles.py clears). The
    # start takes off from the floor and the landing spot comes down to it, so
    # those two must be clear BESIDE every obstacle: a point over a table that
    # the flight ends at would land on the table.
    landing = None if mission.returns_home else (
        mission.flown_points[-1].id if mission.flown_points else None)
    stops: list[tuple[str, tuple[float, float], float | None, float | None]] = [
        ("home", mission.home, None, None)]
    stops += [(p.id, p.xy, p.z_m, p.hold_s) for p in mission.flown_points]
    for where, (x, y), z, hold in stops:
        z_over = None if where == landing else z      # None: must be clear beside
        label = "The start" if where == "home" else f"Point {where}"
        if not fence.contains(x, y):
            problems.append(Problem("outside_fence", f"{label} at ({x:+.2f}, {y:+.2f}) m is "
                                                     f"outside the geofence.", where=where))
            continue
        edge = fence.edge_distance(x, y)
        if edge < clearance:
            problems.append(Problem(
                "near_fence", f"{label} is {edge:.2f} m from the geofence's edge; it needs "
                f"{clearance:.2f} m, or ordinary drift would trip the fence and land the "
                f"drone.", where=where))
        for obstacle in room.obstacles:
            if obstacle.clears((x, y), z_over, clearance):
                continue
            gap = obstacle.distance_to_point((x, y))
            over = obstacle.overflight_height(clearance)
            if where == landing and over is not None:
                fix = " The flight lands here, so it must be beside the obstacle, not over it."
            elif over is not None and where != "home":
                fix = f" Or fly it at least {over:.2f} m high, over the obstacle."
            else:
                fix = ""
            problems.append(Problem(
                "near_obstacle", f"{label} is {gap:.2f} m from obstacle {obstacle.name}; "
                f"it needs {clearance:.2f} m.{fix}", where=where))
        if z is not None and not fence.contains_height(z):
            problems.append(Problem(
                "height", f"{label} height {z:.2f} m is outside the room's permitted "
                f"{fence.z_min:.2f}–{fence.z_max:.2f} m.", where=where))
        if hold is not None and not MIN_HOLD_S <= hold <= MAX_HOLD_S:
            problems.append(Problem(
                "hold", f"{label} holds {hold:.1f} s; it must hold {MIN_HOLD_S:.0f}–"
                f"{MAX_HOLD_S:.0f} s (at least 5 s of readings and 10 frames — story 3.4).",
                where=where))

    # Every leg: inside a fence that may not be convex, and clear all the way —
    # beside an obstacle, or over one with a height (at the leg's lower end).
    heights = {p.id: p.z_m for p in mission.flown_points}
    for (a, b, name), (za, zb) in zip(mission.legs(), _leg_heights(mission, heights),
                                      strict=True):
        if a == b:
            continue
        if not fence.contains_leg(a, b):
            problems.append(Problem("leg_outside_fence",
                                    f"The leg {name} leaves the geofence.", where=name))
            continue
        edge = fence.leg_edge_distance(a, b)
        if edge < clearance:
            problems.append(Problem(
                "leg_near_fence", f"The leg {name} passes {edge:.2f} m from the geofence's "
                f"edge; it needs {clearance:.2f} m.", where=name))
        for obstacle in room.obstacles:
            if obstacle.clears_leg(a, za, b, zb, clearance):
                continue
            gap = obstacle.distance_to_segment(a, b)
            over = obstacle.overflight_height(clearance)
            fix = (f" To pass over it, both ends must be at least {over:.2f} m high."
                   if over is not None else "")
            problems.append(Problem(
                "leg_near_obstacle",
                (f"The leg {name} crosses obstacle {obstacle.name}.{fix}" if gap == 0 else
                 f"The leg {name} passes {gap:.2f} m from obstacle {obstacle.name}; it "
                 f"needs {clearance:.2f} m.{fix}"), where=name))
    return problems


def _leg_heights(mission: Mission, heights: dict[str, float]) -> list[tuple[float, float]]:
    """Each leg's height at its two ends, in Mission.legs() order. The drone
    leaves the start, and comes back over it, at the cruise height (it climbs
    straight up there first, and lands straight down from there)."""
    cruise = mission.cruise_height_m
    stops = [cruise] + [heights[p.id] for p in mission.flown_points]
    if mission.returns_home:
        stops.append(cruise)
    return list(zip(stops, stops[1:], strict=False))
