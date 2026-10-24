"""Measuring the base station from the Set up page: two records, motors off.

The solve is estimate_single()'s (tests/test_geometry.py); what is tested here
is the one-record-per-button walk around it, and the failure the lab hit on
2026-10-05 — two records of an unmoved drone, reported as a "disagreement".
"""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from cropwatcher import session as session_module
from cropwatcher.flight import geometry
from cropwatcher.session import SessionError, State
from cropwatcher.telemetry.stream import Snapshot
from tests.mission.test_session_missions import make_rig
from tests.test_geometry import FakePose, FakeSample


def still_at_origin():
    return FakeSample({0: (FakePose(2, 0, 2), FakePose(-9, -9, -9))})


def one_m_forward():
    return FakeSample({0: (FakePose(1, 0, 2), FakePose(7, 7, 7))})


class TestNotMoved:
    def test_two_records_of_the_same_place_say_so(self):
        samples = iter([still_at_origin(), still_at_origin()])
        result = geometry.estimate_single(
            SimpleNamespace(), lambda step, i: next(samples),
            reference_distance_m=1.0, write=False)
        assert not result.converged
        assert "did not move" in result.message
        assert "disagree" not in result.message

    def test_a_real_step_is_not_mistaken_for_one(self):
        samples = iter([still_at_origin(), one_m_forward()])
        result = geometry.estimate_single(
            SimpleNamespace(), lambda step, i: next(samples),
            reference_distance_m=1.0, write=False)
        assert result.converged


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rig = make_rig(tmp_path, monkeypatch)
    rig.link.scf = SimpleNamespace(cf=SimpleNamespace())
    rig.samples = []
    rig.written = []

    class FakeSweep:
        def __init__(self, cf, *, min_stations):
            assert min_stations == 1                    # one station is a room
        def record(self):
            return rig.samples.pop(0)

    monkeypatch.setattr(session_module, "SweepAngles", FakeSweep)
    monkeypatch.setattr(geometry, "_write",
                        lambda cf, poses: rig.written.append(poses) or True)
    rig.resets = []
    monkeypatch.setattr(session_module, "reset_estimator", rig.resets.append)
    return rig


def upside_down():
    import numpy as np
    a, b = FakePose(2, 0, 2), FakePose(-2, 0, 2)
    a.rot_matrix = b.rot_matrix = np.diag([1.0, -1.0, -1.0])
    return FakeSample({0: (a, b)})


class TestMeasuringFromWhereTheDroneSits:
    """One record, no walking (2026-10-05): estimate_quick, the mirror settled
    by the station standing upright."""

    def test_one_press_stores_the_station_and_restarts_the_estimate(self, rig):
        rig.samples[:] = [still_at_origin()]
        out = rig.session.measure_station()
        assert list(rig.written[0]) == [0]
        # The estimate ran on no geometry until now: started again from it.
        assert rig.resets == [rig.link.scf.cf]
        assert "(0, 0, 0)" in out["message"]
        # The rig's session checked before the store: it is told to check again.
        assert "check again" in out["message"]
        assert rig.session.measuring_station is False

    def test_a_station_upside_down_both_ways_is_refused_and_stores_nothing(self, rig):
        rig.samples[:] = [upside_down()]
        with pytest.raises(SessionError, match="upright"):
            rig.session.measure_station()
        assert rig.written == [] and rig.resets == []

    def test_a_write_the_drone_did_not_confirm_is_a_failure(self, rig, monkeypatch):
        monkeypatch.setattr(geometry, "_write", lambda cf, poses: False)
        rig.samples[:] = [still_at_origin()]
        with pytest.raises(SessionError, match="did not confirm"):
            rig.session.measure_station()
        assert rig.resets == []

    def test_no_beams_is_said_in_words(self, rig, monkeypatch):
        class Deaf:
            def __init__(self, cf, *, min_stations): ...
            def record(self):
                raise TimeoutError("No base station beams reached the drone here.")
        monkeypatch.setattr(session_module, "SweepAngles", Deaf)
        with pytest.raises(SessionError, match="No base station beams"):
            rig.session.measure_station()
        assert rig.session.measuring_station is False

    def test_never_while_flying(self, rig):
        rig.session._set(state=State.BUSY)
        with pytest.raises(SessionError, match="Land first"):
            rig.session.measure_station()

    def test_never_without_a_drone(self, rig):
        rig.link.is_open = False
        with pytest.raises(SessionError, match="Not connected"):
            rig.session.measure_station()


class TestTheGreenIsTheStationsReach:
    """Computed over the whole map, not inside the room's fence (2026-10-05:
    inside the fence it came out as the room's own box), and used by the plan
    that will fly automatically — no button, no walk."""

    def test_it_reaches_beyond_the_rooms_fence(self, rig):
        from tests.mission.test_coverage import CORNERS
        rig.link.station_poses = lambda: list(CORNERS)
        prediction = rig.session.predicted_coverage("lab")
        assert prediction is not None and prediction.everywhere is not None
        x0, y0, x1, y1 = prediction.everywhere.bounds()
        fx0, fy0, fx1, fy1 = rig.plans.room("lab").geofence.bounds()
        assert x0 < fx0 or y0 < fy0 or x1 > fx1 or y1 > fy1

    def test_the_plan_that_will_fly_is_fitted_to_it(self, rig):
        from tests.mission.test_coverage import CORNERS
        rig.link.station_poses = lambda: list(CORNERS)
        room = rig.plans.room("lab")
        assert rig.session._flyable(room) == rig.session._prediction(room).everywhere

    def test_no_station_measured_falls_back_to_the_default_area(self, rig):
        room = rig.plans.room("lab")
        assert rig.session._flyable(room).bounds() == (-2.0, -2.0, 2.0, 2.0)

    def test_the_poses_are_read_once_per_link(self, rig):
        from tests.mission.test_coverage import CORNERS
        reads = []
        rig.link.station_poses = lambda: reads.append(1) or list(CORNERS)
        rig.session.predicted_coverage("lab")
        rig.session.predicted_coverage("lab")
        assert len(reads) == 1


class TestManualSpace:
    """Manual's room: the stations' reach with no room at all (2026-10-24,
    Samuel: "detect the two base stations, then draw that room on the spot")."""

    def test_it_is_the_stations_reach_over_the_flying_area(self, rig):
        from tests.mission.test_coverage import CORNERS
        rig.link.station_poses = lambda: list(CORNERS)
        space = rig.session.manual_space()
        assert space is not None and space.everywhere is not None
        x0, y0, x1, y1 = space.everywhere.bounds()
        half = rig.session.fence_half_extent_m
        assert -half <= x0 < x1 <= half and -half <= y0 < y1 <= half
        assert space.z_min == session_module.MANUAL_SPACE_FLOOR_M
        assert space.z_max == rig.session._max_height

    def test_no_station_measured_is_no_room(self, rig):
        assert rig.session.manual_space() is None

    def test_no_drone_is_no_room(self, rig):
        from tests.mission.test_coverage import CORNERS
        rig.link.station_poses = lambda: list(CORNERS)
        rig.link.is_open = False
        assert rig.session.manual_space() is None

    def test_it_is_computed_once_until_the_stations_change(self, rig, monkeypatch):
        from tests.mission.test_coverage import CORNERS
        rig.link.station_poses = lambda: list(CORNERS)
        runs = []
        real = session_module.predict
        monkeypatch.setattr(session_module, "predict",
                            lambda *a, **k: runs.append(1) or real(*a, **k))
        first = rig.session.manual_space()
        assert rig.session.manual_space() is first
        rig.session._poses_cache = None             # measured again
        rig.session.manual_space()
        assert len(runs) == 2


class TestStatus:
    def test_it_reads_what_the_drone_reports(self, rig):
        rig.link.snapshot = lambda: Snapshot(MappingProxyType({
            "lighthouse.bsReceive": 0b1, "lighthouse.bsCalVal": 0b1,
            "lighthouse.bsGeoVal": 0b1,
            "kalman.varPX": 0.0001, "kalman.varPY": 0.0001, "kalman.varPZ": 0.0004}), 1.0)
        status = rig.session.station_status()
        assert status["connected"]
        assert status["received"] == [0] and status["usable"] == [0]
        assert status["uncertainty_cm"] == 2.0
        assert status["ready"]

    def test_received_but_not_measured_is_not_ready(self, rig):
        rig.link.snapshot = lambda: Snapshot(MappingProxyType({
            "lighthouse.bsReceive": 0b1, "lighthouse.bsCalVal": 0b1,
            "kalman.varPX": 40.0, "kalman.varPY": 40.0, "kalman.varPZ": 1.0}), 1.0)
        status = rig.session.station_status()
        assert status["received"] == [0] and status["measured"] == []
        assert not status["ready"]

    def test_every_stage_is_reported_as_the_drone_read_it(self, rig):
        """2026-10-05, the lab: light on four sensors, the data read, sweeps
        decoded (bsReceive) — and the place never stored."""
        rig.link.snapshot = lambda: Snapshot(MappingProxyType({
            "lighthouse.width0": 246, "lighthouse.width1": 251,
            "lighthouse.width2": 253, "lighthouse.width3": 0,
            "lighthouse.bsCalVal": 0b1, "lighthouse.bsReceive": 0b1,
            "lighthouse.bsActive": 0b0,
            "kalman.varPX": 40.0, "kalman.varPY": 40.0, "kalman.varPZ": 1.0}), 1.0)
        status = rig.session.station_status()
        assert status["light_sensors"] == 3
        assert status["calibrated"] == [0] and status["received"] == [0]
        assert status["measured"] == [] and status["active"] == []
        assert "angles" not in status                   # validAngles is not the signal

    def test_no_drone(self, rig):
        rig.link.is_open = False
        assert rig.session.station_status()["connected"] is False


class TestAPositionIsOnlyAPlaceWhenTheDroneStandsBehindIt:
    """2026-10-05: a still drone with no station measured read 92 m from the
    mission's start, and climbing — the raw estimate, shown as a place."""

    RUNAWAY = {"stateEstimate.x": -91.6, "stateEstimate.y": -8.2, "stateEstimate.z": 1.2,
               "lighthouse.bsReceive": 0b1, "lighthouse.bsCalVal": 0b1,
               "kalman.varPX": 48.0, "kalman.varPY": 48.0, "kalman.varPZ": 0.5}

    def snap(self, **values):
        return Snapshot(MappingProxyType(values), 1.0)

    def test_received_but_not_measured_is_no_position(self, rig):
        rig.link.snapshot = lambda: self.snap(**self.RUNAWAY)
        assert rig.session.position() is None

    def test_measured_but_loose_is_no_position(self, rig):
        values = {**self.RUNAWAY, "lighthouse.bsGeoVal": 0b1}
        rig.link.snapshot = lambda: self.snap(**values)
        assert rig.session.position() is None

    def test_measured_and_tight_is_a_position(self, rig):
        values = {**self.RUNAWAY, "lighthouse.bsGeoVal": 0b1, "stateEstimate.x": 0.4,
                  "kalman.varPX": 0.0004, "kalman.varPY": 0.0004}
        rig.link.snapshot = lambda: self.snap(**values)
        assert rig.session.position() == (0.4, -8.2, 1.2)

    def test_the_check_step_gets_no_drone_from_a_runaway(self, rig):
        rig.link.snapshot = lambda: self.snap(**self.RUNAWAY)
        _, here = rig.session.flying_plan("m1")
        assert here is None

    def test_start_is_refused_on_a_runaway(self, rig):
        rig.link.snapshot = lambda: self.snap(**self.RUNAWAY)
        with pytest.raises(SessionError, match="position is not being reported"):
            rig.session.run_mission("m1")

    def test_the_telemetry_says_whether_it_is_a_place(self, rig):
        rig.events.clear()
        rig.session._publish_telemetry(self.snap(**self.RUNAWAY))
        tight = {**self.RUNAWAY, "lighthouse.bsGeoVal": 0b1,
                 "kalman.varPX": 0.0004, "kalman.varPY": 0.0004}
        rig.session._publish_telemetry(self.snap(**tight))
        flags = [p["positioned"] for kind, p in rig.events if kind == "telemetry"]
        assert flags == [False, True]


class TestNothingRestartsTheDroneMidMeasurement:
    def test_the_camera_watchdog_waits(self, rig):
        from cropwatcher.api import rest

        restarts = []
        rig.session.restart_drone = lambda *, reason: restarts.append(reason)
        agent = SimpleNamespace(session=rig.session, _last_rejoin=0.0)
        rig.session._measuring = True                   # mid-measurement
        assert rest.Agent.rejoin(agent, reason="no frames") is False
        assert restarts == []

        rig.session._measuring = False
        assert rest.Agent.rejoin(agent, reason="no frames") is True
        assert restarts == ["no frames"]


class TestTwoStations:
    """2026-10-24, the second station in the lab: measuring kept only the
    first, and storing erased the other (cflib invalidates every station it is
    not given)."""

    @pytest.fixture
    def two(self, tmp_path, monkeypatch):
        rig = make_rig(tmp_path, monkeypatch)
        rig.link.scf = SimpleNamespace(cf=SimpleNamespace())
        rig.samples, rig.written, rig.asked = [], [], []

        class FakeSweep:
            def __init__(self, cf, *, min_stations):
                rig.asked.append(min_stations)
            def record(self):
                return rig.samples.pop(0)

        monkeypatch.setattr(session_module, "SweepAngles", FakeSweep)
        monkeypatch.setattr(geometry, "_write",
                            lambda cf, poses: rig.written.append(poses) or True)
        monkeypatch.setattr(session_module, "reset_estimator", lambda cf: None)
        return rig

    def seen(self, rig, receive, geo=0):
        rig.link.snapshot = lambda: Snapshot(MappingProxyType({
            "lighthouse.bsReceive": receive, "lighthouse.bsCalVal": receive,
            "lighthouse.bsGeoVal": geo, "lighthouse.bsActive": geo}), 1.0)

    def test_both_are_measured_from_one_record_and_stored_together(self, two):
        self.seen(two, 0b11)
        two.samples[:] = [FakeSample({0: (FakePose(2, 0, 2), FakePose(-2, 0, -2)),
                                      1: (FakePose(-1, 3, 2), FakePose(1, -3, -2))})]
        out = two.session.measure_station()
        assert two.asked == [2]                       # both, or it refuses
        assert sorted(two.written[0]) == [0, 1]
        assert out["stations"] == [0, 1] and out["cleared"] == []
        assert "channel 1" in out["message"] and "channel 2" in out["message"]
        assert "apart" in out["message"]

    def test_a_station_not_in_the_record_is_named_as_cleared(self, two):
        self.seen(two, 0b01, geo=0b11)                # 2 stored, 1 seen now
        two.samples[:] = [still_at_origin()]
        out = two.session.measure_station()
        assert out["cleared"] == [1]
        assert "channel 2 was not seen from here" in out["message"]

    def test_one_upright_one_not_stores_the_one_and_says_so(self, two):
        import numpy as np
        self.seen(two, 0b11)
        flipped_a, flipped_b = FakePose(2, 0, 2), FakePose(-2, 0, 2)
        flipped_a.rot_matrix = flipped_b.rot_matrix = np.diag([1.0, -1.0, -1.0])
        two.samples[:] = [FakeSample({0: (FakePose(2, 0, 2), FakePose(-2, 0, -2)),
                                      1: (flipped_a, flipped_b)})]
        out = two.session.measure_station()
        assert sorted(two.written[0]) == [0]
        assert "channel 2 could not be measured" in out["message"].lower()

    def test_status_lists_each_station_by_channel(self, two):
        self.seen(two, 0b11, geo=0b01)
        stations = two.session.station_status()["stations"]
        assert stations == [
            {"id": 0, "channel": 1, "calibrated": True, "received": True,
             "measured": True, "active": True},
            {"id": 1, "channel": 2, "calibrated": True, "received": True,
             "measured": False, "active": False},
        ]


class TestTripods:
    """The stations on the room map (2026-10-24): where each stands and which
    way it faces — the drone's own stored geometry, by channel."""

    def test_axes_are_the_rotations_columns(self):
        from cropwatcher.mission.plan.coverage import StationPose
        # The lab's station, 2026-10-05 (test_geometry: standing upright).
        rows = ((0.24, 0.95, 0.19), (-0.86, 0.30, -0.41), (-0.45, -0.06, 0.89))
        axes = StationPose((-1.33, 1.74, 1.49), rows, station=0).axes()
        assert axes["forward"] == (0.24, -0.86, -0.45)     # out of its face, tilted down
        assert axes["left"] == (0.95, 0.30, -0.06)
        assert axes["up"] == (0.19, -0.41, 0.89)           # mostly up: upright

    def test_markers_carry_the_channel_place_and_facing(self, rig):
        from cropwatcher.mission.plan.coverage import StationPose
        eye = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        rig.link.station_poses = lambda: [StationPose((2.0, -1.0, 1.8), eye, station=1)]
        (marker,) = rig.session.station_markers()
        assert marker["id"] == 1 and marker["channel"] == 2
        assert marker["origin"] == [2.0, -1.0, 1.8]
        assert marker["forward"] == [1.0, 0.0, 0.0] and marker["up"] == [0.0, 0.0, 1.0]

    def test_no_drone_no_tripods(self, rig):
        rig.link.is_open = False
        assert rig.session.station_markers() == []
