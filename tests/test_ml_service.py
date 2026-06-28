"""
Tests for services/ml_service.py.

Pins the median_lum / frame_med 16-bit normalization fix (R5): a 16-bit raw
frame must be normalized by its dtype bit-depth (0-65535), not by 255, or the
roof model's median_lum feature lands outside [0,1] and roof predictions flip
(the old "Closed on an open roof" bug).
"""
import numpy as np
import pytest

from services.ml_service import MLService


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
