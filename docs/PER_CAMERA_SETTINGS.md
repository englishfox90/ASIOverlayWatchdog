# Per-Camera Settings Implementation

## Problem
Previously, PFRSentinel stored camera settings **globally** - all cameras shared the same settings for gain, exposure, white balance, flip, etc. When you switched between cameras (e.g., Pier camera to another camera), the new camera would inherit whatever settings were last saved, causing cross-contamination between cameras.

## Solution
**Per-Camera Profiles**: Each camera now has its own dedicated settings profile stored separately in config.json. Settings are loaded/saved based on the camera name, so different cameras can have completely different configurations.

## What Changed

### 1. Config Structure (`services/config.py`)
- Added `camera_profiles` section to store settings per camera name
- Added helper methods:
  - `get_camera_profile(camera_name)` - Get profile for a camera
  - `save_camera_profile(camera_name, profile_data)` - Save complete profile
  - `update_camera_profile(camera_name, **kwargs)` - Update specific settings
  - `list_camera_profiles()` - List all saved profiles
  - `delete_camera_profile(camera_name)` - Remove a profile

**Example config structure:**
```json
{
  "camera_profiles": {
    "ZWO ASI676MC": {
      "exposure_ms": 500.0,
      "gain": 150,
      "auto_exposure": true,
      "wb_r": 80,
      "wb_b": 95,
      "flip": 3,
      "bayer_pattern": "BGGR"
    },
    "ZWO ASI224MC": {
      "exposure_ms": 100.0,
      "gain": 100,
      "auto_exposure": false,
      "wb_r": 75,
      "wb_b": 99,
      "flip": 0,
      "bayer_pattern": "RGGB"
    }
  }
}
```

### 2. Camera Controller (`ui/controllers/camera_controller.py`)
- Modified `start_capture()` to load settings from camera-specific profile
- Extracts clean camera name (removes "(Index: N)" suffix)
- Calls `config.get_camera_profile(camera_name)` to get camera's settings
- Falls back to global settings if no profile exists (backward compatibility)
- Syncs profile settings to global config keys for UI display

### 3. Capture Settings Panel (`ui/panels/capture_settings.py`)
- Added `_save_to_camera_profile(**kwargs)` helper method
- Modified all setting change handlers to save to BOTH:
  - Camera-specific profile (via `update_camera_profile()`)
  - Global config (for backward compatibility and UI sync)
- Handlers updated:
  - `_on_exposure_changed()` - saves `exposure_ms`
  - `_on_gain_changed()` - saves `gain`
  - `_on_auto_exposure_changed()` - saves `auto_exposure`
  - `_on_target_brightness_changed()` - saves `target_brightness`
  - `_on_max_exposure_changed()` - saves `max_exposure_ms`
  - `_on_wb_changed()` - saves `wb_r`, `wb_b`
  - `_on_offset_changed()` - saves `offset`
  - `_on_flip_changed()` - saves `flip`
  - `_on_bayer_changed()` - saves `bayer_pattern`

### 4. ROI Handling (`services/camera_connection.py`)
**IMPORTANT**: ROI (Region of Interest) is ALWAYS set to full frame:
- In `connect()` method (line 274-282): Sets ROI to MaxWidth x MaxHeight
- In `configure()` method (line 434-436): Sets ROI to full frame
- This is CORRECT behavior - prevents resolution mismatch errors

The ROI is NOT configurable per camera because:
1. Full frame is the safest default
2. Prevents reshape errors during image processing
3. Camera capabilities (MaxWidth/MaxHeight) are read dynamically

## Camera Fix Script

### Files Created
- **`fix_cameras.py`** - Python script to reset all cameras
- **`fix_cameras.bat`** - Windows batch launcher (activates venv automatically)

### What the Script Does
1. **Backs up** current `config.json` with timestamp
2. **Detects** all connected ZWO cameras
3. **Creates** safe default profile for each camera:
   - Exposure: 100ms
   - Gain: 100
   - Auto Exposure: Disabled
   - White Balance: ASI Auto (R=75, B=99)
   - Offset: 20
   - Flip: None (0)
   - Bayer Pattern: BGGR (or RGGB for ASI224/ASI1600)
4. **Saves** profiles to `config.json`

### Usage
```bash
# Close PFRSentinel first!
fix_cameras.bat

# Or run directly:
python fix_cameras.py
```

### What You'll See
```
================================================================
PFR Sentinel - Camera Settings Reset Script
================================================================

This script will reset all camera settings to safe defaults.
Each camera will get its own profile to prevent cross-contamination.

⚠ IMPORTANT: Close PFRSentinel before continuing!

Continue? [y/N]: y

✓ Config backed up to: C:\Users\...\config_backup_20260102_153045.json

=== Detecting Cameras ===
Found 3 camera(s)
  [0] ZWO ASI676MC (12345)
  [1] ZWO ASI224MC (67890)
  [2] ZWO ASI120MM (54321)

=== Creating Camera Profiles ===

ZWO ASI676MC (12345):
  Exposure: 100.0ms
  Gain: 100
  Bayer Pattern: BGGR
  ...

✓ Camera settings reset complete!

Next steps:
  1. Start PFRSentinel
  2. Select each camera in the Capture tab
  3. Verify settings look correct
  4. Adjust settings as needed for each camera
```

## Migration Path (Backward Compatibility)

### First Run After Upgrade
When you start PFRSentinel after upgrading:
1. **Existing global settings are preserved** - no data loss
2. When you **select a camera**, a profile is auto-created from global settings
3. When you **change settings**, they save to BOTH global + camera profile
4. **Old config.json files still work** - merge pattern handles missing keys

### Manual Migration (Recommended)
Run the fix script to:
1. Back up your current config
2. Reset all cameras to safe defaults
3. Start fresh with per-camera profiles

Then adjust each camera's settings individually in the Capture tab.

## Verification Checklist

After implementing changes, test:
- [ ] Select Camera A, change gain to 150, start capture
- [ ] Select Camera B, verify gain is NOT 150 (should be Camera B's setting)
- [ ] Start capture with Camera B, verify correct settings applied
- [ ] Switch back to Camera A, verify gain is still 150
- [ ] Check `config.json` - should have separate profiles for each camera
- [ ] Run `fix_cameras.py` - should detect all cameras and create profiles
- [ ] Restart PFRSentinel - profiles should persist

## Technical Notes

### Why ROI is Always Full Frame
The ROI (Region of Interest) is intentionally set to the camera's maximum resolution:
- **Line 274-282** in `camera_connection.py`: Initial connection sets full frame
- **Line 434-436** in `camera_connection.py`: Configuration sets full frame
- **Reason**: Prevents resolution mismatch errors during image capture/processing

If you need to capture a smaller region:
- Do it in **post-processing** (resize_percent in output settings)
- NOT in ROI settings (would break compatibility)

### Profile Storage Location
- **Windows**: `%LOCALAPPDATA%\PFRSentinel\config.json`
- **Structure**: `camera_profiles` dict with camera names as keys
- **Backup**: Always created by fix script with timestamp

### Camera Name Handling
Camera names may include index suffix like `"ZWO ASI676MC (Index: 1)"`:
- **Storage**: Uses CLEAN name without index (`"ZWO ASI676MC"`)
- **Cleanup**: `camera_name.split('(Index:')[0].strip()`
- **Reason**: Index can change on reconnection, but name stays constant

## Troubleshooting

### Settings Still Shared Between Cameras
- Check `config.json` - should have `camera_profiles` section
- Verify camera name extraction (check logs for "Loading settings from camera profile")
- Run fix script to recreate profiles

### Profile Not Saving
- Check file permissions on `%LOCALAPPDATA%\PFRSentinel`
- Verify config.save() is called after changes
- Check logs for save errors

### Wrong Bayer Pattern
- Most ZWO color cameras: **BGGR**
- ASI224MC, ASI1600: **RGGB**
- Monochrome cameras: Pattern doesn't matter (no debayering)
- Edit profile in `config.json` or use Capture tab dropdown

### Fix Script Fails
- **No cameras detected**: Check USB connections, close other apps (ASICap, etc.)
- **SDK not found**: Verify `ASICamera2.dll` exists in app directory
- **Permission denied**: Run as administrator or check file permissions
- **Import error**: Run from activated venv: `venv\Scripts\activate.bat`
