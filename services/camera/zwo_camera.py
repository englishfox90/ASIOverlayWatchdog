"""
ZWO ASI Camera capture module
Provides interface to capture images from ZWO cameras using the ASI SDK

This is the main public interface. Connection management is delegated to
camera_connection.py, calibration to camera_calibration.py.
"""
import threading
import time

import numpy as np

from .camera_calibration import CameraCalibration
from .camera_connection import CameraConnection
from .camera_utils import is_within_scheduled_window as check_scheduled_window
from ..logger import app_logger
from . import zwo_capture_worker


class ZWOCamera:
    """Interface to ZWO ASI camera using zwoasi library"""
    
    def __init__(self, sdk_path=None, camera_index=0, exposure_sec=1.0, gain=100,
                 white_balance_r=75, white_balance_b=99, offset=20, flip=0,
                 auto_exposure=False, max_exposure_sec=30.0, auto_wb=False,
                 wb_mode='asi_auto', wb_config=None, bayer_pattern='BGGR',
                 scheduled_capture_enabled=False, scheduled_start_time="17:00",
                 scheduled_end_time="09:00", scheduled_capture_mode=None,
                 scheduled_window_interval=5.0,
                 status_callback=None, camera_name=None,
                 config_callback=None, camera_serial=None):
        # Initialize log callback FIRST (before CameraConnection uses self.log)
        self.on_log_callback = None
        self.on_frame_callback = None
        self.on_calibration_callback = None
        self.on_error_callback = None
        
        # Initialize connection manager (delegates SDK/connection logic)
        self._connection = CameraConnection(sdk_path=sdk_path, logger=self.log)
        self._connection.config_callback = config_callback
        self._connection.camera_name = camera_name
        self._connection.camera_index = camera_index
        self._connection.camera_serial = camera_serial

        # Legacy attribute aliases (for backward compatibility)
        self.sdk_path = sdk_path
        self.camera_index = camera_index
        self.camera_name = camera_name
        self.camera_serial = camera_serial  # Stable hardware identity (authoritative)
        self.config_callback = config_callback
        
        # Capture state
        self.is_capturing = False
        self.capture_thread = None
        # Set by the UI-level watchdog to nudge the capture thread into
        # running its own reconnect on the next poll point.  Kept here (not
        # on the connection) because the capture worker reads it directly.
        self._recovery_requested = False
        self.status_callback = status_callback  # Callback for schedule status updates
        
        # Capture settings
        self.exposure_seconds = exposure_sec
        self.gain = gain
        self.capture_interval = 5.0  # Seconds between captures
        self.auto_exposure = auto_exposure
        self.max_exposure = max_exposure_sec  # Max exposure for auto mode
        self.target_brightness = 100  # Target brightness for auto exposure
        self.exposure_algorithm = 'percentile'  # 'mean', 'median', or 'percentile'
        self.exposure_percentile = 75  # Use 75th percentile (focuses on brighter areas)
        self.clipping_threshold = 245  # Consider pixels > this value as clipped
        self.clipping_prevention = True  # Prevent further exposure increase if clipping detected
        self.white_balance_r = white_balance_r
        self.white_balance_b = white_balance_b
        self.auto_wb = auto_wb
        self.wb_mode = wb_mode  # 'asi_auto', 'manual', or 'gray_world'
        self.wb_config = wb_config if wb_config else {'mode': wb_mode}  # Full WB config
        self.flip = flip  # 0=none, 1=horizontal, 2=vertical, 3=both
        self.offset = offset
        self.bayer_pattern = bayer_pattern  # RGGB, BGGR, GRBG, GBRG
        self.use_raw16 = False  # Use RAW16 mode for full bit depth (set by dev mode)
        
        # Scheduled capture settings
        # mode: "always" | "gated" | "variable" — see services/config.py for semantics.
        # If caller didn't specify a mode, derive it from the legacy boolean so older
        # entry points (tests, headless runner pre-migration) still get sensible behaviour.
        self.scheduled_capture_mode = scheduled_capture_mode or (
            "gated" if scheduled_capture_enabled else "always"
        )
        self.scheduled_capture_enabled = self.scheduled_capture_mode != "always"
        self.scheduled_start_time = scheduled_start_time  # Format: "HH:MM"
        self.scheduled_end_time = scheduled_end_time      # Format: "HH:MM"
        self.scheduled_window_interval = scheduled_window_interval  # seconds (variable mode)
        
        # Exposure tracking for UI
        self.exposure_start_time = None
        self.exposure_remaining = 0.0
        
        # Rapid calibration mode
        self.calibration_mode = False  # Fast convergence before normal capture
        self.calibration_complete = False
        
        # Initialize calibration manager
        self.calibration_manager = None  # Will be initialized after camera connection

        # Pre-allocated ping-pong frame buffers reused each capture to reduce
        # per-frame large numpy allocation churn. Allocated lazily on first frame.
        self._frame_bufs: list = []
        self._frame_buf_idx: int = 0
        self._frame_buf_width: int = 0
        self._frame_buf_height: int = 0
        self._frame_buf_depth: int = 0
    
    # =========================================================================
    # Property aliases for backward compatibility (delegate to connection manager)
    # =========================================================================
    
    @property
    def camera(self):
        """Camera instance (delegated to connection manager)"""
        return self._connection.camera
    
    @camera.setter
    def camera(self, value):
        """Set camera instance"""
        self._connection.camera = value
    
    @property
    def asi(self):
        """ASI SDK instance (delegated to connection manager)"""
        return self._connection.asi
    
    @asi.setter
    def asi(self, value):
        """Set ASI SDK instance"""
        self._connection.asi = value
    
    @property
    def cameras(self):
        """List of detected cameras"""
        return self._connection.cameras
    
    @cameras.setter
    def cameras(self, value):
        """Set cameras list"""
        self._connection.cameras = value
    
    @property
    def supports_raw16(self) -> bool:
        """Whether camera supports RAW16 mode (delegated to connection manager)"""
        return self._connection.supports_raw16
    
    @property
    def sensor_bit_depth(self) -> int:
        """Camera's native ADC bit depth (delegated to connection manager)"""
        return self._connection.bit_depth
    
    @property
    def camera_info(self) -> dict:
        """Camera properties dict (delegated to connection manager)"""
        return self._connection.camera_info
    
    @property
    def current_bit_depth(self) -> int:
        """Current capture bit depth (8 for RAW8, 16 for RAW16)"""
        return self._connection.current_bit_depth
    
    def __del__(self):
        """Destructor to ensure camera is disconnected when object is destroyed"""
        try:
            self.disconnect_camera()
        except Exception:
            pass  # Ignore errors during cleanup in destructor
    
    def __enter__(self):
        """Context manager entry - allows use with 'with' statement"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup even if exception occurs"""
        self.disconnect_camera()
        return False  # Don't suppress exceptions
        
    def log(self, message):
        """Send log message via callback"""
        if self.on_log_callback:
            self.on_log_callback(message)
        app_logger.debug(message)
    
    def is_within_scheduled_window(self):
        """
        Whether capture is currently permitted (i.e. we should NOT pause).

        Only ``gated`` mode ever pauses capture — ``always`` and ``variable``
        both keep the camera live around the clock. The time window still
        matters in ``variable`` mode, but only for interval selection, which
        is handled by :pyattr:`effective_capture_interval`.
        """
        if self.scheduled_capture_mode != "gated":
            return True
        return check_scheduled_window(
            True,
            self.scheduled_start_time,
            self.scheduled_end_time
        )

    def is_in_time_window(self):
        """True when the current clock falls inside the configured window, mode-independent."""
        return check_scheduled_window(
            True,
            self.scheduled_start_time,
            self.scheduled_end_time
        )

    @property
    def effective_capture_interval(self):
        """The interval (seconds) to wait before the next capture, honouring the schedule mode."""
        if self.scheduled_capture_mode == "variable" and self.is_in_time_window():
            return max(1.0, float(self.scheduled_window_interval))
        return self.capture_interval
    
    def _ensure_frame_buffers(self, width: int, height: int, bit_depth: int) -> dict:
        """Return the next ping-pong buffer slot, (re)allocating if geometry changed."""
        if (self._frame_buf_width != width
                or self._frame_buf_height != height
                or self._frame_buf_depth != bit_depth
                or len(self._frame_bufs) < 2):
            self._frame_bufs = [
                {
                    'rgb8':  np.empty((height, width, 3), dtype=np.uint8),
                    'rgb16': np.empty((height, width, 3), dtype=np.uint16) if bit_depth == 16 else None,
                }
                for _ in range(2)
            ]
            self._frame_buf_width  = width
            self._frame_buf_height = height
            self._frame_buf_depth  = bit_depth
            # RAW8: 2 slots × rgb8 only; RAW16: 2 slots × (rgb8 + rgb16)
            mb = 2 * width * height * 3 * (1 + 2 * (bit_depth == 16)) // (1024 * 1024)
            self.log(f"Frame buffers: 2×{width}×{height} {'RAW16' if bit_depth == 16 else 'RAW8'} ({mb} MB)")
        buf = self._frame_bufs[self._frame_buf_idx]
        self._frame_buf_idx = 1 - self._frame_buf_idx
        return buf

    def _release_frame_buffers(self):
        """Drop pre-allocated frame buffers after capture stops.

        Safe to call from the main thread: stop_capture() always joins the
        capture thread (or confirms it has exited) before calling this, so
        no concurrent writer can be using the buffers at this point.
        """
        self._frame_bufs = []
        self._frame_buf_width = 0
        self._frame_buf_height = 0
        self._frame_buf_depth = 0
        self._frame_buf_idx = 0

    def initialize_sdk(self):
        """Initialize the ZWO ASI SDK (delegates to connection manager)"""
        # Update connection manager's logger to use our log method
        self._connection._logger = self.log
        return self._connection.initialize_sdk()
    
    def reset_sdk_completely(self):
        """
        Completely reset the SDK state (nuclear option).
        Delegates to connection manager.
        """
        return self._connection.reset_sdk_completely()
    
    def detect_cameras(self):
        """Detect connected ZWO cameras (delegates to connection manager)"""
        return self._connection.detect_cameras()
    
    def reconnect_camera_safe(self):
        """
        Safely reconnect to camera by re-detecting available cameras first.
        Delegates to connection manager, but handles calibration manager init.
        
        IMPORTANT: This passes current camera settings to ensure ROI and other
        settings are properly restored after reconnection. Without this, the
        camera may capture at wrong resolution causing reshape errors.
        """
        # Build settings dict from current properties to restore after reconnection
        settings = {
            'gain': self.gain,
            'exposure_sec': self.exposure_seconds,
            'wb_r': self.white_balance_r,
            'wb_b': self.white_balance_b,
            'wb_mode': self.wb_mode,
            'offset': self.offset,
            'flip': self.flip,
            'use_raw16': self.use_raw16,  # Preserve RAW16 mode after reconnection
        }
        
        success = self._connection.reconnect_safe(
            target_camera_name=self.camera_name,
            settings=settings,
            target_camera_serial=self.camera_serial
        )

        if success:
            # Sync identity from connection manager
            self.camera_name = self._connection.camera_name
            self.camera_index = self._connection.camera_index
            self.camera_serial = self._connection.camera_serial

            # Initialize calibration manager for the reconnected camera
            self._init_calibration_manager()
        
        return success
    
    def connect_camera(self, camera_index=0):
        """
        Connect to a specific camera.
        Delegates connection to connection manager, then initializes calibration.
        """
        # Build settings dict from our properties
        settings = {
            'gain': self.gain,
            'exposure_sec': self.exposure_seconds,
            'wb_r': self.white_balance_r,
            'wb_b': self.white_balance_b,
            'wb_mode': self.wb_mode,
            'offset': self.offset,
            'flip': self.flip,
            'use_raw16': self.use_raw16,  # RAW16 mode for full bit depth
        }
        
        # Delegate connection to connection manager. Pass expected name AND
        # serial so connect() rejects the wrong physical camera (a shifted
        # index can point the saved selection at a different body).
        success = self._connection.connect(
            camera_index, settings, expected_camera_name=self.camera_name,
            expected_camera_serial=self.camera_serial
        )

        # The saved index may point at the wrong body after a hot-plug; the
        # serial gate above then fails the open. Fall back to the serial-first
        # reconnect path, which probes serials to locate the correct index
        # rather than reconfiguring whichever camera the stale index hit.
        if not success and (self.camera_serial or self.camera_name):
            self.log("Direct connect failed — resolving camera by identity...")
            return self.reconnect_camera_safe()

        if success:
            # Sync identity from connection manager
            self.camera_name = self._connection.camera_name
            self.camera_index = self._connection.camera_index
            self.camera_serial = self._connection.camera_serial

            # Initialize calibration manager
            self._init_calibration_manager()

            self.log(f"✓ Camera connection successful")
            if self.scheduled_capture_enabled:
                self.log(f"Scheduled capture enabled: {self.scheduled_start_time} - {self.scheduled_end_time}")

        return success
    
    def _init_calibration_manager(self):
        """Initialize the calibration manager for connected camera"""
        if not self.camera:
            return
        
        self.log(f"Initializing calibration manager (max_exposure={self.max_exposure}s)...")
        self.calibration_manager = CameraCalibration(
            self.camera, self.asi, self.log, 
            bit_depth=self.current_bit_depth  # Pass current RAW mode bit depth
        )
        self.calibration_manager.update_settings(
            exposure_seconds=self.exposure_seconds,
            gain=self.gain,
            target_brightness=self.target_brightness,
            max_exposure_sec=self.max_exposure,
            algorithm=self.exposure_algorithm,
            percentile=self.exposure_percentile,
            clipping_threshold=self.clipping_threshold,
            clipping_prevention=self.clipping_prevention
        )
    
    def _configure_camera(self):
        """Configure camera settings (delegates to connection manager)"""
        if not self.camera:
            return
        
        settings = {
            'gain': self.gain,
            'exposure_sec': self.exposure_seconds,
            'wb_r': self.white_balance_r,
            'wb_b': self.white_balance_b,
            'wb_mode': self.wb_mode,
            'offset': self.offset,
            'flip': self.flip,
            'use_raw16': self.use_raw16,  # RAW16 mode for full bit depth
        }
        self._connection.configure(settings)
    
    def set_raw16_mode(self, enabled: bool) -> bool:
        """
        Change RAW mode (RAW8/RAW16) during live capture.
        
        Args:
            enabled: True for RAW16, False for RAW8
            
        Returns:
            True if mode changed successfully
        """
        if not self.camera:
            self.log("Cannot change RAW mode: camera not connected")
            return False
        
        if enabled and not self.supports_raw16:
            self.log("Camera does not support RAW16 mode")
            return False
        
        try:
            with self._connection.sdk_lock:
                if not self.camera:
                    raise Exception("Camera disconnected before RAW mode change")

                # Verify we're talking to the right camera before writing settings
                if not self._connection.verify_identity():
                    raise Exception("Camera identity mismatch — aborting RAW mode change")

                # Update our setting
                self.use_raw16 = enabled

                # Get camera info for ROI
                camera_info = self.camera.get_camera_property()
                width = camera_info['MaxWidth']
                height = camera_info['MaxHeight']

                # Set new image type
                image_type = self.asi.ASI_IMG_RAW16 if enabled else self.asi.ASI_IMG_RAW8
                self.camera.set_roi(start_x=0, start_y=0, width=width, height=height,
                                    bins=1, image_type=image_type)
                self.camera.set_image_type(image_type)

                # Update connection manager state
                self._connection.current_image_type = image_type
                self._connection.current_bit_depth = 16 if enabled else 8

            # Update calibration manager bit depth (outside lock — no SDK calls)
            if self.calibration_manager:
                self.calibration_manager.bit_depth = self.current_bit_depth

            mode_str = "RAW16" if enabled else "RAW8"
            self.log(f"Switched to {mode_str} mode ({self.current_bit_depth}-bit capture)")
            return True
            
        except Exception as e:
            self.log(f"Error changing RAW mode: {e}")
            return False

    def disconnect_camera(self):
        """Disconnect from camera gracefully (idempotent - safe to call multiple times)"""
        # Stop capture first if active
        if self.is_capturing:
            self.log("Stopping active capture before disconnect...")
            self.stop_capture()
        
        # Clear exposure tracking before disconnect. The authoritative
        # stop_exposure() runs under sdk_lock inside CameraConnection.disconnect();
        # issuing one here (before that lock) would be an unsynchronized SDK call
        # racing the capture worker, which can corrupt the ZWO DLL. So only reset
        # the UI-facing tracking state here.
        def stop_exposure_callback():
            if self.exposure_start_time is not None:
                self.log("Clearing in-progress exposure tracking before disconnect...")
                self.exposure_start_time = None
                self.exposure_remaining = 0.0
        
        # Delegate to connection manager
        self._connection.disconnect(stop_exposure_callback=stop_exposure_callback)
        
        # Clear exposure tracking
        self.exposure_start_time = None
        self.exposure_remaining = 0.0
    
    def capture_single_frame(self):
        return zwo_capture_worker.capture_single_frame(self)

    def capture_loop(self):
        return zwo_capture_worker.capture_loop(self)

    def start_capture(self, on_frame_callback, on_log_callback=None):
        """Start continuous capture"""
        if self.is_capturing:
            self.log("Capture already running")
            return False
        
        if not self.camera:
            self.log("ERROR: Camera not connected")
            return False
        
        self.on_frame_callback = on_frame_callback
        self.on_log_callback = on_log_callback
        self.is_capturing = True
        
        # Start capture thread
        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()
        
        return True
    
    def wait_for_capture_thread_exit(self, timeout: float = 10.0) -> bool:
        """Wait for the capture thread to exit without issuing new SDK calls.

        Used by the UI-level auto-recovery path: after the watchdog declares a
        fatal wedge, the capture thread may still be blocked inside an ASI SDK
        call. Starting a new ZWOCamera instance (which reinitialises the SDK)
        while that thread is alive has caused C++ SEH exceptions and access
        violations from concurrent SDK access. Join the thread first, then
        recover.

        Unlike stop_capture(), this does NOT call stop_exposure() or touch
        the SDK at all — the caller has already decided the camera is wedged
        and SDK calls may themselves hang or crash. We just wait for the
        thread to unwind on its own.

        Returns True if the thread exited (or was never alive), False on timeout.
        """
        self.is_capturing = False
        if self.calibration_manager:
            try:
                self.calibration_manager.abort()
            except Exception:
                pass

        if not self.capture_thread or not self.capture_thread.is_alive():
            return True

        self.log(f"Waiting up to {timeout:.0f}s for wedged capture thread to exit...")
        self.capture_thread.join(timeout=timeout)
        if self.capture_thread.is_alive():
            self.log(
                "⚠ Capture thread did not exit within timeout — "
                "SDK call still blocked; recovery will proceed anyway"
            )
            return False
        self.log("✓ Capture thread exited cleanly before recovery")
        self.capture_thread = None
        return True

    def stop_capture(self):
        """Stop continuous capture and wait for thread to finish"""
        if not self.is_capturing:
            return

        self.log("Stopping capture...")
        self.is_capturing = False
        self._recovery_requested = False

        # Abort any running calibration so its loop exits quickly
        if self.calibration_manager:
            self.calibration_manager.abort()

        # Abort any in-progress exposure so the poll loop exits immediately.
        # During calibration exposure_start_time isn't set, so also fire when a
        # calibration exposure may be in flight. Take sdk_lock (briefly) so we
        # don't issue stop_exposure() concurrently with the worker's own SDK
        # calls — a documented ZWO DLL corruption trigger. If the worker is
        # wedged holding the lock, the short timeout lets us give up; the
        # bounded readout/calibration timeouts surface the wedge instead.
        if self.camera and (self.exposure_start_time is not None or self.calibration_mode):
            lock = self._connection.sdk_lock
            if lock.acquire(timeout=2.0):
                try:
                    if self.camera:
                        self.camera.stop_exposure()
                except Exception:
                    pass
                finally:
                    lock.release()

        # Wait for capture thread — should exit quickly now that
        # is_capturing is False and exposure is aborted
        if self.capture_thread and self.capture_thread.is_alive():
            self.log("Waiting for capture thread to finish...")
            self.capture_thread.join(timeout=3.0)

            if self.capture_thread.is_alive():
                # Keep the reference: the worker is wedged inside an SDK call,
                # and reinitialising the SDK while it's alive corrupts the ZWO
                # DLL. Callers join it via wait_for_capture_thread_exit().
                self.log("Warning: Capture thread still running (will finish in background)")
            else:
                self.log("Capture thread finished successfully")
                self.capture_thread = None

        self._release_frame_buffers()
        self.log("Capture stopped")
    
    def set_exposure(self, seconds):
        """Set exposure time in seconds"""
        self.exposure_seconds = max(0.000001, min(3600, seconds))
    
    def set_gain(self, gain):
        """Set gain value"""
        self.gain = max(0, min(600, int(gain)))
    
    def set_capture_interval(self, seconds):
        """Set interval between captures"""
        self.capture_interval = max(1.0, seconds)
    
    def _set_control_live(self, control, value, success_msg=None) -> bool:
        """Apply a single control value to the live camera under sdk_lock.

        Live setting writes originate on the UI thread while the capture worker
        is running; both touch the SDK, so they must serialize on sdk_lock or
        concurrent access can corrupt the ZWO DLL. A short timed acquire keeps
        the caller responsive if the worker is momentarily holding the lock.
        """
        if not self.camera or not self.asi:
            return False
        lock = self._connection.sdk_lock
        if not lock.acquire(timeout=2.0):
            self.log("⚠ Live setting skipped — SDK busy (capture worker holds lock)")
            return False
        try:
            if not self.camera:
                return False
            self.camera.set_control_value(control, value)
            if success_msg:
                self.log(success_msg)
            return True
        except Exception as e:
            self.log(f"Failed to apply live setting: {e}")
            return False
        finally:
            lock.release()

    def set_offset_live(self, offset):
        """Set brightness/offset, applying live to the camera under sdk_lock."""
        self.offset = offset
        if self.camera and self.asi:
            self._set_control_live(self.asi.ASI_BRIGHTNESS, offset)

    def set_flip_live(self, flip):
        """Set flip, applying live to the camera under sdk_lock."""
        self.flip = flip
        if self.camera and self.asi:
            self._set_control_live(self.asi.ASI_FLIP, flip)

    def update_exposure(self, exposure_seconds):
        """Update exposure setting and apply immediately to camera if connected"""
        self.exposure_seconds = exposure_seconds

        # If camera is connected and not in auto exposure mode, apply immediately
        # (sdk_lock-guarded — a live write racing the capture worker's SDK calls
        # can corrupt the ZWO DLL).
        if self.camera and not self.auto_exposure:
            self._set_control_live(
                self.asi.ASI_EXPOSURE, int(exposure_seconds * 1000000),
                f"Exposure updated to {exposure_seconds*1000:.2f}ms",
            )
    
    def run_calibration(self):
        """Rapid calibration to find optimal exposure before starting interval captures"""
        if not self.auto_exposure or not self.camera or not self.calibration_manager:
            return

        self.log(f"Starting rapid auto-exposure calibration... "
                 f"(max_exposure={self.max_exposure}s, "
                 f"cal_max={self.calibration_manager.max_exposure_sec}s)")
        self.calibration_mode = True

        # Notify UI that calibration is starting
        if self.on_calibration_callback:
            self.on_calibration_callback(True)

        # Run calibration using the calibration manager
        import time as _time
        _cal_start = _time.time()
        success = self.calibration_manager.run_calibration(max_attempts=15)
        _cal_duration = _time.time() - _cal_start

        # Update our exposure from calibration manager
        self.exposure_seconds = self.calibration_manager.exposure_seconds

        self.calibration_complete = True
        self.calibration_mode = False

        # PostHog: calibration results
        from ..posthog_service import capture_event
        cal_history = getattr(self.calibration_manager, 'calibration_history', [])
        capture_event('calibration_completed', {
            'success': success,
            'duration_seconds': round(_cal_duration, 1),
            'attempts': len(cal_history) if cal_history else None,
            'final_exposure_ms': round(self.exposure_seconds * 1000, 2),
            'final_brightness': round(cal_history[-1][1], 1) if cal_history else None,
            'target_brightness': self.calibration_manager.target_brightness,
            'max_exposure_ms': round(self.max_exposure * 1000, 0),
        })

        # Notify UI that calibration is complete
        if self.on_calibration_callback:
            self.on_calibration_callback(False)
    
    def adjust_exposure_auto(self, img_array):
        """
        Adjust exposure based on image brightness with intelligent step sizing.
        
        Returns:
            dict with 'needs_recalibration' flag and brightness info, or None if auto-exposure disabled
        """
        if not self.auto_exposure or not self.calibration_manager:
            return None
        
        # Use calibration manager to adjust exposure
        result = self.calibration_manager.adjust_exposure_auto(img_array)
        
        # Update our exposure from calibration manager
        self.exposure_seconds = self.calibration_manager.exposure_seconds
        
        return result
