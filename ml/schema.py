#!/usr/bin/env python3
"""
Extended calibration schema for ML training.

Defines the full schema including auto-populated and manual labels.
Based on actual calibration output from DevModeDataSaver.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


# =============================================================================
# AUTO-POPULATED DATACLASSES (from dev_mode_utils.py + context_fetchers.py)
# =============================================================================

@dataclass
class NormalizationInfo:
    """Bit depth normalization analysis (auto-populated)."""
    denom: int = 65535
    reason: str = ""
    raw_max: int = 0
    raw_min: int = 0
    mul16_rate: float = 0.0  # Rate of values divisible by 16 (12-bit shifted indicator)
    unique_ratio: float = 0.0
    unique_count: int = 0
    suggested_downshift_bits: int = 0


@dataclass
class StretchParams:
    """Stretch calibration parameters (auto-populated)."""
    black_point: float = 0.0
    white_point: float = 1.0
    median_lum: float = 0.0
    mean_lum: float = 0.0
    dynamic_range: float = 0.0
    is_dark_scene: bool = False
    recommended_asinh_strength: float = 100.0


@dataclass
class Percentiles:
    """Luminance percentile distribution (auto-populated)."""
    p1: float = 0.0
    p10: float = 0.0
    p50: float = 0.0  # Median
    p90: float = 0.0
    p99: float = 0.0


@dataclass
class CornerAnalysis:
    """Corner vs center brightness analysis (auto-populated)."""
    roi_size: int = 50
    margin: int = 5
    corner_med: float = 0.0
    corner_p90: float = 0.0
    corner_stddev: float = 0.0
    corner_meds: dict = field(default_factory=lambda: {'tl': 0, 'tr': 0, 'bl': 0, 'br': 0})
    center_med: float = 0.0
    center_p90: float = 0.0
    corner_to_center_ratio: float = 1.0  # ~1.0 = roof closed, <0.95 = roof open
    center_minus_corner: float = 0.0
    rgb_corner_bias: dict = field(default_factory=lambda: {'bias_r': 0, 'bias_g': 0, 'bias_b': 0})


@dataclass
class ColorBalance:
    """RGB channel balance (auto-populated)."""
    r_g: float = 1.0  # Red/Green ratio (neutral = 1.0)
    b_g: float = 1.0  # Blue/Green ratio (neutral = 1.0)


@dataclass
class TimeContext:
    """Sun position and time of day (auto-populated from astral)."""
    hour: int = 0
    minute: int = 0
    period: str = "unknown"  # day, twilight, night
    detailed_period: str = "unknown"  # dawn, morning, afternoon, evening, dusk, night
    is_daylight: bool = False
    is_astronomical_night: bool = False
    location: dict = field(default_factory=lambda: {'name': '', 'latitude': 0, 'longitude': 0})
    sun_times: dict = field(default_factory=dict)  # dawn, sunrise, noon, sunset, dusk
    calculation_method: str = "simple_hour_based"  # or "astral"


@dataclass
class MoonContext:
    """Moon phase and visibility (auto-populated from astral)."""
    available: bool = False
    phase_value: float = 0.0  # 0-27.99 cycle (0=new, ~14=full)
    phase_name: str = ""  # new_moon, waxing_crescent, first_quarter, waxing_gibbous, 
                          # full_moon, waning_gibbous, last_quarter, waning_crescent
    illumination_pct: float = 0.0  # 0-100%
    is_bright_moon: bool = False  # illumination > 50%
    moonrise: Optional[str] = None  # ISO timestamp
    moonset: Optional[str] = None  # ISO timestamp
    moon_is_up: bool = False  # Currently above horizon


@dataclass
class RoofState:
    """Roof/safety monitor state (auto-populated from NINA API)."""
    available: bool = False
    source: str = ""  # "nina_api", "inferred_from_corner_ratio"
    is_safe: bool = False  # NINA IsSafe flag
    is_connected: bool = False
    device_name: str = ""
    display_name: str = ""
    description: str = ""
    roof_open: bool = False  # True = open, False = closed
    reason: Optional[str] = None  # Error reason if unavailable


@dataclass
class WeatherContext:
    """Weather conditions (auto-populated from OpenWeatherMap)."""
    available: bool = False
    source: str = ""  # "openweathermap"
    temperature_c: float = 0.0
    feels_like: str = ""
    condition: str = ""  # "Clear", "Clouds", "Rain", etc.
    description: str = ""  # "Clear Sky", "scattered clouds", etc.
    cloud_coverage_pct: int = 0  # 0-100
    humidity_pct: int = 0  # 0-100
    pressure_hpa: int = 0
    visibility_km: float = 10.0
    wind_speed: str = ""
    wind_dir: str = ""
    # Derived flags
    is_cloudy: bool = False  # cloud_coverage > 50%
    is_clear: bool = True  # cloud_coverage < 20%
    low_visibility: bool = False  # visibility < 5km


@dataclass
class SeeingEstimate:
    """Estimated atmospheric seeing conditions (auto-populated)."""
    available: bool = False
    overall_score: float = 0.0  # 0-1 composite score
    quality: str = ""  # "poor", "fair", "good", "excellent"
    humidity_score: float = 0.0  # 0-1
    visibility_score: float = 0.0  # 0-1
    cloud_score: float = 0.0  # 0-1
    dew_score: float = 0.0  # 0-1
    dew_point_c: float = 0.0
    dew_risk: bool = False


@dataclass
class AllskySnapshot:
    """
    All-sky camera snapshot for visual sky reference (auto-populated).
    
    The pier camera can't see the sky when the roof is closed. This
    provides ground truth of actual sky conditions from an external all-sky camera.
    """
    available: bool = False
    source: str = "allsky_camera"
    url: str = ""  # Source URL
    fetched_at: Optional[str] = None  # ISO timestamp
    size_bytes: int = 0
    content_type: str = "image/jpeg"
    saved_path: Optional[str] = None  # Local file path if saved
    filename: Optional[str] = None  # Local filename


# =============================================================================
# MANUAL LABELS (require human annotation)
# =============================================================================

@dataclass
class SceneLabels:
    """Manual scene annotations (human judgment required)."""
    # Binary classifications
    moon_in_frame: Optional[bool] = None  # Moon actually visible IN the image
    stars_visible: Optional[bool] = None  # Stars visible in processed output
    clouds_visible: Optional[bool] = None  # Clouds visible in frame
    imaging_train_visible: Optional[bool] = None  # Telescope/OTA visible
    
    # Continuous metrics (0.0 - 1.0)
    star_density: Optional[float] = None  # 0=none, 0.5=moderate, 1=milky way
    cloud_coverage_visual: Optional[float] = None  # Visual estimate, may differ from API
    moon_brightness_visual: Optional[float] = None  # 0=crescent, 0.5=half, 1=full
    
    # Quality assessment (after processing)
    output_quality_rating: Optional[int] = None  # 1-5 stars


@dataclass  
class RecipeUsed:
    """Recipe parameters that produced good results (for supervised learning)."""
    recipe_name: Optional[str] = None  # e.g., "night_stars", "day_overcast"
    corner_sigma_bp: Optional[float] = None
    hp_k: Optional[float] = None
    hp_max_luma: Optional[float] = None
    shadow_denoise: Optional[float] = None
    shadow_start: Optional[float] = None
    shadow_end: Optional[float] = None
    chroma_blur: Optional[int] = None
    asinh: Optional[float] = None
    gamma: Optional[float] = None
    color_strength: Optional[float] = None
    blue_suppress: Optional[float] = None
    desaturate: Optional[float] = None


@dataclass
class StackingInfo:
    """Stacking decision and results (for stacking advisor)."""
    was_stacked: bool = False
    num_frames: int = 1
    sigma_clip: Optional[float] = None
    rejection_rate: Optional[float] = None  # % of pixels rejected
    noise_reduction_achieved: Optional[float] = None  # SNR improvement


@dataclass
class NormalizedFeatures:
    """Derived normalized features for camera-agnostic ML (computed from raw data)."""
    # Percentile ratios (transfer well across cameras)
    p99_p50_ratio: float = 1.0
    p90_p10_ratio: float = 1.0
    dynamic_range_norm: float = 0.0  # (p99-p1) / p50
    
    # Spatial ratios
    center_minus_corner_norm: float = 0.0  # delta / p50
    corner_stddev_norm: float = 0.0  # stddev / corner_med
    
    # RGB imbalance (max/min of r,g,b bias)
    rgb_imbalance: float = 1.0


# =============================================================================
# FULL CALIBRATION SCHEMA
# =============================================================================

@dataclass
class ExtendedCalibration:
    """
    Full calibration schema with all ML training fields.
    
    This matches the actual output from dev_mode_utils.py _compute_stretch_calibration().
    
    Auto-populated fields (captured automatically):
    - timestamp, camera, exposure, gain, bit depths
    - normalization: Bit depth analysis
    - stretch: Recommended stretch parameters
    - percentiles: Luminance distribution
    - corner_analysis: Spatial brightness analysis
    - color_balance: RGB ratios
    - time_context: Day/night/twilight from astral
    - moon_context: Moon phase and visibility
    - roof_state: From NINA safety monitor API
    - weather_context: From OpenWeatherMap API
    - seeing_estimate: Derived atmospheric quality
    - allsky_snapshot: Visual sky reference from external all-sky camera
    
    Manual fields (require human annotation):
    - scene: Visual scene classifications
    - recipe_used: What parameters worked well
    - stacking: If stacking was beneficial
    - normalized_features: Derived camera-agnostic features
    """
    # Basic metadata
    timestamp: str = ""
    camera: str = ""
    exposure: str = ""
    gain: str = ""
    image_bit_depth: int = 8
    camera_bit_depth: int = 8
    bayer_pattern: str = "BGGR"
    
    # Auto-populated analysis
    normalization: NormalizationInfo = field(default_factory=NormalizationInfo)
    stretch: StretchParams = field(default_factory=StretchParams)
    percentiles: Percentiles = field(default_factory=Percentiles)
    corner_analysis: CornerAnalysis = field(default_factory=CornerAnalysis)
    color_balance: ColorBalance = field(default_factory=ColorBalance)
    
    # Auto-populated context
    time_context: TimeContext = field(default_factory=TimeContext)
    moon_context: MoonContext = field(default_factory=MoonContext)
    roof_state: RoofState = field(default_factory=RoofState)
    weather_context: WeatherContext = field(default_factory=WeatherContext)
    seeing_estimate: SeeingEstimate = field(default_factory=SeeingEstimate)
    allsky_snapshot: AllskySnapshot = field(default_factory=AllskySnapshot)  # Visual sky reference
    
    # Manual labels (for training)
    scene: SceneLabels = field(default_factory=SceneLabels)
    recipe_used: RecipeUsed = field(default_factory=RecipeUsed)
    stacking: StackingInfo = field(default_factory=StackingInfo)
    normalized_features: NormalizedFeatures = field(default_factory=NormalizedFeatures)


# =============================================================================
# FEATURE LISTS FOR ML MODEL
# =============================================================================

# Features that transfer well across different cameras (use ratios/percentages)
NORMALIZED_FEATURES = [
    # Percentile ratios
    "normalized_features.p99_p50_ratio",
    "normalized_features.p90_p10_ratio",
    "normalized_features.dynamic_range_norm",
    
    # Spatial ratios  
    "corner_analysis.corner_to_center_ratio",
    "normalized_features.center_minus_corner_norm",
    "normalized_features.corner_stddev_norm",
    
    # Color balance
    "color_balance.r_g",
    "color_balance.b_g",
    "normalized_features.rgb_imbalance",
    
    # Boolean flags
    "stretch.is_dark_scene",
    "time_context.is_daylight",
    "time_context.is_astronomical_night",
    "moon_context.moon_is_up",
    "moon_context.is_bright_moon",
    "roof_state.roof_open",
    "weather_context.is_clear",
    "weather_context.is_cloudy",
    "seeing_estimate.dew_risk",
]

# Features that may need calibration per camera
CAMERA_SPECIFIC_FEATURES = [
    "percentiles.p1",
    "percentiles.p50",
    "percentiles.p99",
    "corner_analysis.corner_med",
    "corner_analysis.center_med",
    "stretch.black_point",
    "stretch.white_point",
    "stretch.median_lum",
]

# Weather/atmospheric features
WEATHER_FEATURES = [
    "weather_context.cloud_coverage_pct",
    "weather_context.humidity_pct",
    "weather_context.visibility_km",
    "weather_context.is_clear",
    "weather_context.is_cloudy",
    "weather_context.low_visibility",
    "seeing_estimate.overall_score",
    "seeing_estimate.dew_risk",
]

# Moon features
MOON_FEATURES = [
    "moon_context.phase_value",
    "moon_context.illumination_pct",
    "moon_context.is_bright_moon",
    "moon_context.moon_is_up",
]

# Scene classification targets (what the model predicts)
SCENE_CLASSIFICATION_TARGETS = [
    "time_context.period",  # day, twilight, night
    "roof_state.roof_open",  # True/False
    "scene.stars_visible",  # True/False (manual label)
    "scene.moon_in_frame",  # True/False (manual label)
    "scene.clouds_visible",  # True/False (manual label)
]

# Recipe prediction targets (continuous values the model predicts)
RECIPE_TARGETS = [
    "recipe_used.corner_sigma_bp",
    "recipe_used.hp_k",
    "recipe_used.hp_max_luma",
    "recipe_used.shadow_denoise",
    "recipe_used.chroma_blur",
    "recipe_used.asinh",
    "recipe_used.gamma",
    "recipe_used.color_strength",
    "recipe_used.blue_suppress",
]

# Stacking advisor targets
STACKING_TARGETS = [
    "stacking.was_stacked",
    "stacking.num_frames",
    "stacking.sigma_clip",
]

# Quality assessment target
QUALITY_TARGET = "scene.output_quality_rating"


# =============================================================================
# MODE CLASSIFICATION RULES (derived from calibration data)
# =============================================================================

def classify_mode(cal: dict) -> str:
    """
    Classify image mode from calibration data.
    
    Returns one of:
    - "day_roof_open": Daytime with sky visible
    - "day_roof_closed": Daytime, internal view
    - "night_roof_open": Nighttime with sky visible
    - "night_roof_closed": Nighttime, internal view (very dark)
    - "twilight": Dawn/dusk transition
    - "unknown": Cannot determine
    """
    tc = cal.get('time_context', {})
    rs = cal.get('roof_state', {})
    ca = cal.get('corner_analysis', {})
    
    # Determine day/night
    if tc.get('is_daylight'):
        time_period = 'day'
    elif tc.get('is_astronomical_night'):
        time_period = 'night'
    elif tc.get('period') == 'twilight':
        return 'twilight'
    else:
        time_period = 'night' if tc.get('hour', 12) >= 20 or tc.get('hour', 12) < 6 else 'day'
    
    # Determine roof state
    if rs.get('available') and rs.get('source') == 'nina_api':
        roof_open = rs.get('roof_open', False)
    else:
        # Infer from corner ratio (ratio ~1.0 = uniform = closed)
        ratio = ca.get('corner_to_center_ratio', 0.95)
        roof_open = ratio < 0.95
    
    roof_str = 'roof_open' if roof_open else 'roof_closed'
    return f"{time_period}_{roof_str}"


def get_mode_recipe_hints(mode: str) -> dict:
    """
    Get recipe parameter hints for a given mode.
    
    These are starting points; the ML model will refine them.
    """
    hints = {
        'day_roof_open': {
            'asinh': 20,
            'gamma': 1.0,
            'shadow_denoise': 0,
            'chroma_blur': 0,
        },
        'day_roof_closed': {
            'asinh': 50,
            'gamma': 1.2,
            'shadow_denoise': 0,
            'chroma_blur': 0,
        },
        'night_roof_open': {
            'asinh': 150,
            'gamma': 0.75,
            'shadow_denoise': 0.5,
            'chroma_blur': 3,
            'blue_suppress': 0.3,
        },
        'night_roof_closed': {
            'asinh': 300,
            'gamma': 0.6,
            'shadow_denoise': 0.8,
            'chroma_blur': 5,
        },
        'twilight': {
            'asinh': 80,
            'gamma': 0.9,
            'shadow_denoise': 0.2,
            'chroma_blur': 1,
        },
    }
    return hints.get(mode, hints['night_roof_open'])
