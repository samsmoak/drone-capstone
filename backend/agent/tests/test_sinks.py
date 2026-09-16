"""Telemetry sinks — with emphasis on the failure paths.

The rule these enforce: a local CSV write is unconditional, and a remote upload
failing must never disturb it. A flight cannot be re-run.
"""

from __future__ import annotations

import csv

from cropwatcher.telemetry.sinks import CsvSink, FanOutSink


def row(i: int) -> dict:
    return {"index": i, "temp_c": 22.0 + i, "z_m": 0.5}


class TestCsvSink:
    def test_writes_header_from_first_row(self, tmp_path):
        sink = CsvSink(root=tmp_path)
        sink.write(row(0))
        sink.close()

        with sink.path.open() as f:
            rows = list(csv.DictReader(f))
        assert list(rows[0].keys()) == ["index", "temp_c", "z_m"]

    def test_writes_every_row(self, tmp_path):
        sink = CsvSink(root=tmp_path)
        for i in range(25):
            sink.write(row(i))
        sink.close()

        with sink.path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 25
        assert rows[24]["index"] == "24"

    def test_rows_survive_without_close(self, tmp_path):
        """Each row is flushed, so a brownout mid-flight cannot cost the tail."""
        sink = CsvSink(root=tmp_path)
        for i in range(5):
            sink.write(row(i))

        with sink.path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 5
        sink.close()

    def test_uses_date_folder(self, tmp_path):
        sink = CsvSink(root=tmp_path)
        sink.close()
        # <root>/<YYYY-MM-DD>/flight_....csv
        assert sink.path.parent.parent == tmp_path
        assert len(sink.path.parent.name) == len("2026-09-16")

    def test_concurrent_flights_do_not_overwrite(self, tmp_path):
        a = CsvSink(root=tmp_path)
        b = CsvSink(root=tmp_path)
        assert a.path != b.path
        a.close()
        b.close()


class ExplodingSink:
    """Stands in for a Supabase sink with no network."""

    def write(self, row):
        raise ConnectionError("network down")

    def close(self):
        raise ConnectionError("network down")


class RecordingSink:
    def __init__(self):
        self.rows = []
        self.closed = False

    def write(self, row):
        self.rows.append(row)

    def close(self):
        self.closed = True


class TestFanOutSink:
    def test_failing_sink_does_not_stop_the_others(self):
        """The whole point: losing the upload must not lose the CSV."""
        good = RecordingSink()
        fan = FanOutSink([ExplodingSink(), good])

        for i in range(3):
            fan.write(row(i))

        assert len(good.rows) == 3

    def test_failing_close_does_not_stop_the_others(self):
        good = RecordingSink()
        FanOutSink([ExplodingSink(), good]).close()
        assert good.closed

    def test_csv_survives_a_dead_remote(self, tmp_path):
        csv_sink = CsvSink(root=tmp_path)
        fan = FanOutSink([csv_sink, ExplodingSink()])

        for i in range(10):
            fan.write(row(i))
        fan.close()

        with csv_sink.path.open() as f:
            assert len(list(csv.DictReader(f))) == 10
