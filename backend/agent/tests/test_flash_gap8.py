"""camera/flash_gap8.py against a fake drone: a write the drone refuses is a
failure, never "written" (2026-10-24: write_sync returned False at the first
chunk — "cannot sync with bootloader" — and the flasher reported success)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeDeck:
    def __init__(self, write_ok: bool) -> None:
        self.name = "bcAI:esp"
        self.supports_fw_upgrade = True
        self.is_bootloader_active = False
        self.write_ok = write_ok
        self.reset_to_fw_called = False

    def set_fw_new_flash_size(self, _n: int) -> None:
        pass

    def reset_to_bootloader(self) -> None:
        self.is_bootloader_active = True

    def write_sync(self, _addr: int, _data: bytes, _progress) -> bool:
        return self.write_ok

    def reset_to_fw(self) -> None:
        self.reset_to_fw_called = True


@pytest.fixture
def drone(monkeypatch, tmp_path):
    monkeypatch.setenv("DRONEDECK_DATA_DIR", str(tmp_path / "data"))
    import cflib.crazyflie.mem.deck_memory as deck_memory
    import cflib.crazyflie.syncCrazyflie as sync
    import cflib.crtp

    from dronedeck.camera import flash_gap8

    holder: dict[str, FakeDeck] = {}

    class FakeSync:
        def __init__(self, *_a, **_k) -> None:
            self.cf = SimpleNamespace(mem=SimpleNamespace(get_mems=lambda _t: [object()]))

        def __enter__(self):
            return self

        def __exit__(self, *_a) -> None:
            pass

    monkeypatch.setattr(cflib.crtp, "init_drivers", lambda: None)
    monkeypatch.setattr(sync, "SyncCrazyflie", FakeSync)
    monkeypatch.setattr(deck_memory, "SyncDeckMemoryManager",
                        lambda _m: SimpleNamespace(query_decks=lambda: {2: holder["deck"]}))
    monkeypatch.setattr(flash_gap8.time, "sleep", lambda _s: None)
    return holder


def test_a_refused_write_is_a_failure(drone, tmp_path: Path):
    from dronedeck.camera import flash_gap8

    drone["deck"] = FakeDeck(write_ok=False)
    image = tmp_path / "aideck_esp.bin"
    image.write_bytes(b"\xe9" + bytes(63))
    assert flash_gap8.flash(image, chip="esp") == 1
    assert not drone["deck"].reset_to_fw_called


def test_a_completed_write_resets_to_firmware(drone, tmp_path: Path):
    from dronedeck.camera import flash_gap8

    drone["deck"] = FakeDeck(write_ok=True)
    image = tmp_path / "aideck_esp.bin"
    image.write_bytes(b"\xe9" + bytes(63))
    assert flash_gap8.flash(image, chip="esp") == 0
    assert drone["deck"].reset_to_fw_called
