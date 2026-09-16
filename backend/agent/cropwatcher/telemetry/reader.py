"""Reads telemetry off the drone and turns it into rows.

The Crazyflie "log system" is a subscription, not storage: you tell the drone
which variables to send and how often, and it streams them. Nothing is kept on
board. This module is the bridge between that live feed and the sinks.

Barometer variable names differ between firmware builds, so they are discovered
from the drone's own table of contents rather than hardcoded — a name that is
right for one build silently yields no data on another.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from cropwatcher.telemetry.correction import ThermalEngine
from cropwatcher.telemetry.row import TelemetryRow, TempUnit, build_row
from cropwatcher.telemetry.sinks import TelemetrySink, utc_now_iso

log = logging.getLogger(__name__)

SAMPLE_PERIOD_MS = 100          # 10 Hz — plenty for environmental data

# Candidate (temperature, pressure) names, most common first. Different
# firmware builds expose the BMP388 under different group names.
BARO_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("baro.temp", "baro.pressure"),
    ("bmp388.temp", "bmp388.pressure"),
    ("bmp3.temp", "bmp3.pressure"),
)


class BarometerNotFound(RuntimeError):
    pass


def detect_baro_vars(scf: SyncCrazyflie) -> tuple[str, str]:
    """Find this firmware's barometer variable names from the drone's own TOC."""
    toc = scf.cf.log.toc
    for temp_var, press_var in BARO_CANDIDATES:
        if temp_var in toc.toc and press_var in toc.toc:
            log.info("barometer variables: %s / %s", temp_var, press_var)
            return temp_var, press_var

    raise BarometerNotFound(
        f"no known barometer variables in this firmware. Tried: "
        f"{', '.join(t for t, _ in BARO_CANDIDATES)}"
    )


def read_initial(scf: SyncCrazyflie, temp_var: str, press_var: str) -> tuple[float, float]:
    """One reading, to seed the correction engine before flight."""
    from cropwatcher.flight.preflight import sample

    row = sample(scf, [(temp_var, "float"), (press_var, "float")], n=3)[-1]
    return row[temp_var], row[press_var]


class TelemetryReader:
    """Streams telemetry into a sink for the duration of a flight.

    Start it before takeoff and stop it after landing, so the log captures the
    full flight context — the original project deliberately recorded before,
    during and through landing, and the correction engine needs the idle
    samples either side to track its offset.
    """

    def __init__(
        self,
        scf: SyncCrazyflie,
        sink: TelemetrySink,
        engine: ThermalEngine,
        *,
        unit: TempUnit,
        ground_z: float,
        flight_id: str | None = None,
        on_row: Callable[[TelemetryRow], None] | None = None,
    ) -> None:
        self._scf = scf
        self._sink = sink
        self._engine = engine
        self._unit = unit
        self._ground_z = ground_z
        self._flight_id = flight_id
        self._on_row = on_row

        self._temp_var, self._press_var = detect_baro_vars(scf)
        self._config: LogConfig | None = None
        self._index = 0
        self._lock = threading.Lock()
        self.latest: TelemetryRow | None = None

    def start(self) -> None:
        cfg = LogConfig(name="cropwatcher", period_in_ms=SAMPLE_PERIOD_MS)
        cfg.add_variable(self._temp_var, "float")
        cfg.add_variable(self._press_var, "float")
        cfg.add_variable("pm.vbat", "float")
        cfg.add_variable("stabilizer.thrust", "uint16_t")
        cfg.add_variable("stateEstimate.x", "float")
        cfg.add_variable("stateEstimate.y", "float")
        cfg.add_variable("stateEstimate.z", "float")

        cfg.data_received_cb.add_callback(self._on_data)
        self._scf.cf.log.add_config(cfg)
        cfg.start()
        self._config = cfg
        log.info("telemetry logging started at %d Hz", 1000 // SAMPLE_PERIOD_MS)

    def stop(self) -> None:
        if self._config is not None:
            try:
                self._config.stop()
            except Exception:
                log.debug("log config already stopped")
            self._config = None
        self._sink.close()
        log.info("telemetry logging stopped after %d samples", self._index)

    # ── callback ─────────────────────────────────────────────────────────

    def _on_data(self, _timestamp: int, data: dict, _logconf: LogConfig) -> None:
        # Runs on cflib's callback thread. It must never raise: an exception
        # here kills the log stream silently and the flight keeps going blind.
        try:
            row = self._build(data)
        except Exception:
            log.exception("failed to build telemetry row, dropping sample")
            return

        with self._lock:
            self.latest = row

        try:
            self._sink.write(row.to_dict())
        except Exception:
            log.exception("sink write failed, continuing")

        if self._on_row is not None:
            try:
                self._on_row(row)
            except Exception:
                log.exception("telemetry callback failed, continuing")

    def _build(self, data: dict) -> TelemetryRow:
        thrust = int(data["stabilizer.thrust"])
        correction = self._engine.process(
            raw_temp_c=data[self._temp_var],
            thrust=thrust,
            pressure_hpa=data[self._press_var],
        )

        row = build_row(
            index=self._index,
            recorded_at=utc_now_iso(),
            flight_id=self._flight_id,
            correction=correction,
            battery_v=data["pm.vbat"],
            thrust=thrust,
            position=(
                data["stateEstimate.x"],
                data["stateEstimate.y"],
                # Ground-relative, so the stored altitude means what a reader
                # expects it to mean.
                data["stateEstimate.z"] - self._ground_z,
            ),
            unit=self._unit,
        )
        self._index += 1
        return row
