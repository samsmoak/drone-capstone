"""A room — the floor plan every mission in it shares.

    geofence    the closed boundary the drone may never leave
    obstacles   what is inside it that the drone must keep clear of
    coverage    where the Lighthouse position is trustworthy, MEASURED by
                carrying the drone around the room. None until measured.
    clearance   how far every point and every leg keeps from an obstacle and
                from the fence's own edge

A room is drawn once and reused: five missions in one room share one fence, so
the boundary is never redrawn and never drifts between missions.

THE CLEARANCE, 0.25 m BY DEFAULT, IS DERIVED, NOT GUESSED:
    ~0.05 m   the drone's half-span (92 mm motor to motor, diagonally)
    +0.15 m   the manual flight system's drift notice (manual.py
              DRIFT_NOTICE_M): the drift it treats as ordinary before saying
              anything
    +0.05 m   the estimator's measured noise on one base station (1.3 cm
              settled, with margin for motion — flight-status.txt)
A point on the fence line itself would be landed by the in-flight guard on
ordinary drift, which is why the fence edge gets the clearance too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from cropwatcher.mission.plan.geofence import Geofence, GeofenceError
from cropwatcher.mission.plan.obstacles import Obstacle, ObstacleError

DEFAULT_CLEARANCE_M = 0.25
#: Below the drone's own half-span a clearance means nothing; above a metre
#: nothing indoors could be planned.
MIN_CLEARANCE_M = 0.05
MAX_CLEARANCE_M = 1.00
FORMAT = 1

#: Ids go into file names: letters, digits, dash and underscore only, so none
#: can walk out of the folder.
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PlanError(ValueError):
    """A room or a mission that cannot be read or built. Words for the operator."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def check_id(value: str, what: str) -> str:
    if not ID_PATTERN.match(value or ""):
        raise PlanError(f"{what} id {value!r} is not valid: use 1–64 letters, digits, "
                        f"dashes or underscores")
    return value


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    geofence: Geofence
    obstacles: tuple[Obstacle, ...] = ()
    #: The measured Lighthouse coverage, as a closed outline. None = not measured.
    coverage: Geofence | None = None
    clearance_m: float = DEFAULT_CLEARANCE_M
    revision: int = 1
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        check_id(self.id, "room")
        if not self.name.strip():
            raise PlanError("a room needs a name")
        if not MIN_CLEARANCE_M <= self.clearance_m <= MAX_CLEARANCE_M:
            raise PlanError(f"clearance must be between {MIN_CLEARANCE_M:.2f} and "
                            f"{MAX_CLEARANCE_M:.2f} m")
        seen: set[str] = set()
        for obstacle in self.obstacles:
            if obstacle.id in seen:
                raise PlanError(f"two obstacles share the id {obstacle.id!r}")
            seen.add(obstacle.id)

    def edited(self, **changes: Any) -> Room:
        return replace(self, **changes, updated_at=now_iso())

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT, "id": self.id, "name": self.name,
            "geofence": self.geofence.to_dict(),
            "obstacles": [o.to_dict() for o in self.obstacles],
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "clearance_m": self.clearance_m, "revision": self.revision,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Room:
        if not isinstance(data, dict):
            raise PlanError("a room must be an object")
        version = data.get("format", FORMAT)
        if version != FORMAT:
            raise PlanError(f"room format {version!r} is not one this agent reads "
                            f"(it reads {FORMAT})")
        try:
            coverage = data.get("coverage")
            return cls(
                id=str(data["id"]),
                name=str(data.get("name", "")),
                geofence=Geofence.from_dict(data["geofence"]),
                obstacles=tuple(Obstacle.from_dict(o) for o in data.get("obstacles") or []),
                coverage=Geofence.from_dict(coverage) if coverage else None,
                clearance_m=float(data.get("clearance_m", DEFAULT_CLEARANCE_M)),
                revision=int(data.get("revision", 1)),
                created_at=str(data.get("created_at") or now_iso()),
                updated_at=str(data.get("updated_at") or now_iso()),
            )
        except (GeofenceError, ObstacleError) as e:
            raise PlanError(str(e)) from e
        except (KeyError, TypeError, ValueError) as e:
            if isinstance(e, PlanError):
                raise
            raise PlanError(f"the room could not be read: missing or invalid {e}") from e
