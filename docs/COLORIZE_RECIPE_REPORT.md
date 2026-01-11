# Colorize Recipe Testing Report

**Date:** January 5, 2026  
**Script Version:** colorize_from_lum.py v2.0  
**Test Data:** PFRSentinel raw debug captures

## Executive Summary

The refactored `colorize_from_lum.py` script now provides:
- ✅ Modular architecture (`colorize/` package)
- ✅ Batch processing with summary CSV
- ✅ Mode-aware auto parameters
- ✅ Quality metrics for recipe evaluation
- ✅ Comprehensive debug JSON per image

**Classification Results:**
- Night roof-closed: 24/24 correct (100%)
- Day roof-closed: 41/43 correct (95.3%)
- 2 day images classified as DAY_ROOF_OPEN (edge cases - likely brief roof movement or threshold edge)

## Mode Classification

### Detection Logic

The script classifies images into 4 modes:

| Mode | Criteria |
|------|----------|
| `NIGHT_ROOF_CLOSED` | p50 < 0.10, p99 < 0.35, AND (corners much darker than center OR very dark frame) |
| `NIGHT_ROOF_OPEN` | p50 < 0.10, p99 < 0.35, AND corners similar to center |
| `DAY_ROOF_CLOSED` | p50 >= 0.10 OR p99 >= 0.35, AND corners much darker than center |
| `DAY_ROOF_OPEN` | p50 >= 0.10 OR p99 >= 0.35, AND corners similar to center |

**Special Case:** Very dark frames (p99 < 0.05 AND dynamic range < 0.02) are automatically classified as CLOSED regardless of corner/center ratio. This handles bias-like frames where the entire image is uniformly dark.

### Thresholds (configurable via CLI)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--day_p50` | 0.10 | p50 threshold for day detection |
| `--day_p99` | 0.35 | p99 threshold for day detection |
| `--closed_ratio` | 0.55 | corner/center ratio below which = closed |
| `--closed_delta` | 0.02 | minimum center-corner delta for closed |

## Recommended Recipes by Mode

### NIGHT_ROOF_CLOSED

**Recommended Settings:**
```
--black_pct 5 --white_pct 99.9 --asinh 30 --gamma 1.05
--color_strength 1.20 --chroma_clip 0.55
--blue_suppress 0.92 --blue_floor 0.020 --desaturate 0.05
--corner_sigma_bp 1.0
--hp_dab 1 --hp_k 11 --hp_max_luma 0.25
--shadow_denoise 0.25 --shadow_start 0.02 --shadow_end 0.14
--chroma_blur 1
```

**Rationale:**
- Low dynamic range images benefit from aggressive black point (corner_sigma_bp = 1.0)
- Hot pixel dab removes sensor artifacts in dark regions
- Shadow denoise reduces static/noise in shadows without losing detail
- Blue suppression handles sensor blue bias

**Quality Metrics (batch average):**
- luma_mean: ~0.148
- mean_abs_chroma: ~0.047
- detail_proxy: ~0.083
- corner_stddev: ~0.095

### DAY_ROOF_CLOSED

**Recommended Settings:**
```
--black_pct 1 --white_pct 99.7 --asinh 12 --gamma 1.10
--color_strength 1.55 --chroma_clip 0.85
--blue_suppress 0.45 --blue_floor 0.02 --desaturate 0.00
--corner_sigma_bp 0
--hp_dab 0 --shadow_denoise 0 --chroma_blur 0
--midtone_wb 1 --midtone_wb_strength 0.6
```

**Rationale:**
- Higher dynamic range - no need for aggressive noise gating
- Stronger color to preserve daylight tones
- Midtone white balance corrects color cast
- Noise controls disabled to avoid crushing detail

**Quality Metrics (batch average):**
- luma_mean: 0.22-0.49 (varies with sun position)
- mean_abs_chroma: ~0.028-0.037
- detail_proxy: ~0.011
- corner_stddev: 0.007-0.028

### NIGHT_ROOF_OPEN (theoretical)

**Recommended Settings:**
```
--black_pct 3 --white_pct 99.9 --asinh 25 --gamma 1.08
--color_strength 1.15 --chroma_clip 0.60
--blue_suppress 0.80 --blue_floor 0.015 --desaturate 0.03
--corner_sigma_bp 0.5
--hp_dab 1 --hp_k 12 --hp_max_luma 0.30
--shadow_denoise 0.15 --shadow_start 0.02 --shadow_end 0.12
--chroma_blur 1
```

**Note:** No test data available for this mode. Settings are interpolated from night-closed with reduced noise controls.

### DAY_ROOF_OPEN (theoretical)

**Recommended Settings:**
```
--black_pct 0.5 --white_pct 99.5 --asinh 8 --gamma 1.12
--color_strength 1.40 --chroma_clip 0.90
--blue_suppress 0.30 --blue_floor 0.015 --desaturate 0.00
--corner_sigma_bp 0
--hp_dab 0 --shadow_denoise 0 --chroma_blur 0
--midtone_wb 1 --midtone_wb_strength 0.5
```

**Note:** No test data available. Settings based on day-closed with lighter stretch.

## Known Issues & Limitations

### Classification Edge Cases

1. **DAY_ROOF_OPEN misclassification:** 2 images in the day batch were classified as ROOF_OPEN. These may be:
   - Frames during roof movement
   - Edge cases where brightness/contrast is atypical
   - Could tune `closed_ratio` down slightly (0.50 instead of 0.55)

2. **Very dark frames:** The `p99 < 0.05` heuristic catches bias-like frames well, but may misclassify some actual night sky frames with very low signal.

### Processing Limitations

1. **Blue cast handling:** RGB bias subtraction is essential for preventing blue cast. The B-channel bias (~0.041) is consistently higher than R/G (~0.020).

2. **Corner_sigma_bp guardrails:** The black point override is clamped to `min(raw_bp, 0.25*wp, 1.5*p10)` to prevent crushing.

3. **Midtone white balance:** Only applied to DAY modes by default. May help some night images with strong color casts.

## File Structure

```
scripts/
├── colorize_from_lum.py    # Main script (v2.0)
├── colorize/               # Package modules
│   ├── __init__.py
│   ├── io_utils.py         # FITS loading, normalization, output
│   ├── measurement.py      # Corner stats, mode classification, quality metrics
│   ├── transforms.py       # Stretch, denoise, color transforms
│   └── recipes.py          # Mode-aware parameter computation
```

## Usage Examples

### Single Image (Auto Mode)
```powershell
python colorize_from_lum.py lum.fits raw.fits --out_dir output
```

### Single Image (Manual Mode)
```powershell
python colorize_from_lum.py lum.fits raw.fits --auto 0 \
  --black_pct 5 --white_pct 99.9 --asinh 30 --gamma 1.05 \
  --corner_sigma_bp 1.0 --hp_dab 1 --shadow_denoise 0.25
```

### Batch Processing
```powershell
python colorize_from_lum.py --batch_dir /path/to/fits --out_dir output
```

Output structure:
```
output/
├── NIGHT_ROOF_CLOSED/
│   ├── 20260105_003229.png
│   └── 20260105_003229.json
├── DAY_ROOF_CLOSED/
│   ├── 20260105_081903.png
│   └── 20260105_081903.json
└── summary.csv
```

## Next Steps for Production

1. **Integrate into PFRSentinel:** The `colorize/` package can be imported directly:
   ```python
   from colorize import classify_mode_from_lum, compute_effective_params
   from colorize.transforms import stretch_mono, inject_chroma_into_luminance
   ```

2. **Auto-tuning:** Use quality metrics (corner_stddev, detail_proxy) to automatically select best recipe variant.

3. **Collect more test data:** Need ROOF_OPEN examples (both day and night) to validate those recipes.

4. **Add histogram-based classification:** Could use histogram shape to distinguish sky vs. blocked frames.

## Appendix: Quality Metrics

| Metric | Description | Good Range |
|--------|-------------|------------|
| `luma_mean` | Average output luminance | 0.1-0.5 |
| `luma_p50` | Median luminance | 0.1-0.4 |
| `saturation_frac` | Pixels at 0 or 1 | < 0.10 |
| `mean_abs_chroma` | Color intensity | 0.02-0.08 |
| `detail_proxy` | Edge/texture strength | > 0.005 |
| `corner_stddev` | Background noise level | < 0.15 |
