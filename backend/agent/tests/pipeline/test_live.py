"""Story 4.9 — a point's verdict while the mission flies: the flight so far,
processed as the drone finishes holding at each inspection point."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from cropwatcher.pipeline.compose import default_stages
from cropwatcher.pipeline.runner import live_path, run_live_point
from cropwatcher.pipeline.sources import LocalFlightSource
from cropwatcher.processing import JobState, ProcessingQueue, job_key

FIXTURE = Path(__file__).parent / "fixtures" / "data"
FLIGHT = "372bbdc4-d323-42bb-9e6c-29ef02e3794c"


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    shutil.copytree(FIXTURE, root)
    return root


class TestTheLivePoint:
    def test_a_point_held_gets_its_verdict_from_the_flight_so_far(self, data, tmp_path):
        out, where = run_live_point(FLIGHT, "P1", source=LocalFlightSource(data),
                                    results_root=tmp_path / "results", stages=default_stages())
        assert where == live_path(tmp_path / "results", FLIGHT, "P1")
        saved = json.loads(where.read_text())
        assert saved == out
        assert out["point_id"] == "P1" and out["readings"] == 60
        assert out["verdict"] in ("normal", "anomaly", "insufficient_data")
        assert isinstance(out["reasons"], list) and out["reasons"]

    def test_a_row_caught_half_written_is_left_out_not_an_error(self, data, tmp_path):
        (csv_path,) = (data / "flights" / "2026-09-24").glob("*.csv")
        text = csv_path.read_text()
        csv_path.write_text(text + text.splitlines()[-1][:40])       # cut off mid-row
        out, _ = run_live_point(FLIGHT, "P1", source=LocalFlightSource(data),
                                results_root=tmp_path / "results", stages=default_stages())
        assert out["point_id"] == "P1"

    def test_a_point_the_mission_does_not_have_is_refused(self, data, tmp_path):
        with pytest.raises(ValueError, match="P9"):
            run_live_point(FLIGHT, "P9", source=LocalFlightSource(data),
                           results_root=tmp_path / "results", stages=default_stages())

    def test_the_command(self, data, monkeypatch, capsys):
        from cropwatcher import cli, paths

        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(data))
        assert cli.main(["process", "--flight", FLIGHT, "--live-point", "P2"]) == 0
        assert live_path(paths.results_dir(), FLIGHT, "P2").exists()
        assert "P2:" in capsys.readouterr().out
        assert cli.main(["process", "--flight", FLIGHT, "--live-point", "../x"]) == 2


def recorder(log: Path, label: str, delay: float = 0.0) -> list[str]:
    return [sys.executable, "-c",
            f"import time; time.sleep({delay}); open({str(log)!r}, 'a').write({label!r} + '\\n')"]


class TestTheQueue:
    def test_a_live_job_needs_a_point_and_only_it_has_one(self):
        queue = ProcessingQueue()
        with pytest.raises(ValueError):
            queue.submit("f-1", kind="live")
        with pytest.raises(ValueError):
            queue.submit("f-1", point_id="P1")

    def test_live_goes_ahead_of_work_already_waiting(self, tmp_path):
        log = tmp_path / "order.txt"
        queue = ProcessingQueue(command=lambda fid: recorder(log, fid, 0.3 if fid == "busy"
                                                             else 0.0),
                                live_command=lambda fid, pid: recorder(log, f"{fid}#{pid}"))
        queue.submit("busy")                 # running when the others arrive
        time.sleep(0.1)
        queue.submit("later")
        queue.submit("air", kind="live", point_id="P1")
        assert queue.wait_idle()
        assert log.read_text().split() == ["busy", "air#P1", "later"]
        assert queue.job(job_key("air", "P1")).state == JobState.DONE
