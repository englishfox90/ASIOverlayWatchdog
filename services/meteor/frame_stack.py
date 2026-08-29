"""
N-frame ring-buffer stack for meteor transient detection.

Core idea (from MetDetPy's M3Detector):
  transient_map = max(stack) − mean(stack)

Static scene: max ≈ mean → diff ≈ 0. Equipment edges, stars, horizon vanish.
Single-frame streak: bright in one frame only → survives at nearly full contrast.
Plane trail: bright in every frame → max ≈ mean → also vanishes (plane is tracked
separately by the persistence filter).

Memory: N uint8 frames + 1 float64 running sum.
For N=6, 1280×960 frames: ≈ 7 MB frames + 9 MB sum ≈ 16 MB. Fine.
"""
from typing import Optional

import cv2
import numpy as np


class FrameStack:
    """
    Ring buffer of grayscale uint8 frames with O(1) running mean and max.

    Args:
        maxlen: Number of frames to retain (≥ 2). Typical value: 5–8.
    """

    def __init__(self, maxlen: int = 6):
        self._maxlen = max(2, maxlen)
        self._frames: list = []
        self._running_sum: Optional[np.ndarray] = None

    # ------------------------------------------------------------------ #
    #  Ingest                                                              #
    # ------------------------------------------------------------------ #

    def push(self, frame: np.ndarray) -> None:
        """
        Add a single-channel uint8 grayscale frame to the stack.

        If the stack is full, the oldest frame is evicted.
        Mismatched shapes (e.g. resolution change) trigger a full clear first.
        """
        if self._running_sum is not None and frame.shape != self._frames[0].shape:
            self.clear()

        f = frame.astype(np.uint8)

        if self._running_sum is None:
            self._running_sum = f.astype(np.float64)
        else:
            if len(self._frames) >= self._maxlen:
                self._running_sum -= self._frames[0].astype(np.float64)
                self._frames.pop(0)
            self._running_sum += f.astype(np.float64)

        self._frames.append(f)

    def clear(self) -> None:
        self._frames.clear()
        self._running_sum = None

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    @property
    def count(self) -> int:
        return len(self._frames)

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def full(self) -> bool:
        return len(self._frames) >= self._maxlen

    # ------------------------------------------------------------------ #
    #  Derived images                                                      #
    # ------------------------------------------------------------------ #

    def mean(self) -> np.ndarray:
        """Float32 per-pixel mean across all frames in the stack."""
        if not self._frames:
            return np.zeros((1, 1), np.float32)
        return (self._running_sum / len(self._frames)).astype(np.float32)

    def max(self) -> np.ndarray:
        """Per-pixel maximum across all frames (uint8)."""
        if not self._frames:
            return np.zeros((1, 1), np.uint8)
        return np.max(np.array(self._frames, dtype=np.uint8), axis=0)

    def transient_map(self) -> np.ndarray:
        """
        Per-pixel max − mean, clipped to [0, 255] uint8.

        Returns a zero array if the stack has fewer than 2 frames.
        Static background cancels; single-frame bright events survive.
        """
        if len(self._frames) < 2:
            shape = self._frames[0].shape if self._frames else (1, 1)
            return np.zeros(shape, np.uint8)
        diff = self.max().astype(np.float32) - self.mean()
        return np.clip(diff, 0, 255).astype(np.uint8)

    def hot_mask(self, threshold: int = 5) -> np.ndarray:
        """
        Binary mask (255 = hot pixel) for pixels that exceed their frame's
        own background (per-frame median) by *threshold* in EVERY frame of
        the current stack.

        These are static artefacts (equipment edges, hot pixels) that should
        be suppressed before Hough detection. The test is background-RELATIVE:
        the linear detection frame's floor sits at the sensor offset plus sky
        background (typically 10–30 DN, and auto-exposure pushes the mean far
        above that), so an absolute `pixel > threshold` test marks the entire
        frame hot and blanks the transient map — no detection can ever fire.

        No erosion is applied — thin equipment lines (the primary target)
        are 1–2 px wide and erosion would remove them from the mask entirely.

        Returns a zero mask if the stack has fewer than 2 frames.
        """
        if len(self._frames) < 2:
            shape = self._frames[0].shape if self._frames else (1, 1)
            return np.zeros(shape, np.uint8)
        stacked = np.array(self._frames, dtype=np.uint8)
        backgrounds = np.median(
            stacked.reshape(stacked.shape[0], -1), axis=1).astype(np.float32)
        limits = backgrounds[:, None, None] + float(threshold)
        hot = np.all(stacked.astype(np.float32) > limits, axis=0)
        return hot.astype(np.uint8) * 255

    def structure_mask(self, threshold: int = 5, min_fraction: float = 0.5,
                       dilate_px: int = 3) -> np.ndarray:
        """
        Binary mask (255 = suppress) for the *slew/drift envelope* of bright
        scene structure — a superset of :meth:`hot_mask`.

        ``hot_mask`` demands a pixel exceed its frame background in EVERY frame,
        so it only catches perfectly-static equipment edges. The dominant
        false-positive class on the pier camera is *moving* bright structure:

          * the Moon drifts ~0.25°/min, so its leading/trailing edge sweeps a
            crescent that is bright in only the newer or older frames;
          * the mount slews between exposures, so a tube/cable edge sits at
            position A early in the stack and position B later.

        In the ``max−mean`` transient map these motion residuals survive and
        HoughLinesP fits them as ~50 px "streaks". This mask marks any pixel
        bright above background in at least *min_fraction* of the stacked
        frames (so a half-stack crescent or either slew position qualifies),
        then dilates by *dilate_px* to bridge the A→B gap and swallow the
        crescent lip. A genuine one-frame meteor lights ≤ ``1/maxlen`` of the
        stack, well under any sane *min_fraction*, so it is never masked.

        Set *dilate_px*=0 and *min_fraction*=1.0 to recover ``hot_mask``.
        Returns a zero mask if the stack has fewer than 2 frames.
        """
        if len(self._frames) < 2:
            shape = self._frames[0].shape if self._frames else (1, 1)
            return np.zeros(shape, np.uint8)
        stacked = np.array(self._frames, dtype=np.uint8)
        backgrounds = np.median(
            stacked.reshape(stacked.shape[0], -1), axis=1).astype(np.float32)
        limits = backgrounds[:, None, None] + float(threshold)
        over = stacked.astype(np.float32) > limits           # (N, H, W) bool
        fraction = over.mean(axis=0)                          # (H, W) in [0, 1]
        mask = (fraction >= float(min_fraction)).astype(np.uint8) * 255
        if dilate_px > 0 and mask.any():
            k = 2 * int(dilate_px) + 1
            mask = cv2.dilate(mask, np.ones((k, k), np.uint8), iterations=1)
        return mask
