"""The Set up page's engine, against a fake drone — no radio, no flashing."""

from __future__ import annotations

import shutil
from dataclasses import replace

import pytest

from dronedeck import drone_setup
from dronedeck.drone_setup import (
    BUNDLE_DIR,
    DroneSetup,
    Facts,
    SetupError,
    deck_id,
    deck_unrecorded,
    load_manifest,
    needed_parts,
    reinstall_set,
)

MANIFEST = load_manifest()
#: Two real-looking 1-wire serials: family code first, CRC last.
DECK_A, DECK_B = deck_id("2D3F8A1C00000062"), deck_id("2D91C04E000000B7")
FRESH = Facts(battery_v=4.1, ai_deck=True, fw_version=None, deck_bundle=None,
              lighthouse_deck=True, lighthouse_needs_fw=True, ai_deck_id=DECK_A)
DONE = Facts(battery_v=4.1, ai_deck=True, fw_version=MANIFEST["drone_wifi"],
             deck_bundle=MANIFEST["bundle"], lighthouse_deck=True,
             ai_deck_id=DECK_A, deck_id_marker=DECK_A)
#: The same drone, its AI deck swapped for a new one.
SWAPPED = replace(DONE, ai_deck_id=DECK_B)


class Rig:
    def __init__(self, facts: Facts | None, *, present_after_unplug=True, started=True,
                 flash_ok=True, deck_keeps_fw=True, deck_takes_fw=True,
                 main_asks_for_deck_fw=False) -> None:
        self.facts = facts
        self.deck_keeps_fw = deck_keeps_fw          # survives the battery unplug
        self.deck_takes_fw = deck_takes_fw          # the write is accepted
        self.main_asks_for_deck_fw = main_asks_for_deck_fw
        self.flashed: list[str] = []
        self.marked: list[tuple[int, int]] = []
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
                if not self.deck_keeps_fw and self.facts is not None:
                    self.facts = replace(self.facts, lighthouse_needs_fw=True)
                return None
            return self.facts if self.present_after_unplug else None
        return self.facts

    def flash(self, part, path, on_progress) -> bool:
        on_progress(0.5)
        on_progress(1.0)
        self.flashed.append(part)
        if self.flash_ok and self.facts is not None:
            if part == "main" and self.main_asks_for_deck_fw:
                # a new main firmware can name a different deck image
                self.facts = replace(self.facts, lighthouse_needs_fw=True)
            if part == "lighthouse" and self.deck_takes_fw:
                self.facts = replace(self.facts, lighthouse_needs_fw=False)
        return self.flash_ok

    def mark(self, bundle: int, deck: int) -> bool:
        self.marked.append((bundle, deck))
        if self.facts is not None:
            self.facts = replace(self.facts, deck_bundle=bundle, deck_id_marker=deck)
        return True

    def run(self, action: str, *args) -> dict:
        getattr(self.setup, action)(*args)
        self.setup.wait(10)
        return self.setup.state()


class TestNeededParts:
    def test_a_new_drone_needs_all_four(self):
        assert set(needed_parts(FRESH, MANIFEST).values()) == {"needed"}

    def test_a_set_up_drone_needs_nothing(self):
        assert set(needed_parts(DONE, MANIFEST).values()) == {"installed"}

    def test_old_drone_software_alone_is_updated(self):
        old_main = Facts(4.1, True, MANIFEST["drone_wifi"] - 1, MANIFEST["bundle"])
        parts = needed_parts(old_main, MANIFEST)
        assert parts == {"main": "needed", "lighthouse": "installed",
                         "camera": "installed", "wifi": "installed"}

    def test_the_positioning_deck_reports_its_own_state(self):
        assert needed_parts(replace(DONE, lighthouse_needs_fw=True), MANIFEST)["lighthouse"] \
            == "needed"
        assert needed_parts(replace(DONE, lighthouse_deck=False), MANIFEST)["lighthouse"] \
            == "absent"


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
    def test_a_new_drone_gets_all_four_in_order_then_the_unplug_then_the_marker(self):
        rig = Rig(FRESH)
        state = rig.run("install")
        assert rig.flashed == ["main", "lighthouse", "camera", "wifi"]
        assert rig.unplugged, "the check must wait for a real unplug"
        assert rig.marked == [(MANIFEST["bundle"], DECK_A)]
        assert state["phase"] == "done"

    def test_a_drone_with_no_positioning_deck_is_set_up_without_it(self):
        rig = Rig(replace(FRESH, lighthouse_deck=False, lighthouse_needs_fw=False))
        state = rig.run("install")
        assert rig.flashed == ["main", "camera", "wifi"]
        assert state["phase"] == "done" and state["parts"]["lighthouse"] == "absent"

    def test_the_deck_is_asked_again_after_main_because_main_names_its_image(self):
        rig = Rig(replace(DONE, fw_version=None), main_asks_for_deck_fw=True)
        state = rig.run("install")
        assert rig.flashed == ["main", "lighthouse"]
        assert state["phase"] == "done"

    def test_a_deck_that_still_asks_after_the_write_is_reported(self):
        rig = Rig(FRESH, deck_takes_fw=False)
        state = rig.run("install")
        assert state["phase"] == "failed" and "still asks for its firmware" in state["message"]
        assert rig.flashed == ["main", "lighthouse"]

    def test_a_deck_that_loses_its_firmware_on_the_unplug_is_reported(self):
        rig = Rig(FRESH, deck_keeps_fw=False)
        state = rig.run("install")
        assert state["phase"] == "failed" and "lost its firmware" in state["message"]
        assert rig.marked == []

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


class TestADeckIsToldApartByItsSerial:
    def test_the_digest_is_stable_never_zero_and_ignores_case(self):
        assert deck_id("2d3f8a1c00000062") == DECK_A
        assert DECK_A != DECK_B
        assert all(deck_id(f"{n:016X}") != 0 for n in range(2000))

    def test_a_swapped_deck_needs_its_camera_and_wifi_and_nothing_else(self):
        assert needed_parts(SWAPPED, MANIFEST) == {
            "main": "installed", "lighthouse": "installed",
            "camera": "needed", "wifi": "needed"}
        assert deck_unrecorded(SWAPPED, MANIFEST)

    def test_the_deck_it_was_set_up_on_needs_nothing(self):
        assert set(needed_parts(DONE, MANIFEST).values()) == {"installed"}
        assert not deck_unrecorded(DONE, MANIFEST)

    def test_a_drone_from_before_decks_were_recorded_sets_its_deck_up_once_more(self):
        # drone_wifi v2: the bundle is on record, the deck it was put on is not.
        v2 = replace(DONE, fw_version=2, deck_id_marker=None)
        assert needed_parts(v2, MANIFEST) == {
            "main": "needed", "lighthouse": "installed",
            "camera": "needed", "wifi": "needed"}

    def test_a_serial_that_could_not_be_read_leaves_the_bundle_marker_to_decide(self):
        unread = replace(DONE, ai_deck_id=None, deck_id_marker=0)
        assert needed_parts(unread, MANIFEST)["camera"] == "installed"
        assert not deck_unrecorded(unread, MANIFEST)

    def test_a_check_says_the_deck_is_not_the_one_on_record(self):
        state = Rig(SWAPPED).run("check")
        assert state["phase"] == "ready" and state["facts"]["deck_unrecorded"] is True

    def test_a_swapped_deck_is_installed_and_recorded_as_the_new_deck(self):
        rig = Rig(SWAPPED)
        state = rig.run("install")
        assert rig.flashed == ["camera", "wifi"]
        assert rig.unplugged
        assert rig.marked == [(MANIFEST["bundle"], DECK_B)]
        assert state["phase"] == "done" and state["facts"]["deck_unrecorded"] is False
        # and the next check finds it set up
        assert Rig(rig.facts).run("check")["phase"] == "done"

    def test_the_deck_recorded_is_the_one_read_after_the_unplug(self):
        rig = Rig(SWAPPED)
        probe = rig.probe

        def swapped_during_unplug():
            facts = probe()
            if facts is not None and rig.unplugged:
                return replace(facts, ai_deck_id=DECK_A)
            return facts

        rig.setup._probe = swapped_during_unplug
        rig.run("install")
        assert rig.marked == [(MANIFEST["bundle"], DECK_A)]

    def test_an_unread_serial_is_recorded_as_none(self):
        rig = Rig(replace(FRESH, ai_deck_id=None))
        rig.run("install")
        assert rig.marked == [(MANIFEST["bundle"], 0)]


class TestReinstallAnyway:
    def test_one_deck_part_brings_the_other(self):
        assert reinstall_set(["camera"]) == {"camera", "wifi"}
        assert reinstall_set(["wifi", "main"]) == {"camera", "wifi", "main"}
        assert reinstall_set([]) == frozenset()

    def test_an_unknown_part_is_refused_by_name(self):
        with pytest.raises(SetupError, match="gap8"):
            reinstall_set(["gap8"])

    def test_nothing_asked_on_a_set_up_drone_changes_nothing(self):
        rig = Rig(DONE)
        state = rig.run("install")
        assert rig.flashed == [] and state["phase"] == "done"

    def test_the_camera_again_writes_both_deck_parts_then_the_unplug_and_record(self):
        rig = Rig(DONE)
        state = rig.run("install", ["camera"])
        assert rig.flashed == ["camera", "wifi"]
        assert rig.unplugged and rig.marked == [(MANIFEST["bundle"], DECK_A)]
        assert state["phase"] == "done"

    def test_the_drone_firmware_again_needs_no_unplug(self):
        rig = Rig(DONE)
        state = rig.run("install", ["main"])
        assert rig.flashed == ["main"]
        assert not rig.unplugged and rig.marked == []
        assert state["phase"] == "done"

    def test_a_positioning_deck_asked_for_again_is_not_overruled_after_main(self):
        # After main the deck is normally asked again — and answers it is fine.
        rig = Rig(DONE)
        rig.run("install", ["main", "lighthouse"])
        assert rig.flashed == ["main", "lighthouse"]

    def test_a_deck_that_is_not_fitted_is_not_written(self):
        rig = Rig(replace(DONE, lighthouse_deck=False))
        state = rig.run("install", ["lighthouse"])
        assert rig.flashed == [] and state["parts"]["lighthouse"] == "absent"

    def test_everything_again_runs_in_the_usual_order(self):
        rig = Rig(DONE)
        rig.run("install", ["main", "lighthouse", "camera", "wifi"])
        assert rig.flashed == ["main", "lighthouse", "camera", "wifi"]

    def test_reinstalling_still_refuses_a_low_battery(self):
        rig = Rig(replace(DONE, battery_v=3.7))
        state = rig.run("install", ["camera"])
        assert state["phase"] == "failed" and rig.flashed == []

    def test_an_unknown_part_is_refused_before_the_radio_is_taken(self):
        rig = Rig(DONE)
        with pytest.raises(SetupError):
            rig.setup.install(["gap8"])
        assert rig.radio == []
