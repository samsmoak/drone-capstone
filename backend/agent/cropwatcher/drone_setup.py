"""Set up a drone's camera software: the desktop's Set up page, step 2.

A new Crazyflie 2.1 with an AI deck runs stock firmware; the camera needs three
pieces this project installed by hand on the first drone. They ship inside the
agent (firmware_bundle/, with a checksummed manifest):

    main    the drone's STM32: stock 2025.12.1 + drone_wifi (Wi-Fi over radio)
    camera  the AI deck's GAP8: Bitcraze's Wi-Fi image streamer 2025.02
    wifi    the AI deck's ESP32: Bitcraze 2025.02 + the close-once patch

WHAT IS ALREADY INSTALLED is read from the drone, never assumed:
    cwsetup.fw    drone_wifi's version — present only when "main" is ours
    cwsetup.deck  the bundle last VERIFIED on the deck, stored permanently on
                  the drone (the deck's chips cannot report their firmware)
Only what is missing or older is flashed.

ORDER AND THE UNPLUG, both learned the hard way (2026-09-24):
  - main first: it reboots the drone, which resets the deck cleanly
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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BUNDLE_DIR = Path(__file__).parent / "firmware_bundle"
URI = "radio://0/80/2M"
MIN_BATTERY_V = 3.8
#: How long to wait for the operator to unplug and replug the battery.
UNPLUG_WAIT_S = 300.0
PART_ORDER = ("main", "camera", "wifi")
PART_LABEL = {"main": "Drone firmware", "camera": "Camera", "wifi": "Camera Wi-Fi"}


class SetupError(RuntimeError):
    """A refusal or failure in words the operator can act on."""


@dataclass(frozen=True)
class Facts:
    """What the drone says about itself."""

    battery_v: float | None
    ai_deck: bool | None
    fw_version: int | None       # cwsetup.fw; None = not our firmware
    deck_bundle: int | None      # cwsetup.deck; None = not our firmware


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
                         "Reinstall CropWatcher.")
    return path


def needed_parts(facts: Facts, manifest: dict[str, Any]) -> dict[str, str]:
    """Which parts to install. The deck's two parts go together: they were
    tested together, and the marker records them as one bundle."""
    main_ok = facts.fw_version is not None and facts.fw_version >= manifest["drone_wifi"]
    deck_ok = facts.deck_bundle is not None and facts.deck_bundle >= manifest["bundle"]
    return {
        "main": "installed" if main_ok else "needed",
        "camera": "installed" if deck_ok else "needed",
        "wifi": "installed" if deck_ok else "needed",
    }


# ── talking to the drone (replaced in tests) ─────────────────────────────


def _with_drone(fn: Callable[[Any], Any], timeout_s: float = 30.0) -> Any:
    """Run fn(cf) on a fresh link, or None when no drone answers in time."""
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    from cropwatcher.paths import cflib_cache_dir

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
    return Facts(
        battery_v=round(got["pm.vbat"], 2) if "pm.vbat" in got else None,
        ai_deck=None if ai is None else ai == "1",
        fw_version=None if fw is None else int(fw),
        deck_bundle=None if deck is None else int(deck),
    )


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


def _store_marker(bundle: int) -> Callable[[Any], bool]:
    def store(cf: Any) -> bool:
        stored = threading.Event()
        cf.param.set_value("cwsetup.deck", bundle)
        time.sleep(0.3)
        def done(_name: str, ok: bool) -> None:
            if ok:
                stored.set()

        cf.param.persistent_store("cwsetup.deck", done)
        return stored.wait(5.0)
    return store


def store_marker(bundle: int) -> bool:
    return bool(_with_drone(_store_marker(bundle)))


def flash_part(part: str, path: Path, on_progress: Callable[[float], None]) -> bool:
    if part == "main":
        from cropwatcher.flash_firmware import flash as flash_main
        return flash_main(path, URI, on_progress) == 0
    from cropwatcher.camera.flash_gap8 import flash as flash_deck
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
        mark: Callable[[int], bool] = store_marker,
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

    def install(self) -> None:
        self._start(self._do_install)

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
        if all(v == "installed" for v in parts.values()):
            self._set(phase="done", parts=parts,
                      message="This drone's camera software is already installed.")
        else:
            self._set(phase="ready", parts=parts, message=None)

    def _do_install(self) -> None:
        self._do_check()
        with self._lock:
            if self._state.phase == "done":
                return
            parts = dict(self._state.parts)
        facts = self._facts()
        if facts.battery_v is not None and facts.battery_v < MIN_BATTERY_V:
            raise SetupError(f"The battery is at {facts.battery_v:.2f} V. Charge it above "
                             f"{MIN_BATTERY_V} V first — a flash that loses power can "
                             "leave the drone unable to start.")
        manifest = load_manifest(self._bundle)
        deck_flashed = False
        for part in PART_ORDER:
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
            if part == "main":
                self._sleep(6.0)          # the drone reboots into the new firmware

        if deck_flashed:
            self._await_unplug()
            self._set(phase="verifying", current=None,
                      message="Checking the camera started…")
            if not self._started():
                raise SetupError("The camera did not start. Unplug the battery for 10 "
                                 "seconds again, then press Install to re-check.")
            if not self._mark(manifest["bundle"]):
                raise SetupError("Installed, but the drone did not save the set-up marker. "
                                 "Press Install again to finish.")
        self._set(phase="done", current=None, parts={p: "installed" for p in PART_ORDER},
                  message="The drone's camera software is installed.")

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
        self._set(facts={"battery_v": facts.battery_v, "ai_deck": facts.ai_deck})
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
