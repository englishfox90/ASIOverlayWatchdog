"""Row-banded evaluation of the linked-RGB stretch.

The linked stretch is elementwise apart from five whole-frame reductions
(luminance median, luminance MAD, the 1st luminance percentile, and the median
of the post-clip luminance). Everything else can therefore be evaluated one
band of rows at a time, which keeps the resident footprint to a couple of
single-channel planes instead of several full float32 RGB frames.

The cost is that the clipping arithmetic is evaluated twice — once to build the
post-clip luminance the MTF midtone is derived from, once to produce the output
pixels. That trade is deliberate: peak memory, not CPU, is what limits how
large a frame this app can process.

Every expression here is a transcription of the full-frame version in
``image_stretch.py``, operator for operator, because NEP 50 makes the result
dtype depend on whether a scalar is a Python float (weak) or a NumPy scalar
(strong) — several intermediates here are float64 purely because
``np.clip``/``np.median`` returned NumPy scalars. Rewriting them "more
sensibly" silently changes the rounding of the uint8 result.
"""
from typing import NamedTuple

import numpy as np

from .logger import app_logger

# Target size of one source band in bytes. Small enough that the float64
# temporaries mtf_stretch builds stay incidental, large enough that the
# per-band Python overhead disappears into the vectorised work.
BAND_TARGET_BYTES = 4 * 1024 * 1024


class _ClipPlan(NamedTuple):
    preserve_blacks: bool
    transition_start: object
    transition_end: object
    effective_black_point: object


class FrameSource:
    """Supplies the stretch input as float32 [0, 1] row bands.

    Holds only the caller's original buffer; bands are converted on demand so
    the full float32 frame (3x the size of a uint16 input) is never resident.
    """

    def __init__(self, img, raw_16bit=None):
        self._img = img
        self._raw = raw_16bit if (raw_16bit is not None
                                  and raw_16bit.dtype == np.uint16) else None
        self._cached = None
        if self._raw is not None:
            self.bit_depth_str = "16-bit"
            self.shape = self._raw.shape
            self._scale = 65535.0
        else:
            self.bit_depth_str = "8-bit"
            self.shape = np.asarray(img).shape
            self._scale = 255.0

        channels = self.shape[2] if len(self.shape) == 3 else 1
        per_row = max(1, self.shape[1] * channels * 4)
        self.band_rows = max(1, BAND_TARGET_BYTES // per_row)

    @property
    def is_rgb(self):
        return len(self.shape) == 3 and self.shape[2] == 3

    def _source_array(self):
        if self._raw is not None:
            return self._raw
        if self._cached is None:
            self._cached = np.asarray(self._img)
        return self._cached

    def bands(self):
        height = self.shape[0]
        for start in range(0, height, self.band_rows):
            yield start, min(start + self.band_rows, height)

    def band(self, start, stop):
        chunk = self._source_array()[start:stop].astype(np.float32)
        chunk /= self._scale
        return chunk

    def full(self):
        """Materialise the whole float32 frame (legacy / non-chunked paths)."""
        if self._raw is not None:
            arr = self._raw.astype(np.float32)
        else:
            arr = np.array(self._img, dtype=np.float32)
        arr /= self._scale
        return arr

    def luminance_plane(self):
        """Rec.601 luminance of the whole frame as a single float32 plane."""
        lum = np.empty(self.shape[:2], dtype=np.float32)
        for start, stop in self.bands():
            band = self.band(start, stop)
            lum[start:stop] = (0.299 * band[:, :, 0] + 0.587 * band[:, :, 1]
                               + 0.114 * band[:, :, 2])
        return lum


def _clip_band(band, lum, plan):
    """Apply the shadow-clip / black-preservation stage to one band."""
    effective_black_point = plan.effective_black_point
    out = np.empty_like(band)

    if plan.preserve_blacks and plan.transition_end > plan.transition_start:
        transition_start = plan.transition_start
        transition_end = plan.transition_end

        is_black = lum <= transition_start
        is_transition = (lum > transition_start) & (lum <= transition_end)
        is_normal = lum > transition_end

        # Channel-independent, so it is hoisted out of the channel loop; the
        # full-frame version recomputes it per channel to the same values.
        t = (lum[is_transition] - transition_start) / (transition_end - transition_start)
        t = t * t * (3 - 2 * t)

        for c in range(3):
            channel = band[:, :, c].copy()
            channel[is_black] = 0.0

            orig_val = channel[is_transition]
            stretched_val = (orig_val - effective_black_point) / (1.0 - effective_black_point)
            stretched_val = np.clip(stretched_val, 0, 1)
            channel[is_transition] = t * stretched_val

            normal_vals = channel[is_normal]
            normal_vals = np.clip(normal_vals, effective_black_point, 1.0)
            channel[is_normal] = (normal_vals - effective_black_point) / (1.0 - effective_black_point)

            out[:, :, c] = channel
    else:
        for c in range(3):
            channel = band[:, :, c]
            if effective_black_point > 0:
                channel = np.clip(channel, effective_black_point, 1.0)
                channel = (channel - effective_black_point) / (1.0 - effective_black_point)
            out[:, :, c] = channel

    return out


def _build_clip_plan(luminance, target_median, preserve_blacks, black_point,
                     shadow_aggressiveness):
    median_lum = np.median(luminance)

    deviation = luminance - median_lum
    np.abs(deviation, out=deviation)
    mad_lum = np.median(deviation, overwrite_input=True)
    del deviation
    mad_lum = max(mad_lum, 0.001)

    shadow_clip = max(0.0, median_lum - shadow_aggressiveness * mad_lum)
    shadow_clip = min(shadow_clip, median_lum * 0.8)

    effective_black_point = max(shadow_clip, black_point)

    app_logger.debug(f"Auto-stretch (linked): lum_median={median_lum:.4f}, MAD={mad_lum:.4f}, "
                     f"shadow_clip={shadow_clip:.4f}, black_point={black_point:.4f}")

    transition_start = None
    transition_end = None
    if preserve_blacks:
        transition_start = np.percentile(luminance, 1)
        transition_end = effective_black_point
        app_logger.debug(f"Preserve blacks: true_black={transition_start:.4f}, "
                         f"transition=[{transition_start:.4f}-{transition_end:.4f}]")

    return _ClipPlan(preserve_blacks, transition_start, transition_end,
                     effective_black_point)


def _post_clip_median(source, luminance, plan):
    lum_clipped = np.empty_like(luminance)
    for start, stop in source.bands():
        clipped = _clip_band(source.band(start, stop), luminance[start:stop], plan)
        lum_clipped[start:stop] = (0.299 * clipped[:, :, 0] + 0.587 * clipped[:, :, 1]
                                   + 0.114 * clipped[:, :, 2])
    return np.median(lum_clipped, overwrite_input=True)


def stretch_linked_rgb_to_uint8(source, luminance, target_median,
                                preserve_blacks=True, black_point=0.0,
                                shadow_aggressiveness=2.8):
    """Chunked equivalent of ``_stretch_linked_rgb`` + the ``*255``/uint8 cast.

    Returns an ``(H, W, 3)`` uint8 array bit-identical to what the full-frame
    path produces for the same inputs. *luminance* must be the float32 Rec.601
    luminance plane of *source* (i.e. ``source.luminance_plane()``).
    """
    from .image_stretch import mtf_stretch, _calculate_mtf_midtone

    plan = _build_clip_plan(luminance, target_median, preserve_blacks,
                            black_point, shadow_aggressiveness)

    current_median = _post_clip_median(source, luminance, plan)

    if abs(current_median - target_median) < 0.01:
        app_logger.debug(f"MTF (linked): skipped - already at target (median={current_median:.4f})")
        midtone = None
    else:
        midtone = _calculate_mtf_midtone(current_median, target_median)
        app_logger.debug(f"MTF (linked): post-clip_median={current_median:.4f}, "
                         f"midtone={midtone:.4f}, target={target_median:.3f}")

    height, width = luminance.shape
    out = np.empty((height, width, 3), dtype=np.uint8)

    for start, stop in source.bands():
        clipped = _clip_band(source.band(start, stop), luminance[start:stop], plan)
        if midtone is not None:
            for c in range(3):
                clipped[:, :, c] = mtf_stretch(clipped[:, :, c], midtone)
        np.multiply(clipped, 255.0, out=clipped)
        out[start:stop] = clipped.astype(np.uint8)

    return out
