"""Rooms and missions for the tests, built the way the editor builds them."""

from __future__ import annotations

from cropwatcher.mission.plan.floorplan import Room
from cropwatcher.mission.plan.geofence import Geofence
from cropwatcher.mission.plan.mission import InspectionPoint, Mission
from cropwatcher.mission.plan.obstacles import Obstacle, ObstacleKind

#: The agent's default flying area, the outer bound while coverage is unmeasured.
OUTER = Geofence.square(2.0)


def room(**changes) -> Room:
    """A 3 m × 3 m room centred on the origin with one table in its middle."""
    base = Room(
        id="lab", name="Lab",
        geofence=Geofence.rectangle(-1.5, -1.5, 1.5, 1.5),
        obstacles=(Obstacle("table", ObstacleKind.RECTANGLE, ((-0.3, -0.3), (0.3, 0.3)),
                            label="Table"),),
    )
    return base.edited(**changes) if changes else base


def l_room() -> Room:
    """An L: the square (0..2, 0..2) minus its top-right quarter (1..2, 1..2)."""
    return Room(id="ell", name="L room", geofence=Geofence.polygon(
        [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]))


def mission(**changes) -> Mission:
    """Home in the room's corner, three points around the table and back —
    every leg clear of it (a diagonal home would cross it)."""
    base = Mission(
        id="m1", name="Pump check", room_id="lab", home=(-1.0, -1.0),
        points=(InspectionPoint("P1", -1.0, 0.9, 0.40, 5.0, "Pump 1"),
                InspectionPoint("P2", 0.9, 0.9, 0.50, 6.0, "Pump 2"),
                InspectionPoint("P3", 0.9, -1.0, 0.40, 5.0, "Valve")),
        cruise_height_m=0.40, return_to_start=True,
    )
    return base.edited(**changes) if changes else base
