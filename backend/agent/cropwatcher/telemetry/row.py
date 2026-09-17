"""The telemetry row.

One schema, shared by the CSV file and the Postgres table, so the two can never
drift apart. The previous project defined its CSV columns in one place and its
API payload in another; adding a field meant remembering both.

**Temperatures are stored in the unit the operator chose at launch**, and that
unit is recorded in every row. A column of numbers with no unit is the kind of
thing that silently invalidates a dataset — the original project inferred it
from a launch prompt and never wrote it down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from cropwatcher.telemetry.correction import CorrectionResult, c_to_f


class TempUnit(StrEnum):
    CELSIUS = "C"
    FAHRENHEIT = "F"


@dataclass(frozen=True)
class TelemetryRow:
    """One sample. Distances metres, pressure hPa, temperatures in `temp_unit`."""

    # Identity and timing
    index: int
    recorded_at: str                  # ISO-8601 UTC
    flight_id: str | None

    # Correction engine state, for explaining a reading after the fact
    mode: str
    thermal_state: str
    event: str

    # Temperature, in temp_unit
    temp_unit: str
    raw_temp: float
    corrected_temp: float
    expected_raw: float
    deviation: float
    thermal_offset: float
    ambient_est: float
    roc_per_s: float

    # Pressure and derived environment
    station_pressure_hpa: float
    sea_level_pressure_hpa: float
    air_density_kg_m3: float
    pressure_altitude_m: float

    # Flight context
    battery_v: float
    thrust: int

    # Position, metres. Relative to the ground reference captured at takeoff —
    # NOT raw lighthouse z, whose origin is wherever the rig was calibrated.
    x_m: float
    y_m: float
    z_m: float

    # Live sensor data shown in the desktop app's windows, stored so the web's
    # history holds what the operator saw. None when this firmware does not
    # publish the variable.
    vx_m_s: float | None = None
    vy_m_s: float | None = None
    vz_m_s: float | None = None
    roll_deg: float | None = None
    pitch_deg: float | None = None
    yaw_deg: float | None = None
    acc_x_g: float | None = None
    acc_y_g: float | None = None
    acc_z_g: float | None = None
    gyro_x_deg_s: float | None = None
    gyro_y_deg_s: float | None = None
    gyro_z_deg_s: float | None = None
    motor_m1: int | None = None
    motor_m2: int | None = None
    motor_m3: int | None = None
    motor_m4: int | None = None
    lighthouse_received: int | None = None      # count of base stations received

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_row(
    *,
    index: int,
    recorded_at: str,
    flight_id: str | None,
    correction: CorrectionResult,
    battery_v: float,
    thrust: int,
    position: tuple[float, float, float],
    unit: TempUnit,
    sensors: Mapping[str, float] | None = None,
) -> TelemetryRow:
    """Assemble a row, converting temperatures into the operator's unit.

    Conversion happens here and nowhere else: the correction engine works
    entirely in Celsius, and the unit is a presentation concern applied once at
    the boundary.
    """
    conv = (lambda c: c) if unit is TempUnit.CELSIUS else c_to_f

    # A rate of change and an offset are *differences*, so they scale by 9/5
    # but must not take the +32. Converting them like absolute temperatures is
    # an easy and invisible mistake.
    delta = (lambda c: c) if unit is TempUnit.CELSIUS else (lambda c: c * 9.0 / 5.0)

    x, y, z = position
    return TelemetryRow(
        index=index,
        recorded_at=recorded_at,
        flight_id=flight_id,
        mode=str(correction.mode),
        thermal_state=str(correction.state),
        event=correction.event,
        temp_unit=str(unit),
        raw_temp=conv(correction.raw_temp_c),
        corrected_temp=conv(correction.corrected_temp_c),
        expected_raw=conv(correction.expected_raw_c),
        deviation=delta(correction.deviation_c),
        thermal_offset=delta(correction.thermal_offset_c),
        ambient_est=conv(correction.ambient_est_c),
        roc_per_s=delta(correction.roc_c_per_s),
        station_pressure_hpa=correction.station_pressure_hpa,
        sea_level_pressure_hpa=correction.sea_level_pressure_hpa,
        air_density_kg_m3=correction.air_density_kg_m3,
        pressure_altitude_m=correction.absolute_altitude_m,
        battery_v=battery_v,
        thrust=thrust,
        x_m=x,
        y_m=y,
        z_m=z,
        **_sensor_columns(sensors or {}),
    )


# Stream variable → row column. One mapping, so the CSV header, the Postgres
# columns and the live windows all use the same names for the same readings.
SENSOR_COLUMNS: dict[str, str] = {
    "stateEstimate.vx": "vx_m_s", "stateEstimate.vy": "vy_m_s", "stateEstimate.vz": "vz_m_s",
    "stabilizer.roll": "roll_deg", "stabilizer.pitch": "pitch_deg", "stabilizer.yaw": "yaw_deg",
    "acc.x": "acc_x_g", "acc.y": "acc_y_g", "acc.z": "acc_z_g",
    "gyro.x": "gyro_x_deg_s", "gyro.y": "gyro_y_deg_s", "gyro.z": "gyro_z_deg_s",
    "motor.m1": "motor_m1", "motor.m2": "motor_m2", "motor.m3": "motor_m3", "motor.m4": "motor_m4",
}
_INT_COLUMNS = {"motor_m1", "motor_m2", "motor_m3", "motor_m4"}


def _sensor_columns(sensors: Mapping[str, float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variable, column in SENSOR_COLUMNS.items():
        value = sensors.get(variable)
        if value is not None:
            out[column] = int(value) if column in _INT_COLUMNS else float(value)
    received = sensors.get("lighthouse.bsReceive")
    if received is not None:
        out["lighthouse_received"] = bin(int(received)).count("1")
    return out


def parse_ambient(text: str) -> tuple[float, TempUnit]:
    """Parse an operator-entered ambient temperature such as ``74F`` or ``22C``.

    Returns Celsius plus the unit the operator used, which then governs how
    every temperature column in that flight is stored.
    """
    cleaned = text.strip().upper().replace("°", "")
    if not cleaned:
        raise ValueError("ambient temperature is required")

    if cleaned.endswith("F"):
        unit = TempUnit.FAHRENHEIT
        value = float(cleaned[:-1])
        celsius = (value - 32.0) * 5.0 / 9.0
    elif cleaned.endswith("C"):
        unit = TempUnit.CELSIUS
        celsius = float(cleaned[:-1])
    else:
        # No suffix: assume Celsius, the engine's native unit.
        unit = TempUnit.CELSIUS
        celsius = float(cleaned)

    if not -50.0 <= celsius <= 60.0:
        raise ValueError(f"ambient {celsius:.1f}C is outside any plausible greenhouse")

    return celsius, unit
