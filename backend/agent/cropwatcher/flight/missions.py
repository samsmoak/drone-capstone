"""Missions — a plan, validated before anything spins.

A mission is data: an ordered list of waypoints plus what to do at each. It can
be built, saved, validated and reviewed without a drone in the room, which is
the point — the previous project could only tell you a route was bad by flying
it.

Validation is separate from execution and always runs first. ``validate()``
checks every waypoint against the geofence and every *leg* against the
occupancy map. Checking legs matters: two waypoints can both be in clear space
with a bench between them.

A route the software accepts is still not proven safe — the map is static and
does not know about people, trolleys, or a plant that grew since it was made.
The operator looks at the actual room.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from cropwatcher.flight.core import Flight, Waypoint
from cropwatcher.safety.geofence import Geofence, GeofenceViolation
from cropwatcher.safety.occupancy import ObstacleViolation, OccupancyGrid

log = logging.getLogger(__name__)


class MissionType(StrEnum):
    HOVER = "hover"
    LAWNMOWER = "lawnmower"
    WAYPOINT = "waypoint"


class EventKind(StrEnum):
    STARTED = "started"
    TAKEOFF = "takeoff"
    WAYPOINT_REACHED = "waypoint_reached"
    LANDED = "landed"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass(frozen=True)
class MissionEvent:
    kind: EventKind
    detail: str
    waypoint_index: int | None = None


class MissionValidationError(ValueError):
    """The plan is unsafe. Raised before anything arms."""

    def __init__(self, index: int, waypoint: Waypoint, cause: Exception) -> None:
        label = waypoint.label or f"#{index + 1}"
        super().__init__(f"waypoint {label}: {cause}")
        self.index = index
        self.waypoint = waypoint
        self.cause = cause


class MissionAborted(RuntimeError):
    """Execution stopped deliberately — low voltage, operator, or safety."""


@dataclass
class Mission:
    """A flight plan. Coordinates are metres relative to the takeoff point."""

    type: MissionType
    waypoints: list[Waypoint]
    altitude_m: float = 0.5
    hold_s: float = 0.0
    leg_duration_s: float = 3.0
    return_to_start: bool = True
    name: str = "mission"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.waypoints:
            raise ValueError("a mission needs at least one waypoint")

    # ── validation ───────────────────────────────────────────────────────

    def validate(
        self,
        geofence: Geofence | None = None,
        occupancy: OccupancyGrid | None = None,
        start: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """Check every waypoint and every leg. Raises on the first problem.

        Legs are checked from the *previous* waypoint, starting at `start`, so
        the path out of the takeoff point is covered too — an obstacle between
        the drone and its first waypoint is the easiest one to forget.
        """
        previous = start
        for i, wp in enumerate(self.waypoints):
            if geofence is not None:
                try:
                    geofence.check(wp.x, wp.y, wp.z)
                except GeofenceViolation as e:
                    raise MissionValidationError(i, wp, e) from e

            if occupancy is not None:
                try:
                    occupancy.check_path(previous[0], previous[1], wp.x, wp.y)
                except ObstacleViolation as e:
                    raise MissionValidationError(i, wp, e) from e

            previous = (wp.x, wp.y)

        if self.return_to_start and occupancy is not None:
            try:
                occupancy.check_path(previous[0], previous[1], start[0], start[1])
            except ObstacleViolation as e:
                raise MissionValidationError(
                    len(self.waypoints) - 1, self.waypoints[-1], e
                ) from e

    def describe(self) -> str:
        """Human-readable plan, for dry runs and the mission log."""
        lines = [
            f"{self.name} ({self.type}) — {len(self.waypoints)} waypoints, "
            f"{self.estimated_duration_s():.0f}s estimated"
        ]
        for i, wp in enumerate(self.waypoints, 1):
            label = f"  {wp.label}" if wp.label else ""
            lines.append(
                f"  {i:>3}. x={wp.x:+.2f} y={wp.y:+.2f} z={wp.z:.2f}{label}"
            )
        return "\n".join(lines)

    def estimated_duration_s(self) -> float:
        """Takeoff + legs + holds + landing. Used for the endurance gate."""
        legs = len(self.waypoints) + (1 if self.return_to_start else 0)
        return 2.0 + legs * self.leg_duration_s + len(self.waypoints) * self.hold_s + 2.5

    # ── serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "type": str(self.type),
            "name": self.name,
            "altitude_m": self.altitude_m,
            "hold_s": self.hold_s,
            "leg_duration_s": self.leg_duration_s,
            "return_to_start": self.return_to_start,
            "metadata": self.metadata,
            "waypoints": [
                {"x": w.x, "y": w.y, "z": w.z, "label": w.label} for w in self.waypoints
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Mission:
        try:
            waypoints = [
                Waypoint(float(w["x"]), float(w["y"]), float(w["z"]), w.get("label"))
                for w in data["waypoints"]
            ]
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"malformed waypoint list: {e}") from e

        return cls(
            type=MissionType(data.get("type", "waypoint")),
            waypoints=waypoints,
            altitude_m=float(data.get("altitude_m", 0.5)),
            hold_s=float(data.get("hold_s", 0.0)),
            leg_duration_s=float(data.get("leg_duration_s", 3.0)),
            return_to_start=bool(data.get("return_to_start", True)),
            name=str(data.get("name", "mission")),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_file(cls, path: Path | str) -> Mission:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


# ── generators ───────────────────────────────────────────────────────────


def hover_mission(altitude_m: float, hold_s: float, name: str = "hover") -> Mission:
    """Hold position over the takeoff point."""
    return Mission(
        type=MissionType.HOVER,
        waypoints=[Waypoint(0.0, 0.0, altitude_m, "hover")],
        altitude_m=altitude_m,
        hold_s=hold_s,
        return_to_start=False,
        name=name,
    )


def lawnmower_mission(
    width_m: float,
    height_m: float,
    step_m: float,
    altitude_m: float,
    *,
    layers: int = 1,
    layer_gap_m: float = 0.3,
    hold_s: float = 0.0,
    name: str = "lawnmower",
) -> Mission:
    """Serpentine coverage of a rectangle centred on the takeoff point.

    Lanes alternate direction so the drone never flies a wasted return leg —
    that is what makes it a lawnmower rather than a raster.
    """
    if step_m <= 0:
        raise ValueError("step must be positive")
    if width_m <= 0 or height_m <= 0:
        raise ValueError("area must be positive")

    half_w, half_h = width_m / 2, height_m / 2
    lanes = max(2, int(round(width_m / step_m)) + 1)

    waypoints: list[Waypoint] = []
    for layer in range(layers):
        z = altitude_m + layer * layer_gap_m
        for i in range(lanes):
            x = -half_w + i * (width_m / (lanes - 1))
            # Alternate the y direction per lane; on odd layers start from the
            # other end so each layer begins where the last one finished.
            top_first = (i % 2 == 0) == (layer % 2 == 0)
            ys = (half_h, -half_h) if top_first else (-half_h, half_h)
            for y in ys:
                waypoints.append(Waypoint(x, y, z, f"L{layer + 1}-{i + 1}"))

    return Mission(
        type=MissionType.LAWNMOWER,
        waypoints=waypoints,
        altitude_m=altitude_m,
        hold_s=hold_s,
        name=name,
        metadata={
            "width_m": width_m,
            "height_m": height_m,
            "step_m": step_m,
            "layers": layers,
        },
    )


# ── execution ────────────────────────────────────────────────────────────


def execute(
    mission: Mission,
    flight: Flight,
    *,
    on_event: Callable[[MissionEvent], None] | None = None,
    abort_on_low_voltage: bool = True,
) -> Iterator[MissionEvent]:
    """Fly a validated mission, yielding progress events.

    Validate first — this does not re-check the plan, because the caller may
    have supplied a geofence and map this layer knows nothing about.

    Lands on every exit path. A raised exception must never leave the drone in
    the air, so the landing happens in ``finally``.
    """
    def emit(kind: EventKind, detail: str, index: int | None = None) -> MissionEvent:
        event = MissionEvent(kind, detail, index)
        log.info("mission %s: %s", kind, detail)
        if on_event is not None:
            on_event(event)
        return event

    yield emit(EventKind.STARTED, f"{mission.name}: {len(mission.waypoints)} waypoints")

    try:
        flight.takeoff(mission.altitude_m)
        yield emit(EventKind.TAKEOFF, f"at {mission.altitude_m:.2f} m")

        for i, wp in enumerate(mission.waypoints):
            if abort_on_low_voltage and flight.voltage_critical():
                yield emit(
                    EventKind.ABORTED,
                    f"battery critical at waypoint {i + 1}, landing early",
                    i,
                )
                break

            flight.goto(wp, duration_s=mission.leg_duration_s)
            if mission.hold_s > 0:
                flight.hold(mission.hold_s)

            x, y, z = flight.position()
            yield emit(
                EventKind.WAYPOINT_REACHED,
                f"{i + 1}/{len(mission.waypoints)} at "
                f"({x:+.2f}, {y:+.2f}, {z:.2f})",
                i,
            )

        if mission.return_to_start:
            flight.goto(
                Waypoint(0.0, 0.0, mission.altitude_m),
                duration_s=mission.leg_duration_s,
            )

    except Exception as e:
        yield emit(EventKind.FAILED, f"{type(e).__name__}: {e}")
        raise
    finally:
        try:
            if flight.airborne:
                flight.land()
        except Exception:
            log.exception("landing failed during mission cleanup")

    yield emit(EventKind.LANDED, "mission complete")
