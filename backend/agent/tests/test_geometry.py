"""Measuring where the base stations are.

The solver itself is Bitcraze's; what is tested here is everything around it —
the order the operator is walked through, and the two ways a position can fail
to give a usable sample. Both were written after the lab session of
2026-09-21, where stale geometry made the drone's own position jump 21 cm in a
tenth of a second while it sat still on the floor.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cropwatcher.flight import geometry


class FakeReader:
    """Stands in for cflib's averaging reader: answers with whatever it was given."""

    answer: dict | None = None

    def __init__(self, cf, ready_cb):
        self._ready = ready_cb

    def start_angle_collection(self):
        if FakeReader.answer is not None:
            self._ready(FakeReader.answer)


@pytest.fixture(autouse=True)
def fake_cflib(monkeypatch):
    """No radio, no drone: the reader and the pose type are stubbed."""
    import cflib.localization as localization
    import cflib.localization.lighthouse_cf_pose_sample as pose_sample

    monkeypatch.setattr(localization, "LighthouseSweepAngleAverageReader", FakeReader)
    monkeypatch.setattr(
        pose_sample, "LhCfPoseSample",
        lambda angles_calibrated: SimpleNamespace(angles_calibrated=angles_calibrated),
    )
    FakeReader.answer = None


class TestTheSteps:
    def test_the_order_is_origin_then_scale_then_spread(self):
        keys = [s.key for s in geometry.steps(1.0)]
        assert keys == ["origin", "x_axis", "xy_plane", "space"]

    def test_the_measured_distance_is_in_the_words_the_operator_reads(self):
        step = geometry.steps(1.25)[1]
        assert "1.25 m" in step.instruction
        assert "scale" in step.instruction              # says why it is measured

    def test_the_floor_and_the_space_ask_for_several(self):
        plan = {s.key: s.count for s in geometry.steps(1.0)}
        assert plan["origin"] == 1 and plan["x_axis"] == 1
        assert plan["xy_plane"] > 1 and plan["space"] > 1

    def test_the_space_step_says_to_lift_it(self):
        """The drone flies above the floor; samples taken only on the floor
        leave the solver guessing about the vertical."""
        assert "in the air" in geometry.steps(1.0)[3].instruction


class TestRecordingOneSample:
    def test_two_stations_gives_a_sample(self):
        FakeReader.answer = {0: (10, "vectors-0"), 1: (10, "vectors-1")}
        sample = geometry.SweepAngles(SimpleNamespace()).record()
        assert sorted(sample.angles_calibrated) == [0, 1]

    def test_one_station_is_refused_and_says_which(self):
        """A sample from a single station reads fine and poisons the solution."""
        FakeReader.answer = {0: (10, "vectors-0")}
        with pytest.raises(ValueError, match="Only base station 0"):
            geometry.SweepAngles(SimpleNamespace()).record()

    def test_no_beams_at_all_times_out_with_something_to_do(self):
        FakeReader.answer = None                          # the callback never fires
        with pytest.raises(TimeoutError, match="powered and pointing"):
            geometry.SweepAngles(SimpleNamespace(), timeout_s=0.05).record()


class TestTheResult:
    def test_a_failed_solve_carries_the_reason_not_just_false(self):
        result = geometry.GeometryResult(converged=False, message="samples too close")
        assert not result.converged
        assert result.to_dict()["message"] == "samples too close"

    def test_a_solved_geometry_reports_its_error_in_the_record(self):
        result = geometry.GeometryResult(
            converged=True, stations={0: object(), 1: object()},
            mean_error_m=0.012, max_error_m=0.031, written=True,
        )
        assert result.to_dict() == {
            "converged": True, "stations": [0, 1],
            "mean_error_m": 0.012, "max_error_m": 0.031,
            "written": True, "message": "",
        }
