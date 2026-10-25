"""Which of a session's frames count as CAPTURED — the auto-capture rule.

Every frame of a session with auto-capture on is still written to disk
(recording.py; a flight cannot be re-run). "Captured" decides which of them go
to Supabase and fill the galleries — and a drone hovering in front of one
wall used to fill them with hundreds of copies of the same picture.

MEASURED on the lab laptop's sessions (2026-10-24), the mean absolute
difference between consecutive frames, in grey levels, on a 4x-downsampled
copy:

    a still scene     p50 0.35 · p90 0.42 · the highest of any still session 1.7
    the drone moving  2 to 50

Sensor noise alone never reached CHANGE_THRESHOLD; movement nearly always
does. In 9 of 11 sessions more than 80 % of consecutive frames were this kind
of near-copy — none byte-identical, so "the same" has to mean "close enough".

THE RULE (2026-10-24, Samuel: "if there are 3 same images captured from the
past three seconds, the new images that are coming, if they do not differ from
the ones that we already have, don't save them"). Each frame is compared with
the LAST CAPTURED one — never the previous frame, or a slow drift would never
look like a change and never be captured:

    first frame               captured
    under MIN_INTERVAL_S      never: at most 2 a second, the pacing decided
                              2026-09-24 for upload size
    holding a point           captured — every inspection point gets its frames
    changed                   captured, and the run of similar ones restarts
    similar                   captured at most once every SIMILAR_EVERY_S, and
                              only the first SIMILAR_RUN in a row
    still for STILL_EVERY_S   one captured anyway, so a long still stretch still
                              shows the camera was working (Samuel: "okay
                              thats fine, if the auto capture is on")

A frame that cannot be decoded falls back to the pacing alone, as before this
rule existed: a capture is never lost to a decoding problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: At most this often — 2 a second, as UPLOAD_FPS was.
MIN_INTERVAL_S = 0.5
#: Mean absolute grey-level difference that counts as a change (see above).
CHANGE_THRESHOLD = 2.0
#: Similar frames: no more often than this, and no more than this many in a row.
SIMILAR_EVERY_S = 1.0
SIMILAR_RUN = 3
#: Nothing has changed for this long: capture one anyway.
STILL_EVERY_S = 30.0
#: Frames are compared at 1/DOWNSAMPLE of their size: noise averages out, and
#: the comparison costs well under a millisecond.
DOWNSAMPLE = 4

#: Why a frame was captured, as written in frames.csv's `why` column.
FIRST, POINT, CHANGE, SIMILAR, STILL, UNDECODED, MANUAL = (
    "first", "point", "change", "similar", "still", "undecoded", "manual")


def small_grey(data: bytes) -> Any | None:
    """The frame as a small greyscale array (numpy, int16), or None when it
    cannot be decoded. PNG and JPEG alike — whatever the deck sent."""
    try:
        import cv2
        import numpy as np
    except ImportError:                                   # pragma: no cover
        return None
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    h, w = image.shape
    small = cv2.resize(image, (max(1, w // DOWNSAMPLE), max(1, h // DOWNSAMPLE)),
                       interpolation=cv2.INTER_AREA)
    return small.astype(np.int16)


def change(a: Any, b: Any) -> float | None:
    """Mean absolute difference in grey levels; None when they cannot be
    compared (a different size: the camera changed format)."""
    if a is None or b is None or a.shape != b.shape:
        return None
    import numpy as np
    return float(np.mean(np.abs(a - b)))


@dataclass(frozen=True)
class Decision:
    captured: bool
    why: str | None
    #: The difference from the last captured frame, when it was measured.
    change: float | None


class CaptureRule:
    """The rule above, one session long. Not thread-safe: the recording calls
    it under its own lock."""

    def __init__(self) -> None:
        self._ref: Any | None = None
        self._last_t: float | None = None
        self._similar_run = 0

    def decide(self, t: float, image: Any | None, holding_point: bool) -> Decision:
        """Whether the frame at `t` (seconds into the session) is captured.
        Nothing changes until commit(): a frame the disk refuses must not
        become the reference."""
        if self._last_t is None:
            return Decision(True, FIRST, None)
        since = t - self._last_t
        if since < MIN_INTERVAL_S:
            return Decision(False, None, None)
        if image is None:
            return Decision(True, UNDECODED, None)
        diff = change(image, self._ref)
        if holding_point:
            return Decision(True, POINT, diff)
        if diff is None or diff >= CHANGE_THRESHOLD:
            return Decision(True, CHANGE, diff)
        if self._similar_run < SIMILAR_RUN and since >= SIMILAR_EVERY_S:
            return Decision(True, SIMILAR, diff)
        if since >= STILL_EVERY_S:
            return Decision(True, STILL, diff)
        return Decision(False, None, diff)

    def commit(self, t: float, image: Any | None, why: str) -> None:
        """The captured frame was written: it is the reference from now on."""
        self._last_t = t
        if image is not None:
            self._ref = image
        if why in (FIRST, CHANGE, UNDECODED):
            self._similar_run = 0
        elif why == SIMILAR:
            self._similar_run += 1
