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
the operator wait: a name over 32 bytes; a password of 1-7 characters (WPA2's
minimum) or over 47 — NOT WPA2's 63, because the ESP32 keeps the password in a
50-byte buffer (firmware/drone-wifi/src/wire.h). It cannot tell from here
whether a network is 5 GHz-only or enterprise — the desktop's list does that.

THE PASSWORD. Held in memory for the life of the agent, sent over the radio,
never written to disk, never logged, never returned by any route. The radio
link is not encrypted: this is a network for the drone, not a home network.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CMD_SSID = 0x01
CMD_KEY = 0x02
CMD_APPLY = 0x03
CMD_STATUS = 0x04
#: drone_wifi v4: ask the deck to say its address again (wifi-recovery.patch).
CMD_REPORT = 0x05

CODE_OK = 0
CODE_BAD_REQUEST = 1
CODE_ALREADY_APPLIED = 2
CODE_TOO_EARLY = 3
#: drone_wifi v4 on a deck whose ESP32 cannot report or rejoin (bundle < 2).
CODE_UNSUPPORTED = 4

#: CRTP app-channel payload limit (APPCHANNEL_MTU in the firmware).
MTU = 30
#: Header bytes in a chunk packet: command, offset.
_CHUNK = MTU - 2

SSID_MAX = 32
#: 8 is WPA2's minimum. 47 is the AI deck's ESP32 buffer, not WPA2's 63.
KEY_MIN, KEY_MAX = 8, 47

#: How long to wait for the drone_wifi app to answer one packet. Stock firmware
#: has no app and never answers, which is the signature of "not flashed".
REPLY_TIMEOUT_S = 1.5
#: The firmware refuses an apply in the deck's first 8 s (the GAP8 raises its own
#: access point at 2 s and would override it). Retry within this window.
EARLY_RETRY_S = 14.0
#: How long the deck gets to join and report an address.
JOIN_TIMEOUT_S = 30.0
#: The ESP32 logs a disconnect on every failed attempt and retries forever. This
#: many in a row with no address is a wrong password or an out-of-range network.
MAX_DISCONNECTS = 4
#: How long the deck gets to say its address when asked (CMD_REPORT). It answers
#: at once when it is on the network; silence this long means it is not.
REPORT_WAIT_S = 4.0

_IP = re.compile(r"WiFi connected to ip: (\d{1,3}(?:\.\d{1,3}){3})")
#: The ESP32's own line for the same event (aideck-esp-firmware main/wifi.c).
_GOT_IP = re.compile(r"WIFI: got ip: (\d{1,3}(?:\.\d{1,3}){3})")
_RSSI = re.compile(r"WIFI: rssi: (-?\d+)")
_DISCONNECT = "Disconnected from access point"
#: wifi-recovery.patch adds the reason: "…access point, reason 201".
_REASON = re.compile(r"Disconnected from access point, reason (\d+)|"
                     r"not connected, last reason (\d+)")

#: Why the deck's ESP32 dropped off, in words (ESP-IDF 4.3.1 wifi_err_reason_t,
#: components/esp_wifi/include/esp_wifi_types.h). The ones that tell the
#: operator what to do; anything else is shown by its number.
REASON_WORDS = {
    2: "the network stopped answering it",
    3: "the network turned it away",
    4: "the network stopped answering it",
    8: "it left the network",
    15: "the password was not accepted",
    200: "it lost the signal",
    201: "it cannot find the network — out of range, or not 2.4 GHz",
    202: "the network refused it — a wrong password, or a WPA3-only network",
    203: "the network would not take it — it may limit how many devices join",
    204: "the password was not accepted",
    205: "the connection failed",
}


def reason_words(code: int | None) -> str | None:
    """A disconnect reason in the operator's words, or None when none is known."""
    if code is None or code == 0:
        return None
    return REASON_WORDS.get(code, f"it dropped off (reason {code})")

#: Below this, a 2.4 GHz link from the deck's chip antenna drops out when the
#: drone turns. Measured: joined at -84 dBm and fell off the network minutes
#: later with the laptop, on the same network, still fine (2026-09-24).
WEAK_RSSI_DBM = -75


class WifiError(ValueError):
    """The credentials cannot work, before anything is sent."""


class Phase(StrEnum):
    NOT_SET = "not-set"          # no network given to the agent yet
    WAITING = "waiting"          # a network is set; no drone link yet
    SENDING = "sending"          # talking to the drone_wifi app
    JOINING = "joining"          # the deck is associating
    JOINED = "joined"            # the deck has an address
    RECONNECTING = "reconnecting"  # it had one, dropped off, and is rejoining
    FAILED = "failed"            # this attempt did not work; `message` says why


@dataclass
class WifiState:
    ssid: str | None = None
    phase: Phase = Phase.NOT_SET
    ip: str | None = None
    message: str | None = None
    #: The signal the deck last reported when it joined, in dBm.
    rssi: int | None = None
    #: How many times it has dropped off since it last joined.
    drops: int = 0
    #: The address is REMEMBERED from an earlier join, not heard this link.
    #: On a campus network the deck can be given a new one (roaming, a renewed
    #: lease) without restarting — measured 2026-09-24 — so it is unverified
    #: until the camera reaches it.
    remembered: bool = False
    #: Only a restart of the drone gets it onto this network now: it applied a
    #: network already this power-on and its ESP32 cannot rejoin (a deck
    #: without bundle 2's wifi-recovery.patch).
    needs_restart: bool = False
    #: Why it last dropped off, as the deck said (REASON_WORDS); None if never.
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ssid": self.ssid, "phase": str(self.phase), "ip": self.ip,
                "message": self.message, "rssi": self.rssi, "drops": self.drops,
                "remembered": self.remembered, "needs_restart": self.needs_restart,
                "reason": self.reason}


def validate(ssid: str, password: str) -> tuple[bytes, bytes]:
    """The credentials as the firmware will receive them, or WifiError."""
    name = ssid.encode("utf-8")
    if not 1 <= len(name) <= SSID_MAX:
        raise WifiError("A Wi-Fi network name is 1 to 32 bytes.")
    key = password.encode("utf-8")
    if key and not KEY_MIN <= len(key) <= KEY_MAX:
        raise WifiError("The drone takes a Wi-Fi password of 8 to 47 characters, or "
                        "none for an open network.")
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
        #: The last disconnect reason the deck gave, if it gave one.
        self.reason: int | None = None
        self.changed = threading.Event()

    def feed(self, text: str) -> None:
        self._buf += text
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            match = _IP.search(line) or _GOT_IP.search(line)
            if match:
                self.ip = match.group(1)
                self.changed.set()
                continue
            why = _REASON.search(line)
            if why:
                self.reason = int(why.group(1) or why.group(2))
            if _DISCONNECT in line:
                self.disconnects += 1
                self.changed.set()


def follow_console(cf: Any, on_line: Callable[[str], None]) -> Callable[[], None]:
    """Call `on_line` with each complete line the drone prints, until the
    returned function is called. cflib delivers the console in arbitrary
    fragments, so a line is only passed on once its newline has arrived."""
    buffer = [""]

    def feed(text: str) -> None:
        buffer[0] += text
        *lines, buffer[0] = buffer[0].split("\n")
        for line in lines:
            on_line(line)

    cf.console.receivedChar.add_callback(feed)

    def stop() -> None:
        with contextlib.suppress(Exception):
            cf.console.receivedChar.remove_callback(feed)
    return stop


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
        joined_file: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._creds: _Credentials | None = None
        self._state = WifiState()
        #: The last network the deck joined and its address. Kept apart from the
        #: live state, which "sending" overwrites before the drone can say it
        #: already applied this network in the same power-on.
        #:
        #: ALSO ON DISK (joined_file): the drone refuses a second apply until it
        #: restarts, so an agent that restarted without the drone doing so would
        #: otherwise not know where the camera is. Not secret — a name and an
        #: address — and valid exactly as long as the drone stays on, which is
        #: exactly when the drone answers ALREADY_APPLIED.
        self._joined_file = joined_file
        #: The deck's last reported signal. Kept apart from the state, which
        #: every step rewrites; the signal belongs to the association.
        self._rssi: int | None = None
        self._joined: tuple[str, str] | None = self._load_joined()
        self._on_change = on_change
        self._on_ip = on_ip
        self._clock = clock
        self._sleep = sleep
        #: Why the deck last dropped off (REASON_WORDS key), from its console.
        self._reason: int | None = None
        #: When the phase last changed — how long "joining" has been joining.
        self._phase_since = clock()
        #: One conversation with drone_wifi at a time: an apply from a new link
        #: and a recovery from the watchdog must not interleave their packets.
        self._busy = threading.Lock()

    def phase_age(self) -> float:
        """Seconds the current phase has lasted."""
        with self._lock:
            return self._clock() - self._phase_since

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
            self._state = WifiState()
        self._remember(None)
        self._changed()
        return self.state()

    # ── watching the deck for as long as the drone is connected ──────────

    def watch(self, cf: Any) -> Callable[[], None]:
        """Follow the deck's own Wi-Fi reports on the drone's console until the
        returned function is called (at link-down).

        WHY. Reading the console only while joining left "joined" standing for
        ever: the deck dropped off the network (weak signal) and the page kept
        saying "joined at 100.96.93.94" beside a camera that could not reach it
        (2026-09-24). The ESP32 reports every drop, every new address and its
        signal; now each one updates the state as it happens, and a new address
        moves the camera at once.
        """
        return follow_console(cf, self._console_line)

    def _console_line(self, line: str) -> None:
        gave = _REASON.search(line)
        if gave:
            with self._lock:
                self._reason = int(gave.group(1) or gave.group(2))
        signal = _RSSI.search(line)
        if signal:
            with self._lock:
                self._rssi = int(signal.group(1))
                state = self._state
            if state.phase is Phase.JOINED:
                self._set(Phase.JOINED, state.ssid, ip=state.ip, drops=state.drops,
                          message=self._joined_words(
                              WifiState(ssid=state.ssid, ip=state.ip, rssi=self._rssi)))
            return
        got = _GOT_IP.search(line) or _IP.search(line)
        if got:
            ip = got.group(1)
            with self._lock:
                state = self._state
                ssid = state.ssid or (self._creds.ssid if self._creds else None)
            if state.phase is Phase.JOINED and state.ip == ip:
                return                       # the same news twice (ESP32 and STM32 lines)
            if ssid is not None:
                self._remember((ssid, ip))
            self._on_ip(ip)
            self._set(Phase.JOINED, ssid, ip=ip, drops=state.drops,
                      message=self._joined_words(WifiState(ssid=ssid, ip=ip, rssi=self._rssi)))
            return
        if _DISCONNECT in line:
            with self._lock:
                state = self._state
            if state.phase not in (Phase.JOINED, Phase.RECONNECTING):
                return                       # joining: apply() counts these itself
            drops = state.drops + 1
            rssi = self._rssi
            with self._lock:
                said = reason_words(self._reason)
            weak = rssi is not None and rssi < WEAK_RSSI_DBM
            if said:
                why = f": {said}" + (f" ({rssi} dBm)" if weak else "")
            else:
                why = f" — weak signal ({rssi} dBm)" if weak else ""
            self._set(Phase.RECONNECTING, state.ssid, ip=None, drops=drops,
                      message=f"The drone dropped off {state.ssid}{why}. Rejoining…")

    @staticmethod
    def _joined_words(state: WifiState) -> str:
        signal = ""
        if state.rssi is not None:
            signal = f" · {state.rssi} dBm" + (" (weak)" if state.rssi < WEAK_RSSI_DBM else "")
        return f"On {state.ssid} at {state.ip}{signal}."

    def link_down(self) -> WifiState:
        """The radio link to the drone closed or dropped.

        A "joined" shown after that is a claim nobody can check any more — the
        drone may be off, or restarted onto its own access point. It becomes
        "waiting", naming where it was last. Measured 2026-09-24: with the
        drone's battery flat, the page read "Radio: no drone" beside "On VT Open
        WiFi" — two statements that could not both be true.
        """
        with self._lock:
            state = self._state
            if state.phase not in (Phase.JOINED, Phase.JOINING, Phase.SENDING,
                                   Phase.RECONNECTING):
                return WifiState(**vars(state))
            last = f" Last on {state.ssid} at {state.ip}." if state.ip else ""
            self._state = WifiState(
                ssid=state.ssid, phase=Phase.WAITING, ip=None,
                message=f"Waiting for the drone to connect.{last}")
        self._changed()
        return self.state()

    def apply(self, cf: Any) -> WifiState:
        """Put the deck on the network and wait for its address — the link
        just opened. Never raises: every outcome ends in a state the window
        can show.

        ASK BEFORE JOINING. A drone that already applied a network this
        power-on (the agent restarted, the radio dropped and came back) is
        usually still on it: the deck is ASKED where it is first
        (CMD_REPORT), and only if it does not answer is the network sent
        again. Rejoining a deck that was fine would cost the camera seconds
        of picture for nothing.
        """
        with self._lock:
            creds = self._creds
        if creds is None:
            return self.state()
        if not self._busy.acquire(blocking=False):
            return self.state()                  # another conversation is under way
        try:
            with self._talk(cf) as (exchange, watch):
                self._set(Phase.SENDING, creds.ssid, message="Sending the network to the drone…")
                status = exchange(bytes([CMD_STATUS]))
                if status is None:
                    return self._not_flashed(creds)
                with self._lock:
                    joined = self._joined
                # Asked only when it is THIS network the deck is on: after the
                # operator chose another one, asking would find the deck happy
                # on the old network and never move it.
                if status[1] and joined is not None and joined[0] == creds.ssid:
                    found, _supported = self._ask(exchange, watch, creds)
                    if found is not None:
                        return found
                outcome = self._send(exchange, creds)
                if outcome is not None:
                    return outcome
                return self._await_join(creds, watch)
        finally:
            self._busy.release()

    def recover(self, cf: Any, why: str) -> str:
        """Get the camera back on the network WITHOUT restarting the drone —
        so it works in a session too: nothing here touches the radio link or
        the flight, only the deck's Wi-Fi.

          1. ASK where it is (CMD_REPORT): it may be on the network at a new
             address the agent missed.
          2. Not answering: REJOIN — the network sent again; a deck with
             wifi-recovery.patch rejoins in place.

        Returns what happened: "answered", "rejoined", "failed" (tried, not
        back yet), "unsupported" (firmware older than drone_wifi v4 or deck
        bundle 2 — the caller falls back to restarting the drone),
        "needs_restart", "unreachable" (no answer over the radio), "busy" or
        "no-network".
        """
        with self._lock:
            creds = self._creds
        if creds is None:
            return "no-network"
        if not self._busy.acquire(blocking=False):
            return "busy"
        try:
            with self._talk(cf) as (exchange, watch):
                if exchange(bytes([CMD_STATUS])) is None:
                    return "unreachable"
                with self._lock:
                    drops = self._state.drops
                self._set(Phase.RECONNECTING, creds.ssid, drops=drops,
                          message=f"{why} Asking the drone where its camera is…")
                found, supported = self._ask(exchange, watch, creds)
                if found is not None:
                    log.info("deck recovery: it answered at %s", found.ip)
                    return "answered"
                if not supported:
                    return "unsupported"
                self._set(Phase.RECONNECTING, creds.ssid, drops=drops,
                          message=f"The camera is not on {creds.ssid}. Rejoining it — the "
                                  "drone keeps flying as it is.")
                outcome = self._send(exchange, creds)
                if outcome is not None:
                    return "needs_restart" if (outcome.needs_restart or outcome.remembered) \
                        else "failed"
                joined = self._await_join(creds, watch)
                log.info("deck recovery: rejoin %s", joined.phase)
                return "rejoined" if joined.phase is Phase.JOINED else "failed"
        finally:
            self._busy.release()

    # ── the exchange ─────────────────────────────────────────────────────

    @contextlib.contextmanager
    def _talk(self, cf: Any) -> Any:
        """The app channel and the console, for one conversation. Yields
        (exchange, watch): exchange(pkt) -> (code, applied) or None."""
        replies: list[bytes] = []
        got_reply = threading.Event()
        watch = ConsoleWatch()

        def on_packet(data: bytes) -> None:
            replies.append(bytes(data))
            got_reply.set()

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

        cf.appchannel.packet_received.add_callback(on_packet)
        cf.console.receivedChar.add_callback(watch.feed)
        try:
            yield exchange, watch
        finally:
            cf.appchannel.packet_received.remove_callback(on_packet)
            cf.console.receivedChar.remove_callback(watch.feed)

    def _not_flashed(self, creds: _Credentials) -> WifiState:
        return self._set(
            Phase.FAILED, creds.ssid,
            message="The drone's firmware cannot take a Wi-Fi network. Flash it with "
                    "the drone_wifi firmware (docs/features/desktop/drone-wifi.txt).")

    def _ask(self, exchange: Callable[[bytes], tuple[int, int] | None], watch: ConsoleWatch,
             creds: _Credentials) -> tuple[WifiState | None, bool]:
        """Ask the deck where it is. (JOINED state, True) when it says;
        (None, True) when it was asked and is not on the network; (None, False)
        when this drone or deck cannot be asked (older firmware)."""
        answer = exchange(bytes([CMD_REPORT]))
        if answer is None or answer[0] != CODE_OK:
            return None, False
        deadline = self._clock() + REPORT_WAIT_S
        while self._clock() < deadline:
            watch.changed.wait(0.25)
            watch.changed.clear()
            if watch.ip is not None:
                self._remember((creds.ssid, watch.ip))
                self._on_ip(watch.ip)
                return self._set(Phase.JOINED, creds.ssid, ip=watch.ip,
                                 message=self._joined_words(
                                     WifiState(ssid=creds.ssid, ip=watch.ip,
                                               rssi=self._rssi))), True
        if watch.reason is not None:
            with self._lock:
                self._reason = watch.reason
        return None, True

    def _send(self, exchange: Callable[[bytes], tuple[int, int] | None],
              creds: _Credentials) -> WifiState | None:
        """The network, every packet acknowledged, then apply. None means go
        on and wait to join."""
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
                    self._on_ip(known)
                    return self._set(Phase.JOINED, creds.ssid, ip=known, remembered=True,
                                     message=f"Joined {creds.ssid} earlier, at {known} — "
                                             "checking it is still there.")
                # An older deck (no wifi-recovery.patch) cannot rejoin, and
                # nothing remembered says where it is: only a restart makes it
                # join afresh and say so. On standby the agent does that itself.
                return self._set(
                    Phase.FAILED, creds.ssid, needs_restart=True,
                    message="The drone joined a network earlier and its address is not "
                            "known. It needs a restart to rejoin (its camera software "
                            "predates rejoining — Set up updates it).")
            return self._set(Phase.FAILED, creds.ssid,
                             message="The drone refused the network's name or password.")

    def _await_join(self, creds: _Credentials, watch: ConsoleWatch) -> WifiState:
        self._set(Phase.JOINING, creds.ssid, message=f"The drone is joining {creds.ssid}…")
        deadline = self._clock() + JOIN_TIMEOUT_S
        while self._clock() < deadline:
            watch.changed.wait(0.5)
            watch.changed.clear()
            if watch.ip is not None:
                self._remember((creds.ssid, watch.ip))
                self._on_ip(watch.ip)
                return self._set(Phase.JOINED, creds.ssid, ip=watch.ip,
                                 message=self._joined_words(
                                     WifiState(ssid=creds.ssid, ip=watch.ip, rssi=self._rssi)))
            if watch.reason is not None:
                with self._lock:
                    self._reason = watch.reason
                said = reason_words(watch.reason)
                self._set(Phase.JOINING, creds.ssid,
                          message=f"The drone is joining {creds.ssid} — not yet: {said}.")
            if watch.disconnects >= MAX_DISCONNECTS:
                break
        said = reason_words(watch.reason)
        cause = (f"The drone could not join {creds.ssid}: {said}." if said else
                 f"The drone could not join {creds.ssid}. Check the password, that the "
                 "network is 2.4 GHz and in range, and that it has no sign-in page.")
        return self._set(Phase.FAILED, creds.ssid,
                         message=f"{cause} It keeps trying, and the app asks again shortly.")

    # ── the last join, kept across agent restarts ────────────────────────

    def _load_joined(self) -> tuple[str, str] | None:
        if self._joined_file is None:
            return None
        try:
            data = json.loads(self._joined_file.read_text())
            return (str(data["ssid"]), str(data["ip"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _remember(self, joined: tuple[str, str] | None) -> None:
        with self._lock:
            self._joined = joined
        if self._joined_file is None:
            return
        try:
            if joined is None:
                self._joined_file.unlink(missing_ok=True)
            else:
                self._joined_file.write_text(json.dumps({"ssid": joined[0], "ip": joined[1]}))
        except OSError:
            log.warning("could not record the deck's address")

    # ── state ────────────────────────────────────────────────────────────

    def _set(self, phase: Phase, ssid: str | None, *, ip: str | None = None,
             message: str | None = None, drops: int = 0,
             remembered: bool = False, needs_restart: bool = False) -> WifiState:
        with self._lock:
            if phase is not self._state.phase:
                self._phase_since = self._clock()
            self._state = WifiState(ssid=ssid, phase=phase, ip=ip, message=message,
                                    rssi=self._rssi, drops=drops, remembered=remembered,
                                    needs_restart=needs_restart,
                                    reason=reason_words(self._reason))
        self._changed()
        return self.state()

    def _changed(self) -> None:
        try:
            self._on_change(self.state())
        except Exception:
            log.exception("camera wifi listener failed")
