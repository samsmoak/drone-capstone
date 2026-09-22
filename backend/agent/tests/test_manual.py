"""Manual control loop.

Every test here is about something going wrong or being done gently, because
manual control is the one surface where a software mistake drops a real
aircraft. A fake clock drives the timing so heartbeat expiry and the climb rate
can be tested in microseconds rather than by sleeping.
"""

from __future__ import annotations

import pytest

from cropwatcher.flight.manual import (
    CLIMB_ACCEL_M_S2,
    CLIMB_RATE_M_S,
    HEARTBEAT_TIMEOUT_S,
    IDLE_THRUST,
    LAND_RATE_M_S,
    LAND_S,
    MAX_HEIGHT_M,
    MAX_TILT_DEG,
    MAX_UNASSISTED_HEIGHT_M,
    MOVE_ACCEL_M_S2,
    MOVE_SPEED_M_S,
    TICK_S,
    TOUCHDOWN_HOLD_S,
    YAW_RATE_DEG_S,
    ControlState,
    Fix,
    Intent,
    ManualController,
)

GROUND = 1.0


def glide_distance(seconds: float) -> float:
    """How far the height target moves from rest while a key is held."""
    ramp = CLIMB_RATE_M_S / CLIMB_ACCEL_M_S2
    if seconds <= ramp:
        return 0.5 * CLIMB_ACCEL_M_S2 * seconds**2
    return 0.5 * CLIMB_ACCEL_M_S2 * ramp**2 + CLIMB_RATE_M_S * (seconds - ramp)


#: Distance covered easing from full climb speed to a stop.
STOPPING_DISTANCE = CLIMB_RATE_M_S**2 / (2 * CLIMB_ACCEL_M_S2)


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

    def send_position_setpoint(self, x, y, z, yaw):
        self.commands.append(("position", x, y, z, yaw))

    def send_notify_setpoint_stop(self, remain_valid_milliseconds=0):
        self.commands.append(("notify_stop",))

    def send_stop_setpoint(self):
        self.commands.append(("stop",))

    def last(self, kind):
        return next(c for c in reversed(self.commands) if c[0] == kind)

    def kinds(self):
        return [c[0] for c in self.commands]

    #: The setpoints that fly the drone, as opposed to notify/stop bookkeeping.
    FLYING = ("hover", "zdistance", "position", "setpoint")

    def height(self):
        """The commanded height, off whichever setpoint last carried one.

        Which setpoint that is depends on the law and on whether the spot is
        being held, and no test here is about that — they are about the height.
        """
        for c in reversed(self.commands):
            if c[0] in ("hover", "zdistance"):
                return c[4]
            if c[0] == "position":
                return c[3]
        raise AssertionError("nothing carrying a height was ever sent")

    def first_flying(self):
        """Index of the first setpoint that flies the drone."""
        return next(i for i, c in enumerate(self.commands) if c[0] in self.FLYING)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


#: An arbitrary spot the estimator reports the drone at, so tests that care
#: about the held position have a number to recognise.
SOMEWHERE = Fix(1.5, -0.5, 90.0)


class Rig:
    def __init__(self, assisted: bool = True, fix: Fix | None = SOMEWHERE):
        self.clock = FakeClock()
        self.cmd = FakeCommander()
        self.lands: list[tuple[float, float]] = []
        #: What the estimator reports. Moving it simulates the drone drifting.
        self.fix = fix
        self.ctl = ManualController(
            self.cmd, ground_z=GROUND, land=lambda z, d: self.lands.append((z, d)),
            assisted=assisted, clock=self.clock,
            position=lambda: self.fix,
        )

    def run(self, seconds: float, intent: Intent | None = None, heartbeat: bool = True):
        if intent is not None:
            self.ctl.set_intent(intent)
        for _ in range(round(seconds / TICK_S)):
            self.clock.advance(TICK_S)
            if heartbeat:
                self.ctl.heartbeat()
            self.ctl.tick()

    def drift(self, dx: float, dy: float, speed: float = 0.5):
        """Push the reported position by (dx, dy) at a believable speed.

        Moving it in one step would be an estimator jump, which the loop
        rejects on purpose — so a test about drift has to drift.
        """
        start = self.fix
        distance = (dx * dx + dy * dy) ** 0.5
        ticks = max(1, round(distance / speed / TICK_S))
        for i in range(1, ticks + 1):
            self.fix = Fix(start.x + dx * i / ticks, start.y + dy * i / ticks, start.yaw_deg)
            self.run(TICK_S)

    def fly_to(self, height: float):
        """Hold W until the target is near `height`, then release and let it
        glide to a stop — which lands it at `height` within a centimetre."""
        self.ctl.arm()
        self.ctl.set_intent(Intent(up=True))
        while self.ctl.target_height + STOPPING_DISTANCE < height:
            self.run(TICK_S)
        self.run(1.0, Intent())


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
        assert rig.ctl.target_height == pytest.approx(glide_distance(2.0), abs=0.01)
        assert rig.ctl.climb_velocity == pytest.approx(CLIMB_RATE_M_S)
        assert rig.ctl.state is ControlState.FLYING

    def test_height_is_commanded_relative_to_ground(self):
        rig = Rig()
        rig.fly_to(0.30)
        rig.run(0.1)
        assert rig.cmd.height() == pytest.approx(GROUND + 0.30, abs=0.015)

    def test_releasing_the_keys_holds_height(self):
        """The old controller bled thrust off and the drone sank."""
        rig = Rig()
        rig.fly_to(0.40)
        before = rig.ctl.target_height
        rig.run(3.0, Intent())
        assert rig.ctl.target_height == pytest.approx(before)
        assert rig.ctl.climb_velocity == 0.0
        assert rig.ctl.state is ControlState.FLYING

    def test_lowering_is_gentle_too(self):
        rig = Rig()
        rig.fly_to(0.60)
        start = rig.ctl.target_height
        rig.run(1.0, Intent(down=True))
        assert rig.ctl.target_height == pytest.approx(start - glide_distance(1.0), abs=0.01)

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
        rig.run(1.0, Intent(forward=True, left=True, yaw_left=True))
        _, vx, vy, yaw, _ = rig.cmd.last("hover")
        assert vx == pytest.approx(MOVE_SPEED_M_S)
        assert vy == pytest.approx(MOVE_SPEED_M_S)     # left is +vy
        assert yaw == pytest.approx(YAW_RATE_DEG_S)    # turning left is +yawrate

    def test_opposite_keys_cancel(self):
        # No position source, so the cancelled velocities stay visible on the
        # wire instead of resolving into a held spot.
        rig = Rig(fix=None)
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
        assert kinds.index("notify_stop") > rig.cmd.first_flying()
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
        assert rig.ctl.target_height == pytest.approx(glide_distance(1.0), abs=0.01)
        _, _, _, _, z = rig.cmd.last("zdistance")
        assert z == pytest.approx(GROUND + glide_distance(1.0), abs=0.01)
        assert "hover" not in rig.cmd.kinds()

    def test_releasing_w_holds_the_height(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        released = rig.ctl.target_height
        rig.run(1.0, Intent())                    # glides to a stop
        settled = rig.ctl.target_height
        assert settled == pytest.approx(released + STOPPING_DISTANCE, abs=0.01)
        rig.run(3.0, Intent())                    # and then holds exactly
        assert rig.ctl.target_height == settled
        assert rig.cmd.last("zdistance")[4] == pytest.approx(GROUND + settled)

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
        # Landing mid-climb eases out of the climb first, then into the descent.
        rig.run(2.0)
        assert rig.ctl.state is ControlState.LANDING
        assert rig.ctl.target_height < start - 0.1           # it is coming down
        assert rig.ctl.climb_velocity == pytest.approx(-LAND_RATE_M_S)

        rig.run(start / LAND_RATE_M_S + 1.0 + TOUCHDOWN_HOLD_S + 0.2)
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



class TestGlide:
    """Nothing the keys command changes in a step.

    The lab traces of 2026-09-17 show motors slamming between 0 and full every
    0.2–0.4 s. A climb speed that jumps on key press and release is a jolt the
    height controller answers with exactly that. These pin the easing.
    """

    @pytest.mark.parametrize("assisted", [True, False])
    def test_the_climb_speed_never_steps(self, assisted):
        rig = Rig(assisted=assisted)
        rig.ctl.arm()
        speeds = []
        plan = [(Intent(up=True), 2.0), (Intent(), 1.0), (Intent(down=True), 1.0), (Intent(), 1.0)]
        for keys, seconds in plan:
            rig.ctl.set_intent(keys)
            for _ in range(round(seconds / TICK_S)):
                rig.run(TICK_S)
                speeds.append(rig.ctl.climb_velocity)
        steps = [abs(b - a) for a, b in zip(speeds, speeds[1:], strict=False)]
        assert max(steps) <= CLIMB_ACCEL_M_S2 * TICK_S + 1e-9

    def test_releasing_w_eases_to_a_stop_rather_than_stopping_dead(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        rig.run(0.1, Intent())
        assert 0 < rig.ctl.climb_velocity < CLIMB_RATE_M_S       # still slowing
        rig.run(1.0, Intent())
        assert rig.ctl.climb_velocity == 0.0

    def test_the_commanded_height_is_smooth(self):
        """Second difference of the setpoint bounded by the acceleration limit."""
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        rig.run(1.5, Intent())
        zs = [c[4] for c in rig.cmd.commands if c[0] == "zdistance"]
        triples = zip(zs, zs[1:], zs[2:], strict=False)
        accel = [abs((c - b) - (b - a)) / TICK_S**2 for a, b, c in triples]
        assert max(accel) <= CLIMB_ACCEL_M_S2 * 1.01

    def test_tilt_and_yaw_ease_in_and_out(self):
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(1.0, Intent(up=True))
        rig.run(0.1, Intent(right=True, yaw_left=True))
        _, roll, _, yaw, _ = rig.cmd.last("zdistance")
        assert 0 < roll < MAX_TILT_DEG
        assert 0 < yaw < YAW_RATE_DEG_S
        rig.run(1.0, Intent(right=True, yaw_left=True))
        _, roll, _, yaw, _ = rig.cmd.last("zdistance")
        assert roll == pytest.approx(MAX_TILT_DEG) and yaw == pytest.approx(YAW_RATE_DEG_S)
        rig.run(0.1, Intent())
        _, roll, _, yaw, _ = rig.cmd.last("zdistance")
        assert 0 < roll < MAX_TILT_DEG                           # levelling, not snapped

    def test_assisted_arrows_ease_too(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(0.1, Intent(forward=True))
        _, vx, _, _, _ = rig.cmd.last("hover")
        assert 0 < vx <= MOVE_ACCEL_M_S2 * 0.1 + 1e-9


class TestHoldingTheSpot:
    """Letting go holds the place, not the speed.

    Zero velocity asks the drone to stop; it does not ask it to stay. Every
    small error in the estimate, and every draught, then moves it, and nothing
    brings it back — which is drift an operator has to fly out by hand.
    """

    def test_flying_by_key_sends_velocities_and_takes_no_spot(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(0.5, Intent(forward=True))
        assert rig.cmd.kinds()[-1] == "hover"
        assert rig.ctl.anchor is None

    def test_letting_go_holds_the_place_it_stopped(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(0.5, Intent(forward=True))
        rig.run(1.5, Intent())                       # glide out, then settle
        kind, x, y, z, yaw = rig.cmd.last("position")
        assert (x, y, yaw) == (1.5, -0.5, 90.0)      # where the estimator said it was
        assert z == pytest.approx(GROUND + rig.ctl.target_height)
        assert rig.ctl.anchor == Fix(1.5, -0.5, 90.0)

    def test_the_spot_is_not_taken_while_still_gliding(self):
        """Anchoring mid-glide would fight the glide and lurch."""
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(0.5, Intent(forward=True))
        rig.run(0.1, Intent())                       # released, still coasting
        assert rig.cmd.kinds()[-1] == "hover"
        assert rig.ctl.anchor is None

    def test_the_drone_drifting_does_not_move_the_spot(self):
        """The point of the anchor: the drone comes back to it, not with it."""
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        held = rig.ctl.anchor
        rig.drift(0.10, 0.0)                         # blown 10 cm downwind
        assert rig.ctl.anchor == held
        _, x, y, _, _ = rig.cmd.last("position")
        assert (x, y) == (held.x, held.y)            # still commanding the old spot

    def test_the_distance_off_the_spot_is_reported(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        assert rig.ctl.drift_m == pytest.approx(0.0, abs=1e-9)
        rig.drift(0.06, 0.08)                        # 3-4-5: exactly 10 cm off
        assert rig.ctl.drift_m == pytest.approx(0.10, abs=0.005)

    def test_flying_again_clears_the_reported_drift(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        rig.drift(0.10, 0.0)
        rig.run(0.1, Intent(forward=True))
        assert rig.ctl.drift_m == 0.0

    def test_moving_again_releases_the_spot(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        assert rig.ctl.anchor is not None
        rig.run(0.2, Intent(left=True))
        assert rig.ctl.anchor is None
        assert rig.cmd.kinds()[-1] == "hover"

    def test_height_still_moves_while_the_spot_is_held(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        before = rig.cmd.last("position")[3]
        rig.run(1.0, Intent(up=True))
        after = rig.cmd.last("position")[3]
        assert after > before                        # W still climbs
        assert rig.ctl.anchor is not None            # and the spot is kept

    def test_without_a_position_it_asks_for_stillness_rather_than_a_coordinate(self):
        rig = Rig(fix=None)
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        assert "position" not in rig.cmd.kinds()
        _, vx, vy, rate, _ = rig.cmd.last("hover")
        assert (vx, vy, rate) == (0.0, 0.0, 0.0)

    def test_unassisted_flight_never_holds_a_spot(self):
        """No base stations, no position worth flying to."""
        rig = Rig(assisted=False)
        rig.ctl.arm()
        rig.run(2.0, Intent(up=True))
        rig.run(2.0, Intent())
        assert "position" not in rig.cmd.kinds()
        assert rig.cmd.kinds()[-1] == "zdistance"

    def test_a_position_that_jumps_is_not_believed(self):
        """Stale geometry moved the estimate 21 cm in one 0.1 s step while the
        drone sat still. Chasing that would fly it hard into the error."""
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        held = rig.ctl.anchor
        rig.fix = Fix(held.x + 0.21, held.y, held.yaw_deg)   # 10.5 m/s
        rig.run(TICK_S)
        assert rig.ctl.drift_m == 0.0                # the jump never became drift
        assert rig.ctl.anchor == held

    def test_a_position_that_stays_put_is_believed_in_the_end(self):
        """Rejecting a jump must not blind the loop for good: a drone really
        carried somewhere keeps reporting it, and that is not a glitch."""
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        held = rig.ctl.anchor
        rig.fix = Fix(held.x + 0.21, held.y, held.yaw_deg)
        rig.run(0.5)                                 # same reading, tick after tick
        assert rig.ctl.drift_m == pytest.approx(0.21, abs=0.005)
        assert rig.ctl.anchor == held                # and still the original spot

    def test_arming_again_forgets_the_old_spot(self):
        rig = Rig()
        rig.fly_to(0.3)
        rig.run(2.0, Intent())
        assert rig.ctl.anchor is not None
        rig.ctl.land()
        rig.run(LAND_S + 0.5)
        rig.ctl.arm()
        assert rig.ctl.anchor is None

