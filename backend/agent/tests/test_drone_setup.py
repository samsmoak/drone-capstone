"""The Set up page's engine, against a fake drone — no radio, no flashing."""

from __future__ import annotations

import shutil

import pytest

from cropwatcher import drone_setup
from cropwatcher.drone_setup import BUNDLE_DIR, DroneSetup, Facts, load_manifest, needed_parts

MANIFEST = load_manifest()
FRESH = Facts(battery_v=4.1, ai_deck=True, fw_version=None, deck_bundle=None)
DONE = Facts(battery_v=4.1, ai_deck=True, fw_version=MANIFEST["drone_wifi"],
             deck_bundle=MANIFEST["bundle"])


class Rig:
    def __init__(self, facts: Facts | None, *, present_after_unplug=True, started=True,
                 flash_ok=True) -> None:
        self.facts = facts
        self.flashed: list[str] = []
        self.marked: list[int] = []
        self.radio: list[str] = []
        self.unplugged = False
        self.present_after_unplug = present_after_unplug
        self._probes_in_unplug = 0
        self.started_ok = started
        self.flash_ok = flash_ok
        self.setup = DroneSetup(
            pause_radio=lambda: self.radio.append("pause"),
            resume_radio=lambda: self.radio.append("resume"),
            probe=self.probe, flash=self.flash, started=lambda: self.started_ok,
            mark=self.mark, sleep=lambda _s: None,
        )

    def probe(self) -> Facts | None:
        if self.setup.state()["phase"] == "unplug":
            self._probes_in_unplug += 1
            # gone for one probe, then back — the battery pulled and replugged
            if self._probes_in_unplug == 1:
                self.unplugged = True
                return None
            return self.facts if self.present_after_unplug else None
        return self.facts

    def flash(self, part, path, on_progress) -> bool:
        on_progress(0.5)
        on_progress(1.0)
        self.flashed.append(part)
        return self.flash_ok

    def mark(self, bundle: int) -> bool:
        self.marked.append(bundle)
        return True

    def run(self, action: str) -> dict:
        getattr(self.setup, action)()
        self.setup.wait(10)
        return self.setup.state()


class TestNeededParts:
    def test_a_new_drone_needs_all_three(self):
        assert set(needed_parts(FRESH, MANIFEST).values()) == {"needed"}

    def test_a_set_up_drone_needs_nothing(self):
        assert set(needed_parts(DONE, MANIFEST).values()) == {"installed"}

    def test_old_drone_software_alone_is_updated(self):
        old_main = Facts(4.1, True, MANIFEST["drone_wifi"] - 1, MANIFEST["bundle"])
        parts = needed_parts(old_main, MANIFEST)
        assert parts == {"main": "needed", "camera": "installed", "wifi": "installed"}


class TestCheck:
    def test_it_reports_without_touching_the_drone(self):
        rig = Rig(FRESH)
        state = rig.run("check")
        assert state["phase"] == "ready"
        assert rig.flashed == [] and rig.marked == []

    def test_an_already_set_up_drone_is_said_so(self):
        state = Rig(DONE).run("check")
        assert state["phase"] == "done" and "already" in state["message"]

    def test_no_drone_says_what_to_do(self):
        state = Rig(None).run("check")
        assert state["phase"] == "failed" and "switch the drone on" in state["message"]

    def test_no_ai_deck_is_refused(self):
        state = Rig(Facts(4.1, False, None, None)).run("check")
        assert state["phase"] == "failed" and "no AI deck" in state["message"]

    def test_the_radio_is_given_back_afterwards(self):
        rig = Rig(FRESH)
        rig.run("check")
        assert rig.radio == ["pause", "resume"]


class TestInstall:
    def test_a_new_drone_gets_all_three_in_order_then_the_unplug_then_the_marker(self):
        rig = Rig(FRESH)
        state = rig.run("install")
        assert rig.flashed == ["main", "camera", "wifi"]
        assert rig.unplugged, "the check must wait for a real unplug"
        assert rig.marked == [MANIFEST["bundle"]]
        assert state["phase"] == "done"

    def test_only_what_is_missing_is_flashed(self):
        rig = Rig(Facts(4.1, True, None, MANIFEST["bundle"]))
        rig.run("install")
        assert rig.flashed == ["main"]
        assert not rig.unplugged and rig.marked == []    # the deck was not touched

    def test_a_low_battery_is_refused_before_anything_is_written(self):
        rig = Rig(Facts(3.7, True, None, None))
        state = rig.run("install")
        assert state["phase"] == "failed" and "3.70 V" in state["message"]
        assert rig.flashed == []

    def test_a_failed_flash_stops_and_says_it_resumes(self):
        rig = Rig(FRESH, flash_ok=False)
        state = rig.run("install")
        assert state["phase"] == "failed" and "continues from here" in state["message"]
        assert rig.flashed == ["main"]

    def test_a_camera_that_does_not_start_is_not_marked_set_up(self):
        rig = Rig(FRESH, started=False)
        state = rig.run("install")
        assert state["phase"] == "failed" and "did not start" in state["message"]
        assert rig.marked == []

    def test_a_damaged_bundle_file_is_refused(self, tmp_path, monkeypatch):
        bundle = tmp_path / "bundle"
        shutil.copytree(BUNDLE_DIR, bundle)
        (bundle / "cf2.bin").write_bytes(b"not the tested file")
        rig = Rig(FRESH)
        rig.setup._bundle = bundle
        state = rig.run("install")
        assert state["phase"] == "failed" and "damaged" in state["message"]
        assert rig.flashed == []

    def test_the_bundle_matches_its_manifest(self):
        for part in drone_setup.PART_ORDER:
            assert drone_setup.verified_file(BUNDLE_DIR, part, MANIFEST).exists()

    def test_a_second_install_while_one_runs_is_refused(self):
        rig = Rig(FRESH)
        rig.setup._worker = type("Busy", (), {"is_alive": lambda self: True})()
        with pytest.raises(drone_setup.SetupError):
            rig.setup.install()
