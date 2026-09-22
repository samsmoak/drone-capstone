"""Flight tuning: read first, scale what the drone reports, restore exactly."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cropwatcher.flight.tuning import (
    BAROMETER_PROFILE,
    BASE_PROFILE,
    MEASURED_HOVER_THRUST,
    FlightTuning,
)
from tests.fakes import make_toc

# This firmware's defaults for the parameters the profiles touch (the names are
# the lab drone's own, from its cached parameter TOC).
# The declared types, from the lab drone's parameter TOC.
TYPES = {"posCtlPid.thrustBase": "uint16_t", "stabilizer.estimator": "uint8_t"}

FIRMWARE = {
    "posCtlPid.thrustBase": "36000",
    "posCtlPid.zKp": "2.0",
    "posCtlPid.zKi": "0.5",
    "velCtlPid.vzKp": "25.0",
    "velCtlPid.vzKi": "15.0",
}


class FakeParam:
    def __init__(self, values: dict[str, str], *, refuse: set[str] = frozenset()):
        self.values = dict(values)
        self.writes: list[tuple[str, str]] = []
        self.refuse = refuse
        self.toc = make_toc({name: TYPES.get(name, "float") for name in values})

    def get_value(self, name: str) -> str:
        return self.values[name]

    def set_value(self, name: str, value: str) -> None:
        if name in self.refuse:
            raise TimeoutError(name)
        self.writes.append((name, value))
        self.values[name] = value


def test_base_profile_sets_the_measured_hover_thrust_as_an_integer():
    param = FakeParam(FIRMWARE)
    applied = FlightTuning(param).apply(BASE_PROFILE)
    assert param.values["posCtlPid.thrustBase"] == str(MEASURED_HOVER_THRUST)
    assert applied[0].before == "36000"


def test_barometer_profile_scales_what_the_drone_reports():
    param = FakeParam(FIRMWARE | {"velCtlPid.vzKp": "20.0"})       # not the default
    FlightTuning(param).apply(BAROMETER_PROFILE)
    assert float(param.values["velCtlPid.vzKp"]) == pytest.approx(20.0 * 0.40)
    assert float(param.values["velCtlPid.vzKi"]) == pytest.approx(15.0 * 0.30)
    assert float(param.values["posCtlPid.zKp"]) == pytest.approx(2.0 * 0.75)


def test_restore_writes_back_the_exact_originals():
    param = FakeParam(FIRMWARE)
    tuning = FlightTuning(param)
    tuning.apply(BASE_PROFILE, BAROMETER_PROFILE)
    assert tuning.active
    tuning.restore()
    assert param.values == FIRMWARE
    assert not tuning.active
    tuning.restore()                                              # safe twice
    assert param.values == FIRMWARE


def test_a_parameter_this_firmware_does_not_publish_is_skipped_not_guessed():
    param = FakeParam({k: v for k, v in FIRMWARE.items() if k != "velCtlPid.vzKi"})
    applied = FlightTuning(param).apply(BAROMETER_PROFILE)
    assert "velCtlPid.vzKi" not in {a.name for a in applied}
    assert "velCtlPid.vzKi" not in param.values


def test_a_refused_write_leaves_that_value_and_carries_on():
    param = FakeParam(FIRMWARE, refuse={"velCtlPid.vzKp"})
    applied = FlightTuning(param).apply(BAROMETER_PROFILE)
    assert param.values["velCtlPid.vzKp"] == "25.0"
    assert {a.name for a in applied} == {"velCtlPid.vzKi", "posCtlPid.zKp", "posCtlPid.zKi"}


def test_no_parameter_store_means_nothing_applied():
    assert FlightTuning(None).apply(BASE_PROFILE) == []


def test_link_applies_both_profiles_on_the_barometer_and_restores_after(monkeypatch):
    from cropwatcher.flight.link import DroneLink
    from tests.test_link import REPORT, FakeStream, make_link

    param = FakeParam(FIRMWARE | {"stabilizer.estimator": "2"})
    link, scf, _ = make_link()
    scf.cf.param = param
    scf.cf.commander = SimpleNamespace()
    scf.cf.high_level_commander = SimpleNamespace()
    link.open()
    monkeypatch.setattr(DroneLink, "_average_z", lambda self, sleep, samples=10: 0.0)
    unassisted = REPORT.__class__(**{**REPORT.__dict__, "assisted": False})
    link.manual(unassisted, sleep=lambda s: None)
    assert {a.name for a in link.tuning_applied} == {
        "posCtlPid.thrustBase", "velCtlPid.vzKp", "velCtlPid.vzKi",
        "posCtlPid.zKp", "posCtlPid.zKi",
    }
    assert param.values["stabilizer.estimator"] == "1"
    link.restore_estimator()
    assert param.values == FIRMWARE | {"stabilizer.estimator": "2"}
    _ = FakeStream


def test_a_float_gain_reported_without_a_decimal_point_keeps_its_fraction():
    param = FakeParam(FIRMWARE | {"posCtlPid.zKp": "2"})
    FlightTuning(param).apply(BAROMETER_PROFILE)
    assert param.values["posCtlPid.zKp"] == "1.5"


class TestTheControllerIsRebuiltNotJustSelected:
    """stabilizer.c re-inits the controller ONLY when the type changes:

        if (controllerGetType() != controllerType) {
            controllerInit(controllerType);
            controllerType = controllerGetType();
        }

    and nowhere else — not on disarm, not when the supervisor stops the
    motors, not between flights. So every PID integrator survives from one
    flight to the next while the drone stays powered, and a crash that
    saturated thrust hands its wind-up to the next takeoff. Writing the value
    it already holds re-inits nothing at all.
    """

    def test_a_controller_already_on_pid_is_still_bounced(self):
        param = FakeParam({"stabilizer.controller": "1", "posCtlPid.thrustBase": "36000"})
        FlightTuning(param).apply(BASE_PROFILE)
        written = [v for n, v in param.writes if n == "stabilizer.controller"]
        assert written == ["2", "1"], "it must change before it can re-init"

    def test_it_ends_on_pid_whatever_it_started_as(self):
        for start in ("1", "2", "3"):
            param = FakeParam({"stabilizer.controller": start,
                               "posCtlPid.thrustBase": "36000"})
            FlightTuning(param).apply(BASE_PROFILE)
            assert param.values["stabilizer.controller"] == "1", f"started at {start}"

    def test_the_bounce_never_lands_on_the_value_it_wants(self):
        """Bouncing through the target would be no change and no re-init."""
        param = FakeParam({"stabilizer.controller": "2", "posCtlPid.thrustBase": "36000"})
        FlightTuning(param).apply(BASE_PROFILE)
        written = [v for n, v in param.writes if n == "stabilizer.controller"]
        assert written[0] != "1"
        assert written[-1] == "1"

    def test_the_original_is_still_what_gets_restored(self):
        """The bounce must not be mistaken for the value the flight found."""
        param = FakeParam({"stabilizer.controller": "2", "posCtlPid.thrustBase": "36000"})
        tuning = FlightTuning(param)
        tuning.apply(BASE_PROFILE)
        tuning.restore()
        assert param.values["stabilizer.controller"] == "2"

    def test_a_refused_bounce_does_not_stop_the_flight(self):
        """Losing the re-init is worth a log line, not a scrubbed flight."""
        param = FakeParam({"stabilizer.controller": "1", "posCtlPid.thrustBase": "36000"},
                          refuse={"stabilizer.controller"})
        applied = FlightTuning(param).apply(BASE_PROFILE)
        assert [a.name for a in applied] == ["posCtlPid.thrustBase"]
