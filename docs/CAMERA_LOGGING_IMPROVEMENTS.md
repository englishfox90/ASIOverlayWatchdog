# Camera Logging Improvements

## Overview
Comprehensive logging enhancements to troubleshoot camera connectivity issues during unattended operation. These improvements provide detailed diagnostic information for all camera operations, especially connection/disconnection events and scheduled capture transitions.

## Problem Statement
**Original Issues:**
- Camera disconnects not fully logged
- Reconnection attempts had minimal logging
- Scheduled capture window transitions unclear
- Detection failures provided limited diagnostic info
- Difficult to troubleshoot multi-day unattended operation

**User Requirements:**
- Run WatchDog app for days without interference
- Detailed logs for camera connections/disconnections
- Clear visibility into schedule activation/deactivation
- Troubleshooting guidance in logs
- Track which camera is being used (multiple camera support)

## Changes Made

### 1. SDK Initialization Logging (`services/zwo_camera.py`)

**Before:**
```python
asi.init(self.sdk_path)
self.log(f"ZWO SDK initialized from: {self.sdk_path}")
```

**After:**
```python
self.log("=== Initializing ZWO ASI SDK ===")
self.log("zwoasi module imported successfully")
self.log(f"Attempting SDK init with configured path: {self.sdk_path}")
asi.init(self.sdk_path)
self.log(f"✓ ZWO SDK initialized successfully from: {self.sdk_path}")
# + Error handling with stack traces
```

**Benefits:**
- Step-by-step initialization tracking
- Clear success/failure indicators (✓/✗)
- Full stack traces for debugging
- Troubleshooting hints for common issues

### 2. Camera Detection Logging

**Enhanced Output:**
```log
=== Starting Camera Detection ===
zwoasi module imported successfully
Starting camera detection...
Initializing ASI SDK from: C:\Program Files\ZWO\ASICamera2.dll
✓ ASI SDK initialized successfully: C:\Program Files\ZWO\ASICamera2.dll
Querying SDK for number of connected cameras...
SDK reports 2 camera(s) connected
Enumerating 2 camera(s)...
Opening camera 0 to retrieve properties...
✓ Camera 0: ASI676MC (ID: 12345678)
  Resolution: 3584x2712, Pixel Size: 2.0µm
Opening camera 1 to retrieve properties...
✓ Camera 1: ASI294MC Pro (ID: 87654321)
  Resolution: 4144x2822, Pixel Size: 2.315µm
✓ Camera detection complete: 2 camera(s) found
```

**Failure Output:**
```log
=== Starting Camera Detection ===
⚠ No cameras detected by SDK
Check: 1) USB cable connected, 2) Camera powered, 3) USB drivers installed
```

### 3. Camera Connection Logging

**Enhanced Output:**
```log
=== Connecting to Camera (Index: 0) ===
SDK not initialized, initializing now...
✓ ZWO SDK initialized successfully from: ASICamera2.dll
Opening camera at index 0...
✓ Connected to camera: ASI676MC
  Camera ID: 12345678
  Max Resolution: 3584x2712
  Pixel Size: 2.0 µm
  Available controls: 18
Configuring camera settings...
  Gain: 100
  Exposure: 1.0s (1000ms)
  White balance mode: Manual (R=75, B=99)
  Bayer pattern: BGGR, Flip: None, Offset: 20
Initializing calibration manager...
✓ Camera connection successful
Scheduled capture enabled: 17:00 - 09:00
```

### 4. Scheduled Capture Logging

**Window Transitions:**
```log
=== Capture Loop Started ===
Scheduled capture enabled: 17:00 - 09:00

# Entering off-peak mode
⏸ Outside scheduled capture window (17:00 - 09:00)
Entering off-peak mode: disconnecting camera to reduce hardware load...
Stopping video capture for off-peak disconnect...
Closing camera connection...
✓ Camera disconnected for off-peak hours (reducing hardware load)

# Returning to active capture
▶ Entered scheduled capture window (17:00 - 09:00)
Transitioning to active capture mode: reconnecting camera...
Attempting to reconnect camera at index 0...
=== Connecting to Camera (Index: 0) ===
✓ Camera reconnected successfully for scheduled captures
```

### 5. Reconnection Logging

**Detailed Reconnection Attempts:**
```log
✗ ERROR in capture loop: Camera disconnected
Consecutive errors: 1/5
Stack trace: ...
Initiating reconnection attempt 1/5...
Cleaning up existing camera connection...
Stopped video capture
Closed camera
Camera reference cleared
Waiting 0.5s before reconnection attempt...
Opening camera at index 0...
Configuring camera settings...
✓ Camera reconnected successfully
Waiting 1s before resuming capture...
```

**Exponential Backoff:**
```log
✗ Reconnection attempt failed: USB device not found
Stack trace: ...
Using exponential backoff: waiting 4s before retry 2/5...
```

**Max Attempts Reached:**
```log
✗ CRITICAL: Maximum reconnection attempts (5) reached
Camera appears to be disconnected or unresponsive
Stopping capture loop. Manual intervention required.
Troubleshooting: 1) Check USB cable, 2) Check camera power, 3) Check USB drivers, 4) Restart application
```

### 6. Disconnection Logging

**Graceful Disconnect:**
```log
=== Disconnecting Camera ===
Stopping active capture before disconnect...
Stopping video capture...
Video capture stopped
Closing camera connection...
✓ Camera disconnected successfully
Camera reference cleared
```

### 7. GUI Detection Logging (`gui/camera_controller.py`)

**Detection Process:**
```log
=== Camera Detection Initiated ===
Starting detection thread...
Starting timeout monitor (10s)...
zwoasi module imported successfully
Initializing ASI SDK from: C:\Program Files\ZWO\ASICamera2.dll
✓ ASI SDK initialized successfully: C:\Program Files\ZWO\ASICamera2.dll
Querying SDK for number of connected cameras...
SDK reports 1 camera(s) connected
Enumerating 1 camera(s)...
Opening camera 0 to retrieve properties...
✓ Camera 0: ASI676MC (ID: 12345678)
  Resolution: 3584x2712, Pixel Size: 2.0µm
✓ Camera detection complete: 1 camera(s) found
Populating camera list with 1 camera(s)
Selected first camera by default
✓ Camera detection successful: 1 camera(s) ready
```

**Detection Failure:**
```log
=== Camera Detection Initiated ===
Detection failed: SDK path not specified
✗ Camera detection failed: SDK path not specified
For detailed diagnostics, check log file: C:\Users\...\watchdog.log
Click 'Detect Cameras' to try again
```

**Timeout:**
```log
✗ Camera detection timed out after 10 seconds
Possible causes: 1) Camera in use by another app, 2) USB driver issue, 3) Camera hardware problem
```

### 8. Startup Logging

**Complete Startup Sequence:**
```log
=== Starting Camera Capture ===
Selected camera: ASI676MC (ID: 12345678)
Camera index: 0
SDK path: C:\Program Files\ZWO\ASICamera2.dll
Camera settings: Exposure=1000ms, Gain=100, WB(R=75, B=99)
  Auto-exposure: True, Max=30s, Target brightness=100
  Bayer pattern: BGGR, Flip: None, Offset: 20
  Capture interval: 5s
White balance mode: asi_auto
Scheduled capture enabled: 17:00 - 09:00
Initializing ZWOCamera instance...
Connecting to camera at index 0...
=== Connecting to Camera (Index: 0) ===
[... connection logs ...]
Set capture interval to 5s
Starting capture loop...
✓ Camera capture started successfully
```

### 9. Error Logging

**All Errors Include:**
- Stack traces for debugging
- Troubleshooting hints
- Clear visual indicators (✗)
- Context about current state
- Next steps or retry information

**Example:**
```log
✗ Failed to start camera capture: Failed to connect to camera (see above logs for details)
Stack trace: ...
Troubleshooting: Check logs above for specific error details
```

## Visual Indicators

To make logs easier to scan, we use Unicode symbols:

- `✓` - Success
- `✗` - Error/Failure
- `⚠` - Warning
- `⏸` - Pause/Off-peak mode
- `▶` - Resume/Active mode
- `===` - Section headers

## Log Verbosity Levels

**INFO Level** (default):
- Connection/disconnection events
- Schedule transitions
- Camera selection
- Capture start/stop
- Reconnection attempts
- Configuration changes

**DEBUG Level**:
- SDK initialization details
- Camera property enumeration
- Step-by-step cleanup
- Stack traces
- Timing information

**ERROR Level**:
- Connection failures
- Reconnection failures
- Detection timeouts
- Critical errors

## Testing Scenarios

### Scenario 1: Normal Startup
1. App starts
2. Detect cameras button clicked
3. Camera selected
4. Capture started
5. **Expected logs:** Full startup sequence with ✓ indicators

### Scenario 2: Camera Disconnected During Capture
1. Camera capturing
2. USB cable unplugged
3. **Expected logs:** 
   - Error detected with stack trace
   - 5 reconnection attempts with exponential backoff
   - Critical error after max attempts
   - Troubleshooting guidance

### Scenario 3: Scheduled Capture Window
1. Capture started at 16:00 (before 17:00 window)
2. App running continuously
3. **Expected logs:**
   - 16:00: Off-peak mode, camera disconnected
   - 17:00: Entering window, reconnecting camera
   - 09:00: Exiting window, disconnecting camera

### Scenario 4: No Cameras Detected
1. Detect cameras with no camera connected
2. **Expected logs:**
   - Detection attempt
   - "No cameras detected" with troubleshooting steps
   - Log file location for diagnostics

### Scenario 5: Detection Timeout
1. Camera in use by another app
2. Detect cameras clicked
3. **Expected logs:**
   - Detection started
   - Timeout after 10 seconds
   - Possible causes listed

## Benefits for Unattended Operation

1. **Complete Audit Trail:** Every camera interaction logged with timestamps
2. **Self-Diagnostic:** Logs include troubleshooting hints
3. **Visual Scanning:** Unicode symbols make it easy to spot issues
4. **Context Preservation:** Stack traces and state information included
5. **Schedule Tracking:** Clear visibility into on/off-peak transitions
6. **Reconnection Tracking:** See all retry attempts and backoff timing
7. **Multi-Camera Support:** Camera ID and index always logged

## Viewing Logs

**Location:** 
- Windows: `C:\Users\<Username>\AppData\Local\ASIOverlayWatchDog\Logs\watchdog.log`
- Logs tab in application UI

**Rotation:** 
- Daily rotation
- 7 days retention

**Searching:**
Use these patterns to find specific events:
- `===` - Major sections (detection, connection, capture loop)
- `✗` - All errors
- `⚠` - Warnings
- `schedule` - Schedule-related events
- `reconnect` - Reconnection attempts
- `Camera 0:` - Specific camera events

## Troubleshooting Guide

### Issue: Camera Disconnects After Hours
**Look for:**
```log
✗ ERROR in capture loop: ...
Consecutive errors: 1/5
✗ Reconnection attempt failed: ...
```
**Action:** Check USB cable, power, drivers

### Issue: Schedule Not Activating
**Look for:**
```log
Scheduled capture enabled: 17:00 - 09:00
⏸ Outside scheduled capture window
```
**Action:** Verify time settings in config

### Issue: Detection Timeout
**Look for:**
```log
✗ Camera detection timed out after 10 seconds
```
**Action:** Close other apps using camera, check USB drivers

### Issue: Wrong Camera Selected
**Look for:**
```log
Camera selected: Index 0 - ASI676MC (ID: 12345678)
```
**Action:** Use Detection to see all cameras, select correct one

## Maintenance Notes

- Logs provide complete diagnostic data for support
- Stack traces help identify code-level issues
- Schedule transitions clearly marked for verification
- Reconnection attempts show network/USB stability
- All errors include next steps for resolution

## Next Steps

With these logging improvements:
1. Start camera capture
2. Monitor logs tab for real-time feedback
3. Let run for 24-48 hours
4. Review `watchdog.log` for any issues
5. Verify schedule transitions occur correctly
6. Confirm reconnection attempts work as expected

The logs now provide everything needed to troubleshoot camera issues during multi-day unattended operation.
