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


class FakePose:
    """Stands in for cflib's Pose: only the translation is used to choose."""

    def __init__(self, x, y, z):
        import numpy as np
        self.translation = np.array([float(x), float(y), float(z)])
        self.rot_matrix = np.eye(3)


class FakeSample:
    """An LhCfPoseSample whose IPPE answers are handed to it.

    Each station maps to the two poses IPPE would return: the true one and its
    mirror. Which order they come in is the whole point — the solver must not
    depend on it.
    """

    def __init__(self, solutions):
        self.angles_calibrated = dict.fromkeys(solutions, "vectors")
        self.ippe_solutions = solutions
        self.augmented = False

    def augment_with_ippe(self, sensor_positions):
        self.augmented = True


class TestOneBaseStationAlone:
    """Lighthouse V2 positions from one station, so a room with one is not a
    room with none. The pose comes from IPPE, which returns the true answer
    AND its mirror; a second sample a measured distance away decides.
    """

    def test_it_asks_for_two_samples_and_says_why_the_second_matters(self):
        plan = geometry.single_station_steps(1.0)
        assert [s.key for s in plan] == ["origin", "x_axis"]
        assert "mirror" in plan[1].instruction
        assert "SAME way" in plan[1].instruction     # the rotation must not change

    def test_it_picks_the_pose_both_samples_agree_on(self):
        # True station at (2, 0, 2). From 1 m forward it therefore sits 1 m
        # nearer in x. The mirrors are nowhere near each other.
        at_origin = FakeSample({0: (FakePose(-9, -9, -9), FakePose(2, 0, 2))})
        one_m_on = FakeSample({0: (FakePose(1, 0, 2), FakePose(7, 7, 7))})
        samples = iter([at_origin, one_m_on])

        result = geometry.estimate_single(
            SimpleNamespace(), lambda step, i: next(samples),
            reference_distance_m=1.0, write=False)

        assert result.converged
        assert list(result.stations) == [0]
        assert result.stations[0].translation.tolist() == [2.0, 0.0, 2.0]
        assert at_origin.augmented and one_m_on.augmented

    def test_the_mirror_is_refused_when_nothing_agrees(self):
        at_origin = FakeSample({0: (FakePose(2, 0, 2), FakePose(-2, 0, 2))})
        one_m_on = FakeSample({0: (FakePose(9, 9, 9), FakePose(-9, 9, 9))})
        result = geometry.estimate_single(
            SimpleNamespace(), lambda step, i: iter([at_origin, one_m_on]).__next__(),
            reference_distance_m=1.0, write=False)
        assert not result.converged
        assert "disagree" in result.message

    def test_samples_of_different_stations_solve_nothing(self):
        samples = iter([FakeSample({0: (FakePose(2, 0, 2),) * 2}),
                        FakeSample({1: (FakePose(1, 0, 2),) * 2})])
        result = geometry.estimate_single(
            SimpleNamespace(), lambda step, i: next(samples),
            reference_distance_m=1.0, write=False)
        assert not result.converged
        assert "same base station" in result.message

    def test_one_station_is_allowed_through_when_asked_for(self):
        """The refusal is a setting, not a law: a room with one station still
        has to be able to take a sample in it."""
        FakeReader.answer = {0: (10, "vectors-0")}
        sample = geometry.SweepAngles(SimpleNamespace(), min_stations=1).record()
        assert sorted(sample.angles_calibrated) == [0]


class TestWhyTheSamplesDisagreed:
    """"Take them again" is not an instruction. Which assumption broke is."""

    def _run(self, origin, forward, **kw):
        samples = iter([FakeSample({0: origin}), FakeSample({0: forward})])
        return geometry.estimate_single(
            SimpleNamespace(), lambda step, i: next(samples),
            reference_distance_m=1.0, write=False, **kw)

    def test_a_turned_drone_is_named_as_the_cause(self):
        yaws = iter([10.0, 55.0])                       # turned 45 degrees
        result = self._run((FakePose(2, 0, 2), FakePose(-9, -9, -9)),
                           (FakePose(9, 9, 9), FakePose(-7, -7, -7)),
                           heading=lambda: next(yaws))
        assert not result.converged
        assert "turned about 45 degrees" in result.message
        assert "SAME way" in result.message

    def test_a_wrap_around_turn_is_measured_the_short_way(self):
        yaws = iter([-175.0, 175.0])                    # 10 degrees, not 350
        result = self._run((FakePose(2, 0, 2), FakePose(-9, -9, -9)),
                           (FakePose(9, 9, 9), FakePose(-7, -7, -7)),
                           heading=lambda: next(yaws))
        assert "turned about" not in result.message     # under the threshold

    def test_a_steady_heading_is_ruled_out_explicitly(self):
        yaws = iter([10.0, 11.0])
        result = self._run((FakePose(2, 0, 2), FakePose(-9, -9, -9)),
                           (FakePose(9, 9, 9), FakePose(-7, -7, -7)),
                           heading=lambda: next(yaws))
        assert "not the cause" in result.message
        assert "m away" in result.message               # gives both distances

    def test_it_still_explains_itself_with_no_heading_available(self):
        result = self._run((FakePose(2, 0, 2), FakePose(-9, -9, -9)),
                           (FakePose(9, 9, 9), FakePose(-7, -7, -7)))
        assert not result.converged
        assert "disagree" in result.message


class TestTheQuickWayBack:
    """One position, no measuring. It trades the mirror check for a much
    smaller ask, because position hold does not care which way the room is
    labelled — only the arrows do."""

    def test_one_sample_is_enough_to_solve(self):
        sample = FakeSample({0: (FakePose(2, 0, 2), FakePose(-9, -9, -9))})
        result = geometry.estimate_quick(
            SimpleNamespace(), lambda step, i: sample, write=False)
        assert result.converged
        assert result.stations[0].translation.tolist() == [2.0, 0.0, 2.0]

    def test_it_takes_the_lower_reprojection_error_one(self):
        """cflib returns the better solution first; the mirror is second."""
        sample = FakeSample({0: (FakePose(1, 1, 1), FakePose(-1, -1, -1))})
        result = geometry.estimate_quick(
            SimpleNamespace(), lambda step, i: sample, write=False)
        assert result.stations[0].translation.tolist() == [1.0, 1.0, 1.0]

    def test_it_asks_for_exactly_one_position(self):
        seen = []
        sample = FakeSample({0: (FakePose(2, 0, 2),) * 2})
        geometry.estimate_quick(
            SimpleNamespace(), lambda step, i: (seen.append(step.key) or sample),
            write=False)
        assert seen == ["origin"]

    def test_it_says_the_mirror_is_the_risk_it_took(self):
        sample = FakeSample({0: (FakePose(2, 0, 2),) * 2})
        result = geometry.estimate_quick(
            SimpleNamespace(), lambda step, i: sample, write=False)
        assert "mirror" in result.message
        assert "Position hold will work" in result.message

    def test_no_station_at_that_spot_is_refused(self):
        result = geometry.estimate_quick(
            SimpleNamespace(), lambda step, i: FakeSample({}), write=False)
        assert not result.converged
        assert "No base station reached" in result.message
