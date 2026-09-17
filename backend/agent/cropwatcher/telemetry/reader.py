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

from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from cropwatcher.telemetry.correction import ThermalEngine
from cropwatcher.telemetry.row import TelemetryRow, TempUnit, build_row
from cropwatcher.telemetry.sinks import TelemetrySink, utc_now_iso
from cropwatcher.telemetry.stream import ALL_VARIABLES, Snapshot, TelemetryStream

log = logging.getLogger(__name__)

# Candidate (temperature, pressure) names, most common first. Different
# firmware builds expose the BMP388 under different group names.
BARO_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("baro.temp", "baro.pressure"),
    ("bmp388.temp", "bmp388.pressure"),
    ("bmp3.temp", "bmp3.pressure"),
)


class BarometerNotFound(RuntimeError):
    pass


def has_log_variable(scf: SyncCrazyflie, complete_name: str) -> bool:
    """Whether the drone's firmware publishes this log variable.

    cflib's TOC is ``{group: {name: element}}``. Testing ``"baro.temp" in
    toc.toc`` looks for a *group* called "baro.temp", which never exists — that
    check refused a hover on the lab drone while ``baro.temp`` sat in its TOC.
    """
    group, _, name = complete_name.partition(".")
    return name in scf.cf.log.toc.toc.get(group, {})


def detect_baro_vars(scf: SyncCrazyflie) -> tuple[str, str]:
    """Find this firmware's barometer variable names from the drone's own TOC."""
    for temp_var, press_var in BARO_CANDIDATES:
        if has_log_variable(scf, temp_var) and has_log_variable(scf, press_var):
            log.info("barometer variables: %s / %s", temp_var, press_var)
            return temp_var, press_var

    raise BarometerNotFound(
        f"no known barometer variables in this firmware. Tried: "
        f"{', '.join(t for t, _ in BARO_CANDIDATES)}"
    )


def stream_variables_for(scf: SyncCrazyflie) -> tuple[str, ...]:
    """The stream's variables, with this firmware's barometer names swapped in.

    The stream lists ``baro.temp`` / ``baro.pressure`` (the lab drone's names).
    Older builds publish the same sensor as ``bmp388.*``; without the swap the
    environment window and the CSV would silently have no temperature.
    """
    try:
        temp_var, press_var = detect_baro_vars(scf)
    except BarometerNotFound:
        return ALL_VARIABLES
    swap = {"baro.temp": temp_var, "baro.pressure": press_var}
    return tuple(swap.get(name, name) for name in ALL_VARIABLES)


class RecorderError(RuntimeError):
    """The flight cannot be recorded. Raised before takeoff, never during."""


class FlightRecorder:
    """Turns the live stream into telemetry rows for the duration of a flight.

    A subscriber of the session's one :class:`TelemetryStream` — it opens no
    log subscription of its own. Start it before takeoff and stop it after
    landing: the correction engine needs the idle samples either side of the
    flight, and the original project recorded before, during and through
    landing for the same reason.

    Positions are stored relative to the ground reference captured by the
    checks, so ``z_m`` is height above the floor. Readers must not subtract the
    ground again.
    """

    def __init__(
        self,
        stream: TelemetryStream,
        sink: TelemetrySink,
        *,
        ambient_c: float,
        unit: TempUnit,
        ground_z: float,
        flight_id: str | None,
        temp_var: str = "baro.temp",
        press_var: str = "baro.pressure",
        on_row: Callable[[TelemetryRow], None] | None = None,
    ) -> None:
        self._stream = stream
        self._sink = sink
        self._unit = unit
        self._ground_z = ground_z
        self._flight_id = flight_id
        self._temp_var = temp_var
        self._press_var = press_var
        self._on_row = on_row

        seed = stream.snapshot().get(temp_var)
        if seed is None:
            raise RecorderError(
                f"no barometer reading ({temp_var}) yet — cannot seed the temperature "
                f"correction. Wait for live telemetry before starting the flight."
            )
        self._engine = ThermalEngine(seed, ambient_c)
        self._unsubscribe: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self.rows_written = 0
        self.latest: TelemetryRow | None = None

    def start(self) -> None:
        if self._unsubscribe is None:
            self._unsubscribe = self._stream.subscribe(self._on_snapshot)
            log.info("recording flight %s", self._flight_id)

    def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._sink.close()
        log.info("flight %s recorded: %d rows", self._flight_id, self.rows_written)

    # ── callback ─────────────────────────────────────────────────────────

    def _on_snapshot(self, snap: Snapshot) -> None:
        # cflib's callback thread. Must never raise: an exception here would be
        # swallowed by the stream, but the row it was building is lost.
        try:
            row = self._build(snap)
        except Exception:
            log.exception("failed to build telemetry row, dropping sample")
            return
        if row is None:
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
                log.exception("telemetry row callback failed, continuing")

    def _build(self, snap: Snapshot) -> TelemetryRow | None:
        temp, pressure = snap.get(self._temp_var), snap.get(self._press_var)
        x = snap.get("stateEstimate.x")
        y = snap.get("stateEstimate.y")
        z = snap.get("stateEstimate.z")
        vbat, thrust = snap.get("pm.vbat"), snap.get("stabilizer.thrust")
        # An incomplete first sample, before every block has arrived once.
        if temp is None or pressure is None or vbat is None or thrust is None:
            return None
        if x is None or y is None or z is None:
            return None

        thrust_i = int(thrust)
        correction = self._engine.process(
            raw_temp_c=temp, thrust=thrust_i, pressure_hpa=pressure,
        )
        with self._lock:
            index = self.rows_written
            self.rows_written += 1
        return build_row(
            index=index,
            recorded_at=utc_now_iso(),
            flight_id=self._flight_id,
            correction=correction,
            battery_v=vbat,
            thrust=thrust_i,
            position=(x, y, z - self._ground_z),
            unit=self._unit,
            sensors=snap.values,
        )
