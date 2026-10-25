"""What the USB bus says about the Crazyradio, when no drone answered.

cflib's scan answers one question — did a drone reply? — and an empty answer
has several causes that need different actions. Blaming the battery for all of
them sent an operator to re-plug a working dongle four times on 2026-09-22,
while the real cause was the desktop app holding the radio: a USB device can
only be claimed by one process, and the second one is simply told "no such
device". So the bus is asked, rather than a cause assumed.

WINDOWS IS DIFFERENT. cflib (0.1.33, drivers/crazyradio.py, `_find_devices`)
opens the radio through libusb0 on Windows — the libusb-win32 driver — and
through the bundled libusb-1.0 everywhere else. Windows does not install
libusb-win32 by itself; it is a one-time step with Zadig (Bitcraze's guide:
DRIVER_GUIDE). Without it the dongle is plugged in, visible, and unusable, and
without this module the operator was told to plug it in.

LINUX needs a udev rule, or only root may open the dongle: it is on the bus,
and the second step of opening it is refused. Bitcraze's rule and the plugdev
group fix it (scripts/lib/radio-access.mjs prints them). The device node says
whether this user may: /dev/bus/usb/BBB/DDD, readable and writable or not.

The question "is the dongle on the bus at all" is asked through the bundled
libusb-1.0 on every OS. On Windows that library lists a device whatever
driver it has, which is what lets "no driver" be told apart from "no dongle".
"""

from __future__ import annotations

import os
import sys

#: The Crazyradio's USB ids — the same pair cflib looks for.
CRAZYRADIO_VENDOR_ID = 0x1915
CRAZYRADIO_PRODUCT_ID = 0x7777

DRIVER_GUIDE = (
    "https://www.bitcraze.io/documentation/repository/crazyradio-firmware/master/"
    "building/usbwindows/"
)

# SHORT, every one: with standby (sessions-and-modes.txt) this line is on
# screen whenever the drone is off.
NO_DRIVER = (
    "Crazyradio found, but Windows has no driver for it. Install libusb-win32 with "
    "Zadig — see the desktop setup guide."
)
WRONG_DRIVER = (
    "Crazyradio found, but it has the wrong Windows driver. In Zadig, choose "
    "libusb-win32 and click Replace Driver."
)
NO_PERMISSION = (
    "Crazyradio found, but this user may not open it. Add Bitcraze's udev rule and the "
    "plugdev group — see the setup guide."
)
# BOTH causes, and NOT the battery first: blaming the battery sent an operator
# to re-plug a working dongle four times while another program held it
# (2026-09-22). The long form, though, blamed "another program" for a drone
# that was simply off (2026-09-24).
NOT_ANSWERING = (
    "No drone answering. Switch it on — or quit any other program using the Crazyradio."
)
NOT_FOUND = "No Crazyradio found. Plug the dongle in, directly rather than through a hub."


def radio_seen() -> bool | None:
    """Is a Crazyradio on the bus, whatever its driver? None when USB cannot be read."""
    try:
        import libusb_package
        import usb.core  # type: ignore[import-untyped]

        backend = libusb_package.get_libusb1_backend()
        if backend is None:
            return None
        found = usb.core.find(find_all=True, idVendor=CRAZYRADIO_VENDOR_ID,
                              idProduct=CRAZYRADIO_PRODUCT_ID, backend=backend)
        return any(True for _ in found)
    except Exception:
        return None


def windows_driver_problem(*, windows: bool | None = None) -> str | None:
    """Why cflib cannot use a dongle that is on the bus — Windows only.

    No libusb0 backend means libusb-win32 was never installed. A backend that
    cannot see the dongle means the dongle is bound to another driver (WinUSB
    is the usual one, from picking the wrong entry in Zadig).
    """
    if not (sys.platform == "win32" if windows is None else windows):
        return None
    try:
        import usb.backend.libusb0 as libusb0  # type: ignore[import-untyped]
        import usb.core

        backend = libusb0.get_backend()
    except Exception:
        backend = None
    if backend is None:
        return NO_DRIVER
    try:
        found = usb.core.find(find_all=True, idVendor=CRAZYRADIO_VENDOR_ID,
                              idProduct=CRAZYRADIO_PRODUCT_ID, backend=backend)
        bound = any(True for _ in found)
    except Exception:
        bound = False
    return None if bound else WRONG_DRIVER


def _usb_node(device: object) -> str:
    """Where Linux exposes a USB device: /dev/bus/usb/<bus>/<address>."""
    return f"/dev/bus/usb/{int(device.bus):03d}/{int(device.address):03d}"  # type: ignore[attr-defined]


def linux_permission_problem(*, linux: bool | None = None) -> str | None:
    """Why this user cannot open a Crazyradio that is plugged in — Linux only.

    Asks the device node, not the device: opening the radio to find out would
    claim it, and it may be in use. None when every dongle found is readable
    and writable here, or when none is found (NOT_FOUND covers that).
    """
    if not (sys.platform.startswith("linux") if linux is None else linux):
        return None
    try:
        import libusb_package
        import usb.core

        backend = libusb_package.get_libusb1_backend()
        if backend is None:
            return None
        devices = list(usb.core.find(find_all=True, idVendor=CRAZYRADIO_VENDOR_ID,
                                     idProduct=CRAZYRADIO_PRODUCT_ID, backend=backend))
    except Exception:
        return None
    for device in devices:
        node = _usb_node(device)
        if os.path.exists(node) and not os.access(node, os.R_OK | os.W_OK):
            return NO_PERMISSION
    return None


def _access_problem() -> str | None:
    """The OS-level reason a dongle on the bus cannot be used, if there is one."""
    return windows_driver_problem() or linux_permission_problem()


def nothing_found_reason() -> str:
    """Why a scan found no drone, checked rather than assumed."""
    if radio_seen():
        return _access_problem() or NOT_ANSWERING
    # Unreadable USB (None) keeps the advice it always had.
    return NOT_FOUND


def unopenable_reason() -> str:
    """Why the radio could not even be opened for a scan."""
    if radio_seen():
        problem = _access_problem()
        if problem:
            return problem
    return (
        "The Crazyradio could not be opened. Is it plugged in, and is no other "
        "program using it?"
    )
