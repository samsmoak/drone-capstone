"""Set up a drone's camera software: the desktop's Set up page, step 2.

A new Crazyflie 2.1 with an AI deck runs stock firmware; the camera needs three
pieces this project installed by hand on the first drone. They ship inside the
agent (firmware_bundle/, with a checksummed manifest):

    main        the drone's STM32: stock 2025.12.1 + drone_wifi (Wi-Fi over radio)
    lighthouse  the Lighthouse deck's FPGA: Bitcraze's lighthouse.bin from the
                SAME 2025.12.1 release (lighthouse-fpga V6)
    camera      the AI deck's GAP8: Bitcraze's Wi-Fi image streamer 2025.02
    wifi        the AI deck's ESP32: Bitcraze 2025.02 + the close-once patch

THE LIGHTHOUSE DECK (added 2026-10-01). A new deck can arrive without the image
its drone's firmware asks for: it is detected, sits in its bootloader, and
receives nothing — every position reads as lost, and the base stations look
broken when they are not. The drone SAYS so (its deck memory reports
fw_upgrade_required), so that is read rather than assumed, and read again
after main is flashed, because main decides which image the deck needs.

WHAT IS ALREADY INSTALLED is read from the drone, never assumed:
    cwsetup.fw      drone_wifi's version — present only when "main" is ours
    cwsetup.deck    the bundle last VERIFIED on the deck, stored permanently on
                    the drone (the deck's chips cannot report their firmware)
    cwsetup.deckid  WHICH AI deck it was verified on (drone_wifi v3)
Only what is missing or older is flashed — plus whatever the operator asks to
reinstall anyway.

A REPLACED AI DECK (added 2026-10-15). The marker lives on the drone, so a new
deck on a set-up drone used to read "installed" and get nothing. Every deck
carries a 1-wire memory with a factory-unique serial, which cflib reads before
the link opens (OWElement.addr; the AI deck is vid 0xBC, pid 0x12 — aideck.c).
Its digest is stored beside the bundle after a verified install; a different
serial means a different deck, and both of its parts are installed again.
Drones on drone_wifi v2 recorded no serial, so their deck is set up once more.

ORDER AND THE UNPLUG, both learned the hard way (2026-09-24):
  - main first: it reboots the drone, which resets the deck cleanly
  - lighthouse straight after main: main names the image it requires
  - camera before wifi: the GAP8 is written THROUGH the ESP32
  - after the ESP32 is flashed the GAP8 does not start until the battery is
    unplugged ~10 s (Bitcraze Discussion #1305; a restart over the radio is
    not enough). The operator is asked, and the check only counts once the
    drone has actually disappeared from the radio and come back — the drone's
    console keeps old lines, and "GAP8 is running" from before the flash must
    not pass for after it.

The agent is the radio's only owner: standby is paused while this runs and
resumed after. Refused during a session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BUNDLE_DIR = Path(__file__).parent / "firmware_bundle"
URI = "radio://0/80/2M"
MIN_BATTERY_V = 3.8
#: How long to wait for the operator to unplug and replug the battery.
UNPLUG_WAIT_S = 300.0
PART_ORDER = ("main", "lighthouse", "camera", "wifi")
PART_LABEL = {"main": "Drone firmware", "lighthouse": "Positioning deck",
              "camera": "Camera", "wifi": "Camera Wi-Fi"}
#: The AI deck's two chips: tested together, recorded as one bundle, so they
#: are only ever installed together.
DECK_PARTS = ("camera", "wifi")
#: The AI deck's 1-wire identity (crazyflie-firmware aideck.c).
AI_DECK_VID, AI_DECK_PID = 0xBC, 0x12


class SetupError(RuntimeError):
    """A refusal or failure in words the operator can act on."""


@dataclass(frozen=True)
class Facts:
    """What the drone says about itself."""

    battery_v: float | None
    ai_deck: bool | None
    fw_version: int | None       # cwsetup.fw; None = not our firmware
    deck_bundle: int | None      # cwsetup.deck; None = not our firmware
    #: deck.bcLighthouse4: the positioning deck is detected. None = not asked.
    lighthouse_deck: bool | None = None
    #: The drone's own word that the deck needs its firmware (deck memory).
    lighthouse_needs_fw: bool = False
    #: deck_id() of the fitted AI deck's factory serial. None = not read.
    ai_deck_id: int | None = None
    #: cwsetup.deckid: the deck the bundle was verified on. None = firmware
    #: before drone_wifi v3, which never recorded one; 0 = none recorded.
    deck_id_marker: int | None = None


@dataclass
class SetupState:
    #: idle · checking · ready · installing · unplug · verifying · done · failed
    phase: str = "idle"
    message: str | None = None
    facts: dict[str, Any] | None = None
    #: part -> "installed" | "needed" | "installing" | "done"
    parts: dict[str, str] = field(default_factory=dict)
    current: str | None = None
    progress: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "message": self.message, "facts": self.facts,
                "parts": self.parts, "current": self.current,
                "progress": round(self.progress, 3),
                "labels": PART_LABEL, "order": list(PART_ORDER)}


def load_manifest(bundle: Path = BUNDLE_DIR) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((bundle / "manifest.json").read_text())
    return manifest


def verified_file(bundle: Path, part: str, manifest: dict[str, Any]) -> Path:
    """The part's firmware, refused if it is not byte-for-byte the tested one."""
    entry = manifest["parts"][part]
    path: Path = bundle / str(entry["file"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise SetupError(f"The bundled {PART_LABEL[part].lower()} file is damaged. "
                         "Reinstall DroneDeck.")
    return path


def deck_id(serial: str) -> int:
    """What cwsetup.deckid holds for a deck: a 32-bit digest of its 1-wire
    factory serial (64 bits, too wide for a parameter). Never 0, which means
    no deck recorded."""
    return zlib.crc32(serial.upper().encode()) or 1


def same_deck(facts: Facts) -> bool:
    """The deck bundle on record was verified on the deck fitted now.

    A serial that could not be read leaves the bundle marker alone to decide
    — what Set up did before decks were told apart — rather than reinstalling
    on every check with no way to record that it was done."""
    if facts.ai_deck_id is None:
        return True
    return facts.deck_id_marker == facts.ai_deck_id


def deck_unrecorded(facts: Facts, manifest: dict[str, Any]) -> bool:
    """The bundle is on record, but not for the deck fitted now: a replaced
    deck, or a drone from before decks were recorded (drone_wifi v2)."""
    bundle_ok = facts.deck_bundle is not None and facts.deck_bundle >= manifest["bundle"]
    return bundle_ok and not same_deck(facts)


def needed_parts(facts: Facts, manifest: dict[str, Any]) -> dict[str, str]:
    """Which parts to install. The deck's two parts go together: they were
    tested together, and the marker records them as one bundle — on one deck."""
    main_ok = facts.fw_version is not None and facts.fw_version >= manifest["drone_wifi"]
    deck_ok = (facts.deck_bundle is not None and facts.deck_bundle >= manifest["bundle"]
               and same_deck(facts))
    return {
        "main": "installed" if main_ok else "needed",
        "lighthouse": lighthouse_part(facts),
        "camera": "installed" if deck_ok else "needed",
        "wifi": "installed" if deck_ok else "needed",
    }


def reinstall_set(parts: Iterable[str]) -> frozenset[str]:
    """The parts asked for again, refused by name if unknown. One deck part
    brings the other: they are recorded as one bundle."""
    chosen = set(parts)
    unknown = chosen - set(PART_ORDER)
    if unknown:
        raise SetupError(f"There is no part called {', '.join(sorted(unknown))} to reinstall.")
    if chosen & set(DECK_PARTS):
        chosen |= set(DECK_PARTS)
    return frozenset(chosen)


def lighthouse_part(facts: Facts) -> str:
    """The positioning deck reports its own state — no marker is needed."""
    if facts.lighthouse_needs_fw:
        return "needed"
    return "absent" if facts.lighthouse_deck is False else "installed"


# ── talking to the drone (replaced in tests) ─────────────────────────────


def _with_drone(fn: Callable[[Any], Any], timeout_s: float = 30.0) -> Any:
    """Run fn(cf) on a fresh link, or None when no drone answers in time."""
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    from dronedeck.paths import cflib_cache_dir

    cflib.crtp.init_drivers()
    out: dict[str, Any] = {}

    def run() -> None:
        try:
            with SyncCrazyflie(URI, cf=Crazyflie(rw_cache=str(cflib_cache_dir()))) as scf:
                out["value"] = fn(scf.cf)
        except Exception as e:                              # noqa: BLE001
            out["error"] = e

    worker = threading.Thread(target=run, daemon=True, name="setup-link")
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive() or "value" not in out:
        return None
    return out["value"]


def _read_facts(cf: Any) -> Facts:
    from cflib.crazyflie.log import LogConfig

    def param(name: str) -> str | None:
        group, _, item = name.partition(".")
        if group not in cf.param.toc.toc or item not in cf.param.toc.toc[group]:
            return None
        return str(cf.param.get_value(name))

    got: dict[str, float] = {}
    conf = LogConfig("setup", 100)
    conf.add_variable("pm.vbat", "float")
    conf.data_received_cb.add_callback(lambda _t, data, _c: got.update(data))
    cf.log.add_config(conf)
    conf.start()
    time.sleep(0.6)
    conf.stop()
    fw, deck, ai = param("cwsetup.fw"), param("cwsetup.deck"), param("deck.bcAI")
    marker = param("cwsetup.deckid")
    lighthouse = param("deck.bcLighthouse4")
    return Facts(
        battery_v=round(got["pm.vbat"], 2) if "pm.vbat" in got else None,
        ai_deck=None if ai is None else ai == "1",
        fw_version=None if fw is None else int(fw),
        deck_bundle=None if deck is None else int(deck),
        lighthouse_deck=None if lighthouse is None else lighthouse == "1",
        lighthouse_needs_fw=lighthouse == "1" and _deck_needs_fw(cf, "bcLighthouse4"),
        ai_deck_id=_ai_deck_id(cf) if ai == "1" else None,
        deck_id_marker=None if marker is None else int(marker),
    )


def _ai_deck_id(cf: Any) -> int | None:
    """The fitted AI deck's identity, from its own 1-wire memory — read by
    cflib while the link opened, so this costs no radio traffic."""
    from cflib.crazyflie.mem import MemoryElement

    for ow in cf.mem.get_mems(MemoryElement.TYPE_1W):
        if ow.vid == AI_DECK_VID and ow.pid == AI_DECK_PID and ow.addr:
            return deck_id(str(ow.addr))
    log.warning("the AI deck is fitted but its 1-wire serial was not read")
    return None


def _deck_needs_fw(cf: Any, name: str) -> bool:
    """The drone's deck memory: does this deck need its firmware written?"""
    from cflib.crazyflie.mem import MemoryElement
    from cflib.crazyflie.mem.deck_memory import SyncDeckMemoryManager

    mems = cf.mem.get_mems(MemoryElement.TYPE_DECK_MEMORY)
    if not mems:
        return False
    for deck in SyncDeckMemoryManager(mems[0]).query_decks().values():
        if deck.name == name:
            return bool(deck.is_fw_upgrade_required)
    return False


def probe_drone() -> Facts | None:
    facts = _with_drone(_read_facts)
    return facts if isinstance(facts, Facts) else None


def _camera_started(cf: Any) -> bool:
    """The GAP8 streamer has started this boot — it announces itself."""
    lines: list[str] = []
    cf.console.receivedChar.add_callback(lines.append)
    time.sleep(6.0)
    text = "".join(lines)
    return "GAP8:" in text and "DRONEWIFI: ready" in text


def camera_started() -> bool | None:
    started = _with_drone(_camera_started)
    return None if started is None else bool(started)


def _store_marker(bundle: int, deck: int) -> Callable[[Any], bool]:
    """Both halves of the record — which bundle, on which deck — kept across
    power-offs. The deck's serial first: a bundle saved without it would read
    as set up on whatever deck was recorded before."""
    def store(cf: Any) -> bool:
        for name, value in (("cwsetup.deckid", deck), ("cwsetup.deck", bundle)):
            stored = threading.Event()
            cf.param.set_value(name, value)
            time.sleep(0.3)

            def done(_name: str, ok: bool, stored: threading.Event = stored) -> None:
                if ok:
                    stored.set()

            cf.param.persistent_store(name, done)
            if not stored.wait(5.0):
                return False
        return True
    return store


def store_marker(bundle: int, deck: int) -> bool:
    return bool(_with_drone(_store_marker(bundle, deck)))


def flash_part(part: str, path: Path, on_progress: Callable[[float], None]) -> bool:
    if part == "main":
        from dronedeck.flash_firmware import flash as flash_main
        return flash_main(path, URI, on_progress) == 0
    if part == "lighthouse":
        from dronedeck.flash_firmware import flash_lighthouse_deck
        return flash_lighthouse_deck(path, URI, on_progress) == 0
    from dronedeck.camera.flash_gap8 import flash as flash_deck
    chip = "gap8" if part == "camera" else "esp"
    return flash_deck(path, URI, chip=chip, on_progress=on_progress) == 0


# ── the procedure ────────────────────────────────────────────────────────


class DroneSetup:
    """The Set up page's engine. Every step runs on one worker thread and every
    change is published, so the page shows exactly where it is."""

    def __init__(
        self,
        *,
        pause_radio: Callable[[], None],
        resume_radio: Callable[[], None],
        publish: Callable[[dict[str, Any]], None] = lambda _s: None,
        bundle: Path = BUNDLE_DIR,
        probe: Callable[[], Facts | None] = probe_drone,
        flash: Callable[[str, Path, Callable[[float], None]], bool] = flash_part,
        started: Callable[[], bool | None] = camera_started,
        mark: Callable[[int, int], bool] = store_marker,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pause, self._resume, self._publish = pause_radio, resume_radio, publish
        self._bundle = bundle
        self._probe, self._flash, self._started, self._mark = probe, flash, started, mark
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._state = SetupState()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def check(self) -> None:
        self._start(self._do_check)

    def install(self, reinstall: Iterable[str] = ()) -> None:
        """Install what is missing, plus the parts in `reinstall` even though
        the drone reports them installed."""
        again = reinstall_set(reinstall)
        self._start(lambda: self._do_install(again))

    def wait(self, timeout: float = 30.0) -> None:
        if self._worker is not None:
            self._worker.join(timeout)

    # ── steps ────────────────────────────────────────────────────────────

    def _start(self, work: Callable[[], None]) -> None:
        if self.busy():
            raise SetupError("Set up is already running.")

        def run() -> None:
            self._pause()
            try:
                work()
            except SetupError as e:
                self._set(phase="failed", message=str(e), current=None)
            except Exception:
                log.exception("drone setup failed")
                self._set(phase="failed", current=None,
                          message="Set up stopped unexpectedly. Press the button again "
                                  "to continue where it stopped.")
            finally:
                self._resume()

        self._worker = threading.Thread(target=run, name="drone-setup", daemon=True)
        self._worker.start()

    def _do_check(self) -> None:
        self._set(phase="checking", message="Looking for the drone…", parts={}, progress=0.0)
        facts = self._facts()
        manifest = load_manifest(self._bundle)
        parts = needed_parts(facts, manifest)
        if all(v in ("installed", "absent") for v in parts.values()):
            self._set(phase="done", parts=parts,
                      message="This drone's software is already installed.")
        else:
            self._set(phase="ready", parts=parts, message=None)

    def _do_install(self, again: frozenset[str] = frozenset()) -> None:
        self._do_check()
        with self._lock:
            parts = dict(self._state.parts)
        # Asked for again: an installed part is written anyway. A deck that is
        # not fitted stays absent — there is nothing to write it to.
        for part in again:
            if parts.get(part) == "installed":
                parts[part] = "needed"
        if not any(v == "needed" for v in parts.values()):
            return                     # the check already said it is all installed
        self._set(phase="ready", parts=dict(parts), message=None)
        facts = self._facts()
        if facts.battery_v is not None and facts.battery_v < MIN_BATTERY_V:
            raise SetupError(f"The battery is at {facts.battery_v:.2f} V. Charge it above "
                             f"{MIN_BATTERY_V} V first — a flash that loses power can "
                             "leave the drone unable to start.")
        manifest = load_manifest(self._bundle)
        deck_flashed = False
        for part in PART_ORDER:
            if part == "lighthouse" and parts["main"] == "done" and part not in again:
                # Main decides which image the deck needs: ask again now.
                parts[part] = lighthouse_part(self._facts())
            if parts[part] != "needed":
                continue
            path = verified_file(self._bundle, part, manifest)
            parts[part] = "installing"
            self._set(phase="installing", parts=dict(parts), current=part, progress=0.0,
                      message=f"Installing {PART_LABEL[part].lower()}. Keep the drone "
                              "switched on and the dongle plugged in.")
            if not self._flash(part, path, lambda f: self._set(progress=f)):
                raise SetupError(f"Installing {PART_LABEL[part].lower()} stopped. Check the "
                                 "drone is on and the dongle is plugged in, then press "
                                 "Install again — it continues from here.")
            parts[part] = "done"
            self._set(parts=dict(parts), progress=1.0)
            deck_flashed = deck_flashed or part in ("camera", "wifi")
            if part in ("main", "lighthouse"):
                self._sleep(6.0)          # the drone reboots into the new firmware
            if part == "lighthouse" and self._facts().lighthouse_needs_fw:
                raise SetupError("The positioning deck still asks for its firmware after "
                                 "it was written. Press Install again.")

        if deck_flashed:
            self._await_unplug()
            self._set(phase="verifying", current=None,
                      message="Checking the camera started…")
            if not self._started():
                raise SetupError("The camera did not start. Unplug the battery for 10 "
                                 "seconds again, then press Install to re-check.")
            # The unplug is also the test that the deck's image SURVIVES a power
            # cycle — on 2026-10-01 a first write did not.
            after = self._facts()
            if after.lighthouse_needs_fw:
                raise SetupError("The positioning deck lost its firmware when the battery "
                                 "was unplugged. Press Install to write it again.")
            # The deck recorded is the one that just started the camera, read
            # after the unplug — not one remembered from before it.
            if not self._mark(manifest["bundle"], after.ai_deck_id or 0):
                raise SetupError("Installed, but the drone did not save the set-up marker. "
                                 "Press Install again to finish.")
            self._set(facts={**(self.state()["facts"] or {}), "deck_unrecorded": False})
        self._set(phase="done", current=None,
                  parts={p: "absent" if parts.get(p) == "absent" else "installed"
                         for p in PART_ORDER},
                  message="The drone's software is installed.")

    def _await_unplug(self) -> None:
        """Wait for the battery to be unplugged AND plugged back in."""
        self._set(phase="unplug", current=None,
                  message="Unplug the drone's battery, wait 10 seconds, then plug it back in.")
        deadline = self._clock() + UNPLUG_WAIT_S
        gone = False
        while self._clock() < deadline:
            here = self._probe() is not None
            if not here:
                gone = True
            elif gone:
                return
            self._sleep(2.0)
        raise SetupError("Still waiting for the battery to be unplugged and plugged back "
                         "in. Do that, then press Install to continue.")

    def _facts(self) -> Facts:
        facts = self._probe()
        if facts is None:
            raise SetupError("No drone found. Plug in the Crazyradio and switch the drone "
                             "on, then try again.")
        self._set(facts={"battery_v": facts.battery_v, "ai_deck": facts.ai_deck,
                         "deck_unrecorded": deck_unrecorded(facts, load_manifest(self._bundle))})
        if facts.ai_deck is False:
            raise SetupError("This drone has no AI deck, so there is no camera to set up.")
        return facts

    def _set(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)
            payload = self._state.to_dict()
        try:
            self._publish(payload)
        except Exception:
            log.exception("setup publish failed")
