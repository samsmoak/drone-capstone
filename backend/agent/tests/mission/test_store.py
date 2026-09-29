"""Rooms and missions on the laptop: atomic, revisioned, and never fatal to a
list because one file is bad."""

from __future__ import annotations

import json

import pytest

from cropwatcher.mission.plan.floorplan import PlanError
from cropwatcher.mission.plan.mission import InspectionPoint
from cropwatcher.mission.plan.store import InUse, NotFound, PlanStore
from tests.mission.plans import mission, room


@pytest.fixture
def store(tmp_path):
    rooms, missions = tmp_path / "rooms", tmp_path / "missions"
    rooms.mkdir()
    missions.mkdir()
    return PlanStore(rooms=lambda: rooms, missions=lambda: missions)


def test_a_room_and_a_mission_round_trip(store):
    store.save_room(room())
    saved = store.save_mission(mission())
    assert store.mission("m1").to_dict() == saved.to_dict()
    assert [r.id for r in store.rooms()] == ["lab"]
    assert [m.id for m in store.missions()] == ["m1"]


def test_a_mission_needs_its_room_saved_first(store):
    with pytest.raises(PlanError, match="save the room first"):
        store.save_mission(mission())


def test_an_edit_to_an_unflown_mission_keeps_its_revision(store):
    store.save_room(room())
    store.save_mission(mission())
    edited = store.save_mission(mission(cruise_height_m=0.5))
    assert edited.revision == 1


def test_an_edit_to_a_flown_mission_makes_a_new_revision(store):
    store.save_room(room())
    store.save_mission(mission())
    store.mark_flown("m1", 1)
    assert store.mission("m1").flown_revision == 1
    edited = store.save_mission(mission(points=(InspectionPoint("P1", -1.0, 0.9, 0.4),)))
    assert edited.revision == 2
    assert edited.flown_revision == 1


def test_saving_an_unchanged_mission_changes_nothing(store):
    store.save_room(room())
    first = store.save_mission(mission())
    store.mark_flown("m1", 1)
    again = store.save_mission(mission())
    assert again.revision == first.revision


def test_a_room_in_use_is_not_deleted(store):
    store.save_room(room())
    store.save_mission(mission())
    with pytest.raises(InUse, match="1 mission uses"):
        store.delete_room("lab")
    store.delete_mission("m1")
    store.delete_room("lab")
    assert store.rooms() == []


def test_saving_a_room_again_bumps_its_revision(store):
    store.save_room(room())
    assert store.save_room(room(name="Lab 2")).revision == 2


def test_missing_things_say_so(store):
    with pytest.raises(NotFound):
        store.mission("nope")
    with pytest.raises(NotFound):
        store.room("nope")


def test_an_id_cannot_walk_out_of_the_folder(store):
    with pytest.raises(PlanError):
        store.mission("../../etc/passwd")


def test_one_bad_file_does_not_hide_the_others(store, tmp_path):
    store.save_room(room())
    store.save_mission(mission())
    (tmp_path / "missions" / "broken.json").write_text("{not json", encoding="utf-8")
    assert [m.id for m in store.missions()] == ["m1"]


def test_writes_leave_no_temporary_files(store, tmp_path):
    store.save_room(room())
    assert [p.name for p in (tmp_path / "rooms").iterdir()] == ["lab.json"]
    assert json.loads((tmp_path / "rooms" / "lab.json").read_text())["id"] == "lab"
