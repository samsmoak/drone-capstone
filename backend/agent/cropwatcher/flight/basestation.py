"""Base station channels, read and set over the station's micro-USB port.

WHY THIS EXISTS (2026-10-05, the lab). With the Lighthouse deck on top, light
reached all four sensors on every sample and station 0's calibration was
decoded from it (lighthouse.bsCalVal 1), yet not one sweep became an angle
(lighthouse.validAngles 0, no sweeps in 8 s). Bitcraze's troubleshooting
guide: "Every V2 base station in the system must be set to a unique
channel" — two on the same channel overlap their sweeps, and channel 0 is
"not supported" by the firmware. The calibration survives that; the angles
do not.

HOW (Bitcraze's own client, cfclient ui/dialogs/basestation_mode_dialog.py,
"Set BS channel"): a SteamVR Base Station 2.0 on USB is a serial console,
vendor 0x28de product 0x2500. "mode" prints "Current mode: N"; "mode N" sets
it; "param save" keeps it over a power cycle. One station at a time, powered
by its own power block AND on the USB cable.

Nothing here touches the drone or the radio.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: Valve's USB ids for the Base Station 2.0's serial console.
VID = 0x28DE
PID = 0x2500
#: The channels the firmware decodes. Bitcraze: "support for V2 base stations
#: ... must use channel 1 and 2" for two stations; 1-16 exist.
CHANNELS = range(1, 17)
#: How long a command is given before its reply is read, as cfclient waits.
SETTLE_S = 1.0
READ_TIMEOUT_S = 0.4


class BaseStationError(RuntimeError):
    """In words the operator can act on."""


@dataclass(frozen=True)
class Station:
    port: str
    serial_number: str | None
    #: None when the station did not answer; 0 is "not supported".
    channel: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"port": self.port, "serial_number": self.serial_number,
                "channel": self.channel,
                "supported": self.channel is not None and self.channel in CHANNELS}


#: (port, lines to send, seconds to wait after each) -> every line it printed.
Talk = Callable[[str, list[str], float], list[str]]


def _talk(port: str, lines: list[str], wait_s: float) -> list[str]:
    import serial

    try:
        conn = serial.Serial(port, timeout=READ_TIMEOUT_S)
    except serial.SerialException as e:
        raise BaseStationError(
            f"Could not open the base station on {port}: {e}. Unplug its USB cable, "
            f"plug it back in, and try again.") from None
    try:
        for line in lines:
            conn.write(f"\r\n{line}\r\n".encode())
            conn.flush()
            time.sleep(wait_s)
        reply: bytes = conn.read(4096)
        return reply.decode(errors="replace").splitlines()
    finally:
        conn.close()


def _list_ports() -> list[Any]:
    from serial.tools.list_ports import comports

    return list(comports())


def parse_channel(output: list[str]) -> int | None:
    """The last "Current mode: N" the station printed."""
    channel = None
    for line in output:
        line = line.strip()
        if line.startswith("Current mode:"):
            try:
                channel = int(line.split()[2])
            except (IndexError, ValueError):
                continue
    return channel


def find(*, talk: Talk = _talk,
         list_ports: Callable[[], list[Any]] = _list_ports) -> list[Station]:
    """Every base station on USB, with the channel it reports."""
    found = []
    for port in list_ports():
        if getattr(port, "vid", None) != VID or getattr(port, "pid", None) != PID:
            continue
        try:
            channel = parse_channel(talk(port.device, ["mode"], READ_TIMEOUT_S))
        except BaseStationError:
            channel = None
        found.append(Station(port.device, getattr(port, "serial_number", None), channel))
    return found


def set_channel(port: str, channel: int, *, talk: Talk = _talk) -> int:
    """Set, save, and read back. Returns the channel the station confirms."""
    if channel not in CHANNELS:
        raise BaseStationError(f"Channel {channel} is not one the drone decodes: "
                               f"use 1 to 16 — 1 and 2 for a pair.")
    confirmed = parse_channel(talk(port, [f"mode {channel}", "param save", "mode"], SETTLE_S))
    if confirmed != channel:
        raise BaseStationError(
            f"The base station did not confirm channel {channel} (it says "
            f"{confirmed if confirmed is not None else 'nothing'}). Check it is powered by "
            f"its own power block as well as the USB cable, then try again.")
    return confirmed
