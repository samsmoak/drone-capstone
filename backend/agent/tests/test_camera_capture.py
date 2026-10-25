"""camera/capture.py: which frames count as captured."""

from __future__ import annotations

import cv2
import numpy as np

from dronedeck.camera.capture import (
    CHANGE,
    CHANGE_THRESHOLD,
    FIRST,
    MIN_INTERVAL_S,
    POINT,
    SIMILAR,
    SIMILAR_EVERY_S,
    SIMILAR_RUN,
    STILL,
    STILL_EVERY_S,
    UNDECODED,
    CaptureRule,
    change,
    small_grey,
)


def scene(level: int, noise: int = 0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((61, 81), level, np.int16)
    if noise:
        img = img + rng.integers(-noise, noise + 1, img.shape).astype(np.int16)
    return img


def run(rule: CaptureRule, t: float, img, holding: bool = False):
    d = rule.decide(t, img, holding)
    if d.captured:
        assert d.why is not None
        rule.commit(t, img, d.why)
    return d


def test_the_first_frame_is_captured():
    d = CaptureRule().decide(0.0, scene(100), False)
    assert d.captured and d.why == FIRST


def test_never_more_often_than_the_pacing():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    d = rule.decide(MIN_INTERVAL_S / 2, scene(200), False)     # a big change, too soon
    assert not d.captured


def test_a_change_is_captured():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    d = run(rule, 1.0, scene(100 + int(CHANGE_THRESHOLD) + 3))
    assert d.captured and d.why == CHANGE
    assert d.change is not None and d.change >= CHANGE_THRESHOLD


def test_three_similar_then_nothing_until_it_changes():
    rule = CaptureRule()
    run(rule, 0.0, scene(100, noise=1))
    captured = []
    t = 0.0
    for i in range(1, 60):                       # 0.25 s apart for ~15 s, all similar
        t = i * 0.25
        d = run(rule, t, scene(100, noise=1, seed=i))
        if d.captured:
            captured.append((t, d.why))
    assert [w for _, w in captured] == [SIMILAR] * SIMILAR_RUN
    times = [t for t, _ in captured]
    assert all(b - a >= SIMILAR_EVERY_S for a, b in zip(times, times[1:], strict=False))
    # ...and a real change is captured at once, restarting the run.
    d = run(rule, t + 0.5, scene(160))
    assert d.why == CHANGE
    d = run(rule, t + 1.5, scene(160, noise=1, seed=99))
    assert d.why == SIMILAR


def test_compared_with_the_last_captured_frame_so_slow_drift_counts():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    for i in range(SIMILAR_RUN):
        run(rule, 1.0 + i, scene(100))
    # Each step is under the threshold from the one before — but not from the
    # last captured frame, which stays at 100.
    level, t, whys = 100, 10.0, []
    for _ in range(4):
        level += 1
        t += 0.6
        whys.append(run(rule, t, scene(level)).why)
    assert CHANGE in whys


def test_a_long_still_stretch_captures_one_anyway():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    for i in range(SIMILAR_RUN):
        run(rule, 1.0 + i, scene(100))
    last = float(SIMILAR_RUN)
    assert not rule.decide(last + STILL_EVERY_S - 1, scene(100), False).captured
    d = run(rule, last + STILL_EVERY_S, scene(100))
    assert d.why == STILL


def test_holding_a_point_captures_similar_frames_too():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    for i in range(SIMILAR_RUN):
        run(rule, 1.0 + i, scene(100))
    d = run(rule, 10.0, scene(100), holding=True)
    assert d.why == POINT


def test_an_undecodable_frame_falls_back_to_the_pacing():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    assert run(rule, MIN_INTERVAL_S, None).why == UNDECODED


def test_a_frame_of_another_size_counts_as_a_change():
    assert change(scene(100), np.zeros((10, 10), np.int16)) is None
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    assert run(rule, 1.0, np.zeros((10, 10), np.int16)).why == CHANGE


def test_a_refused_write_does_not_become_the_reference():
    rule = CaptureRule()
    run(rule, 0.0, scene(100))
    d = rule.decide(1.0, scene(150), False)      # decided, never committed
    assert d.why == CHANGE
    assert rule.decide(1.5, scene(150), False).why == CHANGE


def test_small_grey_decodes_png_and_jpeg_alike():
    img = np.full((244, 324), 90, np.uint8)
    ok_png, png = cv2.imencode(".png", img)
    ok_jpg, jpg = cv2.imencode(".jpg", img)
    assert ok_png and ok_jpg
    for data in (png.tobytes(), jpg.tobytes()):
        small = small_grey(data)
        assert small is not None and small.shape == (61, 81)
    assert small_grey(b"not an image") is None
