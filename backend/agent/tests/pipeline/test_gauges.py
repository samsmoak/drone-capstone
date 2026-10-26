"""The reticle remover and the pressure gauge reader (stage 3, story 4.4):
classify/reticle.py and classify/pressure_gauge.py. Both are geometric, not learned.
"""

from __future__ import annotations

import numpy as np

from cropwatcher.pipeline.stages.classify import pressure_gauge, status_gauge
from cropwatcher.pipeline.stages.classify.reticle import remove_reticle


def test_reticle_arms_are_removed_and_a_clean_image_is_untouched() -> None:
    clean = np.full((244, 324), 120, np.uint8)
    marked = clean.copy()
    marked[122, 150:175] = 0                  # inside the arms' reach at this size
    marked[110:135, 162] = 0
    assert np.array_equal(remove_reticle(clean), clean)
    cleaned = remove_reticle(marked)
    assert cleaned.shape == marked.shape
    centre = (slice(110, 135), slice(150, 175))
    assert int(np.abs(cleaned[centre].astype(int) - 120).max()) < 20


def test_a_blank_frame_is_an_error_reading_not_an_exception() -> None:
    blank = np.full((244, 324), 128, np.uint8)
    for reading in (pressure_gauge.read_gauge(blank), status_gauge.read_gauge(blank)):
        assert reading.error and reading.label.startswith("ERROR")


def test_the_fault_bands_are_inclusive_where_they_say() -> None:
    for kpa, faulty in ((399.9, False), (400.0, True), (600.0, True)):
        assert pressure_gauge.Reading(kpa).faulty is faulty
    for value, danger in ((69.9, False), (70.0, True), (100.0, True)):
        assert status_gauge.Reading(value).danger is danger
