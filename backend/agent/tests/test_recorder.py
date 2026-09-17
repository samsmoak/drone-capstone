"""FlightRecorder: rows from the shared stream, ground-relative, sensors included."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from cropwatcher.telemetry.reader import FlightRecorder, RecorderError, stream_variables_for
from cropwatcher.telemetry.row import TempUnit
from cropwatcher.telemetry.stream import ALL_VARIABLES, Snapshot
from tests.fakes import fake_scf


class FakeStream:
    def __init__(self, values=None):
        self.values = values or {}
        self.subscribers = []

    def snapshot(self):
        return Snapshot(MappingProxyType(dict(self.values)), updated_at=1.0)

    def subscribe(self, cb):
        self.subscribers.append(cb)
        return lambda: self.subscribers.remove(cb)

    def emit(self, **values):
        self.values |= {k.replace("__", "."): v for k, v in values.items()}
        for cb in list(self.subscribers):
            cb(self.snapshot())


class ListSink:
    def __init__(self):
        self.rows = []
        self.closed = False

    def write(self, row):
        self.rows.append(row)

    def close(self):
        self.closed = True


FULL = {
    "baro.temp": 30.0, "baro.pressure": 1013.0, "pm.vbat": 3.95, "stabilizer.thrust": 38000.0,
    "stateEstimate.x": 0.1, "stateEstimate.y": -0.2, "stateEstimate.z": 1.30,
    "stateEstimate.vz": 0.02, "motor.m1": 41000.0, "acc.z": 1.0, "lighthouse.bsReceive": 0b11,
}


def recorder(stream, sink, **kw):
    return FlightRecorder(stream, sink, ambient_c=22.0, unit=TempUnit.CELSIUS,
                          ground_z=1.0, flight_id="f-1", **kw)


class TestRecorder:
    def test_refuses_to_start_without_a_barometer_reading(self):
        with pytest.raises(RecorderError, match="barometer"):
            recorder(FakeStream({}), ListSink())

    def test_writes_ground_relative_rows_with_sensors(self):
        stream, sink = FakeStream({"baro.temp": 30.0}), ListSink()
        rec = recorder(stream, sink)
        rec.start()
        stream.emit(**{k.replace(".", "__"): v for k, v in FULL.items()})

        row = sink.rows[0]
        assert row["z_m"] == pytest.approx(0.30)       # 1.30 estimate − 1.0 ground
        assert row["flight_id"] == "f-1" and row["index"] == 0
        assert row["motor_m1"] == 41000 and isinstance(row["motor_m1"], int)
        assert row["vz_m_s"] == 0.02 and row["lighthouse_received"] == 2
        assert row["thrust"] == 38000

    def test_incomplete_first_samples_are_skipped_not_half_written(self):
        stream, sink = FakeStream({"baro.temp": 30.0}), ListSink()
        rec = recorder(stream, sink)
        rec.start()
        stream.emit(stateEstimate__x=0.1)
        assert sink.rows == []

    def test_indexes_are_consecutive(self):
        stream, sink = FakeStream({"baro.temp": 30.0}), ListSink()
        rec = recorder(stream, sink)
        rec.start()
        for _ in range(3):
            stream.emit(**{k.replace(".", "__"): v for k, v in FULL.items()})
        assert [r["index"] for r in sink.rows] == [0, 1, 2]
        assert rec.rows_written == 3

    def test_stop_unsubscribes_and_closes(self):
        stream, sink = FakeStream({"baro.temp": 30.0}), ListSink()
        rec = recorder(stream, sink)
        rec.start()
        rec.stop()
        stream.emit(**{k.replace(".", "__"): v for k, v in FULL.items()})
        assert sink.rows == [] and sink.closed

    def test_a_failing_sink_does_not_stop_recording(self):
        stream = FakeStream({"baro.temp": 30.0})

        class Broken(ListSink):
            def write(self, row):
                raise OSError("disk full")

        seen = []
        rec = recorder(stream, Broken(), on_row=seen.append)
        rec.start()
        stream.emit(**{k.replace(".", "__"): v for k, v in FULL.items()})
        assert len(seen) == 1


class TestStreamVariables:
    def test_lab_firmware_keeps_baro_names(self):
        scf = fake_scf({"baro.temp": "float", "baro.pressure": "float"})
        assert stream_variables_for(scf) == ALL_VARIABLES

    def test_older_firmware_names_are_swapped_in(self):
        scf = fake_scf({"bmp388.temp": "float", "bmp388.pressure": "float"})
        names = stream_variables_for(scf)
        assert "bmp388.temp" in names and "baro.temp" not in names
