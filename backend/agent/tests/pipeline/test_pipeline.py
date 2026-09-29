"""Loading a flight, running the stages point by point, surviving a stage that
fails or breaks the contract, and saving the result."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cropwatcher.cli import main
from cropwatcher.pipeline.compose import default_stages
from cropwatcher.pipeline.contracts import (
    ClassifyResult,
    CleanResult,
    ImageVerdict,
    Label,
    ReadingFlag,
    StageError,
)
from cropwatcher.pipeline.runner import run_flight
from cropwatcher.pipeline.sinks import LocalResultSink
from cropwatcher.pipeline.sources import FlightNotFound, LocalFlightSource

FIXTURE = Path(__file__).parent / "fixtures" / "data"
FLIGHT = "372bbdc4-d323-42bb-9e6c-29ef02e3794c"


def run(tmp_path, stages=None):
    return run_flight(FLIGHT, source=LocalFlightSource(FIXTURE),
                      sink=LocalResultSink(tmp_path), stages=stages or default_stages())


class TestLoading:
    def test_readings_group_by_inspection_point(self):
        flight = LocalFlightSource(FIXTURE).load(FLIGHT)
        assert [p.point.id for p in flight.points] == ["P1", "P2", "P3"]
        assert [len(p.readings) for p in flight.points] == [60, 60, 0]
        assert flight.unassigned_readings == 400 - 120
        assert flight.temp_unit == "C"

    def test_frames_are_the_sessions_frames_inside_the_flight_and_at_the_point(self):
        flight = LocalFlightSource(FIXTURE).load(FLIGHT)
        assert [[f.seq for f in p.frames] for p in flight.points] == [[2, 3], [5, 6], []]

    def test_readings_keep_their_numbers_and_their_time(self):
        first = LocalFlightSource(FIXTURE).load(FLIGHT).points[0].readings[0]
        assert first.index == 100
        assert isinstance(first.values["corrected_temp"], float)
        assert "temp_unit" not in first.values and "point_id" not in first.values
        assert first.t_s > 0

    def test_a_flight_that_is_not_here_says_so(self):
        with pytest.raises(FlightNotFound):
            LocalFlightSource(FIXTURE).load("00000000-0000-0000-0000-000000000000")


class TestRunning:
    def test_the_whole_flight_gets_a_result_per_point(self, tmp_path):
        result, where = run(tmp_path)
        assert [p.point_id for p in result.points] == ["P1", "P2", "P3"]
        assert all(p.verdict == "insufficient_data" for p in result.points)
        assert result.stages == {"clean": "stub@0", "enhance": "stub@0",
                                 "classify": "stub@0", "interpret": "labels@1"}
        saved = json.loads(Path(where).read_text())
        assert saved["flight_id"] == FLIGHT
        assert saved["summary"]["_transit"] == {"readings": 280}

    def test_running_again_replaces_the_result(self, tmp_path):
        run(tmp_path)
        _, where = run(tmp_path)
        assert sorted(p.name for p in Path(where).parent.iterdir()) == ["result.json", "work"]

    def test_a_faulty_label_is_an_anomaly_with_its_evidence(self, tmp_path):
        class SaysFaulty:
            name, version = "fake", "1"

            def classify(self, data, clean, enhanced, ctx):
                faulty = Label("faulty", 0.9, "fake@1")
                return ClassifyResult(
                    tuple(ImageVerdict(f.seq, "original", faulty) for f in data.frames),
                    Label("normal", 0.1, "fake@1"), {"temp_max_c": 31.0})

        result, _ = run(tmp_path, replace(default_stages(), classifier=SaysFaulty()))
        p1 = result.points[0]
        assert p1.verdict == "anomaly"
        assert p1.alerts[0].evidence_frames == (2, 3)

    def test_a_failing_stage_is_recorded_and_the_flight_still_finishes(self, tmp_path):
        class Broken:
            name, version = "broken", "1"

            def classify(self, *args):
                raise StageError("the model file is missing")

        result, _ = run(tmp_path, replace(default_stages(), classifier=Broken()))
        assert {(f.point_id, f.stage) for f in result.failures} >= {("P1", "classify")}
        assert "model file is missing" in result.failures[0].reason
        assert len(result.points) == 3

    def test_a_cleaner_that_edits_readings_breaks_the_contract(self, tmp_path):
        class Editor:
            name, version = "editor", "1"

            def clean(self, data, ctx):
                return CleanResult(data.readings[1:], ())

        result, _ = run(tmp_path, replace(default_stages(), cleaner=Editor()))
        assert result.points[0].verdict == "insufficient_data"
        assert "may only flag" in result.failures[0].reason

    def test_a_flagged_reading_is_not_usable(self):
        data = LocalFlightSource(FIXTURE).load(FLIGHT).points[0]
        first = data.readings[0].index
        clean = CleanResult(data.readings, (
            ReadingFlag(first, "corrected_temp", "spike", "a planted spike"),))
        assert not clean.usable(first, "corrected_temp")
        assert clean.usable(first, "raw_temp")


class TestCommand:
    def test_process_fixture_runs_the_whole_pipeline(self, capsys):
        assert main(["process", "--fixture"]) == 0
        out = capsys.readouterr().out
        assert "P1" in out and "insufficient_data" in out and "saved" in out

    def test_process_an_unknown_flight_says_so(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        assert main(["process", "--flight", "nope-nope"]) == 2
        assert "No readings" in capsys.readouterr().out
