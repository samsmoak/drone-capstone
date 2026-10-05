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


class TestStationMeasurement:
    def test_start_then_forward_solves(self):
        measure = geometry.StationMeasurement()
        assert measure.step == "origin"
        measure.record_origin(still_at_origin(), 10.0)
        assert measure.step == "forward"
        result = measure.finish(SimpleNamespace(), one_m_forward(), 11.0, write=False)
        assert result.converged
        assert result.stations[0].translation.tolist() == [2.0, 0.0, 2.0]
        assert measure.step == "origin"                 # ready for another go

    def test_a_turned_drone_is_named(self):
        measure = geometry.StationMeasurement()
        measure.record_origin(still_at_origin(), 0.0)
        result = measure.finish(SimpleNamespace(), FakeSample(
            {0: (FakePose(9, 9, 9), FakePose(-7, -7, -7))}), 60.0, write=False)
        assert "turned about 60 degrees" in result.message

    def test_a_refusal_starts_again_from_the_start_mark(self):
        measure = geometry.StationMeasurement()
        measure.record_origin(still_at_origin(), 0.0)
        measure.finish(SimpleNamespace(), still_at_origin(), 0.0, write=False)
        assert measure.step == "origin"

    def test_forward_before_the_start_is_a_bug_not_a_guess(self):
        with pytest.raises(RuntimeError):
            geometry.StationMeasurement().finish(SimpleNamespace(), one_m_forward(), 0.0)


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


class TestTheSessionWalk:
    def test_two_records_store_the_station_on_the_drone(self, rig):
        rig.samples[:] = [still_at_origin(), one_m_forward()]
        first = rig.session.record_station()
        assert first["step"] == "forward" and not first["done"]
        assert "1.00 m straight forward" in first["message"]
        assert rig.written == []                        # nothing stored on one record

        second = rig.session.record_station()
        assert second["done"] and second["step"] == "origin"
        assert list(rig.written[0]) == [0]
        # The estimate ran on no geometry until now: started again from it.
        assert rig.resets == [rig.link.scf.cf]
        # The rig's session checked before the store: it is told to check again.
        assert "Check again" in second["message"]

    def test_an_unmoved_drone_is_refused_and_stores_nothing(self, rig):
        rig.samples[:] = [still_at_origin(), still_at_origin()]
        rig.session.record_station()
        with pytest.raises(SessionError, match="did not move"):
            rig.session.record_station()
        assert rig.written == [] and rig.resets == []
        assert rig.session.station_status()["step"] == "origin"

    def test_a_write_the_drone_did_not_confirm_is_a_failure(self, rig, monkeypatch):
        monkeypatch.setattr(geometry, "_write", lambda cf, poses: False)
        rig.samples[:] = [still_at_origin(), one_m_forward()]
        rig.session.record_station()
        with pytest.raises(SessionError, match="did not confirm"):
            rig.session.record_station()

    def test_no_beams_is_said_in_words(self, rig, monkeypatch):
        class Deaf:
            def __init__(self, cf, *, min_stations): ...
            def record(self):
                raise TimeoutError("No base station beams reached the drone here.")
        monkeypatch.setattr(session_module, "SweepAngles", Deaf)
        with pytest.raises(SessionError, match="No base station beams"):
            rig.session.record_station()

    def test_never_while_flying(self, rig):
        rig.session._set(state=State.BUSY)
        with pytest.raises(SessionError, match="Land first"):
            rig.session.record_station()

    def test_never_without_a_drone(self, rig):
        rig.link.is_open = False
        with pytest.raises(SessionError, match="Not connected"):
            rig.session.record_station()

    def test_reset_forgets_the_start(self, rig):
        rig.samples[:] = [still_at_origin()]
        rig.session.record_station()
        assert rig.session.station_status()["step"] == "forward"
        rig.session.reset_station()
        assert rig.session.station_status()["step"] == "origin"


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
    def test_the_camera_watchdog_waits(self, rig, monkeypatch):
        from cropwatcher.api import rest

        restarts = []
        rig.session.restart_drone = lambda *, reason: restarts.append(reason)
        agent = SimpleNamespace(session=rig.session, _last_rejoin=0.0)
        rig.samples[:] = [still_at_origin()]
        rig.session.record_station()                    # between the two records
        assert rig.session.measuring_station
        assert rest.Agent.rejoin(agent, reason="no frames") is False
        assert restarts == []

        rig.session.reset_station()
        assert rest.Agent.rejoin(agent, reason="no frames") is True
        assert restarts == ["no frames"]
