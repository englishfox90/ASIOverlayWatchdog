"""
Camera connection management for ZWO ASI cameras

Handles SDK initialization, camera detection, connection/reconnection, and configuration.
This module is used internally by ZWOCamera - do not import directly.
"""
import os
import sys
import time
import threading
from typing import Optional, List, Dict, Callable, Any
from .camera_config import verify_camera_identity, configure_camera, wait_for_controls_ready
from .camera_utils import call_with_timeout, SDKTimeoutError
from .sdk_lock import SDK_LOCK

# Hard upper bounds (seconds) on blocking ZWO SDK C-calls. These calls cannot
# be interrupted, so an unbounded wait wedges the connection/disconnection path
# when a USB device hangs. See the connection audit, 2026-06-02.
_OPEN_TIMEOUT_SEC = 20.0          # asi.Camera() — ASIOpenCamera + ASIInitCamera
_PROPERTY_TIMEOUT_SEC = 10.0      # get_camera_property / get_controls
_CONFIGURE_TIMEOUT_SEC = 30.0     # configure_camera (set_roi has internal retries)
_CONTROLS_READY_TIMEOUT_SEC = 12.0  # wait_for_controls_ready (polls get_controls until settled)
# Max wait for the capture worker to release sdk_lock during disconnect. If it
# is wedged inside an uninterruptible SDK call it holds the lock; rather than
# block shutdown forever, we abandon the close and let higher-level recovery
# (which joins the wedged thread first) reclaim the handle.
_DISCONNECT_LOCK_TIMEOUT_SEC = 5.0
# Max wait to take sdk_lock before opening a camera. The open is serialized
# against other SDK calls on the shared DLL (an abandoned serial-probe close,
# a disconnect). Best-effort: on contention we still open — failing a connect
# because the lock was briefly busy would be a reliability regression.
_OPEN_LOCK_TIMEOUT_SEC = 8.0


class CameraConnection:
    """
    Manages ZWO ASI SDK and camera connection lifecycle.

    This class handles:
    - SDK initialization and reset
    - Camera detection and enumeration
    - Camera connection with retry logic
    - Camera configuration (gain, exposure, WB, etc.)
    - Safe reconnection after disconnects
    """

    def __init__(self, sdk_path: Optional[str] = None, logger: Optional[Callable[[str], None]] = None):
        """
        Initialize connection manager.

        Args:
            sdk_path: Path to ASICamera2.dll (optional, will search defaults)
            logger: Callback function for logging messages
        """
        self.sdk_path = sdk_path
        self._logger = logger

        # SDK state
        self.asi = None
        self.camera = None
        self.cameras: List[Dict[str, Any]] = []

        # Camera identification for reconnection
        self.camera_name: Optional[str] = None
        self.camera_index: int = 0
        # Stable hardware serial of the currently-connected camera (the
        # authoritative identity; index/name are non-unique/unstable).
        self.camera_serial: Optional[str] = None

        # Camera capabilities (populated on connect)
        self.camera_info: dict = {}
        self.supports_raw16: bool = False
        self.bit_depth: int = 8  # Sensor ADC bit depth

        # Current capture mode
        self.current_image_type = None  # ASI_IMG_RAW8 or ASI_IMG_RAW16
        self.current_bit_depth: int = 8  # 8 for RAW8, 16 for RAW16

        # Thread safety
        self._cleanup_lock = threading.Lock()
        # Process-global: every connection shares one SDK lock so a dying
        # capture thread and a fresh reconnect can't both call the (non
        # thread-safe) ZWO DLL at once. See services/camera/sdk_lock.py.
        self.sdk_lock = SDK_LOCK  # Guards all SDK calls (capture vs disconnect race)

        # Callback for persisting camera name to config
        self.config_callback: Optional[Callable[[str, Any], None]] = None

        # USB reset capability (Windows only)
        self._usb_reset_available = False
        self._usb_reset_func = None
        self._usb_disable_enable_func = None
        self._init_usb_reset()

    def log(self, message: str) -> None:
        """Log message via callback or app_logger"""
        if self._logger:
            self._logger(message)
        else:
            from ..logger import app_logger
            app_logger.debug(message)

    def _init_usb_reset(self) -> None:
        """Initialize USB reset capability (Windows only)"""
        if sys.platform != 'win32':
            return  # USB reset only supported on Windows

        try:
            from services.usb_reset_win import (
                reset_zwo_camera_usb, disable_enable_zwo_camera_usb,
                is_usb_reset_available
            )
            if is_usb_reset_available():
                self._usb_reset_available = True
                self._usb_reset_func = reset_zwo_camera_usb
                self._usb_disable_enable_func = disable_enable_zwo_camera_usb
                self.log("\u2713 USB reset capability available (includes disable/enable)")
            else:
                self.log("⚠ USB reset not available (Windows API load failed)")
        except ImportError as e:
            self.log(f"⚠ USB reset module not available: {e}")
        except Exception as e:
            self.log(f"⚠ Error initializing USB reset: {e}")

    @staticmethod
    def _is_running_as_admin() -> bool:
        """Check if the current process has Administrator privileges."""
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    # =========================================================================
    # SDK Initialization
    # =========================================================================

    def initialize_sdk(self) -> bool:
        """
        Initialize the ZWO ASI SDK.

        Returns:
            True if successful, False otherwise
        """
        self.log("=== Initializing ZWO ASI SDK ===")
        try:
            import zwoasi as asi
            self.asi = asi
            self.log("zwoasi module imported successfully")

            if self.sdk_path and os.path.exists(self.sdk_path):
                self.log(f"Attempting SDK init with configured path: {self.sdk_path}")
                asi.init(self.sdk_path)
                self.log(f"✓ ZWO SDK initialized successfully from: {self.sdk_path}")
            else:
                # Try default locations
                self.log("SDK path not configured or not found, trying default location")
                if os.path.exists('ASICamera2.dll'):
                    self.log("Found ASICamera2.dll in application directory")
                    asi.init('ASICamera2.dll')
                    self.log("✓ ZWO SDK initialized from: ASICamera2.dll")
                else:
                    self.log("ERROR: ASICamera2.dll not found in application directory")
                    self.log("Please configure SDK path in Capture tab settings")
                    return False

            return True

        except ImportError as e:
            self.log(f"ERROR: zwoasi library not installed: {e}")
            self.log("Run: pip install zwoasi")
            return False
        except Exception as e:
            self.log(f"ERROR initializing ZWO SDK: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            return False

    def reset_sdk_completely(self) -> bool:
        """
        Completely reset the SDK state (nuclear option).
        Use this when SDK gets into an inconsistent state.

        Returns:
            True if successful, False otherwise
        """
        self.log("=== Complete SDK Reset ===")

        try:
            # Close camera if connected
            if self.camera:
                self.log("Disconnecting camera before SDK reset...")
                self.disconnect()

            # Clear SDK reference
            self.log("Clearing SDK reference...")
            self.asi = None

            # Wait for cleanup
            time.sleep(1.0)

            # Reinitialize SDK
            self.log("Reinitializing SDK...")
            if not self.initialize_sdk():
                self.log("✗ SDK reinitialization failed")
                return False

            self.log("✓ SDK reset complete")
            return True

        except Exception as e:
            self.log(f"✗ ERROR during SDK reset: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            return False

    # =========================================================================
    # Camera Detection
    # =========================================================================

    def detect_cameras(self) -> List[Dict[str, Any]]:
        """Detect connected ZWO cameras (delegates to camera_detect)."""
        from .camera_detect import detect_cameras as detect_cameras_impl
        return detect_cameras_impl(self)

    # =========================================================================
    # Camera Connection
    # =========================================================================

    def connect(self, camera_index: int = 0, settings: Optional[Dict[str, Any]] = None,
                expected_camera_name: Optional[str] = None,
                expected_camera_serial: Optional[str] = None,
                post_recovery: bool = False,
                _skip_roi_usb_recovery: bool = False) -> bool:
        """
        Connect to a specific camera.

        Args:
            camera_index: Index of camera to connect to
            settings: Optional dict with camera settings (gain, exposure_sec, wb_r, wb_b, etc.)
            expected_camera_name: If provided, verify the opened camera matches this name.
                Prevents connecting to the wrong physical camera when SDK indices shift.
            post_recovery: If True, we just came out of a USB disable/enable cycle.
                Use a longer retry schedule (6 attempts with exponential backoff)
                and re-run detect_cameras() between attempts, because the camera
                may appear in the SDK list before it's actually openable, and
                its index may shift on re-enumeration.
            _skip_roi_usb_recovery: Internal flag. Suppresses connect()'s own
                USB disable/enable escalation on a set_roi "Invalid size".
                Set True (a) on the single self-recursive retry, to prevent an
                infinite reset loop if the camera stays wedged, and (b) by
                reconnect_safe(), which owns escalation for its flows — so the
                two layers don't double-fire a USB power-cycle. Direct callers
                (e.g. the initial Start Capture path) leave it False to get
                self-healing.

        Returns:
            True if successful, False otherwise
        """
        self.log(f"=== Connecting to Camera (Index: {camera_index}) ===")

        if not self.asi:
            self.log("SDK not initialized, initializing now...")
            if not self.initialize_sdk():
                self.log("Connection failed: SDK initialization failed")
                return False

        try:
            if self.camera:
                self.log("Existing camera connection detected, disconnecting first...")
                self.disconnect()

            # Add delay to allow SDK cleanup (especially important after other apps like ASICap)
            time.sleep(0.5)  # Increased from 0.2s

            self.log(f"Opening camera at index {camera_index}...")

            # Retry schedule: tighter for normal connects, longer & with
            # re-detection for post-recovery opens (driver may still be binding
            # and SDK index may shift).
            if post_recovery:
                backoff_schedule = [1.0, 2.0, 4.0, 4.0, 4.0]  # ~15s total
                self.log(f"  (post-recovery mode: up to {len(backoff_schedule) + 1} attempts with re-detection)")
            else:
                backoff_schedule = [1.0, 1.0]  # 3 attempts total
            max_attempts = len(backoff_schedule) + 1

            for attempt in range(1, max_attempts + 1):
                try:
                    # Bounded: asi.Camera() runs ASIOpenCamera + ASIInitCamera,
                    # which historically hang on a wedged USB device. Serialize
                    # the open under sdk_lock so it can't race another SDK call on
                    # the shared DLL (e.g. an abandoned serial-probe close in
                    # camera_identity._probe_serial). Best-effort: on contention
                    # we still open (pre-lock parity), never fail on the lock.
                    got_lock = self.sdk_lock.acquire(timeout=_OPEN_LOCK_TIMEOUT_SEC)
                    try:
                        self.camera = call_with_timeout(
                            lambda: self.asi.Camera(camera_index), _OPEN_TIMEOUT_SEC,
                            hint="camera open/init — USB may be wedged",
                        )
                    finally:
                        if got_lock:
                            self.sdk_lock.release()
                    break  # Success - exit retry loop
                except Exception as e:
                    if attempt < max_attempts:
                        self.log(f"⚠ Attempt {attempt}/{max_attempts} failed: {e}")
                        if attempt == 1 and not post_recovery:
                            self.log(f"⚠ If you recently used ASICap or other ZWO software, please wait 10-15 seconds before retrying")

                        # On "Invalid ID" during post-recovery, re-enumerate to
                        # pick up the camera's (possibly shifted) new index.
                        if post_recovery and "Invalid ID" in str(e) and expected_camera_name:
                            self.log("  Re-detecting cameras (index may have shifted after recovery)...")
                            try:
                                refreshed = self.detect_cameras()
                                if refreshed:
                                    new_idx = self._find_camera_index_by_name(refreshed, expected_camera_name)
                                    if new_idx is not None and new_idx != camera_index:
                                        self.log(f"  Target now at index {new_idx} (was {camera_index})")
                                        camera_index = new_idx
                            except Exception as detect_err:
                                self.log(f"  Re-detect failed: {detect_err}")

                        wait = backoff_schedule[attempt - 1]
                        self.log(f"Waiting {wait}s before retry...")
                        time.sleep(wait)
                    else:
                        # Final attempt failed - re-raise the exception
                        raise

            camera_info = call_with_timeout(
                self.camera.get_camera_property, _PROPERTY_TIMEOUT_SEC,
                hint="get_camera_property after open",
            )
            actual_name = camera_info['Name']

            # Validate camera identity — if we expected a specific camera, make sure
            # the SDK gave us the right one.  SDK indices can silently shift when
            # cameras are hot-plugged, so this catches cross-wiring.  We require
            # an exact name match (after strip) rather than substring — writing
            # one camera's ROI/gain to a different camera of the same model
            # family could still mis-configure the hardware.
            if expected_camera_name:
                expected = expected_camera_name.strip()
                actual = (actual_name or '').strip()
                if expected != actual:
                    self.log(
                        f"✗ Camera identity mismatch! Expected '{expected}' "
                        f"at index {camera_index}, but SDK returned '{actual}' "
                        f"({camera_info['MaxWidth']}x{camera_info['MaxHeight']}, "
                        f"{camera_info['PixelSize']}µm)"
                    )
                    self.log("  Closing wrong camera and failing connection.")
                    try:
                        self.camera.close()
                    except Exception:
                        pass
                    self.camera = None
                    return False

            # Authoritative identity gate. The model name above is shared by
            # every body of the same model, so when a serial is on file we
            # confirm THIS physical device before writing any settings — the
            # name match alone let the app reconfigure a guide camera when
            # indices shifted (June 2026). Serial reads require the open handle;
            # an unreadable serial (None) falls through to the name match above.
            from .camera_identity import read_serial, serials_match
            actual_serial = read_serial(self.camera)
            if expected_camera_serial and actual_serial is not None \
                    and not serials_match(expected_camera_serial, actual_serial):
                self.log(
                    f"✗ Camera identity mismatch by SERIAL! Expected "
                    f"{expected_camera_serial} at index {camera_index}, but SDK "
                    f"returned {actual_serial}. Closing wrong camera and failing."
                )
                try:
                    self.camera.close()
                except Exception:
                    pass
                self.camera = None
                return False

            # Store identity and persist to config. The serial is the stable
            # key; configs predating it learn it here on the first clean connect.
            self.camera_name = actual_name
            self.camera_index = camera_index
            self.camera_serial = actual_serial
            if self.config_callback:
                self.config_callback('zwo_selected_camera_name', self.camera_name)
                if actual_serial:
                    self.config_callback('zwo_selected_camera_serial', actual_serial)
                self.log(f"Saved camera identity: {self.camera_name} "
                         f"(serial {actual_serial or 'unavailable'})")

            # Store camera capabilities for later access
            self.camera_info = camera_info
            self.supports_raw16 = 2 in camera_info.get('SupportedVideoFormat', [0])  # ASI_IMG_RAW16 = 2
            self.bit_depth = camera_info.get('BitDepth', 8)

            self.log(f"✓ Connected to camera: {actual_name}")
            self.log(f"  Camera ID: {camera_info.get('CameraID', 'N/A')}")
            self.log(f"  Max Resolution: {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")
            self.log(f"  Pixel Size: {camera_info['PixelSize']} µm")
            self.log(f"  Sensor ADC: {self.bit_depth}-bit")
            self.log(f"  RAW16 Support: {'Yes' if self.supports_raw16 else 'No'}")

            # Wait for control enumeration to settle before configuring.  The
            # camera firmware enumerates controls incrementally after open();
            # set_roi() returns Invalid size while it is still partial (the
            # ASI676MC reports only 10/17 controls for ~1s on a cold boot).
            # Polling until the count stops growing is more reliable than a
            # fixed sleep — fast on a warm reconnect, patient on a cold boot.
            controls = call_with_timeout(
                lambda: wait_for_controls_ready(self.camera, self.log),
                _CONTROLS_READY_TIMEOUT_SEC,
                hint="waiting for controls to enumerate",
            )

            # Apply settings — bounded so a camera that opens but won't
            # configure fails the connect cleanly instead of hanging.
            if settings:
                call_with_timeout(
                    lambda: self.configure(settings), _CONFIGURE_TIMEOUT_SEC,
                    hint="camera configure",
                )
            else:
                # Explicit full-frame ROI — the SDK can retain a stale ROI from
                # a prior session, causing reshape failures without this.
                self.log("No settings provided - setting ROI to full frame (default)")

                def _default_full_frame_roi():
                    self.camera.set_roi(
                        start_x=0, start_y=0, width=camera_info['MaxWidth'],
                        height=camera_info['MaxHeight'], bins=1,
                        image_type=self.asi.ASI_IMG_RAW8,
                    )
                    self.camera.set_image_type(self.asi.ASI_IMG_RAW8)

                call_with_timeout(_default_full_frame_roi, _CONFIGURE_TIMEOUT_SEC,
                                  hint="default full-frame ROI")
                self.log(f"  ROI: Full frame {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")

            self.log(f"✓ Camera connection successful")
            return True

        except Exception as e:
            self.log(f"✗ ERROR connecting to camera: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")

            # Close any camera handle opened before the failure so the SDK
            # releases it — otherwise the next open can fail with
            # "already opened" until the process exits.
            if self.camera is not None:
                try:
                    self.camera.close()
                except Exception:
                    pass
                self.camera = None

            # Add diagnostic information for "Invalid ID" errors
            if "Invalid ID" in str(e):
                self._log_invalid_id_diagnostics(camera_index)

            # "Invalid size" on a camera that *opened* fine means set_roi was
            # rejected even at the camera's own native full-frame resolution —
            # the firmware is wedged (half-enumerated controls, locked ROI).
            # An SDK reset cannot clear this; only a USB disable/enable does.
            # Escalate once, then retry the open+configure on a clean device.
            if (not _skip_roi_usb_recovery
                    and "invalid size" in str(e).lower()
                    and expected_camera_name
                    and self._usb_disable_enable_func):
                if not self._is_running_as_admin():
                    self.log("⚠ set_roi failed (camera wedged) but USB disable/enable "
                             "needs Administrator — cannot auto-recover. Run the app as "
                             "Administrator, or physically replug the camera's USB.")
                    return False
                self.log("⚠ set_roi rejected at native full-frame (wedged firmware) "
                         "— escalating to USB disable/enable to power-cycle the camera...")
                from .camera_reconnect import run_recovery_ladder
                target_found, target_index, _post = run_recovery_ladder(
                    self, expected_camera_name, force_disable_enable=True
                )
                if target_found and target_index is not None:
                    return self.connect(
                        target_index, settings,
                        expected_camera_name=expected_camera_name,
                        expected_camera_serial=expected_camera_serial,
                        post_recovery=True, _skip_roi_usb_recovery=True,
                    )
                self.log("✗ Camera still not recoverable after USB disable/enable")

            return False

    def _log_invalid_id_diagnostics(self, camera_index: int) -> None:
        """Log diagnostic information for Invalid ID errors (delegates)."""
        from .camera_detect import log_invalid_id_diagnostics
        log_invalid_id_diagnostics(self, camera_index)

    def _wait_for_stable_detection(self, camera_name: str,
                                    timeout_sec: float = 10.0,
                                    poll_interval: float = 2.0) -> Optional[int]:
        """
        Poll detect_cameras() until the target camera appears at the same index
        on two consecutive polls, or timeout.

        Right after a USB disable/enable cycle, the SDK can briefly show the
        camera before the driver is fully bound — `connect()` then fails with
        "Invalid ID". Waiting for a stable detection avoids that race.

        Args:
            camera_name: Name substring to search for
            timeout_sec: Max wait time
            poll_interval: Seconds between polls

        Returns:
            Stable camera index, or None if not seen stably within timeout.
        """
        from .camera_reconnect import wait_for_stable_detection
        return wait_for_stable_detection(self, camera_name, timeout_sec, poll_interval)

    def _find_camera_index_by_name(self, cameras: List[Dict[str, Any]], camera_name: str) -> Optional[int]:
        """Return the index of the camera whose name exactly matches (after strip).

        Exact, not substring — a substring could match a different model family
        (e.g. "...676MC" inside "...676MC Pro"). This only picks the start index;
        connect()'s serial gate is the authoritative downstream check. None if absent.
        """
        target = (camera_name or '').strip()
        for cam in cameras:
            if target == (cam['name'] or '').strip():
                self.log(f"✓ Found camera '{camera_name}' at index {cam['index']}")
                return cam['index']

        self.log(f"✗ Camera '{camera_name}' not found in detected cameras:")
        for cam in cameras:
            self.log(f"  - [{cam['index']}] {cam['name']}")
        return None

    def reconnect_safe(self, target_camera_name: Optional[str] = None,
                       settings: Optional[Dict[str, Any]] = None,
                       allow_fallback: bool = False,
                       target_camera_serial: Optional[str] = None) -> bool:
        """
        Safely reconnect to camera by re-detecting available cameras first.

        Args:
            target_camera_name: Name of camera to reconnect to (defaults to last connected)
            settings: Camera settings dict to apply after reconnection (ROI, gain, etc.)
                     CRITICAL: Without settings, camera may use default ROI causing
                     resolution mismatch and reshape errors during capture.
            allow_fallback: If False (default), reconnection fails if target camera not found.
                           If True, falls back to first available camera.

        Returns:
            True if reconnection successful, False otherwise

        IMPORTANT: By default, this method will NOT connect to a different camera
        if the target camera is not found. This prevents accidentally connecting
        to the wrong camera when the originally-selected camera loses power or
        is disconnected.
        """
        from .camera_reconnect import reconnect_safe as reconnect_safe_impl
        return reconnect_safe_impl(self, target_camera_name, settings, allow_fallback,
                                   target_camera_serial=target_camera_serial)

    # =========================================================================
    # Camera Configuration
    # =========================================================================

    def verify_identity(self) -> bool:
        """Verify the open camera handle still points to the expected physical camera."""
        return verify_camera_identity(
            self.camera, self.camera_name, self.log, camera_serial=self.camera_serial
        )

    def configure(self, settings: Dict[str, Any]) -> None:
        """Configure camera settings.

        Raises on SDK errors so the caller can fail the connection cleanly.
        Silently swallowing caused the SDK to keep a stale ROI after a
        failed set_roi, which then produced a reshape crash on every frame
        (see production log 2026-04-20 10:31).
        """
        if not self.camera:
            self.log("Cannot configure: camera not connected")
            return
        self.log("Configuring camera settings...")
        if not verify_camera_identity(self.camera, self.camera_name, self.log,
                                      camera_serial=self.camera_serial):
            raise Exception("Camera identity mismatch — aborting configure")
        image_type, bit_depth = configure_camera(
            self.camera, self.asi, settings, self.supports_raw16, self.log
        )
        self.current_image_type = image_type
        self.current_bit_depth = bit_depth

    # =========================================================================
    # Camera Disconnection
    # =========================================================================

    def disconnect(self, stop_exposure_callback: Optional[Callable[[], None]] = None,
                   release_sdk: bool = False) -> None:
        """
        Disconnect from camera gracefully (idempotent - safe to call multiple times).

        Stops any in-progress exposure and closes the camera handle.
        camera.close() is sufficient cleanup — the SDK releases all state for the
        handle.  Previously we reset ROI/controls before closing, but that raced
        with the capture thread and could contaminate other cameras' SDK state when
        multiple ZWO cameras share the same process.

        Args:
            stop_exposure_callback: Optional callback to stop any in-progress exposure
            release_sdk: If True, also drop the SDK reference (self.asi) after
                closing so the next detect/connect re-initializes the SDK from a
                clean state.  Use this for *long* idle gaps such as off-peak
                scheduled disconnects — reusing a multi-hour-stale SDK handle is
                the condition under which the camera came back unopenable
                ("Invalid ID") in production (log 2026-05-31 09:00 → 16:00).
                detect_cameras()/connect() both re-init the SDK when self.asi is
                None, so the reconnect path handles this transparently.
        """
        with self._cleanup_lock:
            if not self.camera:
                if release_sdk and self.asi is not None:
                    self.asi = None
                    self.log("SDK reference released (no camera was open)")
                else:
                    # Identify the caller + thread. A disconnect arriving here
                    # mid-window (camera already None) points to a second code
                    # path racing the capture worker — see the 2026-06-02 17:08
                    # incident. Without this we can't tell who issued it.
                    import traceback
                    caller = "unknown"
                    try:
                        stack = traceback.extract_stack(limit=3)
                        if len(stack) >= 2:
                            frame = stack[-2]
                            fname = os.path.basename(frame.filename)
                            caller = f"{fname}:{frame.lineno} in {frame.name}()"
                    except Exception:
                        pass
                    self.log(
                        "Disconnect called but camera already disconnected "
                        f"(thread={threading.current_thread().name}, caller={caller})"
                    )
                return

            self.log("=== Disconnecting Camera ===")

            try:
                # Call stop exposure callback if provided
                if stop_exposure_callback:
                    try:
                        stop_exposure_callback()
                    except Exception as e:
                        self.log(f"Exposure stop callback error: {e}")

                # Acquire SDK lock so we don't race with capture_single_frame.
                # Bounded: if the capture worker is wedged inside an
                # uninterruptible SDK call it holds this lock, and an unbounded
                # wait here would block disconnect (and app shutdown) forever.
                # On timeout we abandon the close rather than deadlock — the
                # higher-level recovery joins the wedged thread and runs a USB
                # reset to reclaim the handle.
                acquired = self.sdk_lock.acquire(timeout=_DISCONNECT_LOCK_TIMEOUT_SEC)
                if not acquired:
                    self.log(
                        f"⚠ SDK lock still held after {_DISCONNECT_LOCK_TIMEOUT_SEC:.0f}s "
                        "— capture thread wedged in an SDK call. Abandoning close to "
                        "avoid blocking shutdown; USB recovery will reclaim the handle."
                    )
                else:
                    try:
                        # Stop any in-progress exposure before closing.
                        try:
                            self.camera.stop_exposure()
                        except Exception:
                            pass  # Ignore — camera may already be idle

                        # Close camera connection
                        try:
                            self.log("Closing camera connection...")
                            self.camera.close()
                            self.log("✓ Camera disconnected successfully")

                            # Brief delay for SDK to fully release USB device
                            try:
                                time.sleep(0.5)
                            except OSError:
                                pass  # WinError 6: handle invalid during interpreter shutdown

                        except Exception as e:
                            self.log(f"⚠ Warning during camera close: {e}")
                            if self._usb_reset_available and self.camera_name:
                                self.log("  Attempting USB reset due to close failure...")
                                try:
                                    self._usb_reset_func(camera_name=self.camera_name, logger=self.log)
                                except Exception as usb_err:
                                    self.log(f"  USB reset error: {usb_err}")
                    finally:
                        self.sdk_lock.release()

            except Exception as e:
                self.log(f"✗ ERROR during camera disconnect: {e}")
                import traceback
                self.log(f"Stack trace: {traceback.format_exc()}")
            finally:
                # Always clear camera reference even if close failed
                self.camera = None
                self.log("Camera reference cleared")
                # For long idle gaps, also drop the SDK so the next connect
                # starts from a fresh init rather than a stale handle.  This
                # also covers the close()-raised case above: if the handle was
                # only half-released, a fresh SDK init on reconnect avoids
                # reusing it.
                if release_sdk:
                    self.asi = None
                    self.log("SDK reference released for clean reconnect")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def is_connected(self) -> bool:
        """Check if camera is connected"""
        return self.camera is not None

    def get_camera_property(self) -> Optional[Dict[str, Any]]:
        """Get camera properties if connected"""
        if self.camera:
            return self.camera.get_camera_property()
        return None

    def get_controls(self) -> Optional[Dict[str, Any]]:
        """Get camera controls if connected"""
        if self.camera:
            return self.camera.get_controls()
        return None
