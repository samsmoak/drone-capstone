"""A mission — the plan the mission controller flies.

    room               which floor plan it is flown in (by id)
    home               the PLANNED start: where the drone is expected to sit
                       before takeoff. The flight itself starts from wherever
                       the drone really is (from_start) — this mark is what
                       the plan is drawn and checked from until then.
    points             the inspection points, in the order they are flown
    end_point_id       optional: the point the flight ends and lands at. Points
                       after it stay in the plan and are not flown.
    cruise_height_m    the height it takes off to
    speed_m_s          how fast it travels between points: one of SPEED_PRESETS_M_S
    return_to_start    fly back over the start before landing (ignored when an
                       end point is set: the flight lands at the end point)

An INSPECTION POINT is one place the drone must hold and record: x and y in
absolute Lighthouse metres, a height above the floor captured at takeoff
(CLAUDE.md invariant 4), how long to hold, and a stable id. The id is what every
reading and frame taken while holding there is stamped with (story 3.5), so it
never changes once the mission is saved, and it is unique within the mission.

A mission is DATA. Nothing here flies: the mission controller
(mission/controller/) takes a saved, validated mission and flies it through
the manual flight system.

REVISIONS. Once a revision has flown it is history — a result points at the
exact plan that produced it. Saving a change to a flown mission therefore makes
a new revision (store.py), and the flight keeps a copy of the plan it flew.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any

from cropwatcher.mission.plan.floorplan import FORMAT, PlanError, check_id, now_iso
from cropwatcher.mission.plan.shapes import Point, is_finite

#: Story 3.4: "at least 10 frames and 5 seconds of readings are saved for every
#: inspection point" — the camera's ~3.7 frames a second needs about 3 s for 10
#: frames, so the readings' 5 s is the binding figure.
MIN_HOLD_S = 5.0
MAX_HOLD_S = 300.0
MAX_POINTS = 100

#: The travel speeds a mission may choose (2026-10-01, Samuel: "an autonomous
#: flight must be extra steady"). Steady, Normal, Brisk. One speed per
#: mission, never a range: every change of speed is a lean, and leaning is
#: what makes a hold unsteady. Brisk is the manual flight system's own
#: MOVE_SPEED_M_S — the fastest a mission has ever been flown, and the
#: default, so every mission saved before this flies exactly as it did.
SPEED_PRESETS_M_S = (0.10, 0.15, 0.20)
DEFAULT_SPEED_M_S = 0.20

POINT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@dataclass(frozen=True)
class InspectionPoint:
    id: str
    x_m: float
    y_m: float
    z_m: float
    hold_s: float = MIN_HOLD_S
    label: str | None = None

    def __post_init__(self) -> None:
        if not POINT_ID_PATTERN.match(self.id or ""):
            raise PlanError(f"inspection point id {self.id!r} is not valid: use 1–32 "
                            f"letters, digits, dashes or underscores")
        if not is_finite(self.x_m, self.y_m, self.z_m, self.hold_s):
            raise PlanError(f"inspection point {self.id}: a coordinate is not a number")

    @property
    def xy(self) -> Point:
        return (self.x_m, self.y_m)

    @property
    def name(self) -> str:
        return f"{self.id} ({self.label})" if self.label else self.id

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "x_m": round(self.x_m, 4),
                "y_m": round(self.y_m, 4), "z_m": round(self.z_m, 4), "hold_s": self.hold_s}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InspectionPoint:
        try:
            return cls(id=str(data["id"]), x_m=float(data["x_m"]), y_m=float(data["y_m"]),
                       z_m=float(data["z_m"]), hold_s=float(data.get("hold_s", MIN_HOLD_S)),
                       label=(str(data["label"]) if data.get("label") else None))
        except (KeyError, TypeError, ValueError) as e:
            if isinstance(e, PlanError):
                raise
            raise PlanError(f"an inspection point could not be read: missing or invalid "
                            f"{e}") from e


@dataclass(frozen=True)
class Mission:
    id: str
    name: str
    room_id: str
    home: Point
    points: tuple[InspectionPoint, ...]
    cruise_height_m: float = 0.40
    return_to_start: bool = True
    #: The travel speed between points, one of SPEED_PRESETS_M_S.
    speed_m_s: float = DEFAULT_SPEED_M_S
    #: The inspection point the flight ends and lands at, or None to fly every
    #: point. Must name a point of this mission (validate.py says so if not).
    end_point_id: str | None = None
    revision: int = 1
    #: The revision that last flew, or None. Equal to `revision` means the
    #: current plan has flown, and the next edit makes a new revision.
    flown_revision: int | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        check_id(self.id, "mission")
        check_id(self.room_id, "room")
        if not self.name.strip():
            raise PlanError("a mission needs a name")
        if len(self.points) > MAX_POINTS:
            raise PlanError(f"a mission may have at most {MAX_POINTS} inspection points")
        if not is_finite(self.home[0], self.home[1], self.cruise_height_m):
            raise PlanError("the home mark or the cruise height is not a number")
        if self.revision < 1:
            raise PlanError("a mission's revision starts at 1")
        if not any(abs(self.speed_m_s - s) < 1e-9 for s in SPEED_PRESETS_M_S):
            choices = ", ".join(f"{s * 100:.0f}" for s in SPEED_PRESETS_M_S)
            raise PlanError(f"a mission's speed is one of {choices} cm/s")

    @property
    def point_ids(self) -> tuple[str, ...]:
        return tuple(p.id for p in self.points)

    @property
    def flown_points(self) -> tuple[InspectionPoint, ...]:
        """The points actually flown, in order: every point up to and including
        the end point, or all of them when there is none (or it names no point
        — validate.py reports that as an error)."""
        if self.end_point_id is None or self.end_point_id not in self.point_ids:
            return self.points
        last = self.point_ids.index(self.end_point_id)
        return self.points[: last + 1]

    @property
    def returns_home(self) -> bool:
        """Whether the flight flies back over its start before landing. An end
        point means "land there", so it wins over return_to_start."""
        return self.return_to_start and self.end_point_id is None

    def from_start(self, start: Point) -> Mission:
        """The mission as it will actually be flown from `start` — the drone's
        own position when it is started.

        The inspection points are NOT moved. They are absolute Lighthouse
        positions tied to the equipment they inspect; shifting them with the
        drone would put a point beside the wrong pump, or inside a bench. What
        changes is the start: the first leg runs from where the drone really
        is, the return leg (if any) comes back there, and the points after an
        end point are dropped. The result is re-validated like any mission.
        """
        return replace(self, home=(float(start[0]), float(start[1])),
                       points=self.flown_points, end_point_id=None,
                       return_to_start=self.returns_home)

    def legs(self) -> list[tuple[Point, Point, str]]:
        """Every straight line flown, with a name for each: home → P1 → … and,
        when returning, the last point → home. With an end point, the legs stop
        there."""
        stops: list[tuple[Point, str]] = [(self.home, "home")]
        stops += [(p.xy, p.id) for p in self.flown_points]
        if self.returns_home:
            stops.append((self.home, "home"))
        return [(a, b, f"{na} → {nb}") for (a, na), (b, nb) in zip(stops, stops[1:], strict=False)]

    def path_length_m(self) -> float:
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b, _ in self.legs())

    def estimated_duration_s(self, *, move_speed_m_s: float, climb_rate_m_s: float,
                             settle_s: float = 1.0) -> float:
        """Takeoff, every leg, every settle and hold, and the landing.

        The speeds are the manual flight system's own (manual.py
        MOVE_SPEED_M_S, CLIMB_RATE_M_S), passed in by the caller: a plan does
        not import the flight code. The mission travels at its own speed_m_s,
        never faster than the flight system moves. Heights change during a leg
        at the climb rate, so each leg costs whichever of the two is longer.
        """
        move_speed_m_s = min(move_speed_m_s, self.speed_m_s)
        total = self.cruise_height_m / climb_rate_m_s          # takeoff
        height = self.cruise_height_m
        stops = [(self.home, self.cruise_height_m)]
        stops += [(p.xy, p.z_m) for p in self.flown_points]
        if self.returns_home:
            stops.append((self.home, self.cruise_height_m))
        for (a, _), (b, zb) in zip(stops, stops[1:], strict=False):
            horizontal = math.hypot(b[0] - a[0], b[1] - a[1]) / move_speed_m_s
            vertical = abs(zb - height) / climb_rate_m_s
            total += max(horizontal, vertical) + settle_s
            height = zb
        total += sum(p.hold_s for p in self.flown_points)
        total += height / climb_rate_m_s + 1.0                 # landing, and touchdown
        return total

    def edited(self, **changes: Any) -> Mission:
        return replace(self, **changes, updated_at=now_iso())

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT, "id": self.id, "name": self.name, "room_id": self.room_id,
            "home": [round(self.home[0], 4), round(self.home[1], 4)],
            "points": [p.to_dict() for p in self.points],
            "cruise_height_m": self.cruise_height_m,
            "return_to_start": self.return_to_start,
            "speed_m_s": self.speed_m_s,
            "end_point_id": self.end_point_id,
            "revision": self.revision, "flown_revision": self.flown_revision,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mission:
        if not isinstance(data, dict):
            raise PlanError("a mission must be an object")
        version = data.get("format", FORMAT)
        if version != FORMAT:
            raise PlanError(f"mission format {version!r} is not one this agent reads "
                            f"(it reads {FORMAT})")
        try:
            flown = data.get("flown_revision")
            return cls(
                id=str(data["id"]),
                name=str(data.get("name", "")),
                room_id=str(data["room_id"]),
                home=(float(data["home"][0]), float(data["home"][1])),
                points=tuple(InspectionPoint.from_dict(p) for p in data.get("points") or []),
                cruise_height_m=float(data.get("cruise_height_m", 0.40)),
                return_to_start=bool(data.get("return_to_start", True)),
                speed_m_s=float(data.get("speed_m_s", DEFAULT_SPEED_M_S)),
                end_point_id=(str(data["end_point_id"]) if data.get("end_point_id") else None),
                revision=int(data.get("revision", 1)),
                flown_revision=int(flown) if flown is not None else None,
                created_at=str(data.get("created_at") or now_iso()),
                updated_at=str(data.get("updated_at") or now_iso()),
            )
        except (KeyError, TypeError, ValueError, IndexError) as e:
            if isinstance(e, PlanError):
                raise
            raise PlanError(f"the mission could not be read: missing or invalid {e}") from e
