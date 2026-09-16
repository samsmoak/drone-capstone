"""Row assembly and unit handling.

The unit tests here guard a specific, invisible class of bug: converting a
*difference* (an offset, a rate of change) as though it were an absolute
temperature. Adding 32 to a delta is wrong and produces plausible-looking
numbers, which is the worst kind of wrong.
"""

from __future__ import annotations

import pytest

from cropwatcher.telemetry.correction import ThermalEngine
from cropwatcher.telemetry.row import TempUnit, build_row, parse_ambient

AMBIENT_C = 22.0
RAW_C = 25.0
PRESSURE = 1013.25


def a_correction():
    engine = ThermalEngine(RAW_C, AMBIENT_C)
    return engine.process(RAW_C, 0, PRESSURE)


def a_row(unit: TempUnit):
    return build_row(
        index=0,
        recorded_at="2026-09-16T12:00:00+00:00",
        flight_id="f1",
        correction=a_correction(),
        battery_v=3.9,
        thrust=0,
        position=(0.1, -0.2, 0.5),
        unit=unit,
    )


class TestUnits:
    def test_celsius_passes_through(self):
        row = a_row(TempUnit.CELSIUS)
        assert row.temp_unit == "C"
        assert row.raw_temp == pytest.approx(RAW_C, abs=0.01)

    def test_fahrenheit_converts_absolutes(self):
        row = a_row(TempUnit.FAHRENHEIT)
        assert row.temp_unit == "F"
        assert row.raw_temp == pytest.approx(77.0, abs=0.01)   # 25 C

    def test_offset_is_scaled_not_shifted(self):
        """A 3 C offset is 5.4 F, not 37.4 F. The +32 must not be applied."""
        c_row = a_row(TempUnit.CELSIUS)
        f_row = a_row(TempUnit.FAHRENHEIT)
        assert c_row.thermal_offset == pytest.approx(3.0, abs=0.01)
        assert f_row.thermal_offset == pytest.approx(5.4, abs=0.01)

    def test_rate_of_change_is_scaled_not_shifted(self):
        f_row = a_row(TempUnit.FAHRENHEIT)
        c_row = a_row(TempUnit.CELSIUS)
        assert f_row.roc_per_s == pytest.approx(c_row.roc_per_s * 9 / 5, abs=1e-9)

    def test_unit_is_recorded_in_every_row(self):
        """A column of temperatures with no unit invalidates the dataset."""
        for unit in (TempUnit.CELSIUS, TempUnit.FAHRENHEIT):
            assert a_row(unit).temp_unit == str(unit)


class TestPosition:
    def test_position_is_stored_as_given(self):
        row = a_row(TempUnit.CELSIUS)
        assert (row.x_m, row.y_m, row.z_m) == pytest.approx((0.1, -0.2, 0.5))


class TestPressure:
    def test_station_pressure_is_the_raw_reading(self):
        """Regression: station pressure was once populated from the sea-level
        value, which is a different quantity entirely."""
        row = a_row(TempUnit.CELSIUS)
        assert row.station_pressure_hpa == pytest.approx(PRESSURE, abs=0.01)

    def test_sea_level_equals_station_at_zero_altitude(self):
        """QFF reduces station pressure to sea level. At a station altitude of
        zero there is nothing to reduce, so the two agree — the engine passes
        0.0 because indoor altitude comes from Lighthouse, not the barometer."""
        row = a_row(TempUnit.CELSIUS)
        assert row.sea_level_pressure_hpa == pytest.approx(
            row.station_pressure_hpa, abs=0.01
        )

    def test_sea_level_exceeds_station_above_ground(self):
        """Higher up, station pressure is lower, so reducing it to sea level
        must increase it."""
        from cropwatcher.telemetry.correction import sea_level_pressure

        assert sea_level_pressure(900.0, 15.0, 1000.0) > 900.0


class TestParseAmbient:
    @pytest.mark.parametrize(
        "text,celsius,unit",
        [
            ("74F", 23.333, TempUnit.FAHRENHEIT),
            ("22C", 22.0, TempUnit.CELSIUS),
            ("  74f  ", 23.333, TempUnit.FAHRENHEIT),
            ("22", 22.0, TempUnit.CELSIUS),
            ("72°F", 22.222, TempUnit.FAHRENHEIT),
        ],
    )
    def test_accepts_expected_forms(self, text, celsius, unit):
        c, u = parse_ambient(text)
        assert c == pytest.approx(celsius, abs=0.01)
        assert u is unit

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="required"):
            parse_ambient("   ")

    def test_rejects_implausible_values(self):
        """Catches the operator typing 22F when they meant 22C."""
        with pytest.raises(ValueError, match="plausible"):
            parse_ambient("500C")
        with pytest.raises(ValueError, match="plausible"):
            parse_ambient("-100C")

    def test_rejects_nonsense(self):
        with pytest.raises(ValueError):
            parse_ambient("warm")


class TestSerialisation:
    def test_to_dict_is_flat_and_complete(self):
        d = a_row(TempUnit.CELSIUS).to_dict()
        assert all(not isinstance(v, dict) for v in d.values())
        for required in ("index", "recorded_at", "temp_unit", "corrected_temp", "z_m"):
            assert required in d
