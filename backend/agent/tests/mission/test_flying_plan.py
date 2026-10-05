"""The session's side of the flyable space: the survey fills the room's coverage,
and the plan the Check step previews is exactly the plan Start flies."""

from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from cropwatcher.mission.controller import MissionState
from cropwatcher.mission.plan.geofence import Geofence
from cropwatcher.session import SessionError
from cropwatcher.telemetry.stream import Snapshot
from tests.mission.test_coverage import CORNERS
from tests.mission.test_session_missions import STARTED, make_rig
from tests.test_session import wait_for

#: Coverage reaching only x ≤ 1.0: P2 (0.9, 0.9) and P3 (0.9, -1.0) must move in.
LEFT = Geofence.rectangle(-2.0, -2.0, 1.0, 2.0)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def sample(rig, x, y, mask=0b11, trusted=True):
    """One reading while the drone is carried: the stations in `mask`
    received and, when `trusted`, measured with a 1 cm Kalman spread."""
    known = mask if trusted else 0
    spread = 0.0001 if trusted else 40.0
    rig.session._publish_telemetry(Snapshot(MappingProxyType({
        "stateEstimate.x": x, "stateEstimate.y": y, "stateEstimate.z": 1.0,
        "lighthouse.bsReceive": mask, "lighthouse.bsCalVal": known,
        "lighthouse.bsGeoVal": known,
        "kalman.varPX": spread, "kalman.varPY": spread, "kalman.varPZ": spread}), 1.0))


class TestSurvey:
    def walk(self, rig):
        for x, y in [(-1.9, -1.9), (1.0, -1.9), (1.0, 1.9), (-1.9, 1.9), (0.0, 0.0)]:
            sample(rig, x, y)

    def test_a_walk_becomes_the_rooms_coverage(self, rig, monkeypatch):
        monkeypatch.setenv("CROPWATCHER_MIN_STATIONS", "2")     # a two-station room
        rig.session.start_survey("lab")
        self.walk(rig)
        sample(rig, 5.0, 5.0, mask=0b01)              # one station: not counted
        status = rig.session.survey_status()
        assert status["active"] and status["kept"] == 5 and status["seen"] == 6
        room = rig.session.stop_survey(save=True)
        assert room is not None and room.coverage is not None
        assert room.coverage.bounds() == pytest.approx((-1.9, -1.9, 1.0, 1.9))
        assert rig.plans.room("lab").coverage == room.coverage
        assert not rig.session.survey_status()["active"]

    def test_discarding_a_walk_changes_nothing(self, rig):
        rig.session.start_survey("lab")
        self.walk(rig)
        assert rig.session.stop_survey(save=False) is None
        assert rig.plans.room("lab").coverage is None

    def test_a_walk_that_saw_too_little_says_so(self, rig):
        rig.session.start_survey("lab")
        sample(rig, 0.0, 0.0)
        with pytest.raises(SessionError, match="not enough to enclose an area"):
            rig.session.stop_survey(save=True)

    def test_received_but_untrusted_readings_never_count(self, rig):
        """2026-10-05: the station's light arrived, the station was never
        measured, and every drifting reading was counted — an outline from
        -100 m to +100 m saved as the flyable space."""
        rig.session.start_survey("lab")
        for x in (-1.9, 1.0, 40.0, 95.0):
            sample(rig, x, -1.9, trusted=False)
        status = rig.session.survey_status()
        assert status["seen"] == 4 and status["kept"] == 0 and status["spots"] == 0

    def test_readings_are_counted_as_places_not_ticks(self, rig):
        rig.session.start_survey("lab")
        for _ in range(10):                             # 1 s still: one place
            sample(rig, 0.50, 0.50)
        sample(rig, 0.90, 0.50)
        status = rig.session.survey_status()
        assert status["kept"] == 11 and status["spots"] == 2

    def test_no_survey_until_the_drone_knows_where_it_is(self, rig):
        rig.link.snapshot = lambda: Snapshot(MappingProxyType({
            "stateEstimate.x": -91.6, "stateEstimate.y": -8.2, "stateEstimate.z": 1.2,
            "lighthouse.bsReceive": 0b1, "kalman.varPX": 48.0, "kalman.varPY": 48.0,
            "kalman.varPZ": 0.5}), 1.0)
        with pytest.raises(SessionError, match="Measure it first"):
            rig.session.start_survey("lab")

    def test_a_wrong_space_can_be_forgotten(self, rig):
        rig.plans.save_room(rig.plans.room("lab").edited(coverage=LEFT))
        room = rig.session.forget_coverage("lab")
        assert room.coverage is None and rig.plans.room("lab").coverage is None

    def test_no_survey_without_a_drone(self, rig):
        rig.link.is_open = False
        with pytest.raises(SessionError, match="Connect the drone"):
            rig.session.start_survey("lab")


class TestPrediction:
    def test_it_comes_from_the_stations_on_the_drone(self, rig):
        rig.link.station_poses = lambda: list(CORNERS)
        predicted = rig.session.predicted_coverage("lab")
        assert predicted is not None and predicted.everywhere is not None

    def test_no_geometry_stored_means_no_prediction(self, rig):
        rig.link.station_poses = lambda: []
        assert rig.session.predicted_coverage("lab") is None


class TestThePlanThatWillFly:
    def with_left_coverage(self, rig):
        room = rig.plans.room("lab")
        rig.plans.save_room(room.edited(coverage=LEFT))

    def test_the_preview_moves_what_is_outside_and_nothing_else(self, rig):
        self.with_left_coverage(rig)
        plan, here = rig.session.flying_plan("m1")
        assert here == (-1.0, -1.0)
        assert {m.point_id for m in plan.moves} == {"P2", "P3"}
        assert plan.mission.points[0].xy == (-1.0, 0.9)          # P1 untouched

    def test_start_flies_exactly_the_preview(self, rig):
        self.with_left_coverage(rig)
        previewed, _ = rig.session.flying_plan("m1")
        rig.session.run_mission("m1", ambient="22C")
        assert wait_for(lambda: STARTED and STARTED[0].state is MissionState.HOLDING)
        assert STARTED[0].plan.points == previewed.mission.points

    def test_the_plan_kept_with_the_flight_records_every_move(self, rig):
        self.with_left_coverage(rig)
        rig.session.run_mission("m1", ambient="22C")
        assert wait_for(lambda: STARTED and STARTED[0].state is MissionState.HOLDING)
        flight_id = rig.session.snapshot().flight["id"]
        kept = json.loads((rig.session.history.folder / "missions" /
                           f"{flight_id}.json").read_text())
        assert {m["point_id"] for m in kept["moves"]} == {"P2", "P3"}

    def test_a_point_that_cannot_be_fitted_refuses_start_by_name(self, rig):
        from cropwatcher.mission.plan.mission import InspectionPoint
        from tests.mission.plans import mission
        rig.plans.save_mission(mission(id="far", points=(
            InspectionPoint("P1", -1.0, 0.9, 0.4, 5.0),
            InspectionPoint("P9", 40.0, 40.0, 0.4, 5.0))))
        with pytest.raises(SessionError, match="P9 cannot be brought inside"):
            rig.session.run_mission("far", ambient="22C")
        assert "arm" not in rig.link.manual_controller.events
