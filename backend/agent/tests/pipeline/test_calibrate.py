"""`cropwatcher calibrate` — the hand-warmer flights measured (story 4.6).

The fixture flight, with a heat source planted at P1 while the drone holds
there: what the sensor saw, whether today's settings find it, and what the
report recommends."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from cropwatcher.pipeline.calibrate import Marked, measure
from cropwatcher.pipeline.sources import LocalFlightSource
from cropwatcher.pipeline.stages.classify import blocks

FIXTURE = Path(__file__).parent / "fixtures" / "data"
FLIGHT = "372bbdc4-d323-42bb-9e6c-29ef02e3794c"


def warm_at(root: Path, point: str, size_c: float) -> None:
    """Add a smooth bump of `size_c` to raw and corrected temperature over the
    readings held at `point` (ramping in and out over 15 readings)."""
    (path,) = (root / "flights" / "2026-09-24").glob("*.csv")
    rows = list(csv.DictReader(path.open()))
    held = [i for i, r in enumerate(rows) if r.get("point_id") == point]
    n = len(held)
    for k, i in enumerate(held):
        lift = size_c * min(k / 15, 1.0, (n - 1 - k) / 15)
        for c in ("raw_temp", "corrected_temp"):
            rows[i][c] = repr(float(rows[i][c]) + lift)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    shutil.copytree(FIXTURE, root)
    return root


def test_a_real_heat_source_is_measured_found_and_graded(data, tmp_path):
    warm_at(data, "P1", 3.0)
    report = measure([Marked(FLIGHT, "P1")], LocalFlightSource(data), tmp_path)
    (p,) = report.points
    assert p.point_id == "P1" and p.readings == 60
    assert p.peak_c == pytest.approx(3.0, abs=0.6)
    assert p.detected and p.severity in ("warning", "critical")
    assert report.normal_wander_c < blocks.MIN_EVENT_C
    assert report.recommended["MIN_EVENT_C"] == blocks.MIN_EVENT_C


def test_a_heat_source_too_weak_to_tell_apart_is_said_so(data, tmp_path):
    warm_at(data, "P1", 0.3)
    report = measure([Marked(FLIGHT, "P1")], LocalFlightSource(data), tmp_path)
    assert not report.points[0].detected
    assert any("too weak or too far" in n for n in report.notes)


def test_a_point_the_flight_did_not_fly_is_refused(data, tmp_path):
    with pytest.raises(ValueError, match="P9"):
        measure([Marked(FLIGHT, "P9")], LocalFlightSource(data), tmp_path)


def test_the_command_prints_and_saves_the_report(data, monkeypatch, capsys):
    from cropwatcher import cli

    warm_at(data, "P1", 3.0)
    monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(data))
    assert cli.main(["calibrate", "--flight", FLIGHT, "--at", "P1"]) == 0
    out = capsys.readouterr().out
    assert "P1" in out and "MIN_EVENT_C" in out and "reviewed pull request" in out
    (saved,) = (data / "calibration").glob("calibration-*.json")
    assert json.loads(saved.read_text())["points"][0]["point_id"] == "P1"
    assert cli.main(["calibrate", "--flight", FLIGHT, "--at", "P1", "--at", "P2"]) == 2
