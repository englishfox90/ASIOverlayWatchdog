# PFR Sentinel ML Module

Machine learning model for automatic scene understanding and image stretch optimization.

## Overview

The PFR Sentinel ML model analyzes pier camera images to automatically determine:
1. **Roof state** (open/closed) - Primary classification
2. **Weather conditions** - Sky quality assessment  
3. **Celestial information** - Stars visibility, density, and moon presence

This enables automatic selection of optimal image stretch parameters for 24/7 unattended operation.

## Why This Model?

**The Core Problem**: The pier camera captures images in vastly different conditions:
- Daytime vs nighttime
- Roof open (sky visible) vs roof closed (dark enclosure)
- Clear skies vs cloudy/overcast
- Moon up vs moonless nights

Each scenario requires different image processing (stretch) parameters to produce quality output. Currently this requires manual intervention or pre-programmed schedules.

**The Solution**: Train a model to recognize these conditions from the pier camera image alone, then automatically select appropriate stretch recipes.

## Production Environment

### Local Model Integration

The ML model runs **locally** on the same machine as PFR Sentinel - it is NOT a cloud API. This enables:

- **Zero latency**: Direct integration with image processing pipeline
- **No internet required**: Works offline once model is trained
- **Privacy**: Images never leave the local machine
- **Real-time inference**: Can process every captured frame

The model will be loaded by PFR Sentinel at startup and called during the image processing pipeline to determine optimal stretch parameters.

### Available Inputs

**⚠️ CRITICAL**: In production, the model will ONLY have access to:

| Available | NOT Available |
|-----------|---------------|
| ✅ **Pier camera image** (full resolution) | ❌ Weather API |
| ✅ Image statistics (luminance, percentiles, corners) | ❌ Roof state from NINA |
| ✅ Timestamp / date | ❌ All-sky camera |
| ✅ Computed astral data (sun/moon ephemeris) | ❌ Any external sensors |

The model uses the **actual image pixels** (not just statistics) to analyze the scene. A vision model can directly see:
- Sky patterns vs dark enclosure
- Star fields and their distribution
- Cloud structures and gradients
- Moon glow and position

Image statistics serve as supplementary features, but the primary input is the image itself.

## Training Data Strategy

### Ground Truth Sources (Training Only)

During training, we collect rich context that won't be available in production:

| Source | Provides | Purpose |
|--------|----------|---------|
| **NINA API** | Roof open/closed state | Ground truth for roof classification |
| **Weather API** | Cloud %, conditions, humidity | Ground truth for weather inference |
| **All-Sky Camera** | Visual sky conditions | Ground truth when pier camera can't see sky |
| **Manual Labels** | Human verification | Corrects API errors, adds nuance |

### The All-Sky Camera's Role

When the roof is closed, the pier camera sees only darkness - it cannot determine weather conditions. However, the **all-sky camera** can see the actual sky regardless of roof state.

By correlating:
- All-sky observations (stars, clouds, moon) → Weather labels
- Pier camera statistics when roof closed → Input features

The model learns patterns like:
- "When pier camera shows uniform darkness with these statistics AND weather was cloudy, the all-sky showed clouds"
- Later in production: "I see similar pier camera statistics → likely cloudy conditions"

This allows the model to make weather inferences even when it can't directly see the sky.

## Development Phases

### Phase 1: Roof State Classification ✅ COMPLETE

**Goal**: Reliably detect if the roof is open or closed from pier camera image.

**Model Input**: Full pier camera image (resized to 128x128)

**What the model sees**:
- **Roof Open**: Sky gradient, possible stars/clouds, irregular brightness patterns
- **Roof Closed**: Uniform darkness, possibly telescope silhouette, no sky features

**Supplementary Features**:
- `corner_to_center_ratio` - Roof closed ≈ 1.0 (uniform), open < 0.95 (sky gradient)
- `median_lum` - Overall brightness
- Time of day context

**Results**: 100% accuracy on validation set

### Phase 2: Sky/Celestial Classification ✅ COMPLETE

**Goal**: Determine sky conditions and detect celestial objects when roof is open.

**Model Input**: Pier camera image (256x256) + metadata

**Predictions**:
- `sky_condition`: Clear, Mostly Clear, Partly Cloudy, Mostly Cloudy, Overcast
- `stars_visible`: Boolean
- `star_density`: 0-1 scale
- `moon_visible`: Boolean

**Training Strategy**: Trained on both pier camera (roof open only) AND all-sky camera images for increased dataset size, validated on pier camera only.

**Results**:
- Sky Condition: 85.3% accuracy
- Stars Visible: 91.2% accuracy  
- Moon Visible: 100% accuracy

### Phase 3: Production Integration ✅ COMPLETE

**Goal**: Integrate ML predictions into PFR Sentinel DEV MODE for validation.

**Implementation**:
- Roof classifier runs on every captured frame
- Sky classifier runs only when roof is predicted OPEN
- Predictions saved to `calibration_*.json` files for future validation
- Configurable via `dev_mode.ml_predictions` settings

**Usage in PFR Sentinel**:
```python
from ui.controllers.ml_prediction import predict_roof_state, predict_sky_condition, get_ml_status

# Check ML availability
status = get_ml_status()
print(status['roof_classifier']['available'])  # True
print(status['sky_classifier']['available'])   # True

# Run predictions
roof_result = predict_roof_state(image, corner_analysis, time_context)
if roof_result['roof_open']:
    sky_result = predict_sky_condition(image, corner_analysis, time_context, moon_context)
```

**Config Settings** (in `config.json`):
```json
{
  "dev_mode": {
    "enabled": true,
    "ml_predictions": {
      "enabled": true,
      "roof_classifier": true,
      "sky_classifier": true
    }
  }
}
```

### Phase 4: Stretch Recipe Prediction (Future)

**Goal**: Output optimal image processing parameters.

**Output**: Stretch mode/recipe selection based on classified scene.

## Directory Structure

```
ml/
├── README.md              # This file
├── labeling_tool.py       # GUI for efficient data labeling
├── label_report.py        # Dataset distribution analysis
├── schema.py              # Calibration data schema
├── context_fetchers.py    # Data collection utilities
├── train_model.py         # Model training (TODO)
├── predict.py             # Production inference (TODO)
└── models/                # Trained model storage
```

## Calibration Data Structure

Each sample consists of three files with matching timestamps:

```
calibration_20260105_220825.json  # Context + labels
lum_20260105_220825.fits          # Luminance FITS image
allsky_20260105_220825.jpg        # All-sky camera snapshot
```

### Auto-Collected Context (in calibration JSON)

| Section | Fields | Source |
|---------|--------|--------|
| **Image Stats** | percentiles, median_lum, dynamic_range | Image analysis |
| **Corner Analysis** | corner_to_center_ratio, rgb_corner_bias | Spatial analysis |
| **Time Context** | period, is_daylight, is_astronomical_night | Astral library |
| **Moon Context** | phase_name, illumination_pct, moon_is_up | Astral library |
| **Roof State** | roof_open, source | NINA API *(training only)* |
| **Weather Context** | condition, cloud_coverage_pct, is_clear | Weather API *(training only)* |

### Manual Labels (added via labeling tool)

```json
{
  "labels": {
    "roof_open": true,
    "sky_condition": "Mostly Clear",
    "clouds_visible": false,
    "stars_visible": true,
    "star_density": 0.7,
    "moon_visible": false,
    "labeled_at": "2026-01-07T14:30:00"
  }
}
```

## Dataset Requirements

### Current Collection Targets

| Category | Target | Purpose |
|----------|--------|---------|
| **Roof Open** | 200 | Learn open-roof characteristics |
| **Roof Closed** | 200 | Learn closed-roof characteristics |
| **Night + Open** | 150 | Primary imaging scenario |
| **Night + Closed** | 100 | Dark reference |
| **Day + Open** | 50 | Daytime sky |
| **Day + Closed** | 50 | Daytime internal |
| **Twilight** | 50 | Transition periods |
| **Clear Sky** | 100 | Best conditions |
| **Cloudy/Overcast** | 75 | Weather variation |
| **Moon Visible** | 75 | Moon detection |
| **High Star Density** | 50 | Milky Way nights |

### Run Label Report

```bash
python ml/label_report.py "E:\Pier Camera ML Data"
```

Shows current progress vs targets and recommends priority collection.

## Usage

### Labeling Workflow

```bash
# Launch labeling GUI
python ml/labeling_tool.py "E:\Pier Camera ML Data"
```

**Keyboard shortcuts**:
- `Space` - Save & Next
- `A` / `←` - Previous
- `D` / `→` - Next
- `S` - Save

**Features**:
- Auto-suggests labels from collected context
- "Skip labeled" checkbox to process only new samples
- Shows all-sky + pier camera images side by side

### Data Collection

Use the calibration collector (in PFR Sentinel dev mode) to capture samples:
- Runs every N seconds
- Captures pier camera luminance FITS
- Fetches all-sky snapshot
- Records weather, roof state, and astral context

**Priority scenarios to capture**:
1. Clear nights with roof open (stars visible)
2. Twilight transitions (dawn/dusk)
3. Various weather conditions
4. Moon rise/set periods

## Model Architecture (Planned)

### Approach: CNN + Metadata Fusion

The model combines:
1. **Vision backbone** (CNN/ViT) - Analyzes the actual image pixels
2. **Metadata branch** - Time context and computed features
3. **Fusion layer** - Combines visual and metadata features

```
┌─────────────────┐     ┌──────────────────┐
│  Pier Camera    │     │  Metadata        │
│  Image (256x256)│     │  (time, astral)  │
└────────┬────────┘     └────────┬─────────┘
         │                       │
    ┌────▼────┐             ┌────▼────┐
    │   CNN   │             │  Dense  │
    │ Backbone│             │  Layers │
    └────┬────┘             └────┬────┘
         │                       │
         └───────────┬───────────┘
                     │
              ┌──────▼──────┐
              │   Fusion    │
              │   Layer     │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  Predictions│
              │  (roof,sky, │
              │  stars,moon)│
              └─────────────┘
```

### Input Features (Production)

```python
# Primary input: the actual image
image = load_image("pier_camera_frame.fits")  # Resized to 256x256

# Secondary input: metadata features
metadata = {
    # Image statistics (computed from image)
    'median_lum': 0.0219,
    'p99_p50_ratio': 1.36,
    'corner_to_center_ratio': 0.974,
    'dynamic_range': 0.0092,
    
    # Time context (computed locally)
    'hour': 22,
    'is_astronomical_night': True,
    'moon_illumination': 0.85,
    'moon_is_up': False,
}
```

### Output Predictions

```python
predictions = {
    'roof_open': False,           # Phase 1
    'roof_confidence': 0.97,
    
    'sky_condition': 'Clear',     # Phase 2
    'clouds_likely': False,
    
    'stars_visible': False,       # Phase 3 (roof closed, can't see)
    'star_density': 0.0,
    'moon_visible': False,
    
    'recommended_stretch': 'night_dark',  # Phase 4
}
```

## Key Insights

### Roof Detection Heuristics

- `corner_to_center_ratio ≈ 1.0` → Roof closed (uniform darkness)
- `corner_to_center_ratio < 0.95` → Roof open (sky visible, gradient)
- Works well at night; daytime needs additional features

### Weather Correlation

The model learns correlations between:
- Historical weather patterns + pier camera statistics
- All-sky visual observations + image characteristics

This enables weather inference without real-time API access.

### Stretch Mode Mapping

| Scene | Recommended Stretch |
|-------|-------------------|
| Night + Open + Clear | High asinh, star enhancement |
| Night + Open + Cloudy | Moderate asinh, cloud detail |
| Night + Closed | Minimal stretch, dark reference |
| Day + Open | Low asinh, sky gradient |
| Day + Closed | Minimal stretch |
| Twilight | Adaptive based on brightness |

## PFR Sentinel Integration

### Loading the Model

```python
# In PFR Sentinel startup
from ml.predict import SceneClassifier

classifier = SceneClassifier.load("ml/models/scene_v1.onnx")
```

### Using in Image Pipeline

```python
# During image processing
def process_image(image_path):
    # Load image
    image = load_fits(image_path)
    
    # Get model prediction
    prediction = classifier.predict(image)
    
    # Select stretch based on prediction
    if prediction['roof_open']:
        if prediction['sky_condition'] == 'Clear':
            stretch = 'night_clear_sky'
        else:
            stretch = 'night_cloudy'
    else:
        stretch = 'roof_closed_dark'
    
    # Apply stretch
    processed = apply_stretch(image, stretch)
    return processed
```

### Model Format

The trained model will be exported as **ONNX** for:
- Fast inference without full ML framework
- Easy deployment (no PyTorch/TensorFlow runtime needed)
- Cross-platform compatibility

## Future Enhancements

1. **Continuous learning**: Update model with new samples over time
2. **Anomaly detection**: Flag unusual conditions (frost, light leaks)
3. **Quality scoring**: Rate output image quality for feedback loop
4. **Multi-camera support**: Transfer learning to new camera setups
5. **GPU acceleration**: Optional CUDA inference for faster processing
