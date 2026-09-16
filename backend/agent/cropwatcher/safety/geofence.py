"""Geofence — the bounds a waypoint must sit inside.

Deliberately simple: an axis-aligned box. The greenhouse flight area is a
rectangle, the Lighthouse coverage volume is roughly a box, and a shape anyone
can reason about in their head is worth more here than one that fits the room
tightly.

This rejects *coordinates*. It knows nothing about obstacles inside the box —
that is :mod:`cropwatcher.safety.occupancy`. Passing both is what makes a
waypoint safe to fly.
"""

from __future__ import annotations

from dataclasses import dataclass


class GeofenceViolation(ValueError):
    """A waypoint or path left the permitted volume."""


@dataclass(frozen=True)
class Geofence:
    """Permitted volume, metres, relative to the takeoff ground reference.

    `z_min` defaults above zero: a commanded altitude of 0 m is the floor, and
    nothing should be *asked* to fly there.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float = 0.10
    z_max: float = 2.00

    def __post_init__(self) -> None:
        if self.x_min >= self.x_max or self.y_min >= self.y_max or self.z_min >= self.z_max:
            raise ValueError(
                f"geofence bounds are inverted or empty: "
                f"x[{self.x_min}, {self.x_max}] y[{self.y_min}, {self.y_max}] "
                f"z[{self.z_min}, {self.z_max}]"
            )

    @classmethod
    def square(cls, half_extent_m: float, z_max: float = 2.0) -> Geofence:
        """A square centred on the takeoff point — the common greenhouse case."""
        return cls(
            x_min=-half_extent_m,
            x_max=half_extent_m,
            y_min=-half_extent_m,
            y_max=half_extent_m,
            z_max=z_max,
        )

    def contains(self, x: float, y: float, z: float) -> bool:
        return (
            self.x_min <= x <= self.x_max
            and self.y_min <= y <= self.y_max
            and self.z_min <= z <= self.z_max
        )

    def check(self, x: float, y: float, z: float) -> None:
        """Raise :class:`GeofenceViolation` naming the axis that failed.

        Naming the axis matters: "waypoint rejected" sends an operator hunting
        through three numbers, and the dashboard shows this text verbatim.
        """
        for axis, value, low, high in (
            ("x", x, self.x_min, self.x_max),
            ("y", y, self.y_min, self.y_max),
            ("z", z, self.z_min, self.z_max),
        ):
            if not low <= value <= high:
                raise GeofenceViolation(
                    f"{axis}={value:+.2f} m is outside the permitted "
                    f"[{low:+.2f}, {high:+.2f}] m"
                )

    def clamp(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        """Nearest point inside the fence.

        For *suggesting* a correction in the UI. Never use it to silently fix a
        rejected waypoint — an operator who asked to fly somewhere unsafe should
        be told, not quietly redirected.
        """
        return (
            min(max(x, self.x_min), self.x_max),
            min(max(y, self.y_min), self.y_max),
            min(max(z, self.z_min), self.z_max),
        )
