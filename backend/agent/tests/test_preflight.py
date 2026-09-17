"""Preflight gates.

Covers the pure logic only — the hardware paths are marked `hardware` and run
separately. The endurance model in particular is worth pinning: the original
version was linear in duration, which demanded more than 4.2 V for any hold
past about 25 s, a voltage no LiPo can supply.
"""

from __future__ import annotations

import pytest

from cropwatcher.flight.preflight import (
    CRITICAL_VBAT,
    ENDURANCE_AT_FULL_S,
    USABLE_FRACTION,
    VBAT_EMPTY,
    VBAT_FULL,
    estimate_endurance_s,
)


class TestEnduranceModel:
    def test_full_cell_gives_the_rated_endurance(self):
        assert estimate_endurance_s(VBAT_FULL) == pytest.approx(ENDURANCE_AT_FULL_S)

    def test_empty_cell_gives_nothing(self):
        assert estimate_endurance_s(VBAT_EMPTY) == pytest.approx(0.0)

    def test_below_empty_never_goes_negative(self):
        assert estimate_endurance_s(2.5) == 0.0

    def test_endurance_increases_with_voltage(self):
        assert estimate_endurance_s(3.6) < estimate_endurance_s(3.9) < estimate_endurance_s(4.1)

    def test_two_minute_flight_needs_a_well_charged_cell(self):
        """Measured: a part-charged 3.72 V cell could not support 120 s."""
        assert estimate_endurance_s(3.72) * USABLE_FRACTION < 120.0
        assert estimate_endurance_s(VBAT_FULL) * USABLE_FRACTION >= 120.0

    def test_short_hop_fits_on_a_tired_cell(self):
        """A 3 s hop at 3.7 V was flown successfully during bring-up."""
        assert estimate_endurance_s(3.70) * USABLE_FRACTION > 3.0

    def test_model_is_not_linear_in_duration(self):
        """Regression guard. The old rule needed 3.55 + 0.025*secs volts, which
        is over 4.2 V past ~26 s — physically impossible, so long holds were
        refused for the wrong reason."""
        old_rule_required = 3.55 + 0.025 * 120
        assert old_rule_required > VBAT_FULL          # the bug
        assert estimate_endurance_s(VBAT_FULL) * USABLE_FRACTION >= 120.0  # the fix


class TestCriticalVoltage:
    def test_threshold_sits_above_lipo_damage_point(self):
        assert 3.0 <= CRITICAL_VBAT <= 3.2

    def test_threshold_is_below_the_arming_range(self):
        """Auto-land must trigger below arming voltage, or it would fire on
        every takeoff."""
        assert CRITICAL_VBAT < 3.7


@pytest.mark.hardware
class TestAgainstRealDrone:
    """Run with `pytest -m hardware`, a radio plugged in and a drone powered on.

    Never spins a motor: these are the same checks the desktop app runs before
    it asks the operator to confirm the area.
    """

    def test_the_checks_pass_on_a_ready_drone(self):
        from cropwatcher.flight.checks import collect
        from cropwatcher.flight.link import DroneLink

        with DroneLink() as link:
            report = collect(link.checks(), lambda step: print(step.to_dict()))

        assert report.hardware_id.startswith("cf-")
        assert report.vbat > 3.0
        assert report.estimate_spread_m < 0.02
        # The lab crash of 2026-09-16: stations stored is not stations received.
        assert len(report.positioning.usable) >= 2
        assert report.positioning.ready
