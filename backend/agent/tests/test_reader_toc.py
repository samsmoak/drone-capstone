"""Barometer discovery against a TOC shaped like the drone's.

Guards the lab failure of 2026-09-16: a hover was refused with "no known
barometer variables" while the drone listed ``baro.temp`` and ``baro.pressure``.
"""

from __future__ import annotations

import pytest

from cropwatcher.telemetry.reader import (
    BarometerNotFound,
    detect_baro_vars,
    has_log_variable,
)
from tests.fakes import LAB_DRONE_LOG, fake_scf


class TestHasLogVariable:
    def test_finds_a_variable_by_group_and_name(self):
        scf = fake_scf(LAB_DRONE_LOG)
        assert has_log_variable(scf, "baro.temp")

    def test_a_group_name_alone_is_not_a_variable(self):
        scf = fake_scf(LAB_DRONE_LOG)
        assert not has_log_variable(scf, "baro")

    def test_missing_group_is_false_not_an_error(self):
        scf = fake_scf(LAB_DRONE_LOG)
        assert not has_log_variable(scf, "bmp388.temp")


class TestDetectBaroVars:
    def test_the_lab_drone_firmware(self):
        assert detect_baro_vars(fake_scf(LAB_DRONE_LOG)) == ("baro.temp", "baro.pressure")

    def test_older_firmware_group_name(self):
        scf = fake_scf({"bmp388.temp": "float", "bmp388.pressure": "float"})
        assert detect_baro_vars(scf) == ("bmp388.temp", "bmp388.pressure")

    def test_needs_both_temperature_and_pressure(self):
        scf = fake_scf({"baro.temp": "float", "bmp3.pressure": "float"})
        with pytest.raises(BarometerNotFound):
            detect_baro_vars(scf)

    def test_no_barometer_at_all(self):
        with pytest.raises(BarometerNotFound):
            detect_baro_vars(fake_scf({"pm.vbat": "float"}))
