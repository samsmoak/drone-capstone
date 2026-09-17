"""Manual control loop.

Every test here is about something going wrong or being done gently, because
manual control is the one surface where a software mistake drops a real
aircraft. A fake clock drives the timing so heartbeat expiry and the climb rate
can be tested in microseconds rather than by sleeping.
"""

from __future__ import annotations

import pytest

from cropwatcher.api.manual import (
    CLIMB_RATE_M_S,
    HEARTBEAT_TIMEOUT_S,
    IDLE_THRUST,
    LAND_RATE_M_S,
    LAND_S,
    MAX_HEIGHT_M,
    MAX_TILT_DEG,
    MAX_UNASSISTED_HEIGHT_M,
    MOVE_SPEED_M_S,
    TICK_S,
    TOUCHDOWN_HOLD_S,
    YAW_RATE_DEG_S,
    ControlState,
    Intent,
    ManualController,
)

GROUND = 1.0


class FakeCommander:
    """Records every command, so the drone's-eye view can be asserted."""

    def __init__(self):
        self.commands: list[tuple] = []

    def send_setpoint(self, roll, pitch, yaw_rate, thrust):
        self.commands.append(("setpoint", roll, pitch, yaw_rate, thrust))

    def send_hover_setpoint(self, vx, vy, yawrate, zdistance):
        self.commands.append(("hover", vx, vy, yawrate, zdistance))

    def send_zdistance_setpoint(self, roll, pitch, yawrate, zdistance):
        self.commands.append(("zdistance", roll, pitch, yawrate, zdistance))

    def send_notify_setpoint_stop(self, remain_valid_milliseconds=0):
        self.commands.append(("notify_stop",))

    def send_stop_setpoint(self):
        self.commands.append(("stop",))

    def last(self, kind):
        return next(c for c in reversed(self.commands) if c[0] == kind)

    def kinds(self):
        return [c[0] for c in self.commands]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Rig:
    def __init__(self, assisted: bool = True):
        self.clock = FakeClock()
        self.cmd = FakeCommander()
        self.lands: list[tuple[float, float]] = []
        self.ctl = ManualController(
            self.cmd, ground_z=GROUND, land=lambda z, d: self.lands.append((z, d)),
            assisted=assisted, clock=self.clock,
        )

    def run(self, seconds: float, intent: Intent | None = None, heartbeat: bool = True):
        if intent is not None:
            self.ctl.set_intent(intent)
        for _ in range(round(seconds / TICK_S)):
            self.clock.advance(TICK_S)
            if heartbeat:
                self.ctl.heartbeat()
            self.ctl.tick()

    def fly_to(self, height: float):
        self.ctl.arm()
        self.run(height / CLIMB_RATE_M_S + TICK_S, Intent(up=True))
        self.ctl.set_intent(Intent())


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


class TestArming:
    def test_idle_sends_nothing(self):
        rig = Rig()
        rig.run(1.0)
        assert rig.cmd.commands == []

    def test_armed_props_idle_gently_on_the_ground(self):
        rig = Rig()
        rig.ctl.arm()
        rig.run(0.2)
        assert rig.ctl.state is ControlState.ARMED
        assert rig.cmd.last("setpoint") == ("setpoint", 0.0, 0.0, 0.0, IDLE_THRUST)
        assert "hover" not in rig.cmd.kinds()

    def test_idle_thrust_is_just_above_no_power(self):
        # cflib: 10001 is "next to no power", 60000 is full.
        assert 10001 < IDLE_THRUST < 15000

    def test_down_while_armed_does_nothing(self):
        rig = Rig()
        rig.ctl.arm()
        rig.run(1.0, Intent(down=True))
        assert rig.ctl.state is ControlState.ARMED
        assert rig.ctl.target_height == 0.0


class TestGentleClimb:
    def test_holding_up_rises_at_the_gentle_rate(self):
        rig = Rig()
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        assert rig.ctl.target_height == pytest.approx(2.0 * CLIMB_RATE_M_S, abs=0.01)
        assert rig.ctl.state is ControlState.FLYING

    def test_height_is_commanded_relative_to_ground(self):
        rig = Rig()
        rig.fly_to(0.30)
        rig.run(0.1)
        assert rig.cmd.last("hover")[4] == pytest.approx(GROUND + 0.30, abs=0.01)

    def test_releasing_the_keys_holds_height(self):
        """The old controller bled thrust off and the drone sank."""
        rig = Rig()
        rig.fly_to(0.40)
        before = rig.ctl.target_height
        rig.run(3.0, Intent())
        assert rig.ctl.target_height == pytest.approx(before)
        assert rig.ctl.state is ControlState.FLYING

    def test_lowering_is_gentle_too(self):
        rig = Rig()
        rig.fly_to(0.60)
        rig.run(1.0, Intent(down=True))
        assert rig.ctl.target_height == pytest.approx(0.60 - CLIMB_RATE_M_S, abs=0.02)

    def test_height_is_capped(self):
        rig = Rig()
        rig.ctl.arm()
        rig.run(MAX_HEIGHT_M / CLIMB_RATE_M_S + 5, Intent(up=True))
        assert rig.ctl.target_height == MAX_HEIGHT_M

    def test_a_long_stall_does_not_jump_the_height(self):
        rig = Rig()
        rig.fly_to(0.30)
        rig.ctl.set_intent(Intent(up=True))
        rig.clock.advance(0.4)        # one delayed tick
        rig.ctl.heartbeat()
        rig.ctl.tick()
        assert rig.ctl.target_height < 0.30 + 0.1 * CLIMB_RATE_M_S + 0.01


class TestMovement:
    def test_arrows_and_yaw_follow_cflib_conventions(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(0.1, Intent(forward=True, left=True, yaw_left=True))
        _, vx, vy, yaw, _ = rig.cmd.last("hover")
        assert vx == MOVE_SPEED_M_S
        assert vy == MOVE_SPEED_M_S        # left is +vy
        assert yaw == YAW_RATE_DEG_S       # turning left is +yawrate

    def test_opposite_keys_cancel(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(0.1, Intent(forward=True, back=True, yaw_left=True, yaw_right=True))
        _, vx, _, yaw, _ = rig.cmd.last("hover")
        assert vx == 0 and yaw == 0


class TestGracefulLanding:
    def test_land_hands_over_to_the_high_level_commander(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.ctl.land()
        rig.run(0.1)
        kinds = rig.cmd.kinds()
        assert kinds.index("notify_stop") > kinds.index("hover")
        assert rig.lands == [(GROUND, LAND_S)]
        assert rig.ctl.state is ControlState.LANDING

    def test_no_low_level_setpoints_while_landing(self):
        """They would reclaim priority and cancel the landing (CLAUDE.md #2)."""
        rig = Rig()
        rig.fly_to(0.3)
        rig.ctl.land()
        rig.run(0.1)
        count = len(rig.cmd.commands)
        rig.run(1.0, Intent(up=True))
        assert rig.cmd.kinds()[count:] == []

    def test_landing_completes_and_can_arm_again(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.ctl.land()
        rig.run(LAND_S + 0.2)
        assert rig.ctl.state is ControlState.LANDED
        assert rig.cmd.kinds()[-1] == "stop"
        rig.ctl.arm()
        assert rig.ctl.state is ControlState.ARMED

    def test_lowering_to_the_floor_lands(self):
        rig = Rig()
        rig.fly_to(0.2)
        rig.run(2.0, Intent(down=True))
        assert rig.ctl.state in (ControlState.LANDING, ControlState.LANDED)
        assert rig.lands

    def test_land_while_only_idling_disarms(self):
        rig = Rig()
        rig.ctl.arm()
        rig.run(0.2)
        rig.ctl.land()
        assert rig.ctl.state is ControlState.IDLE
        assert rig.cmd.kinds()[-1] == "stop"
        assert rig.lands == []


class TestHeartbeat:
    def test_silence_while_flying_lands_gracefully(self):
        """The core safety property: a dead app lands the drone."""
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(HEARTBEAT_TIMEOUT_S + 0.1, heartbeat=False)
        assert rig.ctl.state is ControlState.LANDING
        assert rig.lands == [(GROUND, LAND_S)]
        assert rig.ctl.stats.heartbeat_timeouts == 1

    def test_silence_while_armed_disarms(self):
        rig = Rig()
        rig.ctl.arm()
        rig.run(HEARTBEAT_TIMEOUT_S + 0.1, heartbeat=False)
        assert rig.ctl.state is ControlState.IDLE
        assert rig.cmd.kinds()[-1] == "stop"

    def test_heartbeat_keeps_it_flying(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(5.0)
        assert rig.ctl.state is ControlState.FLYING
        assert rig.ctl.stats.heartbeat_timeouts == 0

    def test_timeout_does_not_fire_twice(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, heartbeat=False)
        assert rig.ctl.stats.heartbeat_timeouts == 1

    def test_late_input_does_not_cancel_a_landing(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(HEARTBEAT_TIMEOUT_S + 0.1, heartbeat=False)
        rig.run(0.5, Intent(up=True))          # the app reconnects
        assert rig.ctl.state in (ControlState.LANDING, ControlState.LANDED)


class TestEmergencyStop:
    def test_stops_immediately_without_waiting_for_a_tick(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.ctl.emergency_stop()
        assert rig.cmd.kinds()[-1] == "stop"
        assert rig.ctl.state is ControlState.STOPPED

    def test_nothing_is_sent_after_a_stop(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.ctl.emergency_stop()
        count = len(rig.cmd.commands)
        rig.run(1.0, Intent(up=True))
        assert len(rig.cmd.commands) == count

    def test_cannot_arm_again_until_reset(self):
        rig = Rig()
        rig.ctl.emergency_stop()
        with pytest.raises(RuntimeError, match="emergency stop"):
            rig.ctl.arm()
        rig.ctl.reset()
        rig.ctl.arm()
        assert rig.ctl.state is ControlState.ARMED

    def test_stop_is_counted(self):
        rig = Rig()
        rig.ctl.emergency_stop()
        assert rig.ctl.stats.emergency_stops == 1


class TestLoopRate:
    def test_holds_fifty_hertz_in_real_time(self):
        """The rate is the invariant: below ~10 Hz the commander drops the drone.

        Real thread, real sleep — the bug this guards against lives in the
        scheduling, which a fake clock cannot see. A fixed sleep after each tick
        measured 38 Hz. Bounds are loose enough for a busy machine and still
        fail that.
        """
        import time

        cmd = FakeCommander()
        ctl = ManualController(cmd, ground_z=GROUND, land=lambda z, d: None)
        ctl.arm()
        ctl.start()
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            ctl.heartbeat()
            time.sleep(0.05)
        ctl.land()                      # disarm on the ground
        ctl.stop()

        rate = cmd.kinds().count("setpoint") / 1.0
        assert 45 <= rate <= 55, f"loop ran at {rate:.0f} Hz"


class TestUnassisted:
    """No base stations: height from the barometer, held by the firmware.

    The throttle law this replaced let the drone skid through liftoff and
    tumble in the lab (2026-09-16), and letting go of W held nothing. These pin
    the behaviour the operator asked for instead: a gradual climb, a held
    height when the key is released, and a controlled descent — never a drop.
    """

    def test_w_climbs_gradually_on_a_height_setpoint(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(1.0, Intent(up=True))
        assert rig.ctl.state is ControlState.FLYING
        assert rig.ctl.target_height == pytest.approx(CLIMB_RATE_M_S, abs=0.01)
        _, _, _, _, z = rig.cmd.last("zdistance")
        assert z == pytest.approx(GROUND + CLIMB_RATE_M_S, abs=0.01)
        assert "hover" not in rig.cmd.kinds()

    def test_releasing_w_holds_the_height(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        held = rig.ctl.target_height
        rig.run(3.0, Intent())
        assert rig.ctl.target_height == held
        assert rig.cmd.last("zdistance")[4] == pytest.approx(GROUND + held)

    def test_the_height_is_capped(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(30.0, Intent(up=True))
        assert rig.ctl.target_height == MAX_UNASSISTED_HEIGHT_M
        assert all(c[4] <= GROUND + MAX_UNASSISTED_HEIGHT_M
                   for c in rig.cmd.commands if c[0] == "zdistance")

    def test_the_drone_is_kept_level_when_no_arrow_is_held(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        _, roll, pitch, yaw, _ = rig.cmd.last("zdistance")
        assert (roll, pitch, yaw) == (0.0, 0.0, 0.0)

    def test_arrows_tilt_gently_and_never_beyond_the_limit(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(1.0, Intent(up=True))
        rig.run(1.0, Intent(forward=True, right=True))
        _, roll, pitch, _, _ = rig.cmd.last("zdistance")
        assert abs(pitch) == MAX_TILT_DEG and roll == MAX_TILT_DEG
        assert all(abs(c[1]) <= MAX_TILT_DEG and abs(c[2]) <= MAX_TILT_DEG
                   for c in rig.cmd.commands if c[0] == "zdistance")

    def test_land_descends_at_a_fixed_rate_then_stops(self):
        """Land lowers the height target — a descent, not a motor cut — and
        never calls the high-level landing, which needs a position."""
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(3.0, Intent(up=True))
        start = rig.ctl.target_height
        rig.ctl.land()
        rig.run(1.0)
        assert rig.ctl.state is ControlState.LANDING
        assert rig.ctl.target_height == pytest.approx(start - LAND_RATE_M_S, abs=0.02)

        rig.run(start / LAND_RATE_M_S + TOUCHDOWN_HOLD_S + 0.2)
        assert rig.ctl.state is ControlState.LANDED
        assert rig.lands == []
        assert rig.cmd.kinds()[-1] == "stop"

    def test_a_quiet_app_descends_rather_than_drops(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(3.0, Intent(up=True))
        rig.run(HEARTBEAT_TIMEOUT_S + 0.2, heartbeat=False)
        assert rig.ctl.state is ControlState.LANDING
        assert rig.ctl.stats.heartbeat_timeouts >= 1
        assert rig.cmd.kinds()[-1] == "zdistance"

    def test_emergency_stop_cuts_immediately(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        rig.ctl.emergency_stop()
        assert rig.cmd.kinds()[-1] == "stop"
        assert rig.ctl.state is ControlState.STOPPED

    def test_arming_idles_the_props_without_lifting(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(0.2, Intent())
        assert rig.ctl.state is ControlState.ARMED
        assert rig.cmd.last("setpoint")[4] == IDLE_THRUST


class TestThrustUnlock:
    """The firmware holds thrust at zero until it sees one zero-thrust setpoint.

    Missing it cost a lab session: the app armed, reported the props turning,
    and no key moved the drone. Pinned for both control laws.
    """

    @pytest.mark.parametrize("assisted", [True, False])
    def test_arming_sends_the_unlock_before_any_thrust(self, assisted):
        rig = Rig(assisted=assisted)
        rig.ctl.arm()
        rig.run(1.0, Intent(up=True))
        setpoints = [c for c in rig.cmd.commands if c[0] == "setpoint"]
        assert setpoints[0] == ("setpoint", 0.0, 0.0, 0.0, 0)
        assert rig.cmd.commands[0] == ("setpoint", 0.0, 0.0, 0.0, 0)

