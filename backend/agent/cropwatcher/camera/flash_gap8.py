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
from pathlib import Path

log = logging.getLogger(__name__)

TARGET = "bcAI:gap8"
BOOTLOADER_WAIT_S = 20.0


def flash(path: Path, uri: str = "radio://0/80/2M") -> int:
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
                if deck.name == TARGET:
                    return deck
            return None

        deck = target()
        if deck is None:
            print(f"No {TARGET} deck memory. Is the AI deck seated and detected?")
            return 1
        if not deck.supports_fw_upgrade:
            print(f"{TARGET} does not accept a firmware upgrade.")
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
        deck.write_sync(0, data, lambda pct: print(f"  {pct}%", flush=True))
        print("written; resetting to firmware", flush=True)
        deck.reset_to_fw()
        print(
            "\nDone. Power-cycle the drone, then look for a Wi-Fi network the deck "
            "raises (the 'with_ap' build makes its own). Point CAMERA_URL at it."
        )
    return 0


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    return flash(Path(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
