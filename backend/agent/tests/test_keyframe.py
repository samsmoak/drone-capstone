"""keyframe.py — which way the arrows move the drone, decided without a drone."""

from __future__ import annotations

import math

import pytest

from cropwatcher.flight.keyframe import (
    FAR_OPERATOR_M,
    NEAR_OPERATOR_M,
    NOSE_TO_FORWARD_DEG,
    ROOM_FORWARD_DEG,
    ActiveFrame,
    KeyFrame,
    NoseFacing,
    Reason,
    keys_to_room,
    resolve,
    room_to_body,
    turn_nose,
)


def status(chosen=KeyFrame.OPERATOR, drone=(2.0, 0.0), operator=(0.0, 0.0),
           source="marked", takeoff=10.0, was_near=False):
    return resolve(chosen, drone_xy=drone, operator_xy=operator, operator_source=source,
                   takeoff_heading_deg=takeoff, was_near=was_near)


class TestResolve:
    @pytest.mark.parametrize(("drone", "angle"), [
        ((2.0, 0.0), 0.0), ((0.0, 2.0), 90.0), ((-2.0, 0.0), 180.0), ((0.0, -2.0), -90.0),
        ((1.0, 1.0), 45.0),
    ])
    def test_operator_forward_points_from_the_operator_to_the_drone(self, drone, angle):
        s = status(drone=drone)
        assert s.active is ActiveFrame.OPERATOR and s.reason is None
        assert s.forward_deg == pytest.approx(angle)

    def test_operator_spot_need_not_be_the_origin(self):
        s = status(drone=(3.0, 1.0), operator=(1.0, 1.0))
        assert s.forward_deg == pytest.approx(0.0)

    def test_room_is_plus_x_wherever_the_drone_is(self):
        for drone in [(2.0, 0.0), (-3.0, 1.0), (0.1, 0.1)]:
            s = status(chosen=KeyFrame.ROOM, drone=drone)
            assert s.active is ActiveFrame.ROOM and s.reason is None
            assert s.forward_deg == ROOM_FORWARD_DEG

    def test_near_the_operator_it_is_the_room_and_says_why(self):
        s = status(drone=(NEAR_OPERATOR_M - 0.01, 0.0))
        assert s.active is ActiveFrame.ROOM and s.reason is Reason.NEAR_OPERATOR
        assert s.near is True

    def test_hysteresis_between_the_two_radii(self):
        between = ((NEAR_OPERATOR_M + FAR_OPERATOR_M) / 2, 0.0)
        assert status(drone=between, was_near=False).active is ActiveFrame.OPERATOR
        assert status(drone=between, was_near=True).active is ActiveFrame.ROOM
        beyond = (FAR_OPERATOR_M + 0.01, 0.0)
        assert status(drone=beyond, was_near=True).active is ActiveFrame.OPERATOR

    def test_no_spot_yet_is_the_room_without_alarm(self):
        s = status(operator=None, source=None)
        assert s.active is ActiveFrame.ROOM and s.reason is None

    def test_no_position_keeps_the_takeoff_heading(self):
        s = status(drone=None, takeoff=-116.0)
        assert s.active is ActiveFrame.TAKEOFF and s.reason is Reason.NO_POSITION
        assert s.forward_deg == -116.0

    def test_no_position_and_no_heading_is_the_nose(self):
        s = status(drone=None, takeoff=None)
        assert s.active is ActiveFrame.NOSE and s.reason is Reason.NO_HEADING
        assert s.forward_deg is None

    def test_room_chosen_without_position_is_still_the_takeoff_heading(self):
        s = status(chosen=KeyFrame.ROOM, drone=None, takeoff=30.0)
        assert s.active is ActiveFrame.TAKEOFF

    def test_to_dict_is_plain_json(self):
        d = status().to_dict()
        assert d == {"chosen": "operator", "active": "operator", "reason": None,
                     "forward_deg": 0.0, "operator": [0.0, 0.0], "operator_source": "marked"}


class TestRotation:
    def test_forward_along_zero_is_plus_x(self):
        assert keys_to_room(1.0, 0.0, 0.0) == pytest.approx((1.0, 0.0))

    def test_left_is_ninety_degrees_counter_clockwise(self):
        assert keys_to_room(0.0, 1.0, 0.0) == pytest.approx((0.0, 1.0))
        assert keys_to_room(0.0, 1.0, 90.0) == pytest.approx((-1.0, 0.0))

    @pytest.mark.parametrize("heading", [0.0, 37.0, 90.0, 180.0, -116.0])
    def test_body_is_the_inverse(self, heading):
        for keys in [(1.0, 0.0), (0.0, 1.0), (0.3, -0.7)]:
            room = keys_to_room(*keys, heading)
            assert room_to_body(*room, heading) == pytest.approx(keys)

    def test_rotation_keeps_the_speed(self):
        x, y = keys_to_room(0.2, 0.2, 123.0)
        assert math.hypot(x, y) == pytest.approx(math.hypot(0.2, 0.2))


class TestNoseFacing:
    """No position: the operator says which way the nose pointed at takeoff, and
    that turns the takeoff heading into THEIR forward. Headings are degrees
    counter-clockwise, so the nose at their left is 90° counter-clockwise of
    their forward — their forward is the nose turned 90° clockwise."""

    @staticmethod
    def forward(nose: NoseFacing, takeoff: float) -> float:
        s = resolve(KeyFrame.OPERATOR, drone_xy=None, operator_xy=None, operator_source=None,
                    takeoff_heading_deg=takeoff, nose=nose)
        assert s.active is ActiveFrame.TAKEOFF and s.reason is Reason.NO_POSITION
        assert s.forward_deg is not None
        return s.forward_deg

    @pytest.mark.parametrize(("nose", "expected"), [
        (NoseFacing.AWAY, 0.0), (NoseFacing.LEFT, -90.0),
        (NoseFacing.RIGHT, 90.0), (NoseFacing.TOWARDS, -180.0),
    ])
    def test_each_choice_from_a_nose_along_x(self, nose, expected):
        assert self.forward(nose, 0.0) == pytest.approx(expected)

    def test_the_geometry_the_operator_means(self):
        # Operator faces +y (90°). Nose at their LEFT points -x (180°): their
        # forward must come out as +y. Nose at their RIGHT points +x (0°).
        assert self.forward(NoseFacing.LEFT, 180.0) == pytest.approx(90.0)
        assert self.forward(NoseFacing.RIGHT, 0.0) == pytest.approx(90.0)
        assert self.forward(NoseFacing.TOWARDS, -90.0) == pytest.approx(90.0)
        assert self.forward(NoseFacing.AWAY, 90.0) == pytest.approx(90.0)

    def test_it_wraps_into_one_turn(self):
        assert self.forward(NoseFacing.RIGHT, 170.0) == pytest.approx(-100.0)
        assert self.forward(NoseFacing.LEFT, -170.0) == pytest.approx(100.0)

    def test_away_is_what_the_arrows_did_before(self):
        assert self.forward(NoseFacing.AWAY, -116.0) == pytest.approx(-116.0)

    def test_every_choice_has_an_offset(self):
        assert set(NOSE_TO_FORWARD_DEG) == set(NoseFacing)

    def test_with_a_position_it_changes_nothing(self):
        for nose in NoseFacing:
            s = resolve(KeyFrame.OPERATOR, drone_xy=(2.0, 0.0), operator_xy=(0.0, 0.0),
                        operator_source="marked", takeoff_heading_deg=45.0, nose=nose)
            assert s.active is ActiveFrame.OPERATOR and s.forward_deg == pytest.approx(0.0)
            s = resolve(KeyFrame.ROOM, drone_xy=(2.0, 0.0), operator_xy=None,
                        operator_source=None, takeoff_heading_deg=45.0, nose=nose)
            assert s.forward_deg == pytest.approx(ROOM_FORWARD_DEG)

    def test_with_no_heading_there_is_nothing_to_turn(self):
        s = resolve(KeyFrame.OPERATOR, drone_xy=None, operator_xy=None, operator_source=None,
                    takeoff_heading_deg=None, nose=NoseFacing.LEFT)
        assert s.active is ActiveFrame.NOSE and s.forward_deg is None


class TestTurnNose:
    """In the air: "up went <this way> of me" corrects the setting."""

    @pytest.mark.parametrize(("nose", "went", "expected"), [
        (NoseFacing.AWAY, NoseFacing.AWAY, NoseFacing.AWAY),
        (NoseFacing.AWAY, NoseFacing.LEFT, NoseFacing.LEFT),
        (NoseFacing.AWAY, NoseFacing.RIGHT, NoseFacing.RIGHT),
        (NoseFacing.AWAY, NoseFacing.TOWARDS, NoseFacing.TOWARDS),
        (NoseFacing.LEFT, NoseFacing.LEFT, NoseFacing.TOWARDS),
        (NoseFacing.LEFT, NoseFacing.RIGHT, NoseFacing.AWAY),
        (NoseFacing.RIGHT, NoseFacing.TOWARDS, NoseFacing.LEFT),
        (NoseFacing.TOWARDS, NoseFacing.TOWARDS, NoseFacing.AWAY),
    ])
    def test_corrections_compose(self, nose, went, expected):
        assert turn_nose(nose, went) is expected

    @pytest.mark.parametrize("nose", list(NoseFacing))
    @pytest.mark.parametrize("went", list(NoseFacing))
    def test_up_ends_up_away_from_the_operator(self, nose, went):
        """Whatever was set and whichever way up went, after the correction up
        points where the operator actually faces. Up went `went` of them along
        the old forward F; their true forward is F turned back by that."""
        takeoff = 37.0
        def forward(n):
            return resolve(KeyFrame.OPERATOR, drone_xy=None, operator_xy=None,
                           operator_source=None, takeoff_heading_deg=takeoff,
                           nose=n).forward_deg
        old = forward(nose)
        # Where they really face: the direction up went, turned the other way.
        true_forward = (old + NOSE_TO_FORWARD_DEG[went]) % 360.0
        assert forward(turn_nose(nose, went)) % 360.0 == pytest.approx(true_forward)
