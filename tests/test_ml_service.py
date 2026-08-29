"""
Tests for services/ml_service.py.

Pins the median_lum / frame_med 16-bit normalization fix (R5): a 16-bit raw
frame must be normalized by its dtype bit-depth (0-65535), not by 255, or the
roof model's median_lum feature lands outside [0,1] and roof predictions flip
(the old "Closed on an open roof" bug).

Also pins the per-frame memory ceiling: analyze_image_for_tokens runs on the
full-resolution frame and used to build four independent grayscale planes, three
of them in float64.
"""
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from services.ml_service import MLService

ML_MODELS_DIR = Path(__file__).parent.parent / "ml" / "models"

# Measured peak for a 3552x3552x3 uint16 frame with both models loaded: 302.8 MB
# before the shared-gray-plane change, 100.9 MB after. The ceiling leaves room
# for allocator noise without letting a second full-frame copy back in.
MEMORY_CEILING_BYTES = 120 * 1000 * 1000


def _frame_med(array):
    # _compute_corner_analysis needs no ML model loaded; it is a pure feature
    # computation, so this exercises the normalization helper directly.
    return MLService()._compute_corner_analysis(array)['frame_med']


def test_frame_med_normalized_by_bit_depth():
    # uint16 mid-grey: 30000 / 65535 ~= 0.4578
    u16 = np.full((64, 64), 30000, dtype=np.uint16)
    assert _frame_med(u16) == pytest.approx(0.4578, abs=1e-3)

    # uint8 mid-grey: 117 / 255 ~= 0.459
    u8 = np.full((64, 64), 117, dtype=np.uint8)
    assert _frame_med(u8) == pytest.approx(0.459, abs=1e-3)


def test_frame_med_landed_in_unit_range_for_dark_16bit_frame():
    # A dark 16-bit frame peaking below 255 must NOT be mistaken for 8-bit:
    # normalization is keyed off dtype, so frame_med stays tiny, not ~1.0.
    dark = np.full((64, 64), 200, dtype=np.uint16)
    val = _frame_med(dark)
    assert 0.0 <= val <= 1.0
    assert val == pytest.approx(200 / 65535, abs=1e-4)


def test_corner_analysis_does_not_mutate_the_caller_frame():
    frame = np.random.default_rng(3).integers(0, 65535, (64, 64, 3)).astype(np.uint16)
    before = frame.copy()
    MLService()._compute_corner_analysis(frame)
    np.testing.assert_array_equal(frame, before)


def _full_res_frame():
    rng = np.random.default_rng(7)
    frame = rng.integers(200, 4000, size=(3552, 3552, 3), dtype=np.uint16)
    frame[1000:1010, 1000:1010, :] = 60000  # a few saturated stars
    return frame


@pytest.mark.slow
@pytest.mark.requires_ml_models
def test_analyze_image_for_tokens_stays_under_memory_ceiling(monkeypatch):
    for model in ("roof_classifier_v1.onnx", "sky_classifier_v1.onnx"):
        if not (ML_MODELS_DIR / model).exists():
            pytest.skip(f"Model not present: {model}")

    from services.ml_service import analyze_image_for_tokens, get_ml_service

    ml = get_ml_service()
    if not ml.initialize() or ml._roof_classifier is None or ml._sky_classifier is None:
        pytest.skip("ML models did not load")

    # Force the sky branch on. The full-resolution stretch is the expensive half
    # of the pipeline, and whether the roof model calls a synthetic frame "open"
    # is not something a memory ceiling should depend on.
    real_predict = ml._roof_classifier.predict

    def force_open(*args, **kwargs):
        result = real_predict(*args, **kwargs)
        result.roof_open = True
        return result

    monkeypatch.setattr(ml._roof_classifier, "predict", force_open)
    # Freeze the moon cache so astral's lazy imports stay outside the trace.
    monkeypatch.setattr(ml, "_moon_cache", (time.time(), {}), raising=False)

    frame = _full_res_frame()
    analyze_image_for_tokens(frame)  # warm up lazy imports and ONNX arenas

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        analyze_image_for_tokens(frame)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak <= MEMORY_CEILING_BYTES, (
        f"analyze_image_for_tokens peaked at {peak / 1e6:.1f} MB, "
        f"ceiling is {MEMORY_CEILING_BYTES / 1e6:.0f} MB"
    )
