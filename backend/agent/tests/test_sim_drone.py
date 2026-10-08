"""The simulated drone's own tests (mission-verification.txt, PART 1).

The simulator is code, and a simulator that is wrong makes every scenario
built on it lie. Each test here pins one thing the scenarios rely on.
"""

from __future__ import annotations

import math

import pytest

from cropwatcher.flight.manual import (
    HEARTBEAT_TIMEOUT_S,
    LAND_S,
    LEASH_M,
    ControlState,
    Fix,
    Intent,
)
from tests.sim_drone import MANUAL_TICK_S, MISSION_TICK_S, SimDrone, follow

START = Fix(0.5, -0.25, 0.0)
CRUISE_M = 0.4


def airborne(drone: SimDrone, height: float = CRUISE_M) -> SimDrone:
    """Arm, rise to `height` with hold_at() and wait for the goal to finish."""
    drone.arm()
    drone.ctl.hold_at(height)
    drone.run_until(None, lambda: drone.ctl.state is ControlState.FLYING
                    and not drone.ctl.goal_active, limit_s=20.0)
    return drone


def fly(drone: SimDrone, x: float, y: float, height: float = CRUISE_M) -> None:
    drone.ctl.fly_to(x, y, height)
    drone.run_until(None, lambda: not drone.ctl.goal_active, limit_s=60.0)


class Ticks:
    def __init__(self) -> None:
        self.count = 0

    def tick(self) -> None:
        self.count += 1


class TestFollowsAGoal:
    def test_arrives_within_a_centimetre_without_noise(self):
        drone = airborne(SimDrone(start=START))
        fly(drone, 1.2, 0.3, 0.6)
        drone.step(5 * drone.lag_s)
        x, y = drone.true_xy
        assert math.hypot(x - 1.2, y - 0.3) < 0.01
        assert abs(drone.true_height - 0.6) < 0.01
        assert math.hypot(drone.position.x - 1.2, drone.position.y - 0.3) < 0.01

    def test_takes_off_from_the_floor_not_from_zero(self):
        drone = SimDrone(start=START, ground_z=1.3)
        assert drone.true_height == 0.0
        airborne(drone, 0.5)
        drone.step(5 * drone.lag_s)
        assert abs(drone.true_height - 0.5) < 0.01
        assert abs(drone.position_z - 1.8) < 0.01


class TestTheLag:
    @pytest.mark.parametrize("lag_s", [0.3, 0.5, 1.0])     # whole numbers of ticks
    def test_covers_63_percent_of_a_step_in_lag_s(self, lag_s):
        position = 0.0
        ticks = round(lag_s / MANUAL_TICK_S)
        assert ticks * MANUAL_TICK_S == pytest.approx(lag_s)
        for _ in range(ticks):
            position = follow(position, 1.0, MANUAL_TICK_S, lag_s)
        assert position == pytest.approx(1.0 - math.exp(-1.0), abs=1e-9)

    def test_does_not_depend_on_the_step_size(self):
        coarse = fine = 0.0
        for _ in range(25):
            coarse = follow(coarse, 1.0, 0.02, 0.5)
        for _ in range(500):
            fine = follow(fine, 1.0, 0.001, 0.5)
        assert coarse == pytest.approx(fine, abs=1e-12)

    def test_the_drone_lags_its_commanded_point(self):
        drone = airborne(SimDrone(start=START, lag_s=0.5))
        drone.ctl.fly_to(START.x + 1.0, START.y, CRUISE_M)
        drone.step(2.0)
        target = drone.ctl.target
        assert target is not None
        # Moving at speed, the drone trails the point it is told to be at.
        assert target.x - drone.true_xy[0] > 0.02


class TestRepeatable:
    @staticmethod
    def flight(seed: int) -> SimDrone:
        drone = airborne(SimDrone(start=START, noise_m=0.02, seed=seed))
        drone.ctl.fly_to(1.0, 0.5, CRUISE_M)
        drone.step(8.0)
        return drone

    def test_the_same_seed_gives_the_same_flight_byte_for_byte(self):
        a, b = self.flight(7), self.flight(7)
        assert repr(a.cmd.commands) == repr(b.cmd.commands)
        assert a.position == b.position and a.true_xy == b.true_xy

    def test_another_seed_gives_another_flight(self):
        assert self.flight(7).cmd.commands != self.flight(8).cmd.commands


class TestClock:
    def test_ticks_a_mission_every_mission_tick(self):
        drone, mission = SimDrone(start=START), Ticks()
        drone.step(1.0, mission)
        assert mission.count == round(1.0 / MISSION_TICK_S)
        assert drone.clock() == pytest.approx(1.0)

    def test_run_until_fails_at_its_limit_instead_of_hanging(self):
        drone = SimDrone(start=START)
        with pytest.raises(AssertionError, match="not done after 2.0 s"):
            drone.run_until(None, lambda: False, limit_s=2.0)
        assert drone.clock() == pytest.approx(2.0)

    def test_watchers_see_every_manual_tick(self):
        drone, seen = SimDrone(start=START), []
        drone.watch(lambda: seen.append(drone.clock()))
        drone.step(0.2)
        assert len(seen) == round(0.2 / MANUAL_TICK_S)


class TestWhatGoesWrong:
    def test_stall_the_point_moves_on_and_the_leash_holds_it_back(self):
        drone = airborne(SimDrone(start=START))
        held = drone.true_xy
        drone.stall()
        drone.ctl.fly_to(held[0] + 1.0, held[1], CRUISE_M)
        drone.step(6.0)
        assert drone.true_xy == held
        target = drone.ctl.target
        assert target is not None
        gap = math.hypot(target.x - drone.position.x, target.y - drone.position.y)
        assert gap == pytest.approx(LEASH_M, abs=1e-6)
        assert drone.ctl.goal_active

    def test_push_displaces_it_and_the_loop_pulls_it_back(self):
        drone = airborne(SimDrone(start=START))
        here = drone.true_xy
        drone.push(0.2, 0.0)
        drone.step(0.4)
        assert drone.ctl.drift_m > 0.05             # believed, not rejected as a jump
        drone.step(5.0)
        assert math.dist(drone.true_xy, here) < 0.01

    def test_hold_key_cancels_the_goal_and_sets_override(self):
        drone = airborne(SimDrone(start=START))
        drone.ctl.fly_to(START.x + 1.0, START.y, CRUISE_M)
        drone.step(1.0)
        assert drone.ctl.goal_active
        drone.hold_key(Intent(forward=True))
        drone.step(MANUAL_TICK_S)
        assert not drone.ctl.goal_active
        assert drone.ctl.operator_override

    def test_guard_lands_it_where_it_is(self):
        drone = airborne(SimDrone(start=START))
        drone.guard_lands()
        assert drone.ctl.state is ControlState.LANDING
        here = drone.true_xy
        drone.step(LAND_S + 0.5)
        assert drone.ctl.state is ControlState.LANDED
        assert drone.lands, "the high-level land was never called"
        assert drone.landed_at is not None and math.dist(drone.landed_at, here) < 0.01
        assert drone.true_height == 0.0

    def test_emergency_stop_stops_it_and_it_falls_where_it_was(self):
        drone = airborne(SimDrone(start=START))
        here = drone.true_xy
        drone.emergency_stop()
        assert drone.ctl.state is ControlState.STOPPED
        drone.step(MANUAL_TICK_S)
        assert drone.landed_at == here
        assert drone.true_height == 0.0
        assert not drone.lands                      # stopped, never landed

    def test_window_goes_quiet_the_dead_man_lands_it(self):
        drone = airborne(SimDrone(start=START))
        drone.window_goes_quiet()
        drone.step(HEARTBEAT_TIMEOUT_S - 2 * MANUAL_TICK_S)
        assert drone.ctl.state is ControlState.FLYING
        drone.step(4 * MANUAL_TICK_S)
        assert drone.ctl.state is ControlState.LANDING
