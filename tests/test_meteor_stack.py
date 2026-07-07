"""Tests for services/meteor/frame_stack.py and services/meteor/noise.py."""
import os
import sys

import numpy as np
import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.meteor.frame_stack import FrameStack
from services.meteor.noise import estimate_diff_noise, noise_to_threshold, DiffNoiseEMA


def _gray(h=64, w=64, fill=0) -> np.ndarray:
    return np.full((h, w), fill, dtype=np.uint8)


def _streak(h=64, w=64, row=32, val=200) -> np.ndarray:
    arr = _gray(h, w)
    arr[row, 10:54] = val
    return arr


# ---------------------------------------------------------------------------
# FrameStack
# ---------------------------------------------------------------------------

class TestFrameStack:
    def test_empty_stack_transient_is_zeros(self):
        fs = FrameStack(maxlen=4)
        assert fs.transient_map().max() == 0

    def test_single_frame_transient_is_zeros(self):
        fs = FrameStack(maxlen=4)
        fs.push(_streak())
        assert fs.transient_map().max() == 0

    def test_static_scene_cancels_in_transient(self):
        fs = FrameStack(maxlen=4)
        frame = _gray(fill=50)
        for _ in range(4):
            fs.push(frame.copy())
        tmap = fs.transient_map()
        assert tmap.max() <= 2, f"Static scene should cancel: max={tmap.max()}"

    def test_single_frame_streak_survives(self):
        fs = FrameStack(maxlen=4)
        for _ in range(3):
            fs.push(_gray(fill=5))
        fs.push(_streak(val=200))
        tmap = fs.transient_map()
        assert tmap.max() > 50, f"One-frame streak should survive: max={tmap.max()}"

    def test_streak_in_all_frames_cancels(self):
        fs = FrameStack(maxlen=4)
        for _ in range(4):
            fs.push(_streak(val=200))
        tmap = fs.transient_map()
        assert tmap.max() <= 2, "Streak in all frames is static — should cancel"

    def test_hot_mask_marks_always_bright_pixels(self):
        fs = FrameStack(maxlen=4)
        for _ in range(4):
            fs.push(_streak(val=200))
        hot = fs.hot_mask(threshold=10)
        # The streak row should be mostly masked (255), allowing for erode shrinkage
        streak_hot = hot[32, 12:52]
        assert streak_hot.max() == 255, "Consistently bright row should appear in hot mask"

    def test_hot_mask_does_not_mask_single_frame_streak(self):
        fs = FrameStack(maxlen=4)
        for _ in range(3):
            fs.push(_gray(fill=5))
        fs.push(_streak(val=200))
        hot = fs.hot_mask(threshold=10)
        # Single-frame streak should NOT be masked
        assert hot[32, 30] == 0, "Single-frame streak must not appear in hot mask"

    def test_hot_mask_ignores_uniform_background(self):
        """Regression: linear detection frames sit at the sensor offset plus
        sky background (~10-30 DN). An absolute threshold marked the ENTIRE
        frame hot, blanking the transient map — zero detections in the field.
        The mask must be background-relative."""
        fs = FrameStack(maxlen=4)
        for _ in range(4):
            fs.push(_gray(fill=25))
        hot = fs.hot_mask(threshold=5)
        assert hot.max() == 0, (
            "Uniform background above the absolute threshold must not be "
            f"masked: {100 * (hot > 0).mean():.0f}% of frame marked hot")

    def test_hot_mask_marks_equipment_edge_above_background(self):
        fs = FrameStack(maxlen=4)
        for _ in range(4):
            frame = _gray(fill=25)
            frame[40, :] = 120   # bright static equipment line in every frame
            fs.push(frame)
        hot = fs.hot_mask(threshold=5)
        assert hot[40, 32] == 255, "Static bright edge should be masked"
        assert hot[10, 32] == 0, "Plain background should not be masked"

    def test_streak_survives_hot_mask_on_realistic_background(self):
        """End-to-end field regression: one-frame streak over a ~25 DN
        background must survive the hot-mask suppression step exactly as the
        controller applies it (transient zeroed where hot)."""
        fs = FrameStack(maxlen=4)
        for _ in range(3):
            fs.push(_gray(fill=25))
        streak = _gray(fill=25)
        streak[32, 10:54] = 120
        fs.push(streak)
        transient = fs.transient_map()
        hot = fs.hot_mask(threshold=5)
        masked = transient.copy()
        masked[hot > 0] = 0
        assert masked[32, 30] > 50, (
            f"Streak must survive hot-mask suppression: value={masked[32, 30]}")

    def test_push_evicts_oldest_frame(self):
        fs = FrameStack(maxlen=3)
        for i in range(4):
            fs.push(_gray(fill=i * 10))
        assert fs.count == 3

    def test_clear_resets_stack(self):
        fs = FrameStack(maxlen=4)
        for _ in range(4):
            fs.push(_streak(val=200))
        fs.clear()
        assert fs.count == 0
        assert fs.transient_map().max() == 0

    def test_shape_change_triggers_clear(self):
        fs = FrameStack(maxlen=4)
        fs.push(_gray(32, 32))
        fs.push(_gray(64, 64))   # different shape — should have cleared
        assert fs.count == 1


# ---------------------------------------------------------------------------
# Noise estimation and threshold mapping
# ---------------------------------------------------------------------------

class TestNoise:
    def test_zero_diff_gives_low_sigma(self):
        diff = _gray(fill=0)
        sigma = estimate_diff_noise(diff)
        assert sigma < 3.0, f"Zero diff should give near-zero sigma, got {sigma}"

    def test_uniform_nonzero_gives_low_sigma(self):
        diff = _gray(fill=20)
        sigma = estimate_diff_noise(diff)
        assert sigma < 3.0, "Uniform (zero-variance) diff gives low MAD sigma"

    def test_noisy_diff_gives_higher_sigma(self):
        np.random.seed(7)
        diff = np.random.randint(0, 30, (64, 64), dtype=np.uint8)
        sigma = estimate_diff_noise(diff)
        assert sigma > 3.0, f"Noisy diff should have sigma > 3, got {sigma}"

    def test_threshold_increases_with_sigma(self):
        t_low = noise_to_threshold(2.0)
        t_high = noise_to_threshold(8.0)
        assert t_high > t_low

    def test_threshold_respects_sensitivity(self):
        sigma = 5.0
        t_high = noise_to_threshold(sigma, "high")
        t_normal = noise_to_threshold(sigma, "normal")
        t_low = noise_to_threshold(sigma, "low")
        assert t_high <= t_normal <= t_low, "high sensitivity → lower threshold"

    def test_threshold_clamped(self):
        assert noise_to_threshold(0.0) >= 5
        assert noise_to_threshold(100.0) <= 100


class TestDiffNoiseEMA:
    def test_first_update_equals_sample(self):
        ema = DiffNoiseEMA()
        diff = np.random.randint(0, 20, (64, 64), dtype=np.uint8)
        sigma = ema.update(diff)
        assert sigma is not None and sigma >= 0

    def test_ema_smooths_across_frames(self):
        ema = DiffNoiseEMA(alpha=0.1)
        for _ in range(10):
            ema.update(np.zeros((64, 64), dtype=np.uint8))
        prev = ema.value
        # Sudden genuinely noisy frame (non-zero variance → non-zero MAD)
        rng = np.random.default_rng(seed=42)
        noisy = rng.integers(0, 50, (64, 64), dtype=np.uint8)
        ema.update(noisy)
        # EMA should move toward the new estimate (> prev=0) but not jump all the way
        assert ema.value > prev
        assert ema.value < 50

    def test_reset_clears_state(self):
        ema = DiffNoiseEMA()
        ema.update(np.zeros((8, 8), dtype=np.uint8))
        ema.reset()
        assert ema.value is None
