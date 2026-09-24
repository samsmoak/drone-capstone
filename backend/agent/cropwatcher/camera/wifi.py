"""Put the AI deck on the operator's Wi-Fi, over the radio.

WHY. The deck's camera streams over Wi-Fi. Out of the box the deck raises its
own access point, and a laptop joined to it has no internet — so it cannot sync
to Supabase and the operator cannot stream and upload at once. Joining the deck
to the network the laptop is ALREADY on removes the switch entirely.

HOW. The drone runs the drone_wifi app (firmware/drone-wifi), which accepts
the network name and password on the CRTP app channel and forwards them to the
deck's ESP32 — the same three CPX commands stock firmware sends at boot from
compiled-in credentials. The deck's new IP is not sent back on the app channel:
the stock CPX task prints "WiFi connected to ip: a.b.c.d" to the drone's
console, and that line is what is read here.

WHAT THE DECK CANNOT JOIN, and this module refuses up front rather than letting
the operator wait: a name over 32 bytes, a password of 1-7 or over 63
characters (WPA2-Personal's own limits). It cannot tell from here whether a
network is 5 GHz-only or enterprise — the desktop's network list does that.

THE PASSWORD. Held in memory for the life of the agent, sent over the radio,
never written to disk, never logged, never returned by any route. The radio
link is not encrypted: this is a network for the drone, not a home network.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

CMD_SSID = 0x01
CMD_KEY = 0x02
CMD_APPLY = 0x03
CMD_STATUS = 0x04

CODE_OK = 0
CODE_BAD_REQUEST = 1
CODE_ALREADY_APPLIED = 2
CODE_TOO_EARLY = 3

#: CRTP app-channel payload limit (APPCHANNEL_MTU in the firmware).
MTU = 30
#: Header bytes in a chunk packet: command, offset.
_CHUNK = MTU - 2

SSID_MAX = 32
KEY_MIN, KEY_MAX = 8, 63

#: How long to wait for the drone_wifi app to answer one packet. Stock firmware
#: has no app and never answers, which is the signature of "not flashed".
REPLY_TIMEOUT_S = 1.5
#: The firmware refuses an apply in its first 8 s (the GAP8 raises its own
#: access point at 2 s and would override it). Retry within this window.
EARLY_RETRY_S = 12.0
#: How long the deck gets to join and report an address.
JOIN_TIMEOUT_S = 30.0
#: The ESP32 logs a disconnect on every failed attempt and retries forever. This
#: many in a row with no address is a wrong password or an out-of-range network.
MAX_DISCONNECTS = 4

_IP = re.compile(r"WiFi connected to ip: (\d{1,3}(?:\.\d{1,3}){3})")
_DISCONNECT = "Disconnected from access point"


class WifiError(ValueError):
    """The credentials cannot work, before anything is sent."""


class Phase(StrEnum):
    NOT_SET = "not-set"          # no network given to the agent yet
    WAITING = "waiting"          # a network is set; no drone link yet
    SENDING = "sending"          # talking to the drone_wifi app
    JOINING = "joining"          # the deck is associating
    JOINED = "joined"            # the deck has an address
    FAILED = "failed"            # this attempt did not work; `message` says why


@dataclass
class WifiState:
    ssid: str | None = None
    phase: Phase = Phase.NOT_SET
    ip: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ssid": self.ssid, "phase": str(self.phase), "ip": self.ip,
                "message": self.message}


def validate(ssid: str, password: str) -> tuple[bytes, bytes]:
    """The credentials as the firmware will receive them, or WifiError."""
    name = ssid.encode("utf-8")
    if not 1 <= len(name) <= SSID_MAX:
        raise WifiError("A Wi-Fi network name is 1 to 32 bytes.")
    key = password.encode("utf-8")
    if key and not KEY_MIN <= len(key) <= KEY_MAX:
        raise WifiError("A Wi-Fi password is 8 to 63 characters, or empty for an "
                        "open network.")
    return name, key


def packets(name: bytes, key: bytes) -> list[bytes]:
    """Every app-channel packet for one apply, in order."""
    out: list[bytes] = []
    for cmd, value in ((CMD_SSID, name), (CMD_KEY, key)):
        for off in range(0, len(value), _CHUNK):
            out.append(bytes([cmd, off]) + value[off:off + _CHUNK])
    out.append(bytes([CMD_APPLY, len(name), len(key)]))
    return out


class ConsoleWatch:
    """Reassemble the drone's console into lines and pick out the deck's news.

    cflib delivers the console in arbitrary fragments, so a line is only
    matched once it is complete.
    """

    def __init__(self) -> None:
        self._buf = ""
        self.ip: str | None = None
        self.disconnects = 0
        self.changed = threading.Event()

    def feed(self, text: str) -> None:
        self._buf += text
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            match = _IP.search(line)
            if match:
                self.ip = match.group(1)
                self.changed.set()
            elif _DISCONNECT in line:
                self.disconnects += 1
                self.changed.set()


@dataclass
class _Credentials:
    ssid: str
    name: bytes
    key: bytes = field(repr=False)


class DeckWifi:
    """The operator's chosen network, and putting the deck on it.

    `configure` stores the network (from the desktop, which keeps it in the
    operating system's secure store). `apply` runs once per drone link, on a
    worker thread, after the checks have passed.
    """

    def __init__(
        self,
        on_change: Callable[[WifiState], None] = lambda _s: None,
        on_ip: Callable[[str], None] = lambda _ip: None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._lock = threading.Lock()
        self._creds: _Credentials | None = None
        self._state = WifiState()
        #: The last network the deck joined and its address. Kept apart from the
        #: live state, which "sending" overwrites before the drone can say it
        #: already applied this network in the same power-on.
        self._joined: tuple[str, str] | None = None
        self._on_change = on_change
        self._on_ip = on_ip
        self._clock = clock
        self._sleep = sleep

    def state(self) -> WifiState:
        with self._lock:
            return WifiState(**vars(self._state))

    def configure(self, ssid: str, password: str) -> WifiState:
        name, key = validate(ssid, password)
        with self._lock:
            self._creds = _Credentials(ssid=ssid, name=name, key=key)
            self._state = WifiState(ssid=ssid, phase=Phase.WAITING,
                                    message="Sent to the drone when it next connects.")
        self._changed()
        return self.state()

    def forget(self) -> WifiState:
        with self._lock:
            self._creds = None
            self._joined = None
            self._state = WifiState()
        self._changed()
        return self.state()

    def apply(self, cf: Any) -> WifiState:
        """Send the network to the drone and wait for the deck's address.

        Never raises: every outcome ends in a state the window can show.
        """
        with self._lock:
            creds = self._creds
        if creds is None:
            return self.state()

        replies: list[bytes] = []
        got_reply = threading.Event()
        watch = ConsoleWatch()

        def on_packet(data: bytes) -> None:
            replies.append(bytes(data))
            got_reply.set()

        cf.appchannel.packet_received.add_callback(on_packet)
        cf.console.receivedChar.add_callback(watch.feed)
        try:
            self._set(Phase.SENDING, creds.ssid, message="Sending the network to the drone…")
            outcome = self._send(cf, creds, replies, got_reply)
            if outcome is not None:
                return outcome
            return self._await_join(creds, watch)
        finally:
            cf.appchannel.packet_received.remove_callback(on_packet)
            cf.console.receivedChar.remove_callback(watch.feed)

    # ── the exchange ─────────────────────────────────────────────────────

    def _send(self, cf: Any, creds: _Credentials, replies: list[bytes],
              got_reply: threading.Event) -> WifiState | None:
        """Every packet, each acknowledged. None means go on and wait to join."""
        def exchange(pkt: bytes) -> tuple[int, int] | None:
            replies.clear()
            got_reply.clear()
            cf.appchannel.send_packet(pkt)
            if not got_reply.wait(REPLY_TIMEOUT_S):
                return None
            reply = replies[-1]
            if len(reply) < 2 or reply[0] != (0x80 | pkt[0]):
                return None
            return reply[1], (reply[2] if len(reply) > 2 else 0)

        if exchange(bytes([CMD_STATUS])) is None:
            return self._set(
                Phase.FAILED, creds.ssid,
                message="The drone's firmware cannot take a Wi-Fi network. Flash it with "
                        "the drone_wifi firmware (docs/features/desktop/drone-wifi.txt).")

        *chunks, apply_pkt = packets(creds.name, creds.key)
        for pkt in chunks:
            answer = exchange(pkt)
            if answer is None or answer[0] != CODE_OK:
                return self._set(Phase.FAILED, creds.ssid,
                                 message="The drone did not accept the network. Try again.")

        deadline = self._clock() + EARLY_RETRY_S
        while True:
            answer = exchange(apply_pkt)
            if answer is None:
                return self._set(Phase.FAILED, creds.ssid,
                                 message="The drone stopped answering. Try again.")
            code = answer[0]
            if code == CODE_OK:
                return None
            if code == CODE_TOO_EARLY and self._clock() < deadline:
                self._sleep(1.0)
                continue
            if code == CODE_ALREADY_APPLIED:
                with self._lock:
                    joined = self._joined
                known = joined[1] if joined is not None and joined[0] == creds.ssid else None
                if known:
                    return self._set(Phase.JOINED, creds.ssid, ip=known,
                                     message=f"On {creds.ssid} at {known}.")
                return self._set(
                    Phase.FAILED, creds.ssid,
                    message="The drone already joined a network since it was switched "
                            "on. Restart the drone to apply this one.")
            return self._set(Phase.FAILED, creds.ssid,
                             message="The drone refused the network's name or password.")

    def _await_join(self, creds: _Credentials, watch: ConsoleWatch) -> WifiState:
        self._set(Phase.JOINING, creds.ssid, message=f"The drone is joining {creds.ssid}…")
        deadline = self._clock() + JOIN_TIMEOUT_S
        while self._clock() < deadline:
            watch.changed.wait(0.5)
            watch.changed.clear()
            if watch.ip is not None:
                with self._lock:
                    self._joined = (creds.ssid, watch.ip)
                self._on_ip(watch.ip)
                return self._set(Phase.JOINED, creds.ssid, ip=watch.ip,
                                 message=f"On {creds.ssid} at {watch.ip}.")
            if watch.disconnects >= MAX_DISCONNECTS:
                break
        return self._set(
            Phase.FAILED, creds.ssid,
            message=f"The drone could not join {creds.ssid}. Check the password, that the "
                    "network is 2.4 GHz and in range, and that it has no sign-in page. "
                    "Then restart the drone to try again.")

    # ── state ────────────────────────────────────────────────────────────

    def _set(self, phase: Phase, ssid: str | None, *, ip: str | None = None,
             message: str | None = None) -> WifiState:
        with self._lock:
            self._state = WifiState(ssid=ssid, phase=phase, ip=ip, message=message)
        self._changed()
        return self.state()

    def _changed(self) -> None:
        try:
            self._on_change(self.state())
        except Exception:
            log.exception("camera wifi listener failed")
