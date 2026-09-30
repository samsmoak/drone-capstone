"""MANUAL FLIGHT CONTROL IS LOCKED — only Samuel (the owner) changes it.

2026-09-30: "no one should change the manual flight control unless I want to
make that change". It flies right as it is (docs/features/backend/manual-
control.txt, "HOW TO FLY IT"); every well-meant change that day lost the drone.

This test fingerprints the files that decide how the keys fly the drone. Any
edit to them fails it — on purpose. If Samuel asked for the change, update the
fingerprint below IN THE SAME PULL REQUEST, which he reviews (.github/
CODEOWNERS) and only he can merge. If he did not, undo the change. Never
update a fingerprint to make this pass without his say-so. CLAUDE.md, "Manual
flight control is locked".
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

#: sha256 of each locked file, line endings normalised to \n so a Windows
#: checkout (CRLF) fingerprints the same. Locked 2026-09-30 at main ecfb3dc.
LOCKED: dict[str, str] = {
    "backend/agent/cropwatcher/flight/manual.py":
        "f3c59f9798b202c65e00f5d99c7a169e2da69f78fd4fe7096910389d79612c62",
    "backend/agent/cropwatcher/flight/keyframe.py":
        "705d999f2d70966aa582e206d81ac06a62a4eae0357008dded17b4c55819fc41",
    "backend/agent/cropwatcher/flight/tuning.py":
        "0e598dd8a528cd8211d6f5bf78ff009e8c0e662642ed240bdf925fdac5c3568f",
    "desktop/src/lib/keys.ts":
        "c8c96e292a43da80611d7dc9ffc3b414f8fe2289b81268344d410de38af4a9dd",
}


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@pytest.mark.parametrize("relative", sorted(LOCKED))
def test_manual_flight_control_is_unchanged(relative: str) -> None:
    path = REPO / relative
    assert path.is_file(), f"{relative} is missing — it is part of the locked manual control"
    assert fingerprint(path) == LOCKED[relative], (
        f"{relative} changed, and MANUAL FLIGHT CONTROL IS LOCKED: only Samuel "
        f"(the owner) changes it. If he asked for this change, update its "
        f"fingerprint in tests/test_manual_control_lock.py in the same pull "
        f"request for his review. If he did not, undo it. See CLAUDE.md, "
        f'"Manual flight control is locked".'
    )


def test_the_lock_is_written_where_everyone_reads_it() -> None:
    assert "Manual flight control is locked" in (REPO / "CLAUDE.md").read_text()
    owners = (REPO / ".github" / "CODEOWNERS").read_text()
    assert all(f"/{relative}" in owners for relative in LOCKED)
