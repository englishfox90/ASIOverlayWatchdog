"""
Mode-aware recipe computation for effective parameters.

Provides sensible defaults per mode and computes "effective" values
when auto mode is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class RecipeParams:
    """All tunable parameters for the colorize pipeline."""

    # Stretch
    black_pct: float = 5.0
    white_pct: float = 99.9
    asinh: float = 30.0
    gamma: float = 1.05

    # Color
    color_strength: float = 1.20
    chroma_clip: float = 0.55
    blue_suppress: float = 0.92
    blue_floor: float = 0.020
    desaturate: float = 0.05

    # Corner overscan
    corner_roi: int = 50
    corner_margin: int = 5
    corner_sigma_bp: float = 0.0  # Noise floor gate

    # RGB bias
    rgb_bias_subtract: bool = True

    # Hot pixel dab
    hp_dab: bool = False
    hp_k: float = 11.0
    hp_max_luma: float = 0.25

    # Shadow denoise
    shadow_denoise: float = 0.0
    shadow_start: float = 0.02
    shadow_end: float = 0.14

    # Chroma blur
    chroma_blur: int = 0

    # Midtone white balance (for day modes)
    midtone_wb: bool = False
    midtone_wb_strength: float = 0.6

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Mode-specific default recipes based on testing
MODE_DEFAULTS: dict[str, RecipeParams] = {
    "NIGHT_ROOF_CLOSED": RecipeParams(
        black_pct=5.0,
        white_pct=99.9,
        asinh=30.0,
        gamma=1.05,
        color_strength=1.20,
        chroma_clip=0.55,
        blue_suppress=0.92,
        blue_floor=0.020,
        desaturate=0.05,
        corner_sigma_bp=1.0,
        rgb_bias_subtract=True,
        hp_dab=True,
        hp_k=11.0,
        hp_max_luma=0.25,
        shadow_denoise=0.25,
        shadow_start=0.02,
        shadow_end=0.14,
        chroma_blur=1,
        midtone_wb=False,
    ),
    "NIGHT_ROOF_CLOSED_VERY_DARK": RecipeParams(
        # For p99 < 0.05 frames (extreme low light)
        black_pct=5.0,
        white_pct=99.9,
        asinh=30.0,
        gamma=1.05,
        color_strength=1.20,
        chroma_clip=0.55,
        blue_suppress=0.85,
        blue_floor=0.020,
        desaturate=0.05,
        corner_sigma_bp=1.5,
        rgb_bias_subtract=True,
        hp_dab=True,
        hp_k=7.0,
        hp_max_luma=0.35,
        shadow_denoise=0.80,
        shadow_start=0.0,
        shadow_end=0.30,
        chroma_blur=6,
        midtone_wb=False,
    ),
    "NIGHT_ROOF_OPEN": RecipeParams(
        black_pct=3.0,
        white_pct=99.9,
        asinh=25.0,
        gamma=1.08,
        color_strength=1.15,
        chroma_clip=0.60,
        blue_suppress=0.80,
        blue_floor=0.015,
        desaturate=0.03,
        corner_sigma_bp=0.5,
        rgb_bias_subtract=True,
        hp_dab=True,
        hp_k=12.0,
        hp_max_luma=0.30,
        shadow_denoise=0.15,
        shadow_start=0.02,
        shadow_end=0.12,
        chroma_blur=1,
        midtone_wb=False,
    ),
    "DAY_ROOF_CLOSED": RecipeParams(
        black_pct=1.0,
        white_pct=99.7,
        asinh=12.0,
        gamma=1.10,
        color_strength=1.55,
        chroma_clip=0.85,
        blue_suppress=0.45,
        blue_floor=0.02,
        desaturate=0.0,
        corner_sigma_bp=0.0,
        rgb_bias_subtract=True,
        hp_dab=False,
        shadow_denoise=0.0,
        chroma_blur=0,
        midtone_wb=True,
        midtone_wb_strength=0.6,
    ),
    "DAY_ROOF_OPEN": RecipeParams(
        black_pct=0.5,
        white_pct=99.5,
        asinh=8.0,
        gamma=1.12,
        color_strength=1.40,
        chroma_clip=0.90,
        blue_suppress=0.30,
        blue_floor=0.015,
        desaturate=0.0,
        corner_sigma_bp=0.0,
        rgb_bias_subtract=True,
        hp_dab=False,
        shadow_denoise=0.0,
        chroma_blur=0,
        midtone_wb=True,
        midtone_wb_strength=0.5,
    ),
}


def compute_effective_params(
    mode: str,
    requested: dict[str, Any],
    *,
    auto_mode: bool = True,
    wp_value: float | None = None,
    p10_lum: float | None = None,
) -> dict[str, Any]:
    """
    Compute effective parameters based on mode and user requests.

    If auto_mode is True, uses mode defaults and applies guardrails.
    User-specified non-default values override the auto values.

    Guardrails:
      - override_bp clamped to max 0.25 * wp
      - override_bp not above p10 of lum unless explicitly high

    Returns dict with both 'requested' and 'effective' values.
    """
    # Start with mode defaults or generic defaults
    if auto_mode and mode in MODE_DEFAULTS:
        base = MODE_DEFAULTS[mode].to_dict()
    else:
        base = RecipeParams().to_dict()

    # Merge requested values (user overrides)
    effective = base.copy()
    for key, val in requested.items():
        if val is not None:
            effective[key] = val

    # Apply guardrails for corner_sigma_bp
    if effective.get("corner_sigma_bp", 0) > 0 and wp_value is not None:
        max_bp = 0.25 * wp_value
        # Actual override_bp would be corner_sigma_bp * sigma
        # We'll flag this for the caller to apply after sigma is known

    # For DAY modes, auto-disable noise controls if auto_mode and not explicitly set
    if auto_mode and mode.startswith("DAY_"):
        # Only override if user didn't explicitly request these
        if "corner_sigma_bp" not in requested:
            effective["corner_sigma_bp"] = 0.0
        if "hp_dab" not in requested:
            effective["hp_dab"] = False
        if "shadow_denoise" not in requested:
            effective["shadow_denoise"] = 0.0
        if "chroma_blur" not in requested:
            effective["chroma_blur"] = 0
        # Enable midtone WB for day modes
        if "midtone_wb" not in requested:
            effective["midtone_wb"] = True

    # For NIGHT modes, ensure noise controls are reasonable
    if auto_mode and mode.startswith("NIGHT_"):
        if "midtone_wb" not in requested:
            effective["midtone_wb"] = False

    return {
        "mode": mode,
        "auto_mode": auto_mode,
        "requested": requested,
        "effective": effective,
    }


def apply_bp_guardrails(
    override_bp: float | None,
    sigma: float,
    corner_sigma_bp: float,
    wp: float,
    p10: float,
) -> tuple[float | None, dict]:
    """
    Apply guardrails to override_bp to prevent crushing images.

    Returns (clamped_bp, debug_info).
    """
    if corner_sigma_bp <= 0:
        return None, {"applied": False, "reason": "corner_sigma_bp <= 0"}

    raw_bp = corner_sigma_bp * sigma
    max_bp_wp = 0.25 * wp
    
    # For very dark frames (p10 near 0), skip p10 guardrail to allow noise floor clipping
    if p10 < 0.001:
        max_bp_p10 = raw_bp  # Don't limit based on p10 for extreme low-light
    else:
        max_bp_p10 = p10 * 1.5  # Allow slightly above p10

    clamped_bp = min(raw_bp, max_bp_wp, max_bp_p10)

    dbg = {
        "applied": True,
        "raw_override_bp": float(raw_bp),
        "max_bp_from_wp": float(max_bp_wp),
        "max_bp_from_p10": float(max_bp_p10),
        "clamped_bp": float(clamped_bp),
        "was_clamped": clamped_bp < raw_bp,
    }
    return clamped_bp, dbg
