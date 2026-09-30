"""The simulated drone's own tests. A simulator that is wrong makes every
scenario built on it lie, so it is held to the real system's behaviour here
before any mission flies it (mission-verification.txt, PART 1)."""

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
from cropwatcher.mission.controller.mission_controller import ARRIVE_M
from tests.sim_drone import MANUAL_TICK_S, MISSION_TICK_S, SimDrone, follow

START = Fix(1.0, -0.5, 0.0)


def airborne(sim: SimDrone, height: float = 0.40) -> None:
    sim.arm()
    sim.ctl.hold_at(height)
    sim.run_until(None, lambda: sim.ctl.state is ControlState.FLYING
                  and not sim.ctl.goal_active, limit_s=10.0)


def test_it_follows_a_fly_to_goal_and_arrives_within_a_centimetre():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.ctl.fly_to(START.x + 1.0, START.y + 0.5, 0.40)
    sim.run_until(None, lambda: not sim.ctl.goal_active, limit_s=20.0)
    sim.step(3.0)
    x, y = sim.true_xy
    assert math.hypot(x - (START.x + 1.0), y - (START.y + 0.5)) < 0.01
    assert sim.ctl.drift_m < 0.01


def test_the_lag_covers_63_percent_of_a_step_in_lag_s():
    for lag in (0.3, 0.5, 1.0):
        position = (0.0, 0.0)
        for _ in range(round(lag / MANUAL_TICK_S)):
            position = follow(position, (1.0, 0.0), MANUAL_TICK_S, lag)
        assert position[0] == pytest.approx(1.0 - math.exp(-1.0), abs=1e-9)


def test_the_lag_holds_through_the_real_loop():
    """Airborne with the setpoint held still, the drone pushed off it returns
    with the lag it was given."""
    sim = SimDrone(start=START, lag_s=0.5)
    airborne(sim)
    sim._true = (START.x + 0.2, START.y)           # displaced, setpoint unchanged
    sim.step(0.5)
    covered = (START.x + 0.2 - sim.true_xy[0]) / 0.2
    # The setpoint itself moves a little (the leash, the drift it sees), so
    # this is the loop's view of the same law, not an exact identity.
    assert covered == pytest.approx(1.0 - math.exp(-1.0), abs=0.05)


def test_the_same_seed_gives_the_same_flight_byte_for_byte():
    def fly(seed: int) -> str:
        sim = SimDrone(start=START, noise_m=0.02, drift_m_s=(0.01, 0.0), seed=seed)
        trail: list[tuple[float, float]] = []
        sim.watch(lambda: trail.append((sim.position.x, sim.position.y)))
        airborne(sim)
        sim.ctl.fly_to(START.x + 0.5, START.y, 0.40)
        sim.step(6.0)
        return repr((sim.cmd.commands, trail))

    assert fly(7) == fly(7)
    assert fly(7) != fly(8)


def test_noise_is_reported_at_the_estimators_rate_not_the_loops():
    sim = SimDrone(start=START, noise_m=0.02, seed=1)
    seen: list[Fix] = []
    sim.watch(lambda: seen.append(sim.position))
    sim.step(1.0)
    changes = sum(1 for a, b in zip(seen, seen[1:], strict=False) if a != b)
    assert changes == pytest.approx(1.0 / 0.1, abs=1)


def test_a_stalled_drone_stays_and_the_leash_holds_the_point_back():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.stall()
    where = sim.true_xy
    sim.ctl.fly_to(START.x + 2.0, START.y, 0.40)
    sim.step(8.0)
    assert sim.true_xy == where
    target = sim.ctl.target
    assert target is not None
    assert math.hypot(target.x - where[0], target.y - where[1]) <= LEASH_M + 1e-9
    assert sim.ctl.goal_active                     # it never gets there


def test_a_push_moves_the_drone_at_a_believable_speed_and_it_comes_back():
    sim = SimDrone(start=START)
    airborne(sim)
    assert sim.ctl.drift_m < 0.01             # settled before the gust
    sim.push(0.2, 0.0)
    peak = 0.0
    for _ in range(round(1.0 / MANUAL_TICK_S)):
        sim.step(MANUAL_TICK_S)
        peak = max(peak, sim.ctl.drift_m)
    assert peak > ARRIVE_M                        # enough to restart a settle wait
    sim.step(4.0)
    assert sim.ctl.drift_m < 0.01             # and back


def test_holding_a_key_cancels_a_goal_and_sets_operator_override():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.ctl.fly_to(START.x + 1.0, START.y, 0.40)
    sim.step(1.0)
    sim.hold_key(Intent(forward=True))
    sim.step(MANUAL_TICK_S)
    assert not sim.ctl.goal_active
    assert sim.ctl.operator_override
    assert sim.ctl.state is ControlState.FLYING


def test_the_guard_landing_it_puts_the_loop_in_landing_then_landed():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.guard_lands()
    assert sim.ctl.state is ControlState.LANDING
    sim.step(LAND_S + 0.5)
    assert sim.ctl.state is ControlState.LANDED
    assert sim.lands                              # the high-level land was used
    assert sim.landed_at is not None
    assert math.dist(sim.landed_at, (START.x, START.y)) < 0.02


def test_an_emergency_stop_stops_it_at_once():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.emergency_stop()
    assert sim.ctl.state is ControlState.STOPPED
    sim.step(MANUAL_TICK_S)
    assert sim.landed_at is not None              # where it fell


def test_a_quiet_window_is_the_dead_man_it_lands():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.window_goes_quiet()
    sim.step(HEARTBEAT_TIMEOUT_S + 2 * MANUAL_TICK_S)
    assert sim.ctl.state is ControlState.LANDING
    sim.step(LAND_S + 0.5)
    assert sim.ctl.state is ControlState.LANDED


def test_it_lands_where_it_is_when_landing_begins():
    sim = SimDrone(start=START)
    airborne(sim)
    sim.ctl.fly_to(START.x + 0.6, START.y, 0.40)
    sim.run_until(None, lambda: not sim.ctl.goal_active, limit_s=20.0)
    sim.step(2.0)
    sim.ctl.land()
    sim.step(LAND_S + 0.5)
    assert sim.landed_at is not None
    assert math.dist(sim.landed_at, (START.x + 0.6, START.y)) < 0.02


def test_run_until_fails_rather_than_hangs():
    sim = SimDrone(start=START)
    with pytest.raises(AssertionError, match="not done after"):
        sim.run_until(None, lambda: False, limit_s=1.0)


def test_step_ticks_a_mission_every_mission_tick():
    class Counter:
        ticks = 0

        def tick(self) -> None:
            self.ticks += 1

    sim = SimDrone(start=START)
    counter = Counter()
    sim.step(2.0, counter)
    assert counter.ticks == round(2.0 / MISSION_TICK_S)
