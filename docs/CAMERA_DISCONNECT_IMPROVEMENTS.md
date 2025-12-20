# Camera Disconnect Improvements

## Overview
This document describes the improvements made to ensure graceful camera disconnection in all scenarios.

## Problem Statement
Previously, the camera connection could be left open or busy when:
- Application closed unexpectedly
- Camera capture stopped manually
- Errors or timeouts occurred during capture
- Reconnection attempts failed

This could lead to:
- Camera remaining in use (unable to reconnect without restart)
- SDK resources not being released properly
- USB connection issues requiring physical reconnection

## Solution Implemented

### 1. **Destructor Method (`__del__`)**
Added Python destructor to `ZWOCamera` class to ensure cleanup when object is garbage collected.

```python
def __del__(self):
    """Destructor to ensure camera is disconnected when object is destroyed"""
    try:
        self.disconnect_camera()
    except Exception:
        pass  # Ignore errors during cleanup in destructor
```

**Benefits:**
- Automatic cleanup even if application crashes
- Ensures camera is released when `ZWOCamera` object is deleted
- Last line of defense against resource leaks

### 2. **Context Manager Support (`__enter__`, `__exit__`)**
Implemented context manager protocol for use with Python's `with` statement.

```python
def __enter__(self):
    """Context manager entry - allows use with 'with' statement"""
    return self

def __exit__(self, exc_type, exc_val, exc_tb):
    """Context manager exit - ensures cleanup even if exception occurs"""
    self.disconnect_camera()
    return False  # Don't suppress exceptions
```

**Usage Example:**
```python
with ZWOCamera(sdk_path=path, camera_index=0) as camera:
    camera.start_capture(on_frame_callback)
    # ... do work ...
# Camera automatically disconnected here, even if exception occurs
```

**Benefits:**
- Guaranteed cleanup even if exceptions occur
- More Pythonic code pattern
- Explicit resource management

### 3. **Thread-Safe Disconnect with Lock**
Added `_cleanup_lock` to prevent multiple simultaneous disconnect attempts.

```python
def __init__(self, ...):
    # ...
    self._cleanup_lock = threading.Lock()  # Prevent multiple simultaneous disconnects
```

```python
def disconnect_camera(self):
    """Disconnect from camera gracefully (idempotent - safe to call multiple times)"""
    with self._cleanup_lock:
        if not self.camera:
            return  # Already disconnected
        # ... cleanup code ...
```

**Benefits:**
- Prevents race conditions during shutdown
- Idempotent - safe to call multiple times
- Thread-safe for multi-threaded applications

### 4. **Improved `disconnect_camera()` Method**
Enhanced disconnect logic with proper sequencing and error handling:

1. **Stop capture first** - Ensures capture loop exits cleanly
2. **Stop video capture** - Releases SDK video capture mode
3. **Close camera** - Releases camera hardware connection
4. **Clear reference** - Always clears `self.camera` even if errors occur

```python
def disconnect_camera(self):
    with self._cleanup_lock:
        if not self.camera:
            return  # Already disconnected
        
        try:
            # Stop capture first if active
            if self.is_capturing:
                self.log("Stopping active capture before disconnect...")
                self.stop_capture()
            
            # Try to stop video capture if it was started
            try:
                self.camera.stop_video_capture()
            except Exception:
                pass  # May not have been started, ignore
            
            # Close camera connection
            try:
                self.camera.close()
                self.log("Camera disconnected gracefully")
            except Exception as e:
                self.log(f"Warning during camera close: {e}")
                
        except Exception as e:
            self.log(f"Error disconnecting camera: {e}")
        finally:
            # Always clear camera reference even if close failed
            self.camera = None
```

**Benefits:**
- Proper cleanup sequencing
- Handles partial failures gracefully
- Always clears camera reference
- Detailed logging for troubleshooting

### 5. **Improved `stop_capture()` with Thread Join**
Enhanced thread cleanup with longer timeout for long exposures:

```python
def stop_capture(self):
    """Stop continuous capture and wait for thread to finish"""
    if not self.is_capturing:
        return
    
    self.log("Stopping capture...")
    self.is_capturing = False
    
    # Wait for capture thread to finish
    if self.capture_thread and self.capture_thread.is_alive():
        self.log("Waiting for capture thread to finish...")
        self.capture_thread.join(timeout=10.0)  # Increased timeout for long exposures
        
        if self.capture_thread.is_alive():
            self.log("Warning: Capture thread did not finish in time")
        else:
            self.log("Capture thread finished successfully")
        
        self.capture_thread = None
    
    self.log("Capture stopped")
```

**Benefits:**
- Ensures capture thread exits before returning
- 10-second timeout accommodates long exposures
- Warns if thread doesn't exit (debugging aid)
- Proper thread lifecycle management

### 6. **Capture Loop Cleanup with Finally Block**
Added `try-finally` block to ensure cleanup on all exit paths:

```python
def capture_loop(self):
    try:
        # ... calibration code ...
        try:
            while self.is_capturing:
                # ... capture code ...
        finally:
            # Ensure camera is properly stopped on all exit paths
            self.log("Capture loop exiting - cleaning up...")
            if self.camera:
                try:
                    self.camera.stop_video_capture()
                except Exception as e:
                    self.log(f"Error stopping video capture in cleanup: {e}")
    except Exception as e:
        self.log(f"Error during calibration: {e}")
    
    self.log("Capture loop stopped")
```

**Benefits:**
- Cleanup happens even if thread is interrupted
- Handles exceptions during calibration
- Ensures video capture is stopped
- Multiple levels of error handling

### 7. **Improved Scheduled Capture Disconnect**
Enhanced scheduled capture disconnect logic to preserve capture flag:

```python
if self.camera:
    try:
        # Temporarily stop capturing flag
        was_capturing = self.is_capturing
        self.is_capturing = False
        
        # Disconnect camera gracefully
        self.camera.stop_video_capture()
        self.camera.close()
        self.camera = None
        self.log("Camera disconnected during off-peak hours")
        
        # Restore capturing flag for reconnection logic
        self.is_capturing = was_capturing
        
        # Update UI status
        if self.status_callback:
            self.status_callback(f"Idle (off-peak until {self.scheduled_start_time})")
    except Exception as e:
        self.log(f"Error disconnecting camera: {e}")
        self.is_capturing = was_capturing  # Restore flag even on error
```

**Benefits:**
- Preserves capture state during scheduled disconnect
- Proper flag management for reconnection
- Error recovery maintains state consistency

### 8. **Improved Reconnection Cleanup**
Enhanced error recovery reconnection with proper cleanup:

```python
# Clean up existing camera first
if self.camera:
    try:
        self.camera.stop_video_capture()
    except:
        pass
    try:
        self.camera.close()
    except:
        pass
    finally:
        self.camera = None

# Reinitialize camera
time.sleep(0.5)  # Brief delay before reconnecting
self.camera = self.asi.Camera(self.camera_index)
self._configure_camera()
```

**Benefits:**
- Fully cleans up old camera before reconnecting
- Brief delay allows USB/SDK to stabilize
- Multiple try-except blocks prevent one failure from blocking others

### 9. **Enhanced Camera Controller Stop Method**
Improved GUI controller with better error handling:

```python
def stop_camera_capture(self):
    """Stop camera capture with proper cleanup and error handling"""
    self.app.is_capturing = False
    
    if self.zwo_camera:
        try:
            app_logger.info("Stopping camera capture...")
            
            # Disconnect camera gracefully (includes stop_capture call)
            self.zwo_camera.disconnect_camera()
            
            # Wait briefly for cleanup to complete
            import time
            time.sleep(0.2)
            
            app_logger.info("Camera disconnected successfully")
            
        except Exception as e:
            app_logger.error(f"Error during camera disconnect: {e}")
        finally:
            # Always clear reference even if disconnect failed
            self.zwo_camera = None
    
    # ... UI updates ...
```

**Benefits:**
- Always clears camera reference
- Brief wait ensures cleanup completes
- Better logging for troubleshooting
- UI always updates even if disconnect fails

## Testing Recommendations

### Test Scenarios
1. **Normal stop** - Start capture, stop capture (verify clean disconnect)
2. **App close during capture** - Start capture, close app immediately
3. **Error during capture** - Simulate camera disconnect during active capture
4. **Scheduled disconnect** - Verify disconnect during off-peak hours
5. **Reconnection after error** - Verify reconnection works after error
6. **Multiple start/stop cycles** - Rapid start/stop operations
7. **Long exposure disconnect** - Stop during long exposure (>10s)

### Verification Points
- [ ] Camera LED turns off after disconnect
- [ ] No error messages in logs about busy camera
- [ ] Can reconnect immediately without restart
- [ ] No USB issues after disconnect
- [ ] Application closes cleanly (no hanging threads)
- [ ] Memory is freed (no resource leaks)

## Backward Compatibility
All changes are backward compatible:
- Existing code continues to work unchanged
- New context manager support is optional
- Destructor runs automatically (no code changes needed)
- Improved thread handling is transparent

## Future Improvements
Potential enhancements:
1. Add connection health monitoring
2. Implement automatic recovery from USB disconnect
3. Add connection state machine for better state tracking
4. Implement SDK-level keep-alive mechanism
5. Add telemetry for disconnect patterns

## Related Files
- `services/zwo_camera.py` - Core camera interface
- `gui/camera_controller.py` - GUI camera controller
- `gui/main_window.py` - Application window with `on_closing()` handler

## References
- Python `__del__` documentation: https://docs.python.org/3/reference/datamodel.html#object.__del__
- Python context managers: https://docs.python.org/3/reference/datamodel.html#context-managers
- Threading best practices: https://docs.python.org/3/library/threading.html
