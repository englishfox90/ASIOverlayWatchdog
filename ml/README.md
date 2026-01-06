# PFR Sentinel ML Module

Machine learning model for automatic scene understanding and recipe optimization.

## Goals

1. **Scene Classification**: Automatically detect day/night, roof open/closed, weather conditions
2. **Recipe Prediction**: Optimal stretch parameters for each scene type
3. **Stacking Advisor**: When and how many frames to stack for best results

## Directory Structure

```
ml/
├── README.md           # This file
├── schema.py           # Extended calibration schema (dataclasses + feature lists)
├── collect_labels.py   # Script to add manual labels to calibration files
├── train_model.py      # Model training script (TODO)
├── predict.py          # Inference module (TODO)
├── data/
│   └── README.md       # Training data instructions
└── models/
│   └── README.md       # Trained model storage
```

## Calibration Data Structure

Each calibration JSON file now captures comprehensive scene information:

### Auto-Populated Fields (captured automatically by dev_mode)

| Section | Fields | Source |
|---------|--------|--------|
| **Basic Metadata** | timestamp, camera, exposure, gain, bit depths, bayer_pattern | Camera/metadata |
| **Normalization** | denom, raw_min/max, mul16_rate, unique_ratio | Image analysis |
| **Stretch** | black_point, white_point, median_lum, dynamic_range, is_dark_scene, recommended_asinh | Image analysis |
| **Percentiles** | p1, p10, p50, p90, p99 | Luminance histogram |
| **Corner Analysis** | corner_med, center_med, corner_to_center_ratio, rgb_corner_bias | Spatial analysis |
| **Color Balance** | r_g, b_g ratios | RGB channel means |
| **Time Context** | period, is_daylight, is_astronomical_night, sun_times | Astral library |
| **Moon Context** | phase_value, phase_name, illumination_pct, moon_is_up | Astral library |
| **Roof State** | is_safe, roof_open, device_name | NINA API |
| **Weather Context** | temperature, clouds, humidity, visibility, is_clear | OpenWeatherMap |
| **Seeing Estimate** | overall_score, quality, dew_risk | Derived from weather |
| **All-Sky Snapshot** | url, saved_path, filename | External all-sky camera |

> **Note**: The pier camera can't see the sky when the roof is closed. The all-sky
> snapshot provides visual ground truth of actual sky conditions, which is especially
> useful when weather data shows clouds (the reason the roof may have closed).

### Manual Labels (require human annotation)

| Field | Type | Description |
|-------|------|-------------|
| `scene.moon_in_frame` | bool | Moon actually visible in the image |
| `scene.stars_visible` | bool | Stars visible in processed output |
| `scene.clouds_visible` | bool | Clouds visible in frame |
| `scene.star_density` | 0-1 | 0=none, 0.5=moderate, 1=milky way |
| `scene.output_quality_rating` | 1-5 | Quality of processed result |
| `recipe_used.*` | float | Parameters that produced good results |
| `stacking.*` | various | Stacking decisions and outcomes |

## Example Calibration Output

```json
{
  "timestamp": "2026-01-05T21:41:54",
  "camera": "ZWO ASI676MC",
  "exposure": "20.0s",
  "gain": "180",
  "image_bit_depth": 16,
  "camera_bit_depth": 12,
  
  "stretch": {
    "black_point": 0.0206,
    "white_point": 0.0298,
    "median_lum": 0.0219,
    "is_dark_scene": true,
    "recommended_asinh_strength": 227.9
  },
  
  "corner_analysis": {
    "corner_to_center_ratio": 0.9739,
    "rgb_corner_bias": {
      "bias_r": 0.0195,
      "bias_g": 0.0188,
      "bias_b": 0.0401
    }
  },
  
  "time_context": {
    "period": "night",
    "is_astronomical_night": true,
    "calculation_method": "astral"
  },
  
  "moon_context": {
    "phase_name": "waning_gibbous",
    "illumination_pct": 84.8,
    "moon_is_up": false
  },
  
  "roof_state": {
    "source": "nina_api",
    "roof_open": false
  },
  
  "weather_context": {
    "condition": "Clear",
    "cloud_coverage_pct": 0,
    "humidity_pct": 46,
    "is_clear": true
  },
  
  "seeing_estimate": {
    "overall_score": 0.87,
    "quality": "excellent",
    "dew_risk": true
  }
}
```

## Model Transferability

The model uses **normalized features** that transfer well across different cameras:

### Camera-Agnostic Features (use these for cross-camera models)

- **Percentile ratios**: p99/p50, p90/p10, dynamic_range/p50
- **Spatial ratios**: corner_to_center_ratio, center_minus_corner/p50
- **Color ratios**: r_g, b_g, RGB imbalance (max/min bias)
- **Boolean flags**: is_dark_scene, is_daylight, roof_open, is_clear

### Camera-Specific Features (need per-camera calibration)

- Absolute percentile values (p1, p50, p99)
- Corner/center medians (absolute brightness)
- Black/white points

### Transfer Strategy

1. Train primarily on normalized features
2. New camera captures 5-10 calibration frames across different modes
3. Model learns camera-specific offset/scaling
4. Fine-tune or apply offset correction

## Usage

### Adding Manual Labels to Existing Files

```bash
# Interactive labeling session
python ml/collect_labels.py "H:\raw_debug" --interactive

# Add normalized features only (no manual labels)
python ml/collect_labels.py "H:\raw_debug" --add-features

# Process single file
python ml/collect_labels.py calibration_20260105_214154.json --interactive
```

### Training Data Requirements

Collect samples from all 4 primary modes:

| Mode | Description | Example Conditions |
|------|-------------|-------------------|
| `day_roof_open` | Daytime with sky visible | Clear day, blue sky |
| `day_roof_closed` | Daytime internal view | Roof closed during day |
| `night_roof_open` | Nighttime with sky | Stars/moon visible |
| `night_roof_closed` | Very dark internal | Roof closed at night |

Plus twilight transitions (dawn/dusk).

**Minimum recommended**: 20-30 samples per mode with manual labels.

### Model Training (TODO)

```bash
# Train scene classifier + recipe predictor
python ml/train_model.py --data "H:\raw_debug" --output ml/models/v1.pkl

# Evaluate on held-out test set
python ml/train_model.py --data "H:\raw_debug" --eval-only --model ml/models/v1.pkl
```

### Inference (TODO)

```bash
# Predict optimal recipe for new image
python ml/predict.py calibration_file.json

# Output:
# Mode: night_roof_closed
# Confidence: 0.94
# Recommended Recipe:
#   asinh: 280
#   gamma: 0.65
#   shadow_denoise: 0.7
#   chroma_blur: 5
# Stacking: Recommended (3-5 frames)
```

## Mode Classification Logic

The `classify_mode()` function in `schema.py` determines the scene type:

```python
def classify_mode(cal: dict) -> str:
    # 1. Check time_context.is_daylight / is_astronomical_night
    # 2. Check roof_state.roof_open (from NINA API)
    # 3. Fallback: infer roof from corner_to_center_ratio
    #    - ratio ~1.0 = uniform brightness = roof closed
    #    - ratio <0.95 = sky visible = roof open
    
    return f"{time_period}_{roof_state}"  # e.g., "night_roof_closed"
```

## Key Insights from Your Data

From the example calibration:

1. **Roof detection works**: `corner_to_center_ratio: 0.9739` (~1.0) confirms roof closed
2. **RGB bias shows blue excess**: `bias_b: 0.0401` vs `bias_r: 0.0195` - typical for camera sensor
3. **Very dark scene**: `median_lum: 0.0219` (only 2.2% of dynamic range used)
4. **Excellent seeing**: `overall_score: 0.87` but `dew_risk: true` - watch for condensation
5. **NINA integration works**: `source: "nina_api"` confirms live API connection
