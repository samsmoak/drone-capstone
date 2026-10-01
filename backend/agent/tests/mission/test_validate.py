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


class TestSpeed:
    """One speed per mission (2026-10-01): Steady 10, Normal 15, Brisk 20 cm/s."""

    def test_a_saved_mission_flies_at_the_speed_it_always_did(self):
        old = mission().to_dict()
        del old["speed_m_s"]
        assert Mission.from_dict(old).speed_m_s == 0.20

    @pytest.mark.parametrize("speed", [0.10, 0.15, 0.20])
    def test_each_preset_round_trips(self, speed):
        m = mission(speed_m_s=speed)
        assert Mission.from_dict(m.to_dict()).speed_m_s == speed

    @pytest.mark.parametrize("speed", [0.0, 0.05, 0.12, 0.25, float("nan")])
    def test_anything_else_is_refused(self, speed):
        with pytest.raises(PlanError, match="cm/s"):
            mission(speed_m_s=speed)

    def test_a_slower_mission_takes_longer_by_its_travel(self):
        brisk = mission(speed_m_s=0.20)
        steady = mission(speed_m_s=0.10)
        fast = brisk.estimated_duration_s(move_speed_m_s=0.2, climb_rate_m_s=0.15)
        slow = steady.estimated_duration_s(move_speed_m_s=0.2, climb_rate_m_s=0.15)
        travel = brisk.path_length_m()
        assert slow - fast == pytest.approx(travel / 0.10 - travel / 0.20, abs=2.0)

    def test_it_is_never_estimated_faster_than_the_flight_system_moves(self):
        m = mission(speed_m_s=0.20)
        assert (m.estimated_duration_s(move_speed_m_s=0.1, climb_rate_m_s=0.15)
                == mission(speed_m_s=0.10).estimated_duration_s(move_speed_m_s=0.2,
                                                                 climb_rate_m_s=0.15))


class TestEndPoint:
    """An end point: the flight flies up to it and lands there. Points after it
    stay in the plan and are not flown — or checked."""

    def test_only_the_points_up_to_it_are_flown(self):
        m = mission(end_point_id="P2")
        assert [p.id for p in m.flown_points] == ["P1", "P2"]
        assert [name for _, _, name in m.legs()] == ["home → P1", "P1 → P2"]

    def test_it_lands_there_even_with_return_to_start_on(self):
        m = mission(end_point_id="P2", return_to_start=True)
        assert m.returns_home is False
        assert m.path_length_m() < mission().path_length_m()

    def test_the_last_point_as_the_end_point_just_lands_there(self):
        assert mission(end_point_id="P3").legs()[-1][2] == "P2 → P3"

    def test_points_after_it_are_not_held_to_the_flying_rules(self):
        after = InspectionPoint("P4", 0.0, 0.0, 0.40, 5.0)          # on the table
        m = mission(points=(*mission().points, after), end_point_id="P3")
        assert not errors(validate_mission(m, room(), outer=OUTER))
        assert "near_obstacle" in codes(validate_mission(m.edited(end_point_id=None), room(),
                                                         outer=OUTER))

    def test_an_end_point_that_names_no_point_is_an_error(self):
        problems = validate_mission(mission(end_point_id="P9"), room(), outer=OUTER)
        assert "end_point" in codes(errors(problems))

    def test_the_duration_counts_only_what_is_flown(self):
        full = mission().estimated_duration_s(move_speed_m_s=0.2, climb_rate_m_s=0.15)
        short = mission(end_point_id="P1").estimated_duration_s(move_speed_m_s=0.2,
                                                                 climb_rate_m_s=0.15)
        assert short < full

    def test_it_round_trips_and_old_missions_have_none(self):
        m = mission(end_point_id="P2")
        assert Mission.from_dict(m.to_dict()).end_point_id == "P2"
        old = mission().to_dict()
        del old["end_point_id"]
        assert Mission.from_dict(old).end_point_id is None


class TestFromStart:
    """The drone's position is the start. The points never move with it."""

    def test_the_start_moves_and_the_points_do_not(self):
        m = mission().from_start((-1.0, -0.4))
        assert m.home == (-1.0, -0.4)
        assert [p.xy for p in m.points] == [p.xy for p in mission().points]

    def test_it_returns_to_where_it_actually_started(self):
        legs = mission().from_start((-1.0, -0.4)).legs()
        assert legs[0][0] == (-1.0, -0.4) and legs[-1][1] == (-1.0, -0.4)

    def test_an_end_point_is_applied_and_then_cleared(self):
        m = mission(end_point_id="P2").from_start((-1.0, -0.4))
        assert m.point_ids == ("P1", "P2")
        assert m.end_point_id is None and m.return_to_start is False

    def test_a_start_whose_first_leg_crosses_the_table_is_an_error(self):
        m = mission().from_start((0.8, -1.0))
        assert "leg_near_obstacle" in codes(validate_mission(m, room(), outer=OUTER))


class TestObstacleHeight:
    """Height is for the room map. The checks treat every obstacle as floor to
    ceiling, whatever its height."""

    def test_a_low_obstacle_still_blocks_a_leg_above_it(self):
        low = Obstacle("pot", ObstacleKind.CIRCLE, ((0.0, 0.0),), radius=0.2, height_m=0.1)
        # A 10 cm pot on the diagonal; the leg flies it at 0.9 m, well above.
        m = mission(home=(0.9, 0.9), return_to_start=False,
                    points=(InspectionPoint("P1", -1.0, -1.0, 0.9, 5.0),))
        problems = validate_mission(m, room(obstacles=(low,)), outer=OUTER)
        assert "leg_near_obstacle" in codes(problems)

    def test_it_round_trips_and_old_rooms_are_floor_to_ceiling(self):
        tall = Obstacle("shelf", ObstacleKind.RECTANGLE, ((0, 0), (1, 0.5)), height_m=1.8)
        assert Obstacle.from_dict(tall.to_dict()).height_m == 1.8
        old = tall.to_dict()
        del old["height_m"]
        assert Obstacle.from_dict(old).height_m is None

    @pytest.mark.parametrize("height", [0.0, -1.0, float("nan"), 11.0])
    def test_a_height_must_be_real(self, height):
        with pytest.raises(ObstacleError, match="height"):
            Obstacle("x", ObstacleKind.CIRCLE, ((0, 0),), radius=0.2, height_m=height)
