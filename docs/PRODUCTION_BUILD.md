# Production Build Configuration

## Dev Mode Control

### What is Dev Mode?

Development Mode enables features useful for debugging and ML training:
- **Raw debug file saving** - Saves FITS/TIFF files to `%LOCALAPPDATA%\PFRSentinel\raw_debug\`
- **Calibration JSON exports** - Detailed image analysis metadata
- **ML prediction integration** - Roof state prediction from trained models

**RAW16 camera mode is NOT part of dev mode** - it's a user-facing feature that remains available regardless.

### Production Build Process

1. **Before building release:** Set `DEV_MODE_AVAILABLE = False` in `services\dev_mode_config.py`
   ```python
   DEV_MODE_AVAILABLE = False  # Disable for production
   ```

2. **Build the executable:**
   ```powershell
   .\build_sentinel_installer.bat
   ```

3. **Verify dev mode disabled:**
   - Run `dist\PFRSentinel\PFRSentinel.exe`
   - Check UI: Developer Mode section should NOT appear in Image Processing page
   - Capture an image: No `raw_debug` folder should be created

4. **After release:** Re-enable for development
   ```python
   DEV_MODE_AVAILABLE = True  # Re-enable for development
   ```

### Why Disable in Production?

1. **Disk space** - Debug files can be 100+ MB per image
2. **Performance** - Skips unnecessary file I/O and analysis
3. **User confusion** - Most users don't need debug features
4. **ML readiness** - ML models not ready for public release yet

### Environment Variable Override

For testing without editing code:
```powershell
# Temporarily disable dev mode
$env:PFRSENTINEL_DEV_MODE = "0"
python main.py

# Normal (respects code setting)
Remove-Item Env:\PFRSENTINEL_DEV_MODE
python main.py
```

### Features Available in Production

These remain accessible regardless of dev mode:
- **RAW16 camera mode** - Full sensor bit depth capture (user feature)
- **Auto stretch** - MTF-based dynamic range optimization
- **Color balance** - Manual/auto white balance
- **All output modes** - File/Web/Discord/RTSP
- **Overlays** - Full overlay system with tokens
- **Logging** - Normal application logs (not debug stats)

### Dev Mode Status Check

Check current build status:
```python
from services.dev_mode_config import is_dev_mode_available, get_dev_mode_status_message

print(get_dev_mode_status_message())
# Output: "Development features enabled (not a production build)"
# or:     "Development features disabled (production build)"
```

### Build Script Reminders

Both build scripts now show checklist reminders:
- `build_sentinel.bat` - Reminds to verify dev mode disabled
- `build_sentinel_installer.bat` - Shows VirusTotal upload instructions

### Common Mistakes

❌ **DON'T**: Build release with `DEV_MODE_AVAILABLE = True`  
✅ **DO**: Set to `False` before building release

❌ **DON'T**: Commit `DEV_MODE_AVAILABLE = False` to git  
✅ **DO**: Only change for local builds, keep `True` in repository

❌ **DON'T**: Disable RAW16 in production  
✅ **DO**: Keep RAW16 available (it's a user feature, not dev mode)

### Testing Matrix

| Mode | UI Section Visible? | Creates raw_debug? | RAW16 Available? |
|------|--------------------|--------------------|------------------|
| `DEV_MODE_AVAILABLE = True` | ✅ Yes | ✅ Yes (if enabled) | ✅ Yes |
| `DEV_MODE_AVAILABLE = False` | ❌ No | ❌ No | ✅ Yes |

### ML Integration Notes

ML prediction is gated by dev mode because:
- Models are still in training/validation
- Not tested with all allsky camera setups
- Adds processing overhead
- Requires external image sources

When ML is production-ready:
1. Move out of dev mode gate
2. Add UI controls to ML settings page
3. Update documentation
4. Include models in installer

### File Locations

**Dev Mode Config:**
- `services\dev_mode_config.py` - Main flag file

**Dev Mode Features:**
- `ui\controllers\dev_mode_utils.py` - FITS/JSON saving
- `ui\controllers\ml_prediction.py` - ML integration
- `ui\panels\image_processing.py` - UI controls

**Always Available:**
- `services\zwo_camera.py` - RAW16 mode (line 72: `self.use_raw16`)
- `ui\panels\capture_settings.py` - RAW16 toggle (line 618)
