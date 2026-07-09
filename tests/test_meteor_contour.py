"""Tests for services/meteor/contour_streaks.py — contour-based streak finder."""
import numpy as np
import cv2
from PIL import Image

from services.meteor.contour_streaks import detect_streaks_contour, _circularity


def _transient_with_streak(size=200, x1=30, y1=100, x2=170, y2=110, width=2):
    """Black transient map with one bright thin streak, mimicking max-mean output."""
    arr = np.zeros((size, size), np.uint8)
    cv2.line(arr, (x1, y1), (x2, y2), 255, width)
    return Image.fromarray(arr)


def test_detects_a_thin_streak():
    img = _transient_with_streak()
    dets = detect_streaks_contour(img, min_length=50, threshold=10)
    assert len(dets) >= 1
    best = max(dets, key=lambda d: d.length)
    # Roughly horizontal, spanning most of the drawn streak length (~140px).
    assert best.length > 100
    assert abs(best.angle_deg) < 20 or abs(abs(best.angle_deg) - 180) < 20


def test_round_blob_is_rejected():
    arr = np.zeros((200, 200), np.uint8)
    cv2.circle(arr, (100, 100), 25, 255, -1)  # filled disc → high circularity
    dets = detect_streaks_contour(Image.fromarray(arr), min_length=50, threshold=10)
    assert dets == []


def test_short_streak_below_min_length_rejected():
    img = _transient_with_streak(x1=90, y1=100, x2=120, y2=100)  # ~30px
    dets = detect_streaks_contour(img, min_length=50, threshold=10)
    assert dets == []


def test_empty_frame_returns_empty():
    img = Image.fromarray(np.zeros((200, 200), np.uint8))
    assert detect_streaks_contour(img, min_length=50, threshold=10) == []


def test_circularity_disc_vs_line():
    # A perfect circle scores near 1; a long thin rectangle scores near 0.
    r = 40
    area_circle = np.pi * r * r
    perim_circle = 2 * np.pi * r
    assert _circularity(area_circle, perim_circle) > 0.9

    length, width = 200, 3
    area_line = length * width
    perim_line = 2 * (length + width)
    assert _circularity(area_line, perim_line) < 0.2
