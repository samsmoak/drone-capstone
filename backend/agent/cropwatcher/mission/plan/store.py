"""Rooms and missions, saved on this laptop.

    <data folder>/rooms/<room id>.json
    <data folder>/missions/<mission id>.json

The laptop first, like every flight record (CLAUDE.md invariant 6): planning
and flying must work with no internet. Syncing plans to Supabase is a later
step, and the files are shaped for it.

- WRITES ARE ATOMIC: a temporary file, then a rename. A crash mid-save leaves
  the previous plan, never half of one.
- IDS ARE CHECKED before they touch a path (floorplan.ID_PATTERN), so an id
  from the API cannot walk out of the folder.
- A FILE THAT WILL NOT READ is skipped by a list with a log line. One corrupt
  plan must not hide every other.
- A FLOWN MISSION IS HISTORY: saving a change to one whose current revision
  has flown makes a new revision (mission.py, "REVISIONS").
- A ROOM IN USE IS NOT DELETED: the refusal says how many missions use it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cropwatcher import paths
from cropwatcher.mission.plan.floorplan import PlanError, Room, check_id
from cropwatcher.mission.plan.mission import Mission

log = logging.getLogger(__name__)


class NotFound(LookupError):
    """No such room or mission on this laptop."""


class InUse(PlanError):
    """A room that missions still use."""


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class PlanStore:
    """Every room and mission on this laptop."""

    def __init__(self, rooms: Callable[[], Path] = paths.rooms_dir,
                 missions: Callable[[], Path] = paths.missions_dir) -> None:
        self._rooms = rooms
        self._missions = missions

    # ── rooms ────────────────────────────────────────────────────────────

    def _room_path(self, room_id: str) -> Path:
        return self._rooms() / f"{check_id(room_id, 'room')}.json"

    def rooms(self) -> list[Room]:
        return sorted(self._read_all(self._rooms(), Room.from_dict),
                      key=lambda r: r.name.lower())

    def room(self, room_id: str) -> Room:
        path = self._room_path(room_id)
        if not path.exists():
            raise NotFound(f"No room {room_id} on this computer.")
        return Room.from_dict(self._read(path))

    def save_room(self, room: Room) -> Room:
        path = self._room_path(room.id)
        if path.exists():
            previous = Room.from_dict(self._read(path))
            room = room.edited(created_at=previous.created_at,
                               revision=previous.revision + 1)
        _write_atomic(path, room.to_dict())
        log.info("saved room %s (revision %d)", room.id, room.revision)
        return room

    def delete_room(self, room_id: str) -> None:
        path = self._room_path(room_id)
        if not path.exists():
            raise NotFound(f"No room {room_id} on this computer.")
        using = [m for m in self.missions() if m.room_id == room_id]
        if using:
            raise InUse(f"{len(using)} mission{'s' if len(using) != 1 else ''} use"
                        f"{'' if len(using) != 1 else 's'} this room. Delete or move "
                        f"{'them' if len(using) != 1 else 'it'} first.")
        path.unlink()
        log.info("deleted room %s", room_id)

    # ── missions ─────────────────────────────────────────────────────────

    def _mission_path(self, mission_id: str) -> Path:
        return self._missions() / f"{check_id(mission_id, 'mission')}.json"

    def missions(self) -> list[Mission]:
        return sorted(self._read_all(self._missions(), Mission.from_dict),
                      key=lambda m: m.updated_at, reverse=True)

    def mission(self, mission_id: str) -> Mission:
        path = self._mission_path(mission_id)
        if not path.exists():
            raise NotFound(f"No mission {mission_id} on this computer.")
        return Mission.from_dict(self._read(path))

    def save_mission(self, mission: Mission) -> Mission:
        """Save, keeping history honest: a flown revision is never overwritten.

        A mission is saved only once it is COMPLETE — its room saved and at
        least one inspection point — not once it is safe: a half-finished plan
        with a problem can be saved and fixed later, and the safety checks
        gate "use" and Start instead (validate.py, Session.run_mission). The
        desktop greys Save out on the same rule; this is the authority.
        """
        if not mission.points:
            raise PlanError("Add at least one inspection point before saving — a mission "
                            "with no points has nothing to fly to.")
        if not self._room_path(mission.room_id).exists():
            raise PlanError(f"No room {mission.room_id} on this computer — save the room "
                            f"first.")
        path = self._mission_path(mission.id)
        if path.exists():
            previous = Mission.from_dict(self._read(path))
            unchanged = _plan_of(previous) == _plan_of(mission)
            if unchanged:
                return previous
            flown = previous.flown_revision is not None and \
                previous.flown_revision >= previous.revision
            mission = mission.edited(
                created_at=previous.created_at,
                revision=previous.revision + 1 if flown else previous.revision,
                flown_revision=previous.flown_revision,
            )
        _write_atomic(path, mission.to_dict())
        log.info("saved mission %s (revision %d)", mission.id, mission.revision)
        return mission

    def mark_flown(self, mission_id: str, revision: int) -> None:
        """Record that `revision` flew. The next edit then makes a new one."""
        path = self._mission_path(mission_id)
        if not path.exists():
            return
        mission = Mission.from_dict(self._read(path))
        if mission.flown_revision == revision:
            return
        # Not edited(): flying is not an edit, so updated_at stays where it was.
        _write_atomic(path, _with_flown(mission, revision))

    def delete_mission(self, mission_id: str) -> None:
        path = self._mission_path(mission_id)
        if not path.exists():
            raise NotFound(f"No mission {mission_id} on this computer.")
        path.unlink()
        log.info("deleted mission %s", mission_id)

    # ── reading ──────────────────────────────────────────────────────────

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise PlanError(f"{path.name} could not be read: {e}") from e
        if not isinstance(data, dict):
            raise PlanError(f"{path.name} is not a plan")
        return data

    def _read_all(self, folder: Path, parse: Callable[[dict[str, Any]], Any]) -> list[Any]:
        found = []
        for path in sorted(folder.glob("*.json")):
            try:
                found.append(parse(self._read(path)))
            except PlanError as e:
                log.warning("skipping %s: %s", path.name, e)
        return found


def _plan_of(mission: Mission) -> dict[str, Any]:
    """What a mission flies — everything but its bookkeeping."""
    data = mission.to_dict()
    for key in ("revision", "flown_revision", "created_at", "updated_at"):
        data.pop(key)
    return data


def _with_flown(mission: Mission, revision: int) -> dict[str, Any]:
    data = mission.to_dict()
    data["flown_revision"] = revision
    return data
