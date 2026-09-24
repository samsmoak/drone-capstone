"""The camera path, proven without a camera.

The AI deck is fitted on this drone and its Wi-Fi link has never worked, so
there is no source of real frames. Everything downstream of that one link is
ordinary work, and these tests pin it — so that when a lab session works out how
to reach the deck, only one class has to be written.
"""

from __future__ import annotations

import struct

from cropwatcher.camera.source import (
    FRAME_H,
    FRAME_W,
    CameraStatus,
    NoCamera,
)

# Aliased: pytest tries to COLLECT anything named Test*, and warns that it
# cannot because the class takes constructor arguments.
from cropwatcher.camera.source import TestPattern as PatternSource

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TestNoCamera:
    """The honest default, and the one this drone actually has."""

    def test_it_produces_no_frame(self):
        assert NoCamera().frame() is None

    def test_it_says_why_in_words_an_operator_can_read(self):
        status = NoCamera().status()
        assert status.live is False
        assert status.kind == "none"
        assert status.reason and "datalink" in status.reason.lower()

    def test_deck_fitted_is_unknown_until_a_drone_is_asked(self):
        """None is not False. Nothing has asked yet, and recording a guess as a
        measurement is the failure CLAUDE.md #5 exists to stop."""
        assert NoCamera().status().deck_fitted is None


class TestGeneratedPattern:
    def test_it_produces_a_valid_png_of_the_deck_s_size(self):
        frame = PatternSource().frame()
        assert frame is not None
        assert frame[:8] == PNG_MAGIC
        # IHDR width/height live at a fixed offset in a minimal PNG.
        width, height = struct.unpack(">II", frame[16:24])
        assert (width, height) == (FRAME_W, FRAME_H)

    def test_every_frame_differs_from_the_last(self):
        """A still image cannot tell a live feed from a frozen one, which is the
        exact failure this pattern is here to rehearse."""
        source = PatternSource()
        frames = [source.frame() for _ in range(3)]
        assert len(set(frames)) == 3

    def test_it_reports_itself_as_a_test_pattern(self):
        status = PatternSource().status()
        assert status.live is True
        assert status.kind == "test-pattern"
        assert status.reason is None

    def test_the_content_type_matches_what_it_encodes(self):
        assert PatternSource().content_type == "image/png"


class TestCameraStatus:
    def test_it_serialises_every_field_the_window_reads(self):
        payload = CameraStatus(
            live=False, kind="none", reason="no link", deck_fitted=True
        ).to_dict()
        assert payload == {
            "live": False, "kind": "none", "reason": "no link", "deck_fitted": True,
            "width": None, "height": None,
        }
