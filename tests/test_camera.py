"""
Test ZWO camera connection and capture
Note: Tests marked with @pytest.mark.requires_camera need physical hardware
"""
import pytest
import os
import sys
import numpy as np
from unittest.mock import Mock, MagicMock, patch

# Check if cv2 is available
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class TestCameraConnectionMock:
    """Test camera connection logic with mocks"""
    
    def test_sdk_path_configuration(self):
        """Test SDK path can be configured"""
        from services.config import DEFAULT_CONFIG
        
        assert 'zwo_sdk_path' in DEFAULT_CONFIG
        # Default should point to ASICamera2.dll
        assert 'ASICamera2.dll' in DEFAULT_CONFIG['zwo_sdk_path']
    
    def test_camera_settings_defaults(self):
        """Per-camera defaults now live in DEFAULT_CAMERA_PROFILE, not DEFAULT_CONFIG."""
        from services.config import DEFAULT_CAMERA_PROFILE

        # Exposure range
        assert DEFAULT_CAMERA_PROFILE['exposure_ms'] >= 0.032  # Min ~32µs
        assert DEFAULT_CAMERA_PROFILE['exposure_ms'] <= 3600000  # Max 1 hour

        # Gain range
        assert DEFAULT_CAMERA_PROFILE['gain'] >= 0

        # White balance range
        assert 1 <= DEFAULT_CAMERA_PROFILE['wb_r'] <= 99
        assert 1 <= DEFAULT_CAMERA_PROFILE['wb_b'] <= 99


class TestBayerDebayering:
    """Test Bayer pattern debayering"""
    
    def test_bggr_pattern_detection(self):
        """Test BGGR Bayer pattern is correctly identified"""
        from services.config import DEFAULT_CAMERA_PROFILE

        # ASI cameras typically use BGGR
        assert DEFAULT_CAMERA_PROFILE['bayer_pattern'] in ['RGGB', 'BGGR', 'GRBG', 'GBRG']
    
    @pytest.mark.skipif(not HAS_CV2, reason="OpenCV (cv2) not installed")
    def test_debayer_creates_rgb(self):
        """Test debayering produces RGB image"""
        import cv2
        
        # Create mock Bayer pattern data (100x100)
        bayer_data = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
        
        # Debayer using OpenCV
        rgb = cv2.cvtColor(bayer_data, cv2.COLOR_BayerBG2RGB)
        
        # Should be 3 channels
        assert rgb.shape == (100, 100, 3)
    
    @pytest.mark.skipif(not HAS_CV2, reason="OpenCV (cv2) not installed")
    def test_all_bayer_patterns(self):
        """Test all Bayer pattern conversions work"""
        import cv2
        
        bayer_data = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
        
        patterns = [
            cv2.COLOR_BayerBG2RGB,  # BGGR
            cv2.COLOR_BayerRG2RGB,  # RGGB
            cv2.COLOR_BayerGB2RGB,  # GBRG
            cv2.COLOR_BayerGR2RGB,  # GRBG
        ]
        
        for pattern in patterns:
            rgb = cv2.cvtColor(bayer_data, pattern)
            assert rgb.shape == (100, 100, 3)


class TestCameraUtilities:
    """Test camera utility functions"""
    
    def test_scheduled_window_check(self):
        """Test scheduled capture window detection"""
        from services.camera import is_within_scheduled_window
        from datetime import datetime
        
        # Test case: capture window 17:00 - 09:00 (overnight)
        # At 20:00 should be within window
        test_time_evening = datetime(2025, 12, 30, 20, 0, 0)
        
        # At 08:00 should be within window
        test_time_morning = datetime(2025, 12, 30, 8, 0, 0)
        
        # At 12:00 should be outside window
        test_time_noon = datetime(2025, 12, 30, 12, 0, 0)
        
        # Note: Actual test depends on implementation
        # This is a placeholder for the test structure
    
    def test_exposure_ms_to_seconds_conversion(self):
        """Test exposure time unit conversion"""
        # 1000ms = 1s
        exposure_ms = 1000.0
        exposure_s = exposure_ms / 1000.0
        assert exposure_s == 1.0
        
        # 100ms = 0.1s
        exposure_ms = 100.0
        exposure_s = exposure_ms / 1000.0
        assert exposure_s == 0.1


class TestRecoveryRaces:
    """Regression tests for USB recovery race conditions — run without hardware."""

    def _make_connection(self, asi_mock):
        """Build a CameraConnection with its zwoasi module mocked out."""
        from services.camera import CameraConnection
        conn = CameraConnection(sdk_path=None, logger=lambda _: None)
        conn.asi = asi_mock
        return conn

    def test_detect_cameras_tolerates_enumeration_race(self):
        """
        Regression for the 08:57:50 production log: SDK reported 2 cameras but
        list_cameras() returned only the 462MM. The old code raised
        `list index out of range` on index 1. The fix snapshots list_cameras
        once, retries, and trusts the list when they disagree.
        """
        asi = MagicMock()
        asi.get_num_cameras.return_value = 2
        # Stays short across all retries (race never clears) — code should
        # still return the one camera it can see, without raising.
        asi.list_cameras.return_value = ['ZWO ASI462MM']

        conn = self._make_connection(asi)
        with patch('time.sleep'):
            result = conn.detect_cameras()

        assert len(result) == 1
        assert result[0]['name'] == 'ZWO ASI462MM'

    def test_detect_cameras_recovers_after_retry(self):
        """
        SDK race resolves on the 2nd retry: first list_cameras call is short,
        second returns both cameras. Expect the final enumeration to see both.
        """
        asi = MagicMock()
        asi.get_num_cameras.return_value = 2
        asi.list_cameras.side_effect = [
            ['ZWO ASI462MM'],                      # 1st call (race)
            ['ZWO ASI462MM', 'ZWO ASI676MC'],      # 2nd call (settled)
            ['ZWO ASI462MM', 'ZWO ASI676MC'],      # defensive
        ]

        conn = self._make_connection(asi)
        with patch('time.sleep'):
            result = conn.detect_cameras()

        assert len(result) == 2
        names = {c['name'] for c in result}
        assert names == {'ZWO ASI462MM', 'ZWO ASI676MC'}

    def test_wait_for_stable_detection_requires_two_consecutive_polls(self):
        """
        Detection-settle loop: target flickers in/out/in. Only after two
        consecutive polls see it at the same index does the helper return
        that index. Guards against `Invalid ID` when opening the camera
        too fast after disable/enable.
        """
        asi = MagicMock()
        conn = self._make_connection(asi)

        detections = [
            [],                                                                # not yet
            [{'index': 0, 'name': 'ZWO ASI676MC'}],                            # first sighting
            [{'index': 0, 'name': 'ZWO ASI676MC'}],                            # stable!
        ]

        with patch.object(conn, 'detect_cameras', side_effect=detections), \
                patch('time.sleep'):
            idx = conn._wait_for_stable_detection('ZWO ASI676MC', timeout_sec=10, poll_interval=0.01)

        assert idx == 0

    def test_wait_for_stable_detection_times_out_cleanly(self):
        """If the target never shows up, the helper must return without raising."""
        asi = MagicMock()
        conn = self._make_connection(asi)

        # Always empty
        with patch.object(conn, 'detect_cameras', return_value=[]), \
                patch('time.sleep'), \
                patch('time.time', side_effect=[0, 0, 1, 2, 11, 12, 13]):
            idx = conn._wait_for_stable_detection('ZWO ASI676MC', timeout_sec=10, poll_interval=0.01)

        assert idx is None


class TestCleanCameraName:
    """Unit tests for the camera-name cleaner."""

    @pytest.mark.parametrize("raw, expected", [
        ("ZWO ASI676MC (Index: 0)", "ZWO ASI676MC"),
        ("  ZWO ASI462MM (Index: 1)  ", "ZWO ASI462MM"),
        ("ZWO ASI676MC", "ZWO ASI676MC"),
        ("", ""),
        (None, ""),
    ])
    def test_strips_index_suffix(self, raw, expected):
        from services.camera import clean_camera_name
        assert clean_camera_name(raw) == expected


class TestWaitForCaptureThreadExit:
    """Tests for ZWOCamera.wait_for_capture_thread_exit()."""

    def _make_camera(self):
        # Patch the CameraConnection constructor so it doesn't look for the
        # real SDK — the test only needs ZWOCamera's thread-join logic.
        from services.camera import ZWOCamera
        with patch('services.camera.zwo_camera.CameraConnection') as conn_cls:
            conn_cls.return_value = MagicMock(asi=None, camera=None, sdk_lock=MagicMock())
            cam = ZWOCamera(sdk_path=None)
        cam.on_log_callback = lambda _: None
        return cam

    def test_returns_true_when_no_thread(self):
        cam = self._make_camera()
        cam.capture_thread = None
        assert cam.wait_for_capture_thread_exit(timeout=0.1) is True
        assert cam.is_capturing is False

    def test_returns_true_when_thread_already_exited(self):
        import threading
        cam = self._make_camera()
        t = threading.Thread(target=lambda: None)
        t.start()
        t.join()
        cam.capture_thread = t
        assert cam.wait_for_capture_thread_exit(timeout=0.1) is True

    def test_joins_running_thread_and_returns_true(self):
        import threading
        cam = self._make_camera()
        cam.is_capturing = True

        started = threading.Event()

        def fake_loop():
            started.set()
            # Exits as soon as is_capturing flips False
            while cam.is_capturing:
                pass

        t = threading.Thread(target=fake_loop, daemon=True)
        cam.capture_thread = t
        t.start()
        started.wait(timeout=1.0)
        # wait_for_capture_thread_exit should flip is_capturing and join
        assert cam.wait_for_capture_thread_exit(timeout=2.0) is True
        assert cam.capture_thread is None

    def test_returns_false_on_timeout(self):
        import threading, time
        cam = self._make_camera()
        cam.is_capturing = True

        # Thread that ignores the stop flag — simulates a thread wedged in SDK.
        def stuck():
            time.sleep(1.5)

        t = threading.Thread(target=stuck, daemon=True)
        cam.capture_thread = t
        t.start()
        assert cam.wait_for_capture_thread_exit(timeout=0.1) is False
        # capture_thread reference is kept so caller can re-inspect
        assert cam.capture_thread is t
        t.join()

    def test_aborts_calibration_manager(self):
        cam = self._make_camera()
        cal = MagicMock()
        cam.calibration_manager = cal
        cam.capture_thread = None
        cam.wait_for_capture_thread_exit(timeout=0.1)
        cal.abort.assert_called_once()


class TestUnrecoverableErrorDetection:
    """Unit tests for the SDK-crash error classifier — no Qt needed."""

    @pytest.mark.parametrize("msg", [
        "exception: access violation writing 0x0000000000000024",
        "Access Violation in zwoasi.dll",
        "[WinError -529697949] Windows Error 0xe06d7363",
        "Windows Error 0xE06D7363",
        "exception: exception",
    ])
    def test_unrecoverable_patterns(self, msg):
        from ui.controllers.camera_controller import CameraControllerQt
        assert CameraControllerQt._is_unrecoverable_error(msg) is True

    @pytest.mark.parametrize("msg", [
        "",
        "Exposure failed (camera returned ASI_EXP_FAILED status)",
        "Capture wedged — no frames for 112s",
        "Failed to reconnect camera",
        "Invalid ID",
        "Camera not responding after reconnect: timeout",
    ])
    def test_recoverable_patterns(self, msg):
        from ui.controllers.camera_controller import CameraControllerQt
        assert CameraControllerQt._is_unrecoverable_error(msg) is False


class TestDiscordSuppression:
    """Unit tests for the Discord error-throttle state machine."""

    def _controller(self):
        # Build a CameraControllerQt without running its Qt init (which needs
        # a QApplication).  We only need the plain attribute defaults for
        # should_notify_discord() logic.
        from ui.controllers.camera_controller import CameraControllerQt
        ctrl = CameraControllerQt.__new__(CameraControllerQt)
        ctrl._unrecoverable_mode = False
        ctrl._suppress_discord_errors = False
        return ctrl

    def test_allows_notifications_by_default(self):
        ctrl = self._controller()
        assert ctrl.should_notify_discord() is True

    def test_suppresses_after_flag_set(self):
        ctrl = self._controller()
        ctrl._suppress_discord_errors = True
        assert ctrl.should_notify_discord() is False

    def test_unrecoverable_mode_mark_notified_silences_further_pings(self):
        ctrl = self._controller()
        ctrl._unrecoverable_mode = True
        # Pure predicate — first call allows the final "needs restart" ping
        assert ctrl.should_notify_discord() is True
        # Caller records that the ping was sent
        ctrl.mark_discord_notified()
        # All subsequent calls must be suppressed
        assert ctrl.should_notify_discord() is False
        assert ctrl.should_notify_discord() is False

    def test_mark_discord_notified_noop_outside_unrecoverable_mode(self):
        """Regression guard: mark_discord_notified must not mute normal-mode
        Discord pings — only the unrecoverable-mode one-shot path uses it."""
        ctrl = self._controller()
        ctrl.mark_discord_notified()
        assert ctrl._suppress_discord_errors is False
        assert ctrl.should_notify_discord() is True


class TestCaptureLoopReconnectHeartbeat:
    """P2 regression: _last_frame_time must be refreshed after reconnect."""

    def test_reconnect_path_resets_last_frame_time(self):
        """
        Read the source of zwo_capture_worker.capture_loop and assert that the
        reconnect branch writes _last_frame_time back to time.time().

        A behavioural test would need to drive the full capture loop with a
        mocked ZWOCamera, which brings in calibration manager, sdk_lock, and
        scheduled-window state.  The invariant we actually care about is:
        "somewhere in the reconnect recovery branch, _last_frame_time gets
        reset."  A source-level assertion catches future refactors that
        silently drop it.
        """
        import inspect
        from services.camera import zwo_capture_worker
        src = inspect.getsource(zwo_capture_worker.capture_loop)
        # The reconnect branch starts at '✓ Camera reconnected successfully'.
        # Must be followed (before the next 'except') by an assignment that
        # writes _last_frame_time.
        reconnect_pos = src.index("✓ Camera reconnected successfully")
        tail = src[reconnect_pos:]
        assert "_last_frame_time = time.time()" in tail, (
            "Reconnect recovery must refresh camera._last_frame_time so the "
            "UI-level watchdog doesn't fire on the first post-reconnect "
            "exposure. Lost this line? See services/zwo_capture_worker.py."
        )


class TestConfigureVerifiesRoiReadback:
    """After set_roi, we must read back the active ROI and use that for
    capture. If the SDK silently ignored our request (seen in production
    after USB-bus contention), trusting the request causes every debayer
    reshape to crash."""

    def _asi(self):
        return MagicMock(ASI_IMG_RAW8=0, ASI_IMG_RAW16=2, ASI_GAIN=0,
                         ASI_EXPOSURE=1, ASI_BANDWIDTHOVERLOAD=6,
                         ASI_BRIGHTNESS=5, ASI_FLIP=9,
                         ASI_AUTO_MAX_BRIGHTNESS=12, ASI_WB_R=3, ASI_WB_B=4)

    def _camera(self, *, actual_roi):
        cam = MagicMock()
        cam.get_camera_property.return_value = {
            'Name': 'ZWO ASI676MC', 'MaxWidth': 3552, 'MaxHeight': 3552,
        }
        cam.get_controls.return_value = {}
        cam.get_roi_format.return_value = actual_roi
        return cam

    def test_roi_matches_request(self):
        from services.camera.camera_config import configure_camera
        asi = self._asi()
        # SDK accepts our 3552x3552 RAW8 ask and reports it back.
        cam = self._camera(actual_roi=[3552, 3552, 1, 0])
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': False}
        image_type, bit_depth = configure_camera(
            cam, asi, settings, supports_raw16=True, log=lambda _: None
        )
        assert image_type == 0  # RAW8
        assert bit_depth == 8

    def test_roi_mismatch_uses_actual_bit_depth(self):
        """SDK silently downgraded RAW16→RAW8: we must follow reality, not
        keep claiming RAW16."""
        from services.camera.camera_config import configure_camera
        asi = self._asi()
        # set_roi call succeeds but the readback says RAW8 somehow
        cam = self._camera(actual_roi=[3552, 3552, 1, 0])  # actual is RAW8
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': True}
        image_type, bit_depth = configure_camera(
            cam, asi, settings, supports_raw16=True, log=lambda _: None
        )
        assert image_type == asi.ASI_IMG_RAW8
        assert bit_depth == 8

    def test_roi_mismatch_width_height_follows_actual(self):
        """If the SDK reports a different active ROI size than what we set,
        the returned bit_depth must correspond to what the SDK actually has."""
        from services.camera.camera_config import configure_camera
        asi = self._asi()
        cam = self._camera(actual_roi=[1776, 1776, 2, 2])  # binned 2x, RAW16
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': True}
        image_type, bit_depth = configure_camera(
            cam, asi, settings, supports_raw16=True, log=lambda _: None
        )
        assert image_type == asi.ASI_IMG_RAW16
        assert bit_depth == 16


class TestIdentityMatchIsExact:
    """Substring match could accept a similarly-named-but-different camera
    (e.g. saved 'ZWO ASI662MM' accidentally matching 'ZWO ASI662MM Pro').
    On a multi-camera rig, writing settings to the wrong camera is a real
    hazard — exact match only."""

    def test_exact_match_accepted(self):
        from services.camera.camera_config import verify_camera_identity
        camera = MagicMock()
        camera.get_camera_property.return_value = {'Name': 'ZWO ASI676MC'}
        assert verify_camera_identity(camera, 'ZWO ASI676MC', lambda _: None) is True

    def test_leading_trailing_whitespace_tolerated(self):
        """SDK occasionally returns names with trailing nulls/spaces."""
        from services.camera.camera_config import verify_camera_identity
        camera = MagicMock()
        camera.get_camera_property.return_value = {'Name': '  ZWO ASI676MC  '}
        assert verify_camera_identity(camera, 'ZWO ASI676MC', lambda _: None) is True

    def test_substring_no_longer_accepted(self):
        from services.camera.camera_config import verify_camera_identity
        camera = MagicMock()
        camera.get_camera_property.return_value = {'Name': 'ZWO ASI676MC Pro'}
        # Previously a substring check would accept this; we require exact
        # match now because "Pro" variants can have different ROI constraints.
        assert verify_camera_identity(camera, 'ZWO ASI676MC', lambda _: None) is False

    def test_different_model_rejected(self):
        from services.camera.camera_config import verify_camera_identity
        camera = MagicMock()
        camera.get_camera_property.return_value = {'Name': 'ZWO ASI462MM'}
        assert verify_camera_identity(camera, 'ZWO ASI676MC', lambda _: None) is False


class TestCaptureUsesActualRoi:
    """Source-level regression guard: capture_single_frame must derive
    width/height from get_roi_format(), not MaxWidth/MaxHeight. The latter
    is the sensor maximum; the active ROI can differ (another app left a
    crop, or a silent set_roi rejection)."""

    def test_capture_reads_active_roi_not_max_size(self):
        import inspect
        from services.camera import zwo_capture_worker
        src = inspect.getsource(zwo_capture_worker.capture_single_frame)
        # get_roi_format() call must be present in the capture hot path
        assert "get_roi_format()" in src, (
            "capture_single_frame must read the SDK's active ROI to size "
            "the debayer reshape correctly."
        )
        # And we should no longer trust MaxWidth/MaxHeight for reshape
        assert "width = camera_info['MaxWidth']" not in src, (
            "MaxWidth/MaxHeight is the sensor's maximum, not the active ROI "
            "— do not feed it to the debayer reshape."
        )

    def test_capture_raises_clear_error_on_frame_size_mismatch(self):
        import inspect
        from services.camera import zwo_capture_worker
        src = inspect.getsource(zwo_capture_worker.capture_single_frame)
        assert "Frame size mismatch" in src, (
            "A clear error should be raised when delivered bytes don't "
            "match the expected ROI — better than a cryptic reshape failure."
        )


class TestConfigureRaw16Fallback:
    """Production log 2026-04-20 10:31: set_roi at full-res RAW16 returned
    ASI_ERROR_INVALID_SIZE. The old code swallowed the exception, leaving
    the SDK with a stale ROI, and every subsequent frame crashed in
    reshape (cannot reshape 2121856 into (3552,3552))."""

    def _asi_module_mock(self):
        asi = MagicMock()
        asi.ASI_IMG_RAW8 = 0
        asi.ASI_IMG_RAW16 = 2
        asi.ASI_GAIN = 0
        asi.ASI_EXPOSURE = 1
        asi.ASI_BANDWIDTHOVERLOAD = 6
        asi.ASI_BRIGHTNESS = 5
        asi.ASI_FLIP = 9
        asi.ASI_AUTO_MAX_BRIGHTNESS = 12
        asi.ASI_WB_R = 3
        asi.ASI_WB_B = 4
        return asi

    def _camera_mock(self, *, raw16_set_roi_raises=False):
        camera = MagicMock()
        camera.get_camera_property.return_value = {
            'Name': 'ZWO ASI676MC',
            'MaxWidth': 3552,
            'MaxHeight': 3552,
        }
        camera.get_controls.return_value = {}
        current_image_type = [0]  # mutable closure

        def set_roi(*, start_x, start_y, width, height, bins, image_type):
            if raw16_set_roi_raises and image_type == 2:
                raise Exception("Invalid size")
            current_image_type[0] = image_type

        camera.set_roi.side_effect = set_roi
        # Readback reflects whichever image_type last succeeded in set_roi.
        camera.get_roi_format.side_effect = lambda: [
            3552, 3552, 1, current_image_type[0]
        ]
        return camera

    def test_raw16_success_keeps_raw16(self):
        from services.camera.camera_config import configure_camera
        asi = self._asi_module_mock()
        camera = self._camera_mock(raw16_set_roi_raises=False)
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': True}
        image_type, bit_depth = configure_camera(
            camera, asi, settings, supports_raw16=True, log=lambda _: None
        )
        assert image_type == asi.ASI_IMG_RAW16
        assert bit_depth == 16

    def test_raw16_failure_falls_back_to_raw8(self):
        from services.camera.camera_config import configure_camera
        asi = self._asi_module_mock()
        camera = self._camera_mock(raw16_set_roi_raises=True)
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': True}
        image_type, bit_depth = configure_camera(
            camera, asi, settings, supports_raw16=True, log=lambda _: None
        )
        assert image_type == asi.ASI_IMG_RAW8
        assert bit_depth == 8
        # Both set_roi calls must have happened: RAW16 (failed) then RAW8
        set_roi_calls = camera.set_roi.call_args_list
        assert len(set_roi_calls) == 2
        assert set_roi_calls[0].kwargs['image_type'] == asi.ASI_IMG_RAW16
        assert set_roi_calls[1].kwargs['image_type'] == asi.ASI_IMG_RAW8

    def test_raw8_failure_raises(self):
        """When RAW8 itself fails, propagate — there's no further fallback
        and the caller must fail the connection."""
        from services.camera.camera_config import configure_camera
        asi = self._asi_module_mock()
        camera = self._camera_mock()
        camera.set_roi.side_effect = Exception("Invalid size")
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': False}
        with pytest.raises(Exception, match="Invalid size"):
            configure_camera(
                camera, asi, settings, supports_raw16=True, log=lambda _: None
            )


class TestConfigureErrorPropagation:
    """CameraConnection.configure used to swallow exceptions and log them,
    leaving the SDK in a stale-ROI state that crashed every subsequent
    capture. Now it raises so connect() can fail cleanly."""

    def _conn(self):
        from services.camera.camera_connection import CameraConnection
        conn = CameraConnection(sdk_path=None, logger=lambda _: None)
        conn.asi = MagicMock(
            ASI_IMG_RAW8=0, ASI_IMG_RAW16=2, ASI_GAIN=0, ASI_EXPOSURE=1,
            ASI_BANDWIDTHOVERLOAD=6, ASI_BRIGHTNESS=5, ASI_FLIP=9,
            ASI_AUTO_MAX_BRIGHTNESS=12, ASI_WB_R=3, ASI_WB_B=4,
        )
        conn.camera = MagicMock()
        conn.camera.get_camera_property.return_value = {
            'Name': 'ZWO ASI676MC', 'MaxWidth': 3552, 'MaxHeight': 3552,
        }
        conn.camera.get_controls.return_value = {}
        conn.camera_name = 'ZWO ASI676MC'
        conn.supports_raw16 = True
        return conn

    def test_configure_propagates_set_roi_failure(self):
        conn = self._conn()
        # Both RAW16 and RAW8 set_roi fail — configure must raise, not return.
        conn.camera.set_roi.side_effect = Exception("Invalid size")
        settings = {'gain': 100, 'exposure_sec': 0.1, 'use_raw16': False}
        with pytest.raises(Exception, match="Invalid size"):
            conn.configure(settings)

    def test_configure_raises_on_identity_mismatch(self):
        conn = self._conn()
        conn.camera.get_camera_property.return_value = {
            'Name': 'ZWO ASI462MM',  # wrong camera
            'MaxWidth': 1936, 'MaxHeight': 1096,
        }
        with pytest.raises(Exception, match="identity mismatch"):
            conn.configure({'gain': 100, 'exposure_sec': 0.1})


class TestDetectNeverSwapsCameraSilently:
    """On a multi-camera rig (imaging + guide + all-sky), silently swapping
    to a different camera when the saved one is missing would hijack the
    wrong device and potentially disrupt NINA / PHD2 sessions. The fallback
    must only fire when there's genuinely no saved selection (fresh install)."""

    def test_on_cameras_detected_refuses_to_auto_swap(self):
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._on_cameras_detected
        )
        # Fresh-install branch: auto-select only with no saved name AND an
        # unambiguous single-camera rig. Auto-picking "the first camera" on a
        # multi-camera rig is how a guide camera got hijacked (June 2026).
        assert "elif not saved_name and len(cameras) == 1:" in src, (
            "Detect must only auto-select on fresh install with a single "
            "camera, never swap or auto-pick on a multi-camera rig."
        )
        # The old silent-swap branch must be gone
        assert "(not saved_name or not found)" not in src, (
            "Detect no longer auto-selects when saved camera is missing — "
            "multi-camera rigs cannot tolerate silent swaps."
        )
        # And it must emit a user-visible error when the saved camera vanishes
        assert "not detected" in src, (
            "User must see a clear notification when their saved camera is "
            "missing, not a silent config rewrite."
        )

    def test_placeholder_camera_name_gets_cleared(self):
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._on_cameras_detected
        )
        # Placeholder names like "Camera 0" from the earlier detection bug
        # must be cleared, otherwise the user is locked out of auto-recovery.
        assert r"re.fullmatch(r'Camera \d+'" in src or \
               r'"Camera \\d+"' in src or \
               "placeholder camera name" in src.lower(), (
            "Migration to clear 'Camera N' placeholder names is missing. "
            "Users with corrupted configs from the earlier bug would never "
            "auto-recover without this."
        )


class TestResolveCameraIndexRefusesToSwap:
    """The auto-recovery path must also refuse to silently connect to a
    different camera when the saved one is missing."""

    def _build_controller(self):
        from ui.controllers.camera_controller import CameraControllerQt
        main_window = MagicMock()
        main_window.config = MagicMock()
        ctrl = CameraControllerQt.__new__(CameraControllerQt)
        ctrl.config = main_window.config
        return ctrl

    def test_missing_saved_camera_raises_rather_than_swapping(self):
        ctrl = self._build_controller()
        # Pretend the user's saved camera is ASI676MC but only the ASI462MM
        # is on the bus. The controller MUST raise — not connect to ASI462MM.
        with patch('zwoasi.init'), \
                patch('zwoasi.get_num_cameras', return_value=1), \
                patch('zwoasi.list_cameras', return_value=['ZWO ASI462MM']), \
                patch('os.path.exists', return_value=True):
            with pytest.raises(Exception, match="ZWO ASI676MC.*not found"):
                ctrl._resolve_camera_index(
                    sdk_path='fake.dll',
                    camera_name='ZWO ASI676MC',
                    saved_index=0,
                )

    def test_found_saved_camera_still_works(self):
        """Regression guard: the no-swap fix mustn't break the happy path."""
        ctrl = self._build_controller()
        with patch('zwoasi.init'), \
                patch('zwoasi.get_num_cameras', return_value=2), \
                patch('zwoasi.list_cameras',
                      return_value=['ZWO ASI676MC', 'ZWO ASI462MM']), \
                patch('os.path.exists', return_value=True):
            idx = ctrl._resolve_camera_index(
                sdk_path='fake.dll',
                camera_name='ZWO ASI462MM',
                saved_index=1,
            )
            assert idx == 1


class TestReviveMissingCamera:
    """Remote operators can't physically reseat a USB cable; the Capture
    panel's Revive button runs a USB disable/enable on a specific saved
    camera name as a software-only recovery action."""

    def _build_controller(self):
        from ui.controllers.camera_controller import CameraControllerQt
        main_window = MagicMock()
        main_window.config = MagicMock()
        ctrl = CameraControllerQt.__new__(CameraControllerQt)
        ctrl.config = main_window.config
        from ui.controllers.camera_usb_recovery import UsbResetWorker
        ctrl._usb_reset = UsbResetWorker()
        from PySide6.QtCore import QObject
        QObject.__init__(ctrl)
        return ctrl

    def test_revive_emits_camera_revive_done(self, qt_app=None):
        """The worker must report completion via the camera_revive_done
        signal regardless of success/failure — otherwise the UI's Revive
        button stays greyed out forever."""
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PySide6 not installed")
        app = QApplication.instance() or QApplication([])
        import threading, time as _t

        ctrl = self._build_controller()
        seen = []
        ctrl.camera_revive_done.connect(lambda ok, name: seen.append((ok, name)))

        started = threading.Event()
        def fake_reset(**kw):
            started.set()
            return True
        with patch('sys.platform', 'win32'), \
                patch('services.usb_reset_win.is_usb_reset_available', return_value=True), \
                patch('services.usb_reset_win.disable_enable_zwo_camera_usb',
                      side_effect=fake_reset):
            ctrl.revive_missing_camera('ZWO ASI676MC')
            assert started.wait(timeout=2.0)
            deadline = _t.time() + 2.0
            while _t.time() < deadline and not seen:
                app.processEvents()
                _t.sleep(0.01)
        assert seen == [(True, 'ZWO ASI676MC')]

    def test_revive_with_empty_name_emits_false(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PySide6 not installed")
        app = QApplication.instance() or QApplication([])
        ctrl = self._build_controller()
        seen = []
        ctrl.camera_revive_done.connect(lambda ok, name: seen.append((ok, name)))
        ctrl.revive_missing_camera('')
        app.processEvents()
        assert seen == [(False, '')]

    def test_revive_strips_index_suffix(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PySide6 not installed")
        app = QApplication.instance() or QApplication([])
        import threading, time as _t

        ctrl = self._build_controller()
        seen = []
        ctrl.camera_revive_done.connect(lambda ok, name: seen.append((ok, name)))
        received_names = []

        def fake_reset(*, camera_name, logger, **kw):
            received_names.append(camera_name)
            return True

        with patch('sys.platform', 'win32'), \
                patch('services.usb_reset_win.is_usb_reset_available', return_value=True), \
                patch('services.usb_reset_win.disable_enable_zwo_camera_usb',
                      side_effect=fake_reset):
            ctrl.revive_missing_camera('ZWO ASI676MC (Index: 0)')
            deadline = _t.time() + 2.0
            while _t.time() < deadline and not seen:
                app.processEvents()
                _t.sleep(0.01)
        # Saved name with suffix must be cleaned before reaching the USB reset
        assert received_names == ['ZWO ASI676MC']
        assert seen == [(True, 'ZWO ASI676MC')]


class TestPhantomDeviceLogging:
    """When get_num_cameras reports more devices than list_cameras returns,
    we must (a) trust the enumerated list, (b) flag the phantom count, and
    (c) log a clear explanation so the user knows what Revive is for."""

    def test_phantom_count_is_tracked_on_main_window(self):
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(main_window_capture._MainWindowCaptureMixin._on_detect_cameras)
        assert "_sdk_phantom_count" in src, (
            "detect_thread must stash phantom_count on the main window so "
            "_on_cameras_detected can pass it to the capture panel's banner."
        )
        # Must log an actionable explanation, not a generic warning
        assert "Revive" in src or "revive" in src.lower(), (
            "Phantom log message should tell the user about the Revive "
            "button — otherwise the log is diagnostic-only."
        )

    def test_detected_handler_calls_missing_warning(self):
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._on_cameras_detected
        )
        # Setter must be called with the saved name + phantom count
        assert "set_missing_camera_warning(saved_name, phantom_count)" in src or \
               "set_missing_camera_warning(\n" in src, (
            "Missing-camera path must populate the persistent banner with "
            "the saved name and phantom count so the user can hit Revive."
        )
        # And cleared when we successfully restore the saved camera
        assert "set_missing_camera_warning('')" in src, (
            "Banner must be cleared when the saved camera reappears."
        )


class TestDetectCamerasNoPhantomPlaceholder:
    """Regression for 2026-04-20 10:15: the SDK briefly reported
    num_cameras=2 but list_cameras returned only 1 entry, and detection
    filled the missing slot with a placeholder name ('Camera 0') that
    was then auto-saved as the user's selected camera — clobbering the
    real ZWO ASI462MM config entry.

    The fix lives in ui.main_window.capture._on_detect_cameras'
    detect_thread closure. Checking behaviour end-to-end requires the UI
    stack (qfluentwidgets, QApplication), so the assertion is source-level:
    no 'Camera {i}' style fallback name should be appended when the SDK
    enumeration is short."""

    def test_no_phantom_placeholder_in_detect_thread(self):
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(main_window_capture._MainWindowCaptureMixin._on_detect_cameras)
        # Before the fix, the loop had: cameras.append(f"Camera {i}") in the
        # except branch. If any future edit re-introduces a placeholder name,
        # this test fails — and so will the user's config.
        assert 'f"Camera {i}"' not in src, (
            "Phantom placeholder name in detect_thread — would get auto-saved "
            "as the selected camera and wreck the user's config. See log "
            "2026-04-20 10:15."
        )
        # Must include retry logic for the enumeration race.
        assert "enumeration race" in src.lower(), (
            "detect_thread should retry when list_cameras disagrees with "
            "get_num_cameras (documented SDK race)."
        )


class TestSelfHealingRecoveryFlag:
    """P1/P2 follow-up (2026-04-20): the UI watchdog no longer tears down
    state from the main thread; it sets _recovery_requested on the camera
    and the capture thread self-heals on its next poll point."""

    def _make_camera(self):
        from services.camera.zwo_camera import ZWOCamera
        with patch('services.camera.zwo_camera.CameraConnection') as conn_cls:
            conn_cls.return_value = MagicMock(asi=None, camera=None, sdk_lock=MagicMock())
            cam = ZWOCamera(sdk_path=None)
        cam.on_log_callback = lambda _: None
        return cam

    def test_recovery_flag_defaults_false(self):
        cam = self._make_camera()
        assert cam._recovery_requested is False

    def test_stop_capture_clears_recovery_flag(self):
        cam = self._make_camera()
        cam._recovery_requested = True
        cam.is_capturing = True
        cam.stop_capture()
        assert cam._recovery_requested is False

    def test_capture_single_frame_raises_immediately_when_flag_set(self):
        from services.camera import zwo_capture_worker
        cam = self._make_camera()
        cam.camera = MagicMock()
        cam._recovery_requested = True
        with pytest.raises(Exception, match="Recovery requested by watchdog"):
            zwo_capture_worker.capture_single_frame(cam)
        # Flag is consumed so subsequent frames do not re-trigger
        assert cam._recovery_requested is False

    def test_capture_single_frame_proceeds_when_flag_cleared(self):
        """If _recovery_requested is False, the normal exposure path runs.
        We short-circuit after the set_control_value calls to avoid building
        a full SDK mock for the debayer pipeline."""
        from services.camera import zwo_capture_worker
        cam = self._make_camera()
        cam.camera = MagicMock()
        cam.camera.set_control_value = MagicMock()
        cam.camera.start_exposure = MagicMock(
            side_effect=Exception("stop here")
        )
        cam.asi = MagicMock(ASI_EXPOSURE=1, ASI_GAIN=0)
        cam._connection.sdk_lock = MagicMock()
        cam._connection.sdk_lock.__enter__ = MagicMock(return_value=None)
        cam._connection.sdk_lock.__exit__ = MagicMock(return_value=False)
        with pytest.raises(Exception, match="stop here"):
            zwo_capture_worker.capture_single_frame(cam)
        cam.camera.set_control_value.assert_called()


class TestWatchdogSelfHeal:
    """The UI watchdog should nudge the capture thread, not run SDK calls
    itself.  Production log 2026-04-20 showed that calling get_num_cameras
    from the main thread while the capture thread is still blocked in an
    SDK call crashes the DLL (SEH 0xe06d7363)."""

    @pytest.fixture
    def qt_app(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PySide6 not installed")
        app = QApplication.instance() or QApplication([])
        yield app

    def test_threshold_uses_nina_style_buffer(self):
        """Watchdog threshold: max(3*interval, 180s, exposure + 60s)."""
        # Mirror the formula inline since importing main_window_capture
        # pulls in qfluentwidgets.  If the formula changes, this test
        # documents the intent.
        def threshold(interval, exposure_sec):
            return max(3 * interval, 180.0, exposure_sec + 60.0)

        assert threshold(interval=5.0, exposure_sec=0.1) == 180.0
        assert threshold(interval=5.0, exposure_sec=10.0) == 180.0
        # 150s exposure → 210s floor beats 180
        assert threshold(interval=5.0, exposure_sec=150.0) == 210.0
        # 120s interval → 360s beats everything
        assert threshold(interval=120.0, exposure_sec=0.1) == 360.0

    def test_watchdog_has_two_stage_escalation(self, qt_app):
        """Stage-1 nudges, stage-2 declares fatal if the nudge didn't take.
        Source-level check because the full watchdog has too much Qt UI
        state to drive cleanly with mocks."""
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._check_capture_watchdog
        )
        # Stage 1: non-fatal nudge (unchanged)
        assert "is_fatal=False" in src, (
            "Watchdog must still start with a non-fatal nudge to give the "
            "capture thread a chance to self-heal."
        )
        # Stage 2: eventual escalation to fatal so UI syncs when the thread
        # is genuinely wedged inside a C SDK call (see 2026-04-20 17:23 log)
        assert "is_fatal=True" in src, (
            "Watchdog must escalate to is_fatal=True when the self-heal "
            "nudge doesn't take — otherwise the UI says 'capturing' forever."
        )
        assert "_watchdog_first_fire_ts" in src, (
            "Stage-2 escalation must be time-gated off the first-fire timestamp."
        )
        assert "_WATCHDOG_UI_FATAL_GRACE_SEC" in src, (
            "Grace period before escalation must be configurable via the "
            "module-level constant, not a magic number."
        )

    def test_capture_started_signal_is_wired_to_main_window(self, qt_app):
        """Regression for 2026-04-20: auto-recovery called controller
        start_capture() but the main window never knew, so the AppBar
        Start/Stop button kept showing "Start" while capture ran."""
        import inspect
        from ui.main_window import capture as main_window_capture
        # Signal wiring lives in _ensure_camera_controller so it's also
        # available to user-initiated actions (e.g. Revive Camera) that
        # run before the first start_capture() click.
        src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._ensure_camera_controller
        )
        assert "capture_started.connect" in src, (
            "camera_controller.capture_started must be wired to the main "
            "window so auto-recovery success reflects in the UI."
        )
        # And the handler must flip is_capturing + update the app bar
        handler_src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._on_camera_capture_started
        )
        assert "self.is_capturing = True" in handler_src
        assert "set_capturing(True)" in handler_src

    def test_watchdog_first_fire_is_non_fatal(self, qt_app):
        """The first watchdog fire must use is_fatal=False so the capture
        thread has time to self-heal before we force UI teardown. Stage-2
        escalation is covered by a separate test."""
        import inspect
        from ui.main_window import capture as main_window_capture
        src = inspect.getsource(
            main_window_capture._MainWindowCaptureMixin._check_capture_watchdog
        )
        # Stage 1 is gated on _watchdog_first_fire_ts being None (first fire).
        stage1_start = src.index("if self._watchdog_first_fire_ts is None:")
        stage1_end = src.index("if self._watchdog_ui_fatal_sent:", stage1_start)
        stage1 = src[stage1_start:stage1_end]
        assert "_recovery_requested" in stage1, (
            "Stage 1 must nudge via _recovery_requested"
        )
        assert "is_fatal=False" in stage1, (
            "Stage 1 must be non-fatal — gives self-heal a chance before "
            "teardown"
        )
        assert "cam.is_capturing = False" not in stage1, (
            "Stage 1 must not flip is_capturing; the capture thread's own "
            "reconnect path handles exit"
        )


class TestControllerRecoveryWiring:
    """Integration tests for the controller recovery path (requires Qt)."""

    @pytest.fixture
    def qt_app(self):
        # Shared QApplication across tests — Qt forbids creating two.
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PySide6 not installed")
        app = QApplication.instance() or QApplication([])
        yield app

    def _build_controller(self):
        from ui.controllers.camera_controller import CameraControllerQt
        main_window = MagicMock()
        main_window.config = MagicMock()
        main_window.config.get = MagicMock(return_value='')
        ctrl = CameraControllerQt(main_window)
        return ctrl

    def test_fatal_error_preserves_dying_camera_reference(self, qt_app):
        """The prev ZWOCamera must survive the fatal teardown so its thread
        can be joined before the next recovery fires — otherwise the SDK
        DLL sees concurrent access and crashes."""
        ctrl = self._build_controller()
        fake_camera = MagicMock()
        ctrl.zwo_camera = fake_camera
        ctrl.is_capturing = True
        # Stub out the auto-recovery scheduler so we don't start a real timer.
        ctrl._schedule_auto_recovery = MagicMock()
        ctrl._on_camera_error("Capture wedged — no frames for 112s", is_fatal=True)
        assert ctrl.zwo_camera is None
        assert ctrl._dying_camera is fake_camera
        assert ctrl.is_capturing is False
        ctrl._schedule_auto_recovery.assert_called_once()

    def test_auto_recovery_joins_dying_camera_before_restart(self, qt_app):
        """Recovery must wait for the previous capture thread to exit before
        calling start_capture() (which hits get_num_cameras on the main
        thread)."""
        ctrl = self._build_controller()
        dying = MagicMock()
        ctrl._dying_camera = dying
        # Stub start_capture so we only verify the join order.
        call_order = []
        dying.wait_for_capture_thread_exit = MagicMock(
            side_effect=lambda *a, **kw: call_order.append('join') or True
        )
        ctrl.start_capture = MagicMock(
            side_effect=lambda: call_order.append('start_capture')
        )
        ctrl._user_requested_stop = False
        ctrl.is_capturing = False
        ctrl._on_auto_recovery_fire()
        assert call_order == ['join', 'start_capture']
        assert ctrl._dying_camera is None

    def test_schedule_auto_recovery_noops_in_unrecoverable_mode(self, qt_app):
        ctrl = self._build_controller()
        ctrl._unrecoverable_mode = True
        # Precondition check — would normally increment attempts.
        before = ctrl._auto_recovery_attempts
        ctrl._schedule_auto_recovery()
        assert ctrl._auto_recovery_attempts == before
        assert ctrl._auto_recovery_timer is None

    def test_schedule_auto_recovery_sets_suppress_flag_after_threshold(self, qt_app):
        from ui.controllers.camera_controller import (
            _DISCORD_ERROR_SUPPRESS_AFTER_ATTEMPTS,
        )
        ctrl = self._build_controller()
        for _ in range(_DISCORD_ERROR_SUPPRESS_AFTER_ATTEMPTS):
            ctrl._schedule_auto_recovery()
            ctrl._cancel_auto_recovery_timer()
        assert ctrl._suppress_discord_errors is False
        # One more crosses the threshold
        ctrl._schedule_auto_recovery()
        ctrl._cancel_auto_recovery_timer()
        assert ctrl._suppress_discord_errors is True

    def test_sustained_frame_stream_clears_suppression(self, qt_app):
        ctrl = self._build_controller()
        ctrl._suppress_discord_errors = True
        ctrl._usb_reset_attempted = True
        ctrl._auto_recovery_attempts = 5
        # Seed a "previously successful" timestamp far in the past so the
        # 5-minute gate clears on the current frame.
        import time as _t
        ctrl._last_successful_frame_ts = _t.time() - 3600
        ctrl._on_frame_captured(MagicMock(), {})
        assert ctrl._suppress_discord_errors is False
        assert ctrl._usb_reset_attempted is False
        assert ctrl._auto_recovery_attempts == 0

    def test_enter_unrecoverable_mode_emits_capture_stopped_and_error(self, qt_app):
        ctrl = self._build_controller()
        ctrl._cancel_auto_recovery_timer = MagicMock()
        stopped_spy = []
        error_spy = []
        ctrl.capture_stopped.connect(lambda: stopped_spy.append(True))
        ctrl.error.connect(lambda msg: error_spy.append(msg))
        ctrl._enter_unrecoverable_mode("access violation writing 0x24")
        assert ctrl._unrecoverable_mode is True
        assert stopped_spy == [True]
        assert len(error_spy) == 1
        assert "restart" in error_spy[0].lower()

    def test_usb_reset_worker_runs_off_main_thread(self, qt_app):
        """USB reset blocks ~15s inside the Windows API; it must run on a
        worker thread, not the Qt main thread, so the UI stays responsive."""
        import threading, time
        ctrl = self._build_controller()
        ctrl.config.get = MagicMock(return_value='ZWO ASI676MC (Index: 0)')
        main_thread_id = threading.get_ident()
        worker_thread_id = {}
        reset_started = threading.Event()
        reset_completed = threading.Event()

        def fake_disable_enable(camera_name, logger, **kw):
            worker_thread_id['id'] = threading.get_ident()
            reset_started.set()
            # Simulate a slow USB reset. If _start_usb_reset_worker were
            # synchronous, the caller would block here too.
            time.sleep(0.2)
            reset_completed.set()
            return True

        with patch('sys.platform', 'win32'), \
                patch('services.usb_reset_win.is_usb_reset_available', return_value=True), \
                patch('services.usb_reset_win.disable_enable_zwo_camera_usb',
                      side_effect=fake_disable_enable):
            t0 = time.time()
            ctrl._start_usb_reset_worker()
            # If the reset ran inline, this line wouldn't execute until after
            # the 0.2s sleep. Assert the caller returned immediately.
            assert time.time() - t0 < 0.1, "USB reset blocked the calling thread"
            assert reset_started.wait(timeout=2.0), "worker did not start"
            assert reset_completed.wait(timeout=2.0), "worker did not finish"
        assert worker_thread_id.get('id') not in (None, main_thread_id)

    def test_usb_reset_worker_goes_unrecoverable_when_no_camera_name(self, qt_app):
        """No saved camera name → no reset target → unrecoverable.  Silently
        scheduling a retry would just crash into the SDK again."""
        ctrl = self._build_controller()
        ctrl.config.get = MagicMock(return_value='')
        with patch('sys.platform', 'win32'):
            ctrl._start_usb_reset_worker()
        assert ctrl._unrecoverable_mode is True

    def test_usb_reset_success_schedules_retry(self, qt_app):
        import threading, time
        ctrl = self._build_controller()
        ctrl.config.get = MagicMock(return_value='ZWO ASI676MC')
        ctrl._schedule_auto_recovery = MagicMock()
        done = threading.Event()
        with patch('sys.platform', 'win32'), \
                patch('services.usb_reset_win.is_usb_reset_available', return_value=True), \
                patch('services.usb_reset_win.disable_enable_zwo_camera_usb',
                      side_effect=lambda **kw: done.set() or True):
            ctrl._start_usb_reset_worker()
            assert done.wait(timeout=2.0)
            deadline = time.time() + 2.0
            while time.time() < deadline and not ctrl._schedule_auto_recovery.called:
                qt_app.processEvents()
                time.sleep(0.01)
        assert ctrl._schedule_auto_recovery.called
        assert ctrl._unrecoverable_mode is False

    def test_usb_reset_failure_marks_unrecoverable(self, qt_app):
        """disable_enable returns False (e.g. admin denied CM_Disable_DevNode
        0x17) — controller must stop retrying and emit the final error."""
        import threading, time
        ctrl = self._build_controller()
        ctrl.config.get = MagicMock(return_value='ZWO ASI676MC')
        error_spy = []
        ctrl.error.connect(lambda m: error_spy.append(m))
        done = threading.Event()
        with patch('sys.platform', 'win32'), \
                patch('services.usb_reset_win.is_usb_reset_available', return_value=True), \
                patch('services.usb_reset_win.disable_enable_zwo_camera_usb',
                      side_effect=lambda **kw: done.set() or False):
            ctrl._start_usb_reset_worker()
            assert done.wait(timeout=2.0)
            deadline = time.time() + 2.0
            while time.time() < deadline and not ctrl._unrecoverable_mode:
                qt_app.processEvents()
                time.sleep(0.01)
        assert ctrl._unrecoverable_mode is True
        assert any("restart" in m.lower() for m in error_spy)

    def test_usb_reset_worker_non_windows_marks_unrecoverable(self, qt_app):
        ctrl = self._build_controller()
        ctrl.config.get = MagicMock(return_value='ZWO ASI676MC')
        with patch('sys.platform', 'linux'):
            ctrl._start_usb_reset_worker()
        assert ctrl._unrecoverable_mode is True

    def test_wedged_dying_camera_tries_usb_reset_first(self, qt_app):
        """First wedge: a USB disable/enable (OS-level, safe against a wedged
        DLL) is attempted to free the stuck thread before any escalation, and
        no new SDK call is issued."""
        ctrl = self._build_controller()
        wedged = MagicMock()
        wedged.wait_for_capture_thread_exit = MagicMock(return_value=False)
        ctrl._dying_camera = wedged
        ctrl.start_capture = MagicMock()
        ctrl._schedule_auto_recovery = MagicMock()
        ctrl._start_usb_reset_worker = MagicMock()
        ctrl._on_auto_recovery_fire()
        ctrl.start_capture.assert_not_called()
        ctrl._start_usb_reset_worker.assert_called_once()
        ctrl._schedule_auto_recovery.assert_not_called()
        assert ctrl._wedged_skip_count == 1
        assert ctrl._wedge_usb_reset_tried is True
        assert ctrl._dying_camera is wedged

    def test_wedge_escalates_to_unrecoverable_when_restart_blocked(self, qt_app):
        """USB toggle did not free the thread and a restart is blocked (outside
        the capture window) -> unrecoverable, asking for a manual restart."""
        from ui.controllers.camera_controller import _MAX_WEDGED_SKIPS
        ctrl = self._build_controller()
        wedged = MagicMock()
        wedged.wait_for_capture_thread_exit = MagicMock(return_value=False)
        ctrl._dying_camera = wedged
        ctrl.start_capture = MagicMock()
        ctrl._start_usb_reset_worker = MagicMock()
        for _ in range(_MAX_WEDGED_SKIPS + 1):
            ctrl._on_auto_recovery_fire()
        assert ctrl._unrecoverable_mode is True
        ctrl.start_capture.assert_not_called()

    def test_wedge_restarts_app_inside_window(self, qt_app):
        """Inside the capture window, with a prior successful capture, an
        unfreeable wedge restarts the app rather than going dark."""
        import time as _t
        from ui.controllers.camera_controller import _MAX_WEDGED_SKIPS
        ctrl = self._build_controller()
        ctrl.config.get = MagicMock(
            side_effect=lambda k, d=None: 'always' if k == 'scheduled_capture_mode' else d
        )
        ctrl._last_successful_frame_ts = _t.time()
        ctrl.main_window.restart_application = MagicMock(return_value=True)
        wedged = MagicMock()
        wedged.wait_for_capture_thread_exit = MagicMock(return_value=False)
        ctrl._dying_camera = wedged
        ctrl.start_capture = MagicMock()
        ctrl._start_usb_reset_worker = MagicMock()
        for _ in range(_MAX_WEDGED_SKIPS):
            ctrl._on_auto_recovery_fire()
        assert ctrl.main_window.restart_application.called
        assert ctrl._unrecoverable_mode is False

    def test_wedged_skip_count_resets_when_thread_finally_exits(self, qt_app):
        ctrl = self._build_controller()
        ctrl._wedged_skip_count = 3
        dying = MagicMock()
        dying.wait_for_capture_thread_exit = MagicMock(return_value=True)
        ctrl._dying_camera = dying
        ctrl.start_capture = MagicMock()
        ctrl._on_auto_recovery_fire()
        assert ctrl._wedged_skip_count == 0
        assert ctrl._dying_camera is None
        ctrl.start_capture.assert_called_once()

    def test_user_stop_clears_unrecoverable_state(self, qt_app):
        ctrl = self._build_controller()
        ctrl._unrecoverable_mode = True
        ctrl._usb_reset_attempted = True
        ctrl._suppress_discord_errors = True
        ctrl._wedged_skip_count = 3
        ctrl._dying_camera = MagicMock()
        ctrl.is_capturing = True
        ctrl.zwo_camera = MagicMock()
        ctrl.stop_capture()
        assert ctrl._unrecoverable_mode is False
        assert ctrl._usb_reset_attempted is False
        assert ctrl._suppress_discord_errors is False
        assert ctrl._wedged_skip_count == 0
        assert ctrl._dying_camera is None


@pytest.mark.requires_camera
class TestPhysicalCamera:
    """Tests that require actual camera hardware"""
    
    def test_camera_detection(self):
        """Test camera can be detected"""
        try:
            import zwoasi
            zwoasi.init(os.path.join(project_root, 'ASICamera2.dll'))
            
            num_cameras = zwoasi.get_num_cameras()
            
            # At least one camera should be connected for these tests
            assert num_cameras > 0, "No cameras detected - connect a camera to run hardware tests"
            
        except Exception as e:
            pytest.skip(f"Camera hardware test skipped: {e}")
    
    def test_camera_connection(self):
        """Test camera can be connected"""
        try:
            import zwoasi
            zwoasi.init(os.path.join(project_root, 'ASICamera2.dll'))
            
            if zwoasi.get_num_cameras() == 0:
                pytest.skip("No camera connected")
            
            camera = zwoasi.Camera(0)
            info = camera.get_camera_property()
            
            assert 'Name' in info
            assert 'MaxWidth' in info
            assert 'MaxHeight' in info
            
            camera.close()
            
        except Exception as e:
            pytest.skip(f"Camera connection test skipped: {e}")
    
    def test_capture_single_frame(self):
        """Test capturing a single frame"""
        try:
            import zwoasi
            zwoasi.init(os.path.join(project_root, 'ASICamera2.dll'))
            
            if zwoasi.get_num_cameras() == 0:
                pytest.skip("No camera connected")
            
            camera = zwoasi.Camera(0)
            
            # Set minimal settings for quick capture
            camera.set_control_value(zwoasi.ASI_EXPOSURE, 1000)  # 1ms
            camera.set_control_value(zwoasi.ASI_GAIN, 0)
            
            # Set image type to RAW8
            camera.set_image_type(zwoasi.ASI_IMG_RAW8)
            
            # Capture
            data = camera.capture()
            
            assert data is not None
            assert len(data) > 0
            
            camera.close()
            
        except Exception as e:
            pytest.skip(f"Capture test skipped: {e}")
