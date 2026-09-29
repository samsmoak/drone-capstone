"""Every check a mission passes before it can fly — one test per problem, and a
clean mission with none."""

from __future__ import annotations

import pytest

from cropwatcher.mission.plan.floorplan import PlanError, Room
from cropwatcher.mission.plan.geofence import Geofence
from cropwatcher.mission.plan.mission import MIN_HOLD_S, InspectionPoint, Mission
from cropwatcher.mission.plan.obstacles import Obstacle, ObstacleError, ObstacleKind
from cropwatcher.mission.plan.validate import (
    Severity,
    errors,
    outer_bound,
    validate_mission,
    validate_room,
)
from tests.mission.plans import OUTER, l_room, mission, room


def codes(problems):
    return {p.code for p in problems}


class TestACleanMission:
    def test_has_no_errors_and_says_coverage_is_unmeasured(self):
        problems = validate_mission(mission(), room(), outer=OUTER)
        assert errors(problems) == []
        assert codes(problems) == {"coverage_not_measured"}
        assert problems[0].severity is Severity.WARNING

    def test_measured_coverage_removes_the_warning(self):
        measured = room(coverage=Geofence.square(1.8))
        assert validate_mission(mission(), measured, outer=measured.coverage) == []


class TestTheLayersNest:
    def test_a_fence_beyond_the_rooms_map_is_an_error(self):
        wide = room(geofence=Geofence.rectangle(-2.5, -1.5, 1.5, 1.5))
        assert "fence_outside_coverage" in codes(errors(
            validate_mission(mission(), wide, outer=OUTER)))

    def test_the_outer_bound_is_the_coverage_when_measured(self):
        measured = room(coverage=Geofence.square(1.6))
        assert outer_bound(measured, default_half_extent_m=2.0) is measured.coverage
        assert outer_bound(room(), default_half_extent_m=2.0).bounds() == (-2, -2, 2, 2)

    def test_an_obstacle_outside_the_fence_is_only_a_warning(self):
        stray = room(obstacles=(Obstacle("x", ObstacleKind.CIRCLE, ((1.7, 0.0),), 0.2),))
        problems = validate_room(stray, outer=OUTER)
        found = [p for p in problems if p.code == "obstacle_outside_fence"]
        assert found and found[0].severity is Severity.WARNING


class TestPoints:
    def test_a_point_outside_the_fence(self):
        m = mission(points=(InspectionPoint("P1", 1.8, 0.0, 0.4),))
        assert "outside_fence" in codes(validate_mission(m, room(), outer=OUTER))

    def test_a_point_too_near_the_fence_edge(self):
        m = mission(points=(InspectionPoint("P1", 1.4, 0.0, 0.4),))
        found = [p for p in validate_mission(m, room(), outer=OUTER) if p.code == "near_fence"]
        assert found and found[0].where == "P1"
        assert "0.10 m" in found[0].message

    def test_a_point_on_an_obstacle(self):
        m = mission(points=(InspectionPoint("P1", 0.0, 0.0, 0.4),))
        assert "near_obstacle" in codes(validate_mission(m, room(), outer=OUTER))

    def test_home_is_checked_too(self):
        m = mission(home=(0.1, 0.1))
        found = [p for p in validate_mission(m, room(), outer=OUTER) if p.where == "home"]
        assert found

    def test_a_height_outside_the_band(self):
        m = mission(points=(InspectionPoint("P1", -1.0, 0.9, 1.5),))
        assert "height" in codes(validate_mission(m, room(), outer=OUTER))

    def test_a_short_hold(self):
        m = mission(points=(InspectionPoint("P1", -1.0, 0.9, 0.4, MIN_HOLD_S - 1),))
        assert "hold" in codes(validate_mission(m, room(), outer=OUTER))

    def test_a_cruise_height_outside_the_band(self):
        assert "cruise_height" in codes(validate_mission(
            mission(cruise_height_m=0.05), room(), outer=OUTER))

    def test_no_points(self):
        assert "no_points" in codes(validate_mission(mission(points=()), room(), outer=OUTER))

    def test_duplicate_point_ids(self):
        twin = (InspectionPoint("P1", -1.0, 0.9, 0.4), InspectionPoint("P1", 0.9, 0.9, 0.4))
        assert "duplicate_point_id" in codes(
            validate_mission(mission(points=twin), room(), outer=OUTER))

    def test_the_wrong_room(self):
        assert codes(validate_mission(mission(room_id="other"), room(), outer=OUTER)) >= {
            "wrong_room"}


class TestLegs:
    def test_a_leg_across_the_table(self):
        """Both ends clear of the table; the straight line between them is not."""
        m = mission(home=(-1.0, 0.0), points=(InspectionPoint("P1", 1.0, 0.0, 0.4),),
                    return_to_start=False)
        found = [p for p in validate_mission(m, room(), outer=OUTER)
                 if p.code == "leg_near_obstacle"]
        assert found and found[0].where == "home → P1"
        assert "crosses" in found[0].message

    def test_the_way_home_is_checked_when_returning(self):
        m = mission(home=(-1.0, 0.0), points=(InspectionPoint("P1", -1.0, 1.0, 0.4),
                                              InspectionPoint("P2", 1.0, 0.0, 0.4)))
        wheres = {p.where for p in validate_mission(m, room(), outer=OUTER)
                  if p.code == "leg_near_obstacle"}
        assert "P2 → home" in wheres

    def test_a_leg_across_the_missing_corner_of_an_l(self):
        ell = l_room()
        m = Mission(id="m", name="L", room_id="ell", home=(0.5, 0.5),
                    points=(InspectionPoint("P1", 1.8, 0.5, 0.4),
                            InspectionPoint("P2", 0.5, 1.8, 0.4)))
        found = codes(validate_mission(m, ell, outer=Geofence.square(3.0)))
        assert "leg_outside_fence" in found

    def test_a_leg_hugging_the_fence(self):
        m = mission(home=(-1.35, -1.0), points=(InspectionPoint("P1", -1.35, 1.0, 0.4),),
                    return_to_start=False)
        assert "leg_near_fence" in codes(validate_mission(m, room(), outer=OUTER))


class TestBuilding:
    def test_a_point_id_that_could_break_a_file_name_is_refused(self):
        with pytest.raises(PlanError):
            InspectionPoint("../P1", 0, 0, 0.4)

    def test_a_room_needs_a_sane_clearance(self):
        with pytest.raises(PlanError, match="clearance"):
            room(clearance_m=0.0)

    def test_two_obstacles_cannot_share_an_id(self):
        o = Obstacle("a", ObstacleKind.LINE, ((0, 0), (1, 0)))
        with pytest.raises(PlanError, match="share"):
            room(obstacles=(o, o))

    def test_obstacles_need_real_dimensions(self):
        with pytest.raises(ObstacleError):
            Obstacle("a", ObstacleKind.RECTANGLE, ((0, 0), (1, 0)))
        with pytest.raises(ObstacleError):
            Obstacle("b", ObstacleKind.CIRCLE, ((0, 0),), radius=0)
        with pytest.raises(ObstacleError):
            Obstacle("c", ObstacleKind.LINE, ((0, 0), (0, 0)))

    def test_round_trips(self):
        m = mission()
        assert Mission.from_dict(m.to_dict()).to_dict() == m.to_dict()
        r = room()
        assert Room.from_dict(r.to_dict()).to_dict() == r.to_dict()

    def test_an_unknown_format_is_refused(self):
        data = mission().to_dict()
        data["format"] = 99
        with pytest.raises(PlanError, match="format"):
            Mission.from_dict(data)


class TestDuration:
    def test_counts_every_leg_hold_and_the_landing(self):
        m = mission()
        seconds = m.estimated_duration_s(move_speed_m_s=0.2, climb_rate_m_s=0.15)
        holds = sum(p.hold_s for p in m.points)
        travel = m.path_length_m() / 0.2
        assert seconds > holds + travel
        assert seconds < holds + travel + 30
