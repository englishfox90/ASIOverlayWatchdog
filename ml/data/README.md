# Training Data

Place calibration JSON files here or reference them from `H:\Other computers\My Computer\raw_debug\`.

## Data Requirements

### Minimum Samples for Training
- **Scene classifier**: 30-50 labeled samples across all conditions
- **Recipe predictor**: 50-100 samples with quality ratings
- **Stacking advisor**: 20+ samples with stacking experiments

### Ideal Distribution
- Day Roof Open: 10+ samples
- Day Roof Closed: 10+ samples  
- Night Roof Open: 10+ samples
- Night Roof Closed: 10+ samples
- Moon visible: 5+ samples
- Clouds visible: 5+ samples
- Various star densities

## Labeling Workflow

1. **Auto-populate** weather and roof state:
   ```bash
   python ml/collect_labels.py "H:\raw_debug" --add-weather --add-roof
   ```

2. **Manual labeling** (moon, stars, clouds):
   ```bash
   python ml/collect_labels.py "H:\raw_debug" --interactive
   ```

3. **Quality rating** (after processing):
   - Process image with colorize_from_lum.py
   - Rate output quality 1-5
   - Record recipe parameters used

## File Format

Each calibration file should have:
```json
{
  "timestamp": "...",
  "percentiles": {...},
  "corner_analysis": {...},
  "time_context": {...},
  
  // Extended fields
  "weather": {
    "cloud_coverage_pct": 20,
    "temperature_c": 15.5,
    ...
  },
  "roof_state": "open",
  "scene": {
    "moon_visible": true,
    "star_density": 0.7,
    "cloud_coverage": 0.2,
    ...
  },
  "recipe_used": {
    "corner_sigma_bp": 1.5,
    "hp_k": 7.0,
    ...
  },
  "normalized_features": {
    "p99_p50_ratio": 1.21,
    "corner_stddev_norm": 0.029,
    ...
  }
}
```
