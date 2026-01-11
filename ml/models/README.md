# Trained Models

Store trained model files here.

## Naming Convention

```
{model_type}_v{version}_{date}.pkl

Examples:
- scene_classifier_v1_20260105.pkl
- recipe_predictor_v1_20260105.pkl  
- full_model_v1_20260105.pkl
```

## Model Metadata

Each model should have a companion JSON file with:
```json
{
  "model_type": "scene_classifier",
  "version": "1",
  "created": "2026-01-05",
  "training_samples": 50,
  "features_used": ["p99_p50_ratio", "corner_to_center_ratio", ...],
  "accuracy": {
    "is_day": 0.98,
    "roof_closed": 0.95,
    "moon_visible": 0.92,
    ...
  },
  "camera": "ZWO ASI676MC",
  "notes": "Trained on Rockwood, Texas data"
}
```

## Transfer to Other Cameras

When using model on a new camera:
1. Capture 5-10 calibration frames
2. Run: `python ml/calibrate_camera.py --model full_model_v1.pkl --samples new_camera_data/`
3. Generates camera-specific offset file
4. Use: `python ml/predict.py --model full_model_v1.pkl --camera-offset asi294mc_offset.json`
