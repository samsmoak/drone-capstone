"""The geofence: always closed, never crossing itself, and honest about legs in
rooms that are not convex."""

from __future__ import annotations

import math

import pytest

from cropwatcher.mission.plan import shapes
from cropwatcher.mission.plan.geofence import (
    CIRCLE_SIDES,
    FenceShape,
    Geofence,
    GeofenceError,
    GeofenceViolation,
)
from tests.mission.plans import l_room


class TestAlwaysClosed:
    def test_three_points_enclose_a_room(self):
        fence = Geofence.polygon([(0, 0), (2, 0), (0, 2)])
        assert fence.contains(0.5, 0.5)
        assert fence.area_m2() == pytest.approx(2.0)

    @pytest.mark.parametrize("points", [[], [(0, 0)], [(0, 0), (1, 1)]])
    def test_fewer_than_three_points_is_not_a_fence(self, points):
        with pytest.raises(GeofenceError, match="at least 3"):
            Geofence.polygon(points)

    def test_a_bow_tie_is_refused(self):
        """Four points whose edges cross: there is no single inside."""
        with pytest.raises(GeofenceError, match="cross"):
            Geofence.polygon([(0, 0), (2, 2), (2, 0), (0, 2)])

    def test_three_points_on_a_line_enclose_nothing(self):
        with pytest.raises(GeofenceError):
            Geofence.polygon([(0, 0), (1, 0), (2, 0)])

    def test_two_corners_on_one_spot_are_refused(self):
        with pytest.raises(GeofenceError, match="same spot"):
            Geofence.polygon([(0, 0), (1, 0), (1, 0), (0, 1)])

    def test_a_corner_that_is_not_a_number_is_refused(self):
        with pytest.raises(GeofenceError, match="not a number"):
            Geofence.polygon([(0, 0), (math.nan, 0), (0, 1)])

    def test_an_empty_height_band_is_refused(self):
        with pytest.raises(GeofenceError, match="height band"):
            Geofence.square(1.0, z_min=0.5, z_max=0.5)


class TestPresets:
    def test_a_rectangle_is_four_corners(self):
        fence = Geofence.rectangle(-1, -2, 1, 2)
        assert fence.shape is FenceShape.RECTANGLE
        assert fence.bounds() == (-1, -2, 1, 2)
        assert fence.area_m2() == pytest.approx(8.0)

    def test_a_rectangle_needs_its_far_corner_beyond_the_near(self):
        with pytest.raises(GeofenceError):
            Geofence.rectangle(1, 0, -1, 1)

    def test_a_circle_is_a_polygon_close_to_the_true_circle(self):
        fence = Geofence.circle(0.5, -0.5, 1.0)
        assert fence.shape is FenceShape.CIRCLE
        assert len(fence.vertices) == CIRCLE_SIDES
        # A 32-gon's area is within 0.7 % of the circle's.
        assert fence.area_m2() == pytest.approx(math.pi, rel=0.007)
        assert fence.contains(0.5, -0.5)
        assert not fence.contains(1.6, -0.5)

    def test_a_circle_needs_a_radius(self):
        with pytest.raises(GeofenceError):
            Geofence.circle(0, 0, 0)


class TestQuestions:
    def test_the_boundary_counts_as_inside(self):
        fence = Geofence.square(1.0)
        assert fence.contains(1.0, 0.0)
        assert not fence.contains(1.01, 0.0)

    def test_distance_to_the_edge(self):
        assert Geofence.square(1.0).edge_distance(0.25, 0.0) == pytest.approx(0.75)

    def test_check_names_what_failed(self):
        fence = Geofence.square(1.0)
        with pytest.raises(GeofenceViolation, match="outside the geofence"):
            fence.check(3.0, 0.0)
        with pytest.raises(GeofenceViolation, match="height 0.00"):
            fence.check(0.0, 0.0, 0.0)          # the floor is never a target

    def test_a_leg_with_both_ends_inside_can_still_leave_an_l_shaped_room(self):
        fence = l_room().geofence
        a, b = (1.8, 0.5), (0.5, 1.8)           # across the missing quarter
        assert fence.contains(*a) and fence.contains(*b)
        assert not fence.contains_leg(a, b)

    def test_a_leg_through_the_inner_corner_only_touches_the_fence(self):
        """It meets the boundary at the reflex corner and never leaves: inside,
        but zero clearance — which validation then reports as near_fence."""
        fence = l_room().geofence
        assert fence.contains_leg((1.5, 0.5), (0.5, 1.5))
        assert fence.leg_edge_distance((1.5, 0.5), (0.5, 1.5)) == 0.0

    def test_a_leg_along_the_inside_is_inside(self):
        fence = l_room().geofence
        assert fence.contains_leg((0.5, 0.5), (0.5, 1.5))
        assert fence.contains_leg((0.5, 0.5), (1.5, 0.5))

    def test_a_leg_touching_the_reflex_corner_from_outside_is_outside(self):
        """Grazing the inner corner of the L runs along the outside of it."""
        fence = l_room().geofence
        assert not fence.contains_leg((2.0, 1.0), (1.0, 2.0))

    def test_one_fence_inside_another(self):
        outer = Geofence.square(2.0)
        assert outer.contains_fence(Geofence.square(1.5))
        assert not outer.contains_fence(Geofence.rectangle(-1, -1, 2.5, 1))


class TestStorage:
    def test_round_trip_keeps_the_shape_and_band(self):
        fence = Geofence.circle(0, 0, 1.0, z_min=0.2, z_max=0.9)
        back = Geofence.from_dict(fence.to_dict())
        assert back.shape is FenceShape.CIRCLE
        assert back.z_min == 0.2 and back.z_max == 0.9
        assert len(back.vertices) == CIRCLE_SIDES

    def test_a_malformed_fence_says_so(self):
        with pytest.raises(GeofenceError, match="could not be read"):
            Geofence.from_dict({"vertices": "nope"})


class TestShapes:
    def test_segments_that_touch_intersect_but_do_not_cross(self):
        assert shapes.segments_intersect((0, 0), (1, 0), (1, 0), (1, 1))
        assert not shapes.segments_cross_properly((0, 0), (1, 0), (1, 0), (1, 1))

    def test_distance_between_parallel_segments(self):
        assert shapes.segment_segment_distance((0, 0), (1, 0), (0, 1), (1, 1)) == 1.0
