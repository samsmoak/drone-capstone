"""Why no drone answered — and, on Windows, whether the radio has its driver.

cflib opens the Crazyradio through libusb0 (the libusb-win32 driver) on
Windows, which Windows never installs by itself. Before this, a dongle with no
driver was reported as "No Crazyradio found. Plug the dongle in" — to someone
looking at the dongle, plugged in.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from cropwatcher.flight import radio


@pytest.fixture
def fake_libusb0(monkeypatch):
    """Install a fake `usb.backend.libusb0` and `usb.core.find`.

    Returns a setter: (backend, devices) — backend None means libusb0.dll is
    absent, i.e. libusb-win32 was never installed.
    """
    import usb.backend
    import usb.core

    module = ModuleType("usb.backend.libusb0")
    state = SimpleNamespace(backend=None, devices=[])
    module.get_backend = lambda: state.backend  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "usb.backend.libusb0", module)
    monkeypatch.setattr(usb.backend, "libusb0", module, raising=False)
    monkeypatch.setattr(usb.core, "find", lambda **kw: iter(state.devices))

    def configure(backend, devices):
        state.backend, state.devices = backend, devices
    return configure


class TestWindowsDriver:
    def test_not_windows_has_no_driver_problem(self):
        assert radio.windows_driver_problem(windows=False) is None

    def test_no_libusb0_means_the_driver_was_never_installed(self, fake_libusb0):
        fake_libusb0(None, [])
        assert radio.windows_driver_problem(windows=True) == radio.NO_DRIVER

    def test_libusb0_that_cannot_see_the_dongle_means_the_wrong_driver(self, fake_libusb0):
        """libusb-win32 is installed (for something), but the dongle is bound
        to another driver — WinUSB, from choosing the wrong entry in Zadig."""
        fake_libusb0(object(), [])
        assert radio.windows_driver_problem(windows=True) == radio.WRONG_DRIVER

    def test_libusb0_that_sees_the_dongle_is_fine(self, fake_libusb0):
        fake_libusb0(object(), [object()])
        assert radio.windows_driver_problem(windows=True) is None

    def test_the_messages_name_the_tool_and_the_driver(self):
        for message in (radio.NO_DRIVER, radio.WRONG_DRIVER):
            assert "Zadig" in message and "libusb-win32" in message
            assert len(message) < 120        # on screen whenever the drone is off


class TestNothingFound:
    def test_a_dongle_with_no_driver_says_so_before_anything_else(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: True)
        monkeypatch.setattr(radio, "windows_driver_problem", lambda: radio.NO_DRIVER)
        assert radio.nothing_found_reason() == radio.NO_DRIVER

    def test_a_dongle_with_its_driver_asks_for_the_drone(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: True)
        monkeypatch.setattr(radio, "windows_driver_problem", lambda: None)
        assert radio.nothing_found_reason() == radio.NOT_ANSWERING

    def test_no_dongle_asks_for_the_dongle(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: False)
        assert radio.nothing_found_reason() == radio.NOT_FOUND

    def test_unreadable_usb_keeps_the_old_advice(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: None)
        assert radio.nothing_found_reason() == radio.NOT_FOUND

    def test_the_battery_is_not_blamed_first(self):
        assert "battery" not in radio.NOT_ANSWERING.lower()


class TestUnopenable:
    def test_a_driver_problem_replaces_the_generic_message(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: True)
        monkeypatch.setattr(radio, "windows_driver_problem", lambda: radio.WRONG_DRIVER)
        assert radio.unopenable_reason() == radio.WRONG_DRIVER

    def test_otherwise_the_generic_message_stands(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: False)
        assert "could not be opened" in radio.unopenable_reason()


class TestRadioSeen:
    def test_looks_for_cflibs_exact_ids(self, monkeypatch):
        import usb.core
        asked = {}

        def find(**kw):
            asked.update(kw)
            return iter([object()])
        monkeypatch.setattr(usb.core, "find", find)
        assert radio.radio_seen() is True
        assert asked["idVendor"] == 0x1915 and asked["idProduct"] == 0x7777
        assert asked["backend"] is not None     # the bundled libusb-1.0, not a guess

    def test_a_usb_error_is_unknown_not_absent(self, monkeypatch):
        import usb.core

        def boom(**kw):
            raise OSError("access denied")
        monkeypatch.setattr(usb.core, "find", boom)
        assert radio.radio_seen() is None


class TestLinuxPermission:
    """Linux: the dongle is on the bus, but without Bitcraze's udev rule only
    root may open it. Asked of the device node, never by opening the radio."""

    @pytest.fixture
    def dongle(self, monkeypatch, tmp_path):
        import usb.core

        node = tmp_path / "001-004"
        node.write_bytes(b"")
        device = SimpleNamespace(bus=1, address=4)
        state = SimpleNamespace(devices=[device])
        monkeypatch.setattr(usb.core, "find", lambda **kw: iter(state.devices))
        monkeypatch.setattr(radio, "_usb_node", lambda d: str(node))
        return node, state

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
    def test_a_node_this_user_cannot_open_is_named(self, dongle):
        import os

        node, _ = dongle
        node.chmod(0o444)                                  # read-only: no write, no radio
        if os.access(node, os.W_OK):                        # root ignores modes
            pytest.skip("running as root")
        assert radio.linux_permission_problem(linux=True) == radio.NO_PERMISSION

    def test_a_node_this_user_can_open_is_fine(self, dongle):
        node, _ = dongle
        node.chmod(0o666)
        assert radio.linux_permission_problem(linux=True) is None

    def test_no_dongle_is_not_a_permission_problem(self, dongle):
        _, state = dongle
        state.devices = []
        assert radio.linux_permission_problem(linux=True) is None

    def test_not_linux_has_no_permission_problem(self):
        assert radio.linux_permission_problem(linux=False) is None

    def test_an_unreadable_bus_is_unknown_not_a_problem(self, monkeypatch):
        import usb.core

        def boom(**kw):
            raise OSError("no usbfs")
        monkeypatch.setattr(usb.core, "find", boom)
        assert radio.linux_permission_problem(linux=True) is None

    def test_the_node_path_is_the_kernels(self):
        assert radio._usb_node(SimpleNamespace(bus=3, address=17)) == "/dev/bus/usb/003/017"

    def test_it_comes_before_asking_for_the_drone(self, monkeypatch):
        monkeypatch.setattr(radio, "radio_seen", lambda: True)
        monkeypatch.setattr(radio, "windows_driver_problem", lambda: None)
        monkeypatch.setattr(radio, "linux_permission_problem", lambda: radio.NO_PERMISSION)
        assert radio.nothing_found_reason() == radio.NO_PERMISSION
        assert radio.unopenable_reason() == radio.NO_PERMISSION

    def test_the_message_names_the_fix_and_stays_short(self):
        assert "udev" in radio.NO_PERMISSION and "plugdev" in radio.NO_PERMISSION
        assert len(radio.NO_PERMISSION) < 130
