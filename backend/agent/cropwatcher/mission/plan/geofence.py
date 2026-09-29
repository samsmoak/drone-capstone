"""The geofence — the hard, closed boundary a room's flying happens inside.

ALWAYS CLOSED. "Inside" means nothing for an open line, so a fence is a
rectangle, a circle, or at least three corners — and the last corner joins the
first automatically. Crossing edges are refused: a bow-tie has no single inside
either. A circle is stored as a 32-sided polygon so there is exactly one shape
for every check, in the editor, the validation and the in-flight guard.

The fence also carries the HEIGHT BAND. `z_min` is above the floor on purpose:
a commanded height of 0 m is the floor, and nothing should be asked to fly
there. `z_max` defaults to 1.00 m — the manual flight system's assisted
ceiling (flight/manual.py MAX_HEIGHT_M), which is what will refuse anything
higher anyway, so a plan cannot promise a height the flight cannot give.

Heights are metres above the floor captured at takeoff (CLAUDE.md invariant 4);
x and y are absolute Lighthouse metres.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cropwatcher.mission.plan import shapes
from cropwatcher.mission.plan.shapes import Point

DEFAULT_Z_MIN_M = 0.10
DEFAULT_Z_MAX_M = 1.00
CIRCLE_SIDES = 32
#: A fence smaller than this is a typo, not a room: 10 cm × 10 cm.
MIN_AREA_M2 = 0.01
MAX_VERTICES = 64


class GeofenceViolation(ValueError):
    """A point or leg left the fence. The message names what and where."""


class GeofenceError(ValueError):
    """The fence itself is not a usable shape."""


class FenceShape(StrEnum):
    """How it was drawn — kept so the editor can reopen a preset as a preset."""

    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    POLYGON = "polygon"


@dataclass(frozen=True)
class Geofence:
    vertices: tuple[Point, ...]
    shape: FenceShape = FenceShape.POLYGON
    z_min: float = DEFAULT_Z_MIN_M
    z_max: float = DEFAULT_Z_MAX_M

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise GeofenceError(
                f"a geofence needs at least 3 corners to enclose anything; "
                f"this one has {len(self.vertices)}")
        if len(self.vertices) > MAX_VERTICES:
            raise GeofenceError(f"a geofence may have at most {MAX_VERTICES} corners")
        for x, y in self.vertices:
            if not shapes.is_finite(x, y):
                raise GeofenceError("a geofence corner is not a number")
        for a, b in shapes.edges(self.vertices):
            if math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-6:
                raise GeofenceError(f"two corners sit on the same spot at "
                                    f"({a[0]:+.2f}, {a[1]:+.2f}) m")
        if shapes.self_intersects(self.vertices):
            raise GeofenceError("the geofence's edges cross each other, so it has no "
                                "single inside — move a corner so no two edges cross")
        if abs(shapes.signed_area(self.vertices)) < MIN_AREA_M2:
            raise GeofenceError("the geofence encloses no real area")
        if not (shapes.is_finite(self.z_min, self.z_max) and 0 <= self.z_min < self.z_max):
            raise GeofenceError(f"the height band [{self.z_min:.2f}, {self.z_max:.2f}] m "
                                f"is empty or below the floor")

    # ── presets ──────────────────────────────────────────────────────────

    @classmethod
    def rectangle(cls, x_min: float, y_min: float, x_max: float, y_max: float,
                  **band: float) -> Geofence:
        if not (x_min < x_max and y_min < y_max):
            raise GeofenceError("a rectangle needs its far corner beyond its near one")
        return cls(((x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)),
                   FenceShape.RECTANGLE, **band)

    @classmethod
    def square(cls, half_extent_m: float, **band: float) -> Geofence:
        """Centred on the Lighthouse origin — the agent's default fence."""
        return cls.rectangle(-half_extent_m, -half_extent_m, half_extent_m, half_extent_m,
                             **band)

    @classmethod
    def circle(cls, cx: float, cy: float, radius: float, **band: float) -> Geofence:
        if not radius > 0:
            raise GeofenceError("a circle needs a radius above zero")
        step = 2 * math.pi / CIRCLE_SIDES
        return cls(tuple((cx + radius * math.cos(i * step), cy + radius * math.sin(i * step))
                         for i in range(CIRCLE_SIDES)), FenceShape.CIRCLE, **band)

    @classmethod
    def polygon(cls, points: Sequence[Sequence[float]], **band: float) -> Geofence:
        return cls(tuple((float(p[0]), float(p[1])) for p in points), FenceShape.POLYGON, **band)

    # ── questions ────────────────────────────────────────────────────────

    def contains(self, x: float, y: float) -> bool:
        return shapes.point_in_polygon((x, y), self.vertices)

    def contains_height(self, z: float) -> bool:
        return self.z_min <= z <= self.z_max

    def edge_distance(self, x: float, y: float) -> float:
        return shapes.distance_to_boundary((x, y), self.vertices)

    def contains_leg(self, a: Point, b: Point) -> bool:
        return shapes.segment_in_polygon(a, b, self.vertices)

    def leg_edge_distance(self, a: Point, b: Point) -> float:
        return shapes.segment_boundary_distance(a, b, self.vertices)

    def contains_fence(self, other: Geofence) -> bool:
        return shapes.polygon_in_polygon(other.vertices, self.vertices)

    def bounds(self) -> tuple[float, float, float, float]:
        return shapes.bounds(self.vertices)

    def area_m2(self) -> float:
        return abs(shapes.signed_area(self.vertices))

    def check(self, x: float, y: float, z: float | None = None) -> None:
        """Raise GeofenceViolation naming what failed — the app shows it verbatim."""
        if not self.contains(x, y):
            raise GeofenceViolation(f"({x:+.2f}, {y:+.2f}) m is outside the geofence")
        if z is not None and not self.contains_height(z):
            raise GeofenceViolation(f"height {z:.2f} m is outside the permitted "
                                    f"[{self.z_min:.2f}, {self.z_max:.2f}] m")

    # ── storage ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": str(self.shape),
            "vertices": [[round(x, 4), round(y, 4)] for x, y in self.vertices],
            "z_min": self.z_min, "z_max": self.z_max,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Geofence:
        try:
            vertices = tuple((float(p[0]), float(p[1])) for p in data["vertices"])
            shape = FenceShape(data.get("shape", "polygon"))
            return cls(vertices, shape,
                       z_min=float(data.get("z_min", DEFAULT_Z_MIN_M)),
                       z_max=float(data.get("z_max", DEFAULT_Z_MAX_M)))
        except (KeyError, TypeError, ValueError, IndexError) as e:
            if isinstance(e, GeofenceError):
                raise
            raise GeofenceError(f"the geofence could not be read: {e}") from e
