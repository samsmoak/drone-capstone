"""Write the Wi-Fi image-streamer firmware to the AI deck's GAP8, over the radio.

    python -m cropwatcher.camera.flash_gap8 <firmware.bin>

WHY THIS EXISTS. The camera sits behind the GAP8, a RISC-V processor on the AI
deck, and it sends nothing unless the GAP8 runs an app that streams. Bitcraze
publish a prebuilt one — `aideck_gap8_wifi_img_streamer_with_ap.bin`, from the
aideck-gap8-examples releases — and `with_ap` is the part that matters: the deck
raises its OWN access point, so no network has to be configured.

IT GOES OVER THE CRAZYRADIO. No JTAG, no programmer. The STM32 exposes each
deck's flash as a "deck memory" and cflib writes through it.

TWO TARGETS LIVE ON THIS DECK — `bcAI:gap8` and `bcAI:esp`. They are told apart
ONLY by name, and writing GAP8 firmware to the ESP32 is how a deck gets bricked,
so the name is matched exactly and nothing is written if it is missing.

Run it with the agent stopped: the radio takes one owner at a time.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

#: The AI deck's two chips, by the ONLY name that tells them apart. Writing a
#: GAP8 image to the ESP32 (or the reverse) is how a deck gets bricked, so the
#: name is matched exactly and a .bin is refused for the wrong chip by size.
TARGETS = {"gap8": "bcAI:gap8", "esp": "bcAI:esp"}
TARGET = TARGETS["gap8"]
BOOTLOADER_WAIT_S = 20.0


def flash(path: Path, uri: str = "radio://0/80/2M", *, chip: str = "gap8",
          on_progress: Callable[[float], None] | None = None) -> int:
    """0 on success. `on_progress` gets 0..1 as it writes (the Set up page)."""
    target_name = TARGETS[chip]
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.mem import MemoryElement
    from cflib.crazyflie.mem.deck_memory import SyncDeckMemoryManager
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    data = path.read_bytes()
    print(f"firmware {path.name}: {len(data)} bytes", flush=True)

    cflib.crtp.init_drivers()
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache="./cache")) as scf:
        mgr = SyncDeckMemoryManager(
            scf.cf.mem.get_mems(MemoryElement.TYPE_DECK_MEMORY)[0]
        )

        def target():
            for deck in mgr.query_decks().values():
                if deck.name == target_name:
                    return deck
            return None

        deck = target()
        if deck is None:
            print(f"No {target_name} deck memory. Is the AI deck seated and detected?")
            return 1
        if not deck.supports_fw_upgrade:
            print(f"{target_name} does not accept a firmware upgrade.")
            return 1

        print(f"target {deck.name}: entering its bootloader…", flush=True)
        deck.set_fw_new_flash_size(len(data))
        deck.reset_to_bootloader()

        deadline = time.monotonic() + BOOTLOADER_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(0.5)
            deck = target()
            if deck is not None and deck.is_bootloader_active:
                break
        if deck is None or not deck.is_bootloader_active:
            # Nothing has been written at this point, so the deck is untouched.
            print("The deck never entered its bootloader — NOTHING was written.")
            return 1

        print("bootloader active — writing", flush=True)
        # cflib calls this with (message, progress) — a one-argument callback
        # raises inside its packet thread MID-WRITE, which is how the first
        # attempt left the deck part-written.
        def written(message: str, progress: int) -> None:
            print(f"  {message} {progress}", flush=True)
            if on_progress is not None:
                on_progress(max(0.0, min(1.0, progress / 100)))

        deck.write_sync(0, data, written)
        print("written; resetting to firmware", flush=True)
        deck.reset_to_fw()
        print("\nDone. Power-cycle the drone so both deck chips start clean.")
    return 0


def main() -> int:
    """python -m cropwatcher.camera.flash_gap8 <firmware.bin> [gap8|esp]"""
    logging.basicConfig(level=logging.ERROR)
    if len(sys.argv) < 2 or (len(sys.argv) > 2 and sys.argv[2] not in TARGETS):
        print(__doc__)
        print("chip: gap8 (default) or esp")
        return 2
    return flash(Path(sys.argv[1]), chip=sys.argv[2] if len(sys.argv) > 2 else "gap8")


if __name__ == "__main__":
    raise SystemExit(main())
