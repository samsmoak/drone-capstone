"""Mission planning, validation and execution.

Execution is tested against a fake flight rather than hardware, which lets the
failure paths be exercised properly — a real drone cannot be asked to brown out
mid-mission on demand.
"""

from __future__ import annotations

import json

import pytest

from cropwatcher.flight.core import Waypoint
from cropwatcher.flight.missions import (
    EventKind,
    Mission,
    MissionType,
    MissionValidationError,
    execute,
    hover_mission,
    lawnmower_mission,
)
from cropwatcher.safety.geofence import Geofence
from cropwatcher.safety.occupancy import OccupancyGrid
from tests.test_safety import write_map


class FakeFlight:
    """Stands in for a real Flight. Records what it was told to do."""

    def __init__(self, *, critical_after: int | None = None, fail_at: int | None = None):
        self.calls: list[tuple] = []
        self.airborne = False
        self.ground_z = 0.0
        self._goto_count = 0
        self._critical_after = critical_after
        self._fail_at = fail_at
        self.landed = False

    def takeoff(self, height_m, duration_s=2.0):
        self.calls.append(("takeoff", height_m))
        self.airborne = True

    def goto(self, wp, duration_s=3.0):
        if self._fail_at is not None and self._goto_count == self._fail_at:
            raise RuntimeError("radio link lost")
        self._goto_count += 1
        self.calls.append(("goto", wp.x, wp.y, wp.z))

    def hold(self, seconds):
        self.calls.append(("hold", seconds))

    def land(self, duration_s=2.5):
        self.calls.append(("land",))
        self.airborne = False
        self.landed = True

    def position(self):
        return (0.0, 0.0, 0.5)

    def voltage_critical(self):
        if self._critical_after is None:
            return False
        return self._goto_count >= self._critical_after


class TestMissionModel:
    def test_rejects_an_empty_plan(self):
        with pytest.raises(ValueError, match="at least one waypoint"):
            Mission(type=MissionType.WAYPOINT, waypoints=[])

    def test_round_trips_through_json(self, tmp_path):
        original = lawnmower_mission(2.0, 2.0, 0.5, 0.4, hold_s=1.0)
        path = tmp_path / "m.json"
        original.save(path)
        loaded = Mission.from_file(path)

        assert loaded.type is original.type
        assert len(loaded.waypoints) == len(original.waypoints)
        assert loaded.waypoints[3] == original.waypoints[3]
        assert loaded.hold_s == 1.0

    def test_rejects_malformed_json(self):
        with pytest.raises(ValueError, match="malformed waypoint"):
            Mission.from_dict({"waypoints": [{"x": 1}]})

    def test_duration_estimate_grows_with_waypoints(self):
        short = lawnmower_mission(1.0, 1.0, 1.0, 0.4)
        long = lawnmower_mission(4.0, 4.0, 0.5, 0.4)
        assert long.estimated_duration_s() > short.estimated_duration_s()

    def test_describe_lists_every_waypoint(self):
        text = lawnmower_mission(2.0, 2.0, 1.0, 0.4).describe()
        assert "lawnmower" in text
        assert text.count("x=") == len(lawnmower_mission(2.0, 2.0, 1.0, 0.4).waypoints)


class TestLawnmower:
    def test_covers_the_full_width(self):
        m = lawnmower_mission(4.0, 2.0, 1.0, 0.5)
        xs = sorted({round(w.x, 3) for w in m.waypoints})
        assert xs[0] == pytest.approx(-2.0)
        assert xs[-1] == pytest.approx(2.0)

    def test_lanes_alternate_direction(self):
        """The serpentine property: no wasted return leg between lanes."""
        m = lawnmower_mission(4.0, 2.0, 1.0, 0.5)
        # First lane runs +y to -y, second must run -y to +y.
        assert m.waypoints[0].y > m.waypoints[1].y
        assert m.waypoints[2].y < m.waypoints[3].y

    def test_no_gaps_wider_than_the_step(self):
        m = lawnmower_mission(4.0, 2.0, 0.5, 0.5)
        xs = sorted({round(w.x, 3) for w in m.waypoints})
        gaps = [b - a for a, b in zip(xs[:-1], xs[1:], strict=True)]
        assert max(gaps) <= 0.5 + 1e-6

    def test_layers_are_stacked(self):
        m = lawnmower_mission(2.0, 2.0, 1.0, 0.4, layers=2, layer_gap_m=0.3)
        zs = sorted({round(w.z, 3) for w in m.waypoints})
        assert zs == [0.4, 0.7]

    def test_rejects_nonsense_geometry(self):
        with pytest.raises(ValueError, match="step must be positive"):
            lawnmower_mission(2.0, 2.0, 0.0, 0.4)
        with pytest.raises(ValueError, match="area must be positive"):
            lawnmower_mission(0.0, 2.0, 0.5, 0.4)


class TestValidation:
    def test_accepts_a_plan_inside_the_fence(self):
        lawnmower_mission(1.0, 1.0, 0.5, 0.4).validate(geofence=Geofence.square(2.0))

    def test_rejects_a_plan_outside_the_fence(self):
        with pytest.raises(MissionValidationError, match="outside the permitted"):
            lawnmower_mission(10.0, 10.0, 1.0, 0.4).validate(geofence=Geofence.square(1.0))

    def test_error_names_the_offending_waypoint(self):
        mission = Mission(
            type=MissionType.WAYPOINT,
            waypoints=[Waypoint(0.0, 0.0, 0.5, "safe"), Waypoint(9.0, 0.0, 0.5, "bad")],
        )
        with pytest.raises(MissionValidationError) as e:
            mission.validate(geofence=Geofence.square(1.0))
        assert "bad" in str(e.value)
        assert e.value.index == 1

    def test_rejects_a_leg_crossing_a_wall(self, tmp_path):
        """Both waypoints are clear; the path between them is not."""
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, [
            ".....",
            ".....",
            "#####",
            ".....",
            ".....",
        ], origin=(-2.5, -2.5)))
        mission = Mission(
            type=MissionType.WAYPOINT,
            waypoints=[Waypoint(0.0, -2.0, 0.5), Waypoint(0.0, 2.0, 0.5)],
            return_to_start=False,
        )
        with pytest.raises(MissionValidationError, match="crosses a blocked"):
            mission.validate(occupancy=grid)

    def test_checks_the_leg_out_of_the_takeoff_point(self, tmp_path):
        """An obstacle between the drone and its first waypoint is the easiest
        one to forget, because it is not between two waypoints."""
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, [
            ".....",
            "#####",
            ".....",
            ".....",
            ".....",
        ], origin=(-2.5, -2.5)))
        mission = Mission(
            type=MissionType.WAYPOINT,
            waypoints=[Waypoint(0.0, 2.0, 0.5)],
            return_to_start=False,
        )
        with pytest.raises(MissionValidationError):
            mission.validate(occupancy=grid, start=(0.0, 0.0))

    def test_validation_runs_before_anything_arms(self):
        """A plan can be rejected with no drone present at all."""
        with pytest.raises(MissionValidationError):
            lawnmower_mission(20.0, 20.0, 1.0, 0.4).validate(geofence=Geofence.square(1.0))


class TestExecution:
    def test_flies_every_waypoint(self):
        mission = lawnmower_mission(2.0, 2.0, 1.0, 0.4)
        flight = FakeFlight()
        events = list(execute(mission, flight))

        gotos = [c for c in flight.calls if c[0] == "goto"]
        # Every waypoint, plus the return to start.
        assert len(gotos) == len(mission.waypoints) + 1
        assert events[-1].kind is EventKind.LANDED

    def test_lands_after_a_normal_mission(self):
        flight = FakeFlight()
        list(execute(hover_mission(0.5, 1.0), flight))
        assert flight.landed
        assert not flight.airborne

    def test_lands_even_when_a_leg_fails(self):
        """A raised exception must never leave the drone hovering."""
        flight = FakeFlight(fail_at=1)
        with pytest.raises(RuntimeError, match="radio link lost"):
            list(execute(lawnmower_mission(2.0, 2.0, 1.0, 0.4), flight))
        assert flight.landed

    def test_emits_a_failure_event_before_raising(self):
        flight = FakeFlight(fail_at=0)
        events = []
        with pytest.raises(RuntimeError):
            for e in execute(lawnmower_mission(2.0, 2.0, 1.0, 0.4), flight):
                events.append(e)
        assert events[-1].kind is EventKind.FAILED

    def test_aborts_and_lands_on_critical_voltage(self):
        flight = FakeFlight(critical_after=2)
        events = list(execute(lawnmower_mission(4.0, 2.0, 0.5, 0.4), flight))

        assert any(e.kind is EventKind.ABORTED for e in events)
        assert flight.landed

    def test_abort_stops_early_rather_than_finishing(self):
        mission = lawnmower_mission(4.0, 2.0, 0.5, 0.4)
        flight = FakeFlight(critical_after=2)
        list(execute(mission, flight))

        gotos = [c for c in flight.calls if c[0] == "goto"]
        assert len(gotos) < len(mission.waypoints)

    def test_holds_at_each_waypoint_when_asked(self):
        mission = hover_mission(0.5, hold_s=2.0)
        flight = FakeFlight()
        list(execute(mission, flight))
        assert ("hold", 2.0) in flight.calls

    def test_events_reach_the_callback(self):
        seen = []
        list(execute(hover_mission(0.5, 0.0), FakeFlight(), on_event=seen.append))
        kinds = [e.kind for e in seen]
        assert EventKind.STARTED in kinds
        assert EventKind.LANDED in kinds


class TestSerialisationRoundTrip:
    def test_a_saved_mission_still_validates(self, tmp_path):
        mission = lawnmower_mission(1.5, 1.5, 0.5, 0.4)
        path = tmp_path / "m.json"
        mission.save(path)

        reloaded = Mission.from_file(path)
        reloaded.validate(geofence=Geofence.square(2.0))

    def test_saved_file_is_readable_json(self, tmp_path):
        path = tmp_path / "m.json"
        hover_mission(0.5, 1.0).save(path)
        data = json.loads(path.read_text())
        assert data["type"] == "hover"
        assert len(data["waypoints"]) == 1
