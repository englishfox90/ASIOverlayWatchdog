"""
Colorize processing modules for PFRSentinel stretch/color tuning.

This package provides:
- io_utils: FITS loading, normalization, output writing
- measurement: Corner ROI stats, mode classification, quality metrics
- transforms: Stretch, bias correction, denoise, color injection
- recipes: Mode-aware effective parameter computation
"""

from .io_utils import load_fits, to_hwc_rgb, normalize_if_int, save_output_image
from .measurement import (
    estimate_bias_sigma_from_corners,
    estimate_rgb_bias_from_corners,
    classify_mode_from_lum,
    compute_quality_metrics,
)
from .transforms import (
    stretch_mono,
    stretch_rgb_using_lum_points,
    inject_chroma_into_luminance,
    hot_pixel_dab_lum,
    shadow_luma_denoise,
    blur_chroma_only,
    blue_suppress_chroma,
    desaturate_global,
    midtone_white_balance,
)
from .recipes import compute_effective_params, MODE_DEFAULTS

__all__ = [
    # io
    "load_fits", "to_hwc_rgb", "normalize_if_int", "save_output_image",
    # measurement
    "estimate_bias_sigma_from_corners", "estimate_rgb_bias_from_corners",
    "classify_mode_from_lum", "compute_quality_metrics",
    # transforms
    "stretch_mono", "stretch_rgb_using_lum_points", "inject_chroma_into_luminance",
    "hot_pixel_dab_lum", "shadow_luma_denoise", "blur_chroma_only",
    "blue_suppress_chroma", "desaturate_global", "midtone_white_balance",
    # recipes
    "compute_effective_params", "MODE_DEFAULTS",
]
