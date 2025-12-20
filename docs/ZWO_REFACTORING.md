# ZWO Camera Module Refactoring

## Overview
Refactored `services/zwo_camera.py` to address file size violation (899 lines → 725 lines) and fix syntax errors. Extracted utility functions and calibration logic into focused modules.

## Changes Made

### 1. Syntax Error Fixes
**File:** `services/zwo_camera.py`  
**Lines affected:** 505-640 (capture_loop method)  
**Issues fixed:**
- Malformed nested try blocks in scheduled capture window logic
- Incorrect indentation causing orphaned except handlers
- Missing except/finally clauses

**Root cause:** Manual editing or formatter corruption in camera disconnect/reconnect scheduling logic

### 2. Module Extraction

#### A. camera_utils.py (126 lines) - NEW
**Purpose:** Utility functions for image processing and scheduling

**Extracted functions:**
- `simple_debayer_rggb(raw_data, width, height)` - Bayer RGGB to RGB conversion (fallback when OpenCV unavailable)
- `is_within_scheduled_window(enabled, start_time, end_time)` - Check if within capture window
- `calculate_brightness(img_array, algorithm, percentile)` - Image brightness calculation (mean/median/percentile)
- `check_clipping(img_array, threshold)` - Detect highlight clipping

**Benefits:**
- Pure functions with no side effects
- Easily testable in isolation
- Reusable in other camera modules
- Clear separation of concerns

#### B. camera_calibration.py (193 lines) - NEW
**Purpose:** Auto-exposure calibration and adjustment algorithms

**Class:** `CameraCalibration`

**Methods:**
- `run_calibration(max_attempts=15)` - Rapid auto-exposure convergence before capture
- `adjust_exposure_auto(img_array)` - Ongoing exposure adjustment during capture
- `update_settings(...)` - Update calibration parameters

**Settings:**
- Target brightness, max exposure, algorithm selection
- Clipping detection and prevention
- Percentile-based brightness calculation

**Benefits:**
- Encapsulates complex calibration state
- Separates calibration logic from camera control
- Configurable algorithms (mean/median/percentile)
- Independent clipping prevention logic

#### C. zwo_camera.py (725 lines) - REFACTORED
**Purpose:** Core camera operations and capture orchestration

**Changes:**
- Added imports: `from .camera_utils import ...`, `from .camera_calibration import CameraCalibration`
- Replaced `is_within_scheduled_window()` implementation with call to `camera_utils.check_scheduled_window()`
- Replaced `calculate_brightness()`, `check_clipping()`, `simple_debayer_rggb()` with calls to `camera_utils` functions
- Replaced `run_calibration()` and `adjust_exposure_auto()` with delegation to `CameraCalibration` instance
- Added `self.calibration_manager = CameraCalibration(...)` initialization in `connect_camera()`

**Retained core responsibilities:**
- SDK initialization and camera connection
- Camera configuration (exposure, gain, white balance, flip)
- Frame capture (capture_single_frame, capture_loop)
- Thread management (start_capture, stop_capture)
- Scheduled capture window management

## File Size Impact

| File | Before | After | Change | Target | Status |
|------|--------|-------|--------|--------|--------|
| zwo_camera.py | 899 | 725 | -174 (-19.4%) | 500 | ⚠️ Still over cap |
| camera_utils.py | - | 126 | +126 | 500 | ✅ Compliant |
| camera_calibration.py | - | 193 | +193 | 500 | ✅ Compliant |
| **Total** | **899** | **1,044** | **+145** | - | Modular ✅ |

**Note:** Total line count increased due to module structure overhead (imports, docstrings, class definition), but code is now more maintainable and each file is closer to compliance.

## Architecture

### Before
```
zwo_camera.py (899 lines)
├── SDK initialization
├── Camera connection/configuration
├── Frame capture
├── Scheduled capture management
├── Auto-exposure calibration
├── Brightness calculation
├── Clipping detection
└── Debayering utilities
```

### After
```
zwo_camera.py (725 lines)
├── SDK initialization
├── Camera connection/configuration
├── Frame capture
├── Scheduled capture management
└── Delegates to:
    ├── camera_calibration.py (193 lines)
    │   └── Auto-exposure algorithms
    └── camera_utils.py (126 lines)
        ├── Brightness calculation
        ├── Clipping detection
        ├── Debayering utilities
        └── Schedule checking
```

## Design Patterns Used

1. **Delegation Pattern**: `zwo_camera.py` delegates to `CameraCalibration` for exposure management
2. **Utility Module Pattern**: Pure functions extracted to `camera_utils.py`
3. **Encapsulation**: Calibration state and logic isolated in `CameraCalibration` class

## Breaking Changes

**None** - All changes are internal refactoring. External API remains unchanged:
- `from services.zwo_camera import ZWOCamera` still works
- All public methods have same signatures
- Configuration options unchanged

## Testing Recommendations

1. **Unit Testing** (NEW capabilities):
   - Test `camera_utils` functions independently with mock data
   - Test `CameraCalibration` with mock camera instance
   - Verify brightness algorithms (mean/median/percentile)
   - Verify clipping detection thresholds

2. **Integration Testing** (existing flows):
   - Camera connection and configuration
   - Frame capture with auto-exposure enabled
   - Scheduled capture window (overnight windows)
   - Camera disconnect/reconnect during off-peak hours
   - Calibration convergence with various lighting conditions

3. **Regression Testing**:
   - Verify no changes to captured image quality
   - Verify exposure adjustments behave identically
   - Verify scheduled capture timing unchanged

## Future Improvements

### To reach 550-line hard cap for zwo_camera.py:
1. **Extract connection module** (175 lines):
   - `initialize_sdk()`, `detect_cameras()`, `connect_camera()`, `disconnect_camera()`, `_configure_camera()`
   - Create `camera_connection.py` module
   - Reduce `zwo_camera.py` to ~550 lines

2. **Extract metadata module** (50 lines):
   - Camera property queries
   - Metadata generation for captured frames
   - Create `camera_metadata.py` module

3. **Extract debayering module** (already in utils):
   - Currently in `camera_utils.py`
   - Could expand to support additional Bayer patterns (GRBG, GBRG)

## Implementation Notes

1. **Calibration Manager Initialization**: Created in `connect_camera()` after camera object exists
2. **Settings Sync**: `zwo_camera.py` syncs `self.exposure_seconds` after calibration manager adjustments
3. **Backward Compatibility**: Old code importing from `zwo_camera` works unchanged
4. **Import Pattern**: Used relative imports (`.camera_utils`, `.camera_calibration`) within services package

## Related Documentation

- [Project Structure](PROJECT_STRUCTURE.md) - Overall architecture
- [Refactoring Summary](REFACTORING_SUMMARY.md) - Main window refactoring
- [Copilot Instructions](../.github/copilot-instructions.md) - File size guidelines

## Date

2025-01-XX (refactoring completed)
