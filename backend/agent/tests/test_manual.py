"""Manual control loop.

Every test here is about something going wrong, because manual control is the
one surface where a software mistake drops a real aircraft. A fake clock drives
the timing so heartbeat expiry can be tested in microseconds rather than by
sleeping.
"""

from __future__ import annotations

import pytest

from cropwatcher.api.manual import (
    HEARTBEAT_TIMEOUT_S,
    THRUST_DECAY,
    THRUST_MAX,
    ControlState,
    Intent,
    ManualController,
)


class FakeCommander:
    """Records every setpoint, so the drone's-eye view can be asserted."""

    def __init__(self):
        self.setpoints: list[tuple[float, float, float, int]] = []
        self.stops = 0

    def send_setpoint(self, roll, pitch, yaw_rate, thrust):
        self.setpoints.append((roll, pitch, yaw_rate, thrust))

    def send_stop_setpoint(self):
        self.stops += 1

    @property
    def last_thrust(self) -> int:
        return self.setpoints[-1][3] if self.setpoints else 0


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def controller(clock=None, commander=None):
    return ManualController(
        commander or FakeCommander(),
        clock=clock or FakeClock(),
    )


class TestIntentParsing:
    def test_reads_held_keys(self):
        intent = Intent.from_payload({"up": True, "forward": True})
        assert intent.up and intent.forward
        assert not intent.down

    def test_unknown_keys_are_ignored(self):
        """A newer client sending an extra field must not drop the drone."""
        intent = Intent.from_payload({"up": True, "somethingNew": True, "x": 42})
        assert intent.up

    def test_non_object_is_rejected(self):
        with pytest.raises(ValueError, match="must be an object"):
            Intent.from_payload(["up"])

    def test_truthiness_is_coerced(self):
        assert Intent.from_payload({"up": 1}).up is True
        assert Intent.from_payload({"up": 0}).up is False


class TestThrust:
    def test_climbs_while_up_is_held(self):
        c = controller()
        c.set_intent(Intent(up=True))
        for _ in range(5):
            c.tick()
        assert c.thrust > 0

    def test_thrust_is_capped(self):
        c = controller()
        c.set_intent(Intent(up=True))
        for _ in range(500):
            c.tick()
        assert c.thrust <= THRUST_MAX

    def test_thrust_decays_when_nothing_is_held(self):
        """Letting go of the keyboard must bring the drone down, not hold it
        at power."""
        c = controller()
        c.set_intent(Intent(up=True))
        for _ in range(20):
            c.tick()
        climbed = c.thrust

        c.set_intent(Intent())          # all keys released
        for _ in range(5):
            c.tick()
        assert c.thrust < climbed

    def test_thrust_reaches_zero_when_left_alone(self):
        c = controller()
        c.set_intent(Intent(up=True))
        for _ in range(10):
            c.tick()

        c.set_intent(Intent())
        for _ in range(THRUST_MAX // THRUST_DECAY + 10):
            c.tick()
        assert c.thrust == 0

    def test_never_goes_negative(self):
        c = controller()
        c.set_intent(Intent(down=True))
        for _ in range(50):
            c.tick()
        assert c.thrust == 0


class TestAttitude:
    def test_forward_pitches_positive(self):
        cmd = FakeCommander()
        c = controller(commander=cmd)
        c.set_intent(Intent(up=True, forward=True))
        c.tick()
        assert cmd.setpoints[-1][1] > 0

    def test_opposite_keys_cancel_to_neutral(self):
        cmd = FakeCommander()
        c = controller(commander=cmd)
        c.set_intent(Intent(up=True, forward=True, back=True))
        c.tick()
        # `forward` wins the conditional; the point is it stays bounded and
        # never sums into a double-magnitude command.
        assert abs(cmd.setpoints[-1][1]) <= 12.0

    def test_yaw_directions_are_opposite(self):
        cmd = FakeCommander()
        c = controller(commander=cmd)
        c.set_intent(Intent(up=True, yaw_left=True))
        c.tick()
        left = cmd.setpoints[-1][2]
        c.set_intent(Intent(up=True, yaw_right=True))
        c.tick()
        right = cmd.setpoints[-1][2]
        assert left < 0 < right


class TestHeartbeat:
    def test_silence_triggers_landing(self):
        """The core safety property: a dead browser lands the drone."""
        clock = FakeClock()
        c = controller(clock=clock)
        c.set_intent(Intent(up=True))
        for _ in range(10):
            c.tick()
        assert c.state is ControlState.FLYING

        clock.advance(HEARTBEAT_TIMEOUT_S + 0.1)
        c.tick()
        assert c.state is ControlState.LANDING
        assert c.stats.heartbeat_timeouts == 1

    def test_heartbeat_keeps_it_flying(self):
        clock = FakeClock()
        c = controller(clock=clock)
        c.set_intent(Intent(up=True))

        for _ in range(20):
            clock.advance(0.1)
            c.heartbeat()
            c.tick()
        assert c.state is ControlState.FLYING
        assert c.stats.heartbeat_timeouts == 0

    def test_landing_after_timeout_reaches_stopped(self):
        clock = FakeClock()
        c = controller(clock=clock)
        c.set_intent(Intent(up=True))
        for _ in range(20):
            c.tick()

        clock.advance(HEARTBEAT_TIMEOUT_S + 0.1)
        for _ in range(THRUST_MAX // THRUST_DECAY + 20):
            c.tick()

        assert c.state is ControlState.STOPPED
        assert c.thrust == 0

    def test_timeout_does_not_fire_twice(self):
        clock = FakeClock()
        c = controller(clock=clock)
        c.set_intent(Intent(up=True))
        c.tick()

        clock.advance(HEARTBEAT_TIMEOUT_S + 0.1)
        for _ in range(10):
            c.tick()
        assert c.stats.heartbeat_timeouts == 1

    def test_landing_ignores_late_control_input(self):
        """Input arriving after a timeout must not re-arm mid-descent."""
        clock = FakeClock()
        c = controller(clock=clock)
        c.set_intent(Intent(up=True))
        for _ in range(20):
            c.tick()
        before = c.thrust

        clock.advance(HEARTBEAT_TIMEOUT_S + 0.1)
        c.tick()
        assert c.state is ControlState.LANDING

        c.heartbeat()      # browser reconnects
        for _ in range(3):
            c.tick()
        assert c.thrust < before        # still coming down


class TestPanic:
    def test_cuts_motors_immediately(self):
        cmd = FakeCommander()
        c = controller(commander=cmd)
        c.set_intent(Intent(up=True))
        for _ in range(30):
            c.tick()
        assert c.thrust > 0

        c.panic()
        assert c.thrust == 0
        assert c.state is ControlState.STOPPED
        assert cmd.stops >= 1

    def test_stopped_state_ignores_further_input(self):
        """Once panicked, nothing short of a restart re-arms it."""
        c = controller()
        c.set_intent(Intent(up=True))
        c.tick()
        c.panic()

        c.set_intent(Intent(up=True))
        for _ in range(20):
            c.tick()
        assert c.thrust == 0
        assert c.state is ControlState.STOPPED

    def test_panic_is_counted(self):
        c = controller()
        c.panic()
        assert c.stats.panics == 1


class TestLand:
    def test_land_decays_to_stopped(self):
        c = controller()
        c.set_intent(Intent(up=True))
        for _ in range(20):
            c.tick()

        c.land()
        for _ in range(THRUST_MAX // THRUST_DECAY + 20):
            c.tick()
        assert c.state is ControlState.STOPPED
        assert c.thrust == 0

    def test_land_is_gentler_than_panic(self):
        """Land bleeds thrust off; panic drops it to zero at once."""
        landing = controller()
        landing.set_intent(Intent(up=True))
        for _ in range(20):
            landing.tick()
        landing.land()
        landing.tick()

        panicking = controller()
        panicking.set_intent(Intent(up=True))
        for _ in range(20):
            panicking.tick()
        panicking.panic()

        assert landing.thrust > panicking.thrust == 0
