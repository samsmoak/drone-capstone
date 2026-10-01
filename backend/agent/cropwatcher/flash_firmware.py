"""Write drone firmware to the Crazyflie's STM32, over the radio.

    python -m cropwatcher.flash_firmware firmware/drone-wifi/build/cf2.bin

WHAT IS FLASHED. Stock Crazyflie firmware, the same release the drone already
runs, plus the drone_wifi app (firmware/drone-wifi) that lets the laptop tell
the AI deck which Wi-Fi network to join. Build it with firmware/drone-wifi/build.sh.

ONLY THE STM32 IS WRITTEN. The nRF51 (radio chip) and both AI-deck chips are
left alone: the target list names `cf2 / stm32` and nothing else, so a .bin
cannot land anywhere it was not meant for.

RECOVERY. The bootloader lives in its own protected flash and is never
written. If a flash is interrupted, hold the power button for ~3 s until the
blue LEDs blink (cold bootloader) and run this again.

Run it with the agent idle — no session open. The radio takes one owner at a
time, and the drone reboots at the end.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

#: The platform and target cflib's bootloader uses for a Crazyflie 2.x STM32.
PLATFORM = "cf2"
TARGET = "stm32"


def flash(path: Path, uri: str = "radio://0/80/2M",
          on_progress: Callable[[float], None] | None = None) -> int:
    """0 on success. `on_progress` gets 0..1 as it writes (the Set up page)."""
    import cflib.crtp
    from cflib.bootloader import Bootloader, Target

    data = path.read_bytes()
    # A Crazyflie 2.x STM32 image is a few hundred KB; far outside that is the
    # wrong file (a zip, a GAP8 image, an ELF), and writing it bricks a flight.
    if not 100_000 < len(data) < 1_000_000:
        print(f"{path.name} is {len(data)} bytes — not an STM32 image. Nothing written.")
        return 1
    print(f"firmware {path.name}: {len(data)} bytes -> {PLATFORM}/{TARGET}", flush=True)

    cflib.crtp.init_drivers()
    loader = Bootloader(uri)

    def progress(message: str, percent: int) -> None:
        print(f"  {percent:3d}%  {message}", flush=True)
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, percent / 100)))

    try:
        loader.flash_full(
            cf=None,
            filename=str(path),
            warm=True,
            targets=(Target(PLATFORM, TARGET, "fw", [], []),),
            progress_cb=progress,
        )
    except Exception as e:  # cflib raises bare Exception for every failure
        print(f"flash failed: {e}")
        print("If the drone does not boot, hold its power button ~3 s (blue LEDs "
              "blink) and run this again.")
        return 1
    finally:
        loader.close()
    print("done — the drone has rebooted into the new firmware")
    return 0


#: The Lighthouse deck's FPGA image, as cflib names its deck target.
LIGHTHOUSE_DECK = "bcLighthouse4"


def flash_lighthouse_deck(path: Path, uri: str = "radio://0/80/2M",
                          on_progress: Callable[[float], None] | None = None) -> int:
    """Write the Lighthouse deck's own firmware (Bitcraze's lighthouse.bin). 0 on success.

    A deck the main firmware does not recognise sits in its bootloader and
    receives NOTHING — detected, but deaf (measured 2026-10-01 on the second
    lab drone: fw_upgrade_required, lighthouse.status 0). Which image it needs
    is decided by the MAIN firmware, so this runs after main.

    Only the deck is written: the target list names the deck and nothing else,
    so cflib skips the STM32 and the nRF51. cflib updates decks from a warm
    boot and leaves the drone in its bootloader afterwards, so it is restarted
    into its firmware at the end.
    """
    import cflib.crtp
    from cflib.bootloader import Bootloader, Target
    from cflib.utils.power_switch import PowerSwitch

    data = path.read_bytes()
    # lighthouse-fpga images are ~100 KB; a cf2 image or a zip is the wrong file.
    if not 50_000 < len(data) < 200_000:
        print(f"{path.name} is {len(data)} bytes — not a Lighthouse deck image. Nothing written.")
        return 1
    print(f"deck firmware {path.name}: {len(data)} bytes -> deck/{LIGHTHOUSE_DECK}", flush=True)

    cflib.crtp.init_drivers()
    loader = Bootloader(uri)

    def progress(message: str, percent: int) -> None:
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, percent / 100)))

    try:
        loader.flash_full(
            cf=None, filename=str(path), warm=True,
            targets=(Target("deck", LIGHTHOUSE_DECK, "fw", [], []),),
            progress_cb=progress,
        )
    except Exception as e:  # cflib raises bare Exception for every failure
        print(f"deck flash failed: {e}")
        return 1
    finally:
        loader.close()
    PowerSwitch(uri).reboot_to_fw()
    print("done — the drone has restarted with the deck's firmware")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    return flash(Path(argv[1]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
