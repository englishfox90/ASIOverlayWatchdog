# File Size Compliance Review & Refactoring Plan

**Review Date**: December 20, 2025  
**Status**: ⚠️ 2 Critical Violations, 1 Minor Violation  
**Action Required**: Refactor oversized files to meet 500-line target (550 hard cap)

---

## Copilot Instructions File Size Guidelines

From [.github/copilot-instructions.md](.github/copilot-instructions.md):

> ### File Size & Modularity
> - **Target max: 500 lines per file** (hard cap: **550**)
> - If a file approaches limits, **split by responsibility** (not arbitrary chunks)
> - Prefer extracting:
>   - `models.py` (dataclasses / pydantic models)
>   - `service.py` (core orchestration / use-cases)
>   - `handlers.py` (API/CLI/UI entrypoints)
>   - `repo.py` or `adapters/` (I/O, persistence, external integrations)
>   - `errors.py` (feature-specific exceptions)

---

## Current Status Summary

### ⚠️ CRITICAL VIOLATIONS (Exceeds 550 Hard Cap)

| File | Lines | Over Limit | Priority | Status |
|------|-------|------------|----------|--------|
| [gui/main_window.py](gui/main_window.py) | **1,303** | +753 lines | **P0 - Critical** | 🔴 Needs immediate refactoring |
| [services/zwo_camera.py](services/zwo_camera.py) | **866** | +316 lines | **P0 - Critical** | 🔴 Needs immediate refactoring |

### 🟡 MINOR VIOLATIONS (Over Target, Under Hard Cap)

| File | Lines | Status | Priority | Action |
|------|-------|--------|----------|--------|
| [gui/capture_tab.py](gui/capture_tab.py) | **527** | 🟡 Over 500 target | **P1 - High** | Extract helpers |

### ✅ APPROACHING LIMITS (400-500 lines)

| File | Lines | Status | Priority | Action |
|------|-------|--------|----------|--------|
| [services/processor.py](services/processor.py) | **380** | ✅ Acceptable | P2 - Monitor | None needed |
| [gui/text_editor.py](gui/overlays/text_editor.py) | **345** | ✅ Acceptable | P2 - Monitor | None needed |
| [gui/camera_controller.py](gui/camera_controller.py) | **395** | ✅ Acceptable | P2 - Monitor | None needed |
| [gui/settings_tab.py](gui/settings_tab.py) | **319** | ✅ Good | P3 - Low | None needed |

### ✅ WELL-SIZED FILES (Under 400 lines)

All other files are under 400 lines and well-structured. ✅

---

## Detailed Refactoring Plans

### 1. 🔴 CRITICAL: gui/main_window.py (1,303 lines → Target: 3-4 files of 300-400 lines)

**Current Structure Analysis:**
- Lines 1-125: Initialization, config, services setup
- Lines 125-238: GUI creation, menu setup
- Lines 239-295: Application lifecycle (on_closing, auto-start/stop)
- Lines 296-550: Camera operations & settings (40+ methods)
- Lines 551-700: Directory watch operations
- Lines 701-850: Overlay management
- Lines 851-1000: Settings management
- Lines 1001-1150: Output modes (Web/RTSP/Discord)
- Lines 1151-1303: Preview & utility methods

**Root Cause**: Violates Single Responsibility Principle - handles ALL application business logic

**Refactoring Strategy**: Extract business logic into dedicated managers (already partially done but incomplete)

#### Phase 1: Move Remaining Business Logic to Existing Managers

**Target Files** (already exist, just need to migrate methods):
1. **`gui/camera_controller.py`** (395 lines → 450-500 lines)
   - Already has: detect_cameras, start/stop capture, camera callbacks
   - **Move from main_window.py:**
     - `on_scheduled_capture_toggle()` (line 408)
     - `on_schedule_time_change()` (line 433)
     - `update_camera_status_for_schedule()` (line 447)
     - `on_wb_mode_change()` (line 458)
     - All white balance UI update logic

2. **`gui/overlay_manager.py`** (238 lines → 350-400 lines)
   - Already has: overlay CRUD operations
   - **Move from main_window.py:**
     - `refresh_overlay_list()` methods
     - `apply_overlay_changes()` logic
     - `validate_overlays()` helper
     - Overlay drag-and-drop handlers

3. **`gui/image_processor.py`** (244 lines → 300-350 lines)
   - Already has: process_and_save_image, preview generation
   - **Move from main_window.py:**
     - `on_auto_brightness_toggle()` (line 359)
     - Preview zoom/pan handlers
     - Image export functionality

4. **`gui/status_manager.py`** (202 lines → 250-300 lines)
   - Already has: status updates, logging, monitoring
   - **Move from main_window.py:**
     - Mode change handlers
     - Status text formatters
     - Mini-log management

#### Phase 2: Create New Manager for Watch Operations

5. **NEW FILE: `gui/watch_controller.py`** (~200-250 lines)
   - Extract all directory watch logic from main_window.py:
     - `start_watching()` (currently inline)
     - `stop_watching()` (currently inline)
     - `on_watch_file_processed()` callback
     - Directory selection handlers
     - Watch status management

#### Phase 3: Create Settings Manager

6. **NEW FILE: `gui/settings_manager.py`** (~250-300 lines)
   - Extract all settings-related logic:
     - `apply_settings()` method
     - `save_config()` method
     - `load_config()` method
     - Settings validation
     - Settings change handlers

#### Phase 4: Create Output Manager

7. **NEW FILE: `gui/output_manager.py`** (~200-250 lines)
   - Extract output mode management:
     - Web server start/stop
     - RTSP server start/stop
     - Output mode detection
     - `ensure_output_mode_started()` method

#### Result After Refactoring:
```
gui/main_window.py: ~350-400 lines (GUI setup, delegation only)
gui/camera_controller.py: ~450-500 lines (all camera logic)
gui/overlay_manager.py: ~350-400 lines (all overlay logic)
gui/image_processor.py: ~300-350 lines (all image processing)
gui/status_manager.py: ~250-300 lines (all status/logging)
gui/watch_controller.py: ~200-250 lines (NEW - watch logic)
gui/settings_manager.py: ~250-300 lines (NEW - settings logic)
gui/output_manager.py: ~200-250 lines (NEW - output modes)
```

**Total**: 8 well-sized, focused files instead of 1 monolithic file ✅

---

### 2. 🔴 CRITICAL: services/zwo_camera.py (866 lines → Target: 3 files of 250-300 lines)

**Current Structure Analysis:**
- Lines 1-70: Initialization & configuration
- Lines 71-160: SDK initialization, camera detection, connection
- Lines 161-340: Camera configuration, disconnect, single frame capture
- Lines 341-500: Capture loop with scheduling, reconnection logic
- Lines 501-650: Start/stop capture, exposure management
- Lines 651-750: Brightness calculation, clipping detection, debayering
- Lines 751-866: Auto-exposure calibration & adjustment

**Root Cause**: Single class handles camera control, auto-exposure, scheduling, white balance, and reconnection

**Refactoring Strategy**: Split into focused modules by responsibility

#### Proposed Structure:

1. **`services/zwo_camera.py`** (~250-300 lines) - **Core Camera Control**
   - Class: `ZWOCamera`
   - Responsibilities:
     - SDK initialization
     - Camera detection, connection, disconnection
     - Basic capture (single frame)
     - Camera configuration (exposure, gain, flip, white balance)
     - Context manager support
   - **Keep**: Lines 1-340 (initialization, connection, basic capture)

2. **NEW: `services/camera_capture.py`** (~200-250 lines) - **Capture Loop & Scheduling**
   - Class: `CameraCaptureManager`
   - Responsibilities:
     - Continuous capture loop
     - Scheduled capture (time window management)
     - Reconnection logic with exponential backoff
     - Frame callbacks
   - **Extract**: Lines 341-650 (capture_loop, start/stop, scheduling)

3. **NEW: `services/camera_auto_exposure.py`** (~200-250 lines) - **Auto Exposure**
   - Class: `AutoExposureController`
   - Responsibilities:
     - Brightness calculation algorithms
     - Clipping detection
     - Calibration routine
     - Exposure adjustment logic
   - **Extract**: Lines 651-866 (calibration, auto-exposure, brightness calc)

4. **NEW: `services/camera_utils.py`** (~100-150 lines) - **Utility Functions**
   - Functions:
     - `simple_debayer_rggb()` - Fallback debayering
     - Bayer pattern mapping helpers
     - Temperature conversion helpers
   - **Extract**: Standalone utility functions

#### Integration Pattern:

```python
# services/zwo_camera.py
from .camera_capture import CameraCaptureManager
from .camera_auto_exposure import AutoExposureController

class ZWOCamera:
    def __init__(self, ...):
        # Core camera setup
        self.capture_manager = None
        self.auto_exposure = None if not auto_exposure else AutoExposureController(self, ...)
    
    def start_capture(self, ...):
        self.capture_manager = CameraCaptureManager(self, ...)
        self.capture_manager.start(...)
```

#### Result After Refactoring:
```
services/zwo_camera.py: ~250-300 lines (core camera control)
services/camera_capture.py: ~200-250 lines (capture loop, scheduling)
services/camera_auto_exposure.py: ~200-250 lines (auto exposure logic)
services/camera_utils.py: ~100-150 lines (utility functions)
```

**Total**: 4 well-sized, focused files instead of 1 monolithic file ✅

---

### 3. 🟡 MINOR: gui/capture_tab.py (527 lines → Target: <500 lines)

**Current Structure Analysis:**
- Lines 1-100: Initialization, UI layout
- Lines 101-250: Directory watch UI
- Lines 251-450: Camera settings UI (exposure, gain, WB, etc.)
- Lines 451-527: Helper methods, validators

**Root Cause**: Tab contains both UI layout AND helper methods

**Refactoring Strategy**: Extract helper methods to camera_controller

#### Simple Fix (Priority: P1 - After main_window.py is fixed):

**Move to `gui/camera_controller.py`:**
- Lines 480-527: All validation and helper methods
  - `validate_exposure_input()`
  - `validate_gain_input()`
  - `format_exposure_display()`
  - Camera detection status helpers

**Result**: 
```
gui/capture_tab.py: ~450-480 lines (UI layout only) ✅
gui/camera_controller.py: ~450-500 lines (includes helpers)
```

---

## Implementation Priority

### Phase 1: Critical Files (P0) - **Do Immediately**

1. **Refactor `gui/main_window.py`** (1,303 → ~400 lines)
   - Timeline: 2-3 hours
   - Risk: Medium (many integrations, but managers already exist)
   - Benefit: Major improvement in maintainability

2. **Refactor `services/zwo_camera.py`** (866 → ~300 lines)
   - Timeline: 2-3 hours
   - Risk: Low (clear separation of concerns)
   - Benefit: Much easier to maintain auto-exposure logic

### Phase 2: Minor Violations (P1) - **Do Soon**

3. **Trim `gui/capture_tab.py`** (527 → ~480 lines)
   - Timeline: 30 minutes
   - Risk: Very low
   - Benefit: Cleaner separation

---

## Testing Checklist After Refactoring

After each refactoring, verify:

- [ ] All existing tests still pass
- [ ] Camera capture works (both modes)
- [ ] Directory watching works
- [ ] Overlay management works
- [ ] Settings save/load correctly
- [ ] Auto-exposure functions correctly
- [ ] Scheduled capture works
- [ ] Application starts without errors
- [ ] No circular import issues
- [ ] All imports resolve correctly

---

## Benefits of Refactoring

### Maintainability
- ✅ **Single Responsibility**: Each file has one clear purpose
- ✅ **Easier Testing**: Smaller, focused units are easier to test
- ✅ **Easier Debugging**: Bugs are isolated to specific modules
- ✅ **Easier Code Review**: Reviewers can focus on specific functionality

### Performance
- ✅ **Faster IDE**: Smaller files load and parse faster
- ✅ **Better Intellisense**: Code completion works better on smaller files
- ✅ **Reduced Memory**: Smaller modules loaded on demand

### Collaboration
- ✅ **Fewer Merge Conflicts**: Changes isolated to specific files
- ✅ **Parallel Development**: Multiple developers can work on different modules
- ✅ **Easier Onboarding**: New developers understand focused modules faster

---

## Adherence to Copilot Instructions

After refactoring, the project will fully comply with the file size guidelines:

| Guideline | Before | After |
|-----------|--------|-------|
| No files > 550 lines | ❌ 2 violations | ✅ 0 violations |
| Target < 500 lines | ❌ 3 violations | ✅ 1 minor (capture_tab at ~480) |
| Split by responsibility | ❌ Monolithic classes | ✅ Focused modules |
| Clear separation | ❌ Mixed concerns | ✅ Single responsibility |

---

## Next Steps

1. **Review this plan** - Ensure refactoring approach makes sense
2. **Start with main_window.py** - Biggest impact, highest priority
3. **Then zwo_camera.py** - Second biggest impact
4. **Finally capture_tab.py** - Quick win

**Estimated Total Time**: 5-7 hours for all refactoring

**Risk Level**: Low-Medium (managers already exist, just need to move code)

**Recommendation**: Do Phase 1 (main_window.py and zwo_camera.py) immediately, Phase 2 (capture_tab.py) when convenient.

---

**Prepared by**: GitHub Copilot AI Assistant  
**Review Status**: Ready for implementation
