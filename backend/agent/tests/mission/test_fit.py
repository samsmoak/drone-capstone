"""The plan that will fly: from the drone, fitted to the space, validated."""

from __future__ import annotations

import pytest

from cropwatcher.mission.plan.fit import flying_space, plan_to_fly
from cropwatcher.mission.plan.floorplan import PlanError
from cropwatcher.mission.plan.geofence import Geofence
from cropwatcher.mission.plan.mission import InspectionPoint
from cropwatcher.mission.plan.validate import errors
from tests.mission.plans import OUTER, mission, room

#: Coverage reaching only x ≤ 1.0 — the room's right-hand strip is not covered.
LEFT_COVERAGE = Geofence.rectangle(-2.0, -2.0, 1.0, 2.0)


class TestNothingToFit:
    def test_a_mission_already_fine_flies_exactly_as_drawn_from_the_drone(self):
        plan = plan_to_fly(mission(), room(), outer=OUTER, start=(-1.0, -1.0))
        assert plan.moves == ()
        assert plan.mission.points == mission().points
        assert errors(list(plan.problems)) == []


class TestTheSpace:
    def test_the_fence_is_clipped_to_the_coverage(self):
        space = flying_space(room(), LEFT_COVERAGE)
        assert space.geofence.bounds() == pytest.approx((-1.5, -1.5, 1.0, 1.5))

    def test_a_fence_inside_the_coverage_is_untouched(self):
        r = room()
        assert flying_space(r, OUTER) is r

    def test_no_overlap_is_said_in_words(self):
        with pytest.raises(PlanError, match="do not overlap"):
            flying_space(room(), Geofence.rectangle(5.0, 5.0, 6.0, 6.0))


class TestTheFit:
    def test_a_point_outside_the_coverage_moves_to_the_nearest_fine_spot(self):
        plan = plan_to_fly(mission(), room(), outer=LEFT_COVERAGE, start=(-1.0, -1.0))
        moved = {m.point_id: m for m in plan.moves}
        # P2 (0.9, 0.9) and P3 (0.9, -1.0) sit within 0.25 m of the new edge at 1.0.
        assert set(moved) == {"P2", "P3"}
        for m in moved.values():
            assert m.after[0] <= 1.0 - 0.25 + 1e-6            # clear of the edge
            assert m.distance_m < 0.3                          # the nearest, not anywhere
        # P1 was fine: untouched, exactly.
        assert plan.mission.points[0] == mission().points[0]
        assert errors(list(plan.problems)) == []

    def test_a_height_outside_the_band_is_brought_in_and_recorded(self):
        high = mission(points=(InspectionPoint("P1", -1.0, 0.9, 1.4, 5.0),))
        plan = plan_to_fly(high, room(), outer=OUTER, start=(-1.0, -1.0))
        assert plan.mission.points[0].z_m == room().geofence.z_max
        assert plan.moves[0].before[2] == 1.4

    def test_a_point_nothing_can_fit_is_named(self):
        far = mission(points=(InspectionPoint("P9", 40.0, 40.0, 0.4, 5.0),))
        plan = plan_to_fly(far, room(), outer=OUTER, start=(-1.0, -1.0))
        assert plan.unfitted == ("P9",)
        assert errors(list(plan.problems))

    def test_the_drone_itself_is_never_moved(self):
        plan = plan_to_fly(mission(), room(), outer=LEFT_COVERAGE, start=(1.3, -1.0))
        assert plan.mission.home == (1.3, -1.0)
        assert any(p.where == "home" for p in errors(list(plan.problems)))

    def test_moves_serialise(self):
        plan = plan_to_fly(mission(), room(), outer=LEFT_COVERAGE, start=(-1.0, -1.0))
        d = plan.moves[0].to_dict()
        assert set(d) == {"point_id", "from", "to", "distance_m"}
