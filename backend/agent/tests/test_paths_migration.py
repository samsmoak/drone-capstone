"""The one-time data-folder migration from the old CropWatcher name to DroneDeck
(dronedeck/paths.py). The app was renamed in stages; the data folder moved on
2026-10-25, and an existing install's flights, results and sign-in must come with
it. _migrate_legacy is per-entry on purpose, so it is safe when the desktop shell
created the new folder (its launch log) before the agent ran.
"""

from __future__ import annotations

from pathlib import Path

from dronedeck.paths import APP_NAME, LEGACY_APP_NAME, _migrate_legacy


def _seed(folder: Path) -> None:
    (folder / "flights").mkdir(parents=True)
    (folder / "flights" / "a.csv").write_text("flight")
    (folder / "results").mkdir()
    (folder / "sign_in.json").write_text("token")


def test_migrates_a_whole_legacy_folder(tmp_path: Path) -> None:
    _seed(tmp_path / LEGACY_APP_NAME)
    _migrate_legacy(tmp_path)
    new = tmp_path / APP_NAME
    assert (new / "flights" / "a.csv").read_text() == "flight"
    assert (new / "results").is_dir()
    assert (new / "sign_in.json").read_text() == "token"


def test_keeps_what_the_new_folder_already_has(tmp_path: Path) -> None:
    # The shell wrote a log into the new folder before the agent migrated.
    _seed(tmp_path / LEGACY_APP_NAME)
    new = tmp_path / APP_NAME
    (new / "logs").mkdir(parents=True)
    (new / "logs" / "shell.log").write_text("launch")
    (tmp_path / LEGACY_APP_NAME / "logs").mkdir()
    (tmp_path / LEGACY_APP_NAME / "logs" / "agent.log").write_text("old")
    _migrate_legacy(tmp_path)
    # The precious entries still move across...
    assert (new / "flights" / "a.csv").read_text() == "flight"
    assert (new / "sign_in.json").read_text() == "token"
    # ...and the shell's new log is not clobbered by the old one.
    assert (new / "logs" / "shell.log").read_text() == "launch"
    assert not (new / "logs" / "agent.log").exists()


def test_no_legacy_folder_is_a_no_op(tmp_path: Path) -> None:
    _migrate_legacy(tmp_path)
    assert not (tmp_path / APP_NAME).exists()
