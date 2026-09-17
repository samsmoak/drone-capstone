"""The live telemetry stream: block packing, snapshots, subscribers.

Block layouts are checked against the lab drone's real TOC, captured on
2026-09-16: all 34 variables present, types as the drone reports them.
"""

from __future__ import annotations

import contextlib
import threading

from cropwatcher.telemetry.stream import (
    ALL_VARIABLES,
    CTYPE_BYTES,
    MAX_BLOCK_BYTES,
    TelemetryStream,
    pack_blocks,
)
from tests.fakes import fake_scf, make_toc

# The types the lab drone reported for every stream variable.
LAB_TYPES = {name: "float" for name in ALL_VARIABLES} | {
    "supervisor.info": "uint16_t",
    "pm.state": "int8_t",
    "sys.canfly": "uint8_t",
    "motor.m1": "uint16_t", "motor.m2": "uint16_t",
    "motor.m3": "uint16_t", "motor.m4": "uint16_t",
    "lighthouse.bsReceive": "uint16_t", "lighthouse.bsActive": "uint16_t",
    "lighthouse.bsCalVal": "uint16_t", "lighthouse.bsGeoVal": "uint16_t",
    "lighthouse.bsAvailable": "uint16_t",
}


class FakeLogConfig:
    def __init__(self, name: str, period_ms: int) -> None:
        self.name = name
        self.period_ms = period_ms
        self.variables: list[tuple[str, str]] = []
        self.callbacks: list = []
        self.started = False
        self.data_received_cb = self

    def add_variable(self, name: str, ctype: str) -> None:
        self.variables.append((name, ctype))

    def add_callback(self, cb) -> None:
        self.callbacks.append(cb)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def emit(self, values: dict) -> None:
        for cb in self.callbacks:
            cb(0, values, self)


def lab_scf():
    scf = fake_scf(LAB_TYPES)
    scf.cf.log.configs = []
    scf.cf.log.add_config = scf.cf.log.configs.append
    return scf


def make_stream(clock=lambda: 100.0):
    scf = lab_scf()
    stream = TelemetryStream(scf, clock=clock, log_config_factory=FakeLogConfig)
    stream.start()
    return stream, scf.cf.log.configs


class TestPackBlocks:
    def test_every_block_fits_the_radio_packet(self):
        blocks, missing = pack_blocks(ALL_VARIABLES, make_toc(LAB_TYPES).toc)
        assert missing == []
        for block in blocks:
            assert sum(CTYPE_BYTES[t] for _, t in block) <= MAX_BLOCK_BYTES

    def test_every_variable_is_placed_exactly_once(self):
        blocks, _ = pack_blocks(ALL_VARIABLES, make_toc(LAB_TYPES).toc)
        placed = [name for block in blocks for name, _ in block]
        assert sorted(placed) == sorted(ALL_VARIABLES)

    def test_uses_the_type_the_drone_reports(self):
        blocks, _ = pack_blocks(["pm.state"], make_toc({"pm.state": "int8_t"}).toc)
        assert blocks == [[("pm.state", "int8_t")]]

    def test_variables_missing_from_firmware_are_listed_not_fatal(self):
        blocks, missing = pack_blocks(
            ["pm.vbat", "flow.deltaX"], make_toc({"pm.vbat": "float"}).toc
        )
        assert blocks == [[("pm.vbat", "float")]]
        assert missing == ["flow.deltaX"]

    def test_the_lab_drone_needs_five_blocks(self):
        blocks, _ = pack_blocks(ALL_VARIABLES, make_toc(LAB_TYPES).toc)
        assert len(blocks) == 5


class TestStream:
    def test_starts_one_config_per_block(self):
        stream, configs = make_stream()
        assert len(configs) == len(stream.blocks)
        assert all(c.started for c in configs)

    def test_snapshot_merges_blocks(self):
        stream, configs = make_stream()
        configs[0].emit({"stateEstimate.z": 1.25})
        configs[1].emit({"pm.vbat": 4.01})
        snap = stream.snapshot()
        assert snap.get("stateEstimate.z") == 1.25
        assert snap.get("pm.vbat") == 4.01
        assert snap.updated_at == 100.0

    def test_subscribers_fire_on_the_anchor_block_only(self):
        stream, configs = make_stream()
        seen = []
        stream.subscribe(seen.append)
        configs[1].emit({"pm.vbat": 4.0})
        assert seen == []
        configs[0].emit({"stateEstimate.x": 0.1})
        assert len(seen) == 1

    def test_a_failing_subscriber_does_not_stop_the_others(self):
        stream, configs = make_stream()
        seen = []

        def broken(_snap):
            raise RuntimeError("boom")

        stream.subscribe(broken)
        stream.subscribe(seen.append)
        configs[0].emit({"stateEstimate.x": 0.1})
        assert len(seen) == 1

    def test_unsubscribe(self):
        stream, configs = make_stream()
        seen = []
        unsubscribe = stream.subscribe(seen.append)
        unsubscribe()
        configs[0].emit({"stateEstimate.x": 0.1})
        assert seen == []

    def test_snapshot_is_immutable(self):
        stream, configs = make_stream()
        configs[0].emit({"stateEstimate.x": 0.1})
        snap = stream.snapshot()
        with contextlib.suppress(TypeError):
            snap.values["stateEstimate.x"] = 9.9  # type: ignore[index]
        assert stream.snapshot().get("stateEstimate.x") == 0.1

    def test_age_reports_staleness(self):
        stream, configs = make_stream(clock=lambda: 10.0)
        configs[0].emit({"stateEstimate.x": 0.1})
        age = stream.snapshot().age_s(now=10.7)
        assert age is not None and abs(age - 0.7) < 1e-9

    def test_concurrent_blocks_do_not_lose_updates(self):
        stream, configs = make_stream()

        def pump(config, key):
            for i in range(500):
                config.emit({key: float(i)})

        threads = [
            threading.Thread(target=pump, args=(configs[1], "pm.vbat")),
            threading.Thread(target=pump, args=(configs[2], "baro.temp")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = stream.snapshot()
        assert snap.get("pm.vbat") == 499.0
        assert snap.get("baro.temp") == 499.0

    def test_stop_stops_every_block(self):
        stream, configs = make_stream()
        stream.stop()
        assert not any(c.started for c in configs)
