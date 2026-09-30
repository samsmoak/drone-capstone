"""keyframe.py — which way the arrows move the drone, decided without a drone."""

from __future__ import annotations

import math

import pytest

from cropwatcher.flight.keyframe import (
    FAR_OPERATOR_M,
    NEAR_OPERATOR_M,
    ROOM_FORWARD_DEG,
    ActiveFrame,
    KeyFrame,
    Reason,
    keys_to_room,
    resolve,
    room_to_body,
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
