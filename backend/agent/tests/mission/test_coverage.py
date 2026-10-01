"""Coverage: predicted from the base stations' poses, measured by the survey."""

from __future__ import annotations

import math

import pytest

from cropwatcher.mission.plan.coverage import (
    MAX_RANGE_M,
    StationPose,
    Survey,
    clip_to_convex,
    convex_hull,
    predict,
    simplify,
)
from cropwatcher.mission.plan.geofence import Geofence
from cropwatcher.mission.plan.shapes import point_in_polygon, signed_area


def facing(origin, yaw_deg: float, pitch_down_deg: float) -> StationPose:
    """A station at `origin` whose forward axis turns `yaw` from the room's +x
    and tilts down by `pitch`. Columns of the matrix: its x, y, z in the room."""
    y, p = math.radians(yaw_deg), math.radians(pitch_down_deg)
    fwd = (math.cos(y) * math.cos(p), math.sin(y) * math.cos(p), -math.sin(p))
    left = (-math.sin(y), math.cos(y), 0.0)
    up = (math.cos(y) * math.sin(p), math.sin(y) * math.sin(p), math.cos(p))
    rows = tuple((fwd[i], left[i], up[i]) for i in range(3))
    return StationPose(origin, rows)


#: Two stations high in opposite corners of a 3 m room, each facing the middle.
CORNERS = (facing((-1.5, -1.5, 2.0), 45, 30), facing((1.5, 1.5, 2.0), 225, 30))
ROOM = Geofence.rectangle(-1.5, -1.5, 1.5, 1.5)


class TestOneStation:
    def test_it_sees_what_is_in_front_and_below(self):
        s = facing((-2.0, 0.0, 2.0), 0, 30)
        assert s.sees((0.0, 0.0, 0.5))

    def test_it_does_not_see_behind_itself(self):
        assert not facing((-2.0, 0.0, 2.0), 0, 30).sees((-3.0, 0.0, 1.0))

    def test_it_does_not_see_past_its_side(self):
        # 90° to its left: outside the 75° half-width.
        assert not facing((0.0, 0.0, 1.0), 0, 0).sees((0.0, 2.0, 1.0))

    def test_it_does_not_see_beyond_its_reach(self):
        assert not facing((0.0, 0.0, 1.0), 0, 0).sees((MAX_RANGE_M + 0.5, 0.0, 1.0))


class TestPrediction:
    def test_two_stations_cover_the_middle_of_the_room(self):
        p = predict(CORNERS, ROOM)
        assert p.everywhere is not None
        assert p.everywhere.contains(0.0, 0.0)
        assert ROOM.contains_fence(p.everywhere)
        assert len(p.slices) == 10                       # 0.10 … 1.00 m, every 0.10 m

    def test_one_station_covers_what_it_sees_by_default(self):
        # The project flies on one station (flight_guard MIN_USABLE_STATIONS).
        assert predict(CORNERS[:1], ROOM).everywhere is not None

    def test_a_room_that_insists_on_two_needs_both(self):
        assert predict(CORNERS[:1], ROOM, min_stations=2).everywhere is None

    def test_stations_behind_the_room_cover_nothing(self):
        away = (facing((-1.5, -1.5, 2.0), 225, 30), facing((1.5, 1.5, 2.0), 45, 30))
        assert predict(away, ROOM, min_stations=1).everywhere is None

    def test_it_serialises_every_slice(self):
        d = predict(CORNERS, ROOM).to_dict()
        assert len(d["slices"]) == 10 and d["everywhere"] is not None


class TestOutlines:
    def test_the_hull_of_a_square_and_its_middle_is_the_square(self):
        hull = convex_hull([(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5), (0.5, 0)])
        assert sorted(hull) == [(0, 0), (0, 1), (1, 0), (1, 1)]

    def test_clipping_keeps_only_the_overlap(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        right_half = [(1, -1), (3, -1), (3, 3), (1, 3)]
        clipped = clip_to_convex(square, right_half)
        assert abs(signed_area(clipped)) == pytest.approx(2.0)

    def test_clipping_to_something_apart_leaves_nothing(self):
        assert clip_to_convex([(0, 0), (1, 0), (1, 1)], [(5, 5), (6, 5), (6, 6)]) == []

    def test_simplifying_only_ever_shrinks(self):
        circle = [(math.cos(t * math.pi / 50), math.sin(t * math.pi / 50)) for t in range(100)]
        small = simplify(circle, 12)
        assert len(small) == 12
        assert all(point_in_polygon(p, circle) or math.hypot(*p) <= 1.0 + 1e-9 for p in small)
        assert abs(signed_area(small)) < abs(signed_area(circle))


class TestSurvey:
    def walk(self, survey: Survey, mask: int) -> None:
        for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1), (0, 0)]:
            survey.add(x, y, 1.0, mask)

    def test_one_station_counts_by_default(self, monkeypatch):
        monkeypatch.delenv("CROPWATCHER_MIN_STATIONS", raising=False)
        assert Survey().add(0, 0, 1, 0b01)

    def test_a_room_that_insists_on_two_counts_only_two(self):
        s = Survey(min_stations=2)
        assert s.add(0, 0, 1, 0b11)
        assert not s.add(0, 0, 1, 0b01)
        assert not s.add(math.nan, 0, 1, 0b11)
        assert s.seen == 3 and len(s.kept) == 1

    def test_a_walked_square_is_the_coverage_in_the_rooms_band(self):
        s = Survey()
        self.walk(s, 0b11)
        cov = s.coverage(z_min=0.1, z_max=1.0)
        assert cov is not None and cov.area_m2() == pytest.approx(4.0)
        assert (cov.z_min, cov.z_max) == (0.1, 1.0)

    def test_too_little_is_not_a_coverage(self):
        s = Survey()
        s.add(0, 0, 1, 0b11)
        s.add(1, 0, 1, 0b11)
        assert s.coverage(z_min=0.1, z_max=1.0) is None

    def test_a_walk_with_one_station_measures_nothing_where_two_are_needed(self):
        s = Survey(min_stations=2)
        self.walk(s, 0b10)
        assert s.coverage(z_min=0.1, z_max=1.0) is None
