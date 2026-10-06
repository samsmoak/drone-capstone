"""A session's own vitals reach the web (sync/samples.py, migration
20261006000013): samples.csv read from a cursor, in batches, a re-sent batch
changing nothing — and a session with no flight is still a record."""

from __future__ import annotations

import csv
from pathlib import Path

from cropwatcher.sync import samples
from cropwatcher.sync.outbox import Kind, Outbox
from cropwatcher.sync.syncer import Syncer
from tests.test_sync import FakeCloud

HEADER = ["recorded_at", "mode", "height_m", "baro.pressure", "baro.temp", "kalman.varPX",
          "kalman.varPY", "kalman.varPZ", "lighthouse.bsCalVal", "lighthouse.bsGeoVal",
          "lighthouse.bsReceive", "pm.vbat", "stateEstimate.x", "stateEstimate.y",
          "stateEstimate.z"]


def write_samples(folder: Path, n: int, *, positioned: bool = True) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    spread = 0.0001 if positioned else 40.0
    known = 1 if positioned else 0
    with (folder / samples.SAMPLES_NAME).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(n):
            w.writerow([f"2026-10-05T08:{i // 60:02d}:{i % 60:02d}+00:00", "auto", "",
                        1013.2, 36.1, spread, spread, spread, known, known, 1, 3.85,
                        0.01 * i, -0.02, 0.0])


class TestTheRows:
    def test_a_row_becomes_the_tables_columns(self, tmp_path):
        write_samples(tmp_path, 1)
        (row,) = next(samples.batches(tmp_path, "s-1", 0))
        assert row["session_id"] == "s-1" and row["seq"] == 1
        assert row["battery_v"] == 3.85 and row["raw_temp"] == 36.1
        assert row["station_pressure_hpa"] == 1013.2
        assert row["x_m"] == 0.0 and row["y_m"] == -0.02 and row["mode"] == "auto"
        assert row["height_m"] is None                  # unknown, not zero
        assert row["values"]["pm.vbat"] == 3.85         # nothing recorded is dropped

    def test_a_drifting_estimate_is_marked_unpositioned(self, tmp_path):
        """No station measured: the x-y is a number, not a place — the web
        draws no path from it."""
        write_samples(tmp_path / "good", 1, positioned=True)
        write_samples(tmp_path / "bad", 1, positioned=False)
        assert next(samples.batches(tmp_path / "good", "s", 0))[0]["positioned"] is True
        assert next(samples.batches(tmp_path / "bad", "s", 0))[0]["positioned"] is False

    def test_batches_start_after_the_cursor(self, tmp_path):
        write_samples(tmp_path, 12)
        got = list(samples.batches(tmp_path, "s", 7, size=3))
        assert [[r["seq"] for r in b] for b in got] == [[8, 9, 10], [11, 12]]

    def test_no_file_is_no_rows(self, tmp_path):
        assert list(samples.batches(tmp_path / "missing", "s", 0)) == []


class TestTheUpload:
    def rig(self, tmp_path):
        outbox = Outbox(tmp_path / "outbox")
        cloud = FakeCloud()
        return outbox, cloud, Syncer(outbox, lambda: cloud, sleep=lambda s: None)

    def test_a_session_with_no_flight_is_uploaded(self, tmp_path):
        outbox, cloud, syncer = self.rig(tmp_path)
        folder = tmp_path / "sessions" / "s-1"
        write_samples(folder, 5)
        outbox.put(Kind.SAMPLES, "s-1", {"session_id": "s-1", "folder": str(folder),
                                         "uploaded_through": 0, "ended": False})
        syncer.sync_once()
        assert sorted(cloud.samples["s-1"]) == [1, 2, 3, 4, 5]
        assert outbox.count_pending(Kind.SAMPLES) == 1   # still open: more will come

    def test_it_resumes_and_finishes_once_the_session_ends(self, tmp_path):
        outbox, cloud, syncer = self.rig(tmp_path)
        folder = tmp_path / "sessions" / "s-1"
        write_samples(folder, 3)
        outbox.put(Kind.SAMPLES, "s-1", {"session_id": "s-1", "folder": str(folder),
                                         "uploaded_through": 0, "ended": False})
        syncer.sync_once()
        write_samples(folder, 6)                        # the session went on
        outbox.update(Kind.SAMPLES, "s-1", lambda p: p.__setitem__("ended", True))
        syncer.sync_once()
        assert sorted(cloud.samples["s-1"]) == [1, 2, 3, 4, 5, 6]
        assert outbox.count_pending(Kind.SAMPLES) == 0

    def test_an_upload_that_fails_keeps_the_rows_for_next_time(self, tmp_path):
        from cropwatcher.sync.cloud import CloudError
        outbox, cloud, syncer = self.rig(tmp_path)
        folder = tmp_path / "sessions" / "s-1"
        write_samples(folder, 2)
        outbox.put(Kind.SAMPLES, "s-1", {"session_id": "s-1", "folder": str(folder),
                                         "uploaded_through": 0, "ended": True})
        cloud.fail_with = CloudError("no session_samples table yet")
        syncer.sync_once()
        assert outbox.count_pending(Kind.SAMPLES) == 1
        cloud.fail_with = None
        syncer.sync_once()
        assert sorted(cloud.samples["s-1"]) == [1, 2] and outbox.count_pending(Kind.SAMPLES) == 0
