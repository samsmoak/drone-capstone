"""Obstacles inside a room: a line (a wall, a bench edge), a rectangle (a
cabinet, a table) or a circle (a pillar, a pot).

Fixed presets with adjustable points, never freehand: a shape anyone can place
and resize precisely is worth more than one that follows a hand.

Each obstacle answers one question — how close does this point, or this leg,
come to me? — and the validation compares the answer with the room's
clearance. The drone is never allowed to touch an obstacle's outline, and not
to come within the clearance of it either.

HEIGHT IS DRAWN, NOT FLOWN OVER. An obstacle may carry its height above the
floor (`height_m`), so the 3-D room map shows a knee-high pot and a
ceiling-high shelf differently. None means floor to ceiling — every room saved
before heights existed. The checks treat EVERY obstacle as floor to ceiling
whatever its height: the drone never plans a leg over one. With the flight
system's 1.00 m ceiling and 0.25 m clearance, anything taller than about
0.7 m could never be cleared anyway, and a plan that relied on the height of a
bench someone measured by eye is a plan that clips it.

THIS IS A STATIC MAP. It knows what was drawn, not a person who walked in or a
trolley someone left. The operator still looks at the room before flying.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cropwatcher.mission.plan import shapes
from cropwatcher.mission.plan.shapes import Point

#: The tallest obstacle height accepted: a room, not a warehouse.
MAX_HEIGHT_M = 10.0


class ObstacleError(ValueError):
    """The obstacle is not a usable shape."""


class ObstacleKind(StrEnum):
    LINE = "line"
    RECTANGLE = "rectangle"
    CIRCLE = "circle"


@dataclass(frozen=True)
class Obstacle:
    """One obstacle. `points` holds its defining coordinates:

        line        two ends               ((x1, y1), (x2, y2))
        rectangle   two opposite corners   ((x_min, y_min), (x_max, y_max))
        circle      the centre             ((cx, cy),)  and `radius`
    """

    id: str
    kind: ObstacleKind
    points: tuple[Point, ...]
    radius: float = 0.0
    label: str | None = None
    #: Height above the floor, for the room map; None = floor to ceiling. Never
    #: used to clear a leg — see the module docstring.
    height_m: float | None = None

    def __post_init__(self) -> None:
        if self.height_m is not None and not (math.isfinite(self.height_m)
                                              and 0 < self.height_m <= MAX_HEIGHT_M):
            raise ObstacleError(f"obstacle {self.name}: a height must be above 0 and at "
                                f"most {MAX_HEIGHT_M:.0f} m")
        for x, y in self.points:
            if not shapes.is_finite(x, y):
                raise ObstacleError(f"obstacle {self.name}: a corner is not a number")
        if self.kind is ObstacleKind.CIRCLE:
            if len(self.points) != 1:
                raise ObstacleError(f"obstacle {self.name}: a circle has one centre")
            if not (math.isfinite(self.radius) and self.radius > 0):
                raise ObstacleError(f"obstacle {self.name}: a circle needs a radius above zero")
        elif len(self.points) != 2:
            raise ObstacleError(f"obstacle {self.name}: a {self.kind} has two points")
        elif self.kind is ObstacleKind.LINE:
            (x1, y1), (x2, y2) = self.points
            if math.hypot(x2 - x1, y2 - y1) <= 1e-6:
                raise ObstacleError(f"obstacle {self.name}: a line needs two different ends")
        elif self.kind is ObstacleKind.RECTANGLE:
            (x1, y1), (x2, y2) = self.points
            if abs(x2 - x1) <= 1e-6 or abs(y2 - y1) <= 1e-6:
                raise ObstacleError(f"obstacle {self.name}: a rectangle needs a width and "
                                    f"a depth")

    @property
    def name(self) -> str:
        return self.label or self.id

    # ── geometry ─────────────────────────────────────────────────────────

    def outline(self) -> tuple[Point, ...]:
        """The rectangle's four corners, in order."""
        (x1, y1), (x2, y2) = self.points
        lo_x, hi_x = min(x1, x2), max(x1, x2)
        lo_y, hi_y = min(y1, y2), max(y1, y2)
        return ((lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y))

    def distance_to_point(self, p: Point) -> float:
        """0 inside or on the obstacle."""
        if self.kind is ObstacleKind.CIRCLE:
            (cx, cy), = self.points
            return max(0.0, math.hypot(p[0] - cx, p[1] - cy) - self.radius)
        if self.kind is ObstacleKind.LINE:
            return shapes.point_segment_distance(p, *self.points)
        corners = self.outline()
        if shapes.point_in_polygon(p, corners):
            return 0.0
        return shapes.distance_to_boundary(p, corners)

    def distance_to_segment(self, a: Point, b: Point) -> float:
        """0 when the leg touches or crosses the obstacle."""
        if self.kind is ObstacleKind.CIRCLE:
            (cx, cy), = self.points
            return max(0.0, shapes.point_segment_distance((cx, cy), a, b) - self.radius)
        if self.kind is ObstacleKind.LINE:
            return shapes.segment_segment_distance(a, b, *self.points)
        corners = self.outline()
        if shapes.point_in_polygon(a, corners) or shapes.point_in_polygon(b, corners):
            return 0.0
        return shapes.segment_boundary_distance(a, b, corners)

    def reference_points(self) -> tuple[Point, ...]:
        """Points that must lie inside the fence for the obstacle to be in the
        room: a line's ends, a rectangle's corners, a circle's extremes."""
        if self.kind is ObstacleKind.CIRCLE:
            (cx, cy), = self.points
            r = self.radius
            return ((cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r))
        if self.kind is ObstacleKind.RECTANGLE:
            return self.outline()
        return self.points

    # ── storage ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id, "kind": str(self.kind), "label": self.label,
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
        }
        if self.kind is ObstacleKind.CIRCLE:
            out["radius"] = round(self.radius, 4)
        out["height_m"] = None if self.height_m is None else round(self.height_m, 4)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Obstacle:
        try:
            return cls(
                id=str(data["id"]),
                kind=ObstacleKind(data["kind"]),
                points=tuple((float(p[0]), float(p[1])) for p in data["points"]),
                radius=float(data.get("radius") or 0.0),
                label=(str(data["label"]) if data.get("label") else None),
                height_m=(float(data["height_m"]) if data.get("height_m") is not None
                          else None),
            )
        except (KeyError, TypeError, ValueError, IndexError) as e:
            if isinstance(e, ObstacleError):
                raise
            raise ObstacleError(f"an obstacle could not be read: {e}") from e
