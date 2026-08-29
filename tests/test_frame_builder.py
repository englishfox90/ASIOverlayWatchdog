"""Tests for services/camera/frame_builder.py and the raw-frame cache contract.

Replaces test_frame_buffers.py: the ping-pong buffer pool it covered is gone —
each frame now owns the arrays build_frame allocates for it. The dst= parameters
of debayer_raw_image survive for API stability and are still exercised here.

No hardware required.
"""
import types

import numpy as np
import pytest
from unittest.mock import MagicMock

from services.camera import frame_builder
from services.camera.camera_utils import calculate_image_stats
from ui.main_window.output import _MainWindowOutputMixin

try:
    import cv2 as _cv2  # noqa: F401
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

pytestmark = pytest.mark.skipif(not HAS_CV2, reason="cv2 not installed")

W, H = 64, 48


def _raw8(seed=1):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (H * W,), dtype=np.uint8).tobytes()


def _raw16(seed=1):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 65536, (H * W,), dtype=np.uint16).tobytes()


# ---------------------------------------------------------------------------
# build_frame
# ---------------------------------------------------------------------------

class TestBuildFrame:

    def test_raw8_shapes_and_dtypes(self):
        img, arrays, stats = frame_builder.build_frame(_raw8(), W, H, 8, 'BGGR', {})
        assert img.size == (W, H)
        assert img.mode == 'RGB'
        assert arrays['RAW_RGB_NO_WB'].shape == (H, W, 3)
        assert arrays['RAW_RGB_NO_WB'].dtype == np.uint8
        assert set(stats) == {'mean', 'median', 'min', 'max', 'std_dev', 'p25', 'p75', 'p95'}

    def test_raw16_shapes_and_dtypes(self):
        img, arrays, _ = frame_builder.build_frame(_raw16(), W, H, 16, 'BGGR', {})
        assert img.size == (W, H)
        assert arrays['RAW_RGB_16BIT'].shape == (H, W, 3)
        assert arrays['RAW_RGB_16BIT'].dtype == np.uint16

    def test_no_wb_array_only_exists_in_raw8(self):
        """RAW_RGB_NO_WB is read only as the fallback for a missing 16-bit array,
        so building it in RAW16 mode would pin a full extra frame for no reader."""
        _, raw16_arrays, _ = frame_builder.build_frame(_raw16(), W, H, 16, 'BGGR', {})
        assert raw16_arrays['RAW_RGB_NO_WB'] is None
        assert raw16_arrays['RAW_RGB_16BIT'] is not None

        _, raw8_arrays, _ = frame_builder.build_frame(_raw8(), W, H, 8, 'BGGR', {})
        assert raw8_arrays['RAW_RGB_NO_WB'] is not None
        assert raw8_arrays['RAW_RGB_16BIT'] is None

    def test_stats_match_stats_of_pil_array(self):
        """The array stats are computed from equals np.array(pil) — no copy needed."""
        img, _, stats = frame_builder.build_frame(_raw16(), W, H, 16, 'BGGR', {})
        via_pil = calculate_image_stats(np.array(img))
        assert stats == via_pil

    def test_consecutive_frames_return_distinct_arrays(self):
        """No slot reuse: a queued task can't have its array overwritten."""
        img_a, a, _ = frame_builder.build_frame(_raw16(1), W, H, 16, 'BGGR', {})
        img_b, b, _ = frame_builder.build_frame(_raw16(2), W, H, 16, 'BGGR', {})
        assert a['RAW_RGB_16BIT'] is not b['RAW_RGB_16BIT']
        assert not np.shares_memory(a['RAW_RGB_16BIT'], b['RAW_RGB_16BIT'])
        assert img_a.tobytes() != img_b.tobytes()

    def test_frame_is_not_a_view_of_the_raw_bytes(self):
        """np.frombuffer aliases the SDK bytes; the returned arrays must not."""
        raw = bytearray(_raw16())
        _, arrays, _ = frame_builder.build_frame(raw, W, H, 16, 'BGGR', {})
        before = arrays['RAW_RGB_16BIT'].copy()
        raw[:] = bytearray(len(raw))
        np.testing.assert_array_equal(arrays['RAW_RGB_16BIT'], before)


# ---------------------------------------------------------------------------
# Cache contract: cache_metadata / strip_cache_keys / rebuild_frame
# ---------------------------------------------------------------------------

def _captured_metadata(bit_depth=16):
    raw = _raw16() if bit_depth == 16 else _raw8()
    img, arrays, _ = frame_builder.build_frame(raw, W, H, bit_depth, 'BGGR', {})
    metadata = {
        'FILENAME': 'capture.png',
        'RES': f'{W}x{H}',
        'RAW_RGB_16BIT': arrays['RAW_RGB_16BIT'],
        'RAW_RGB_NO_WB': arrays['RAW_RGB_NO_WB'],
        'RAW_BAYER': raw,
        'RAW_GEOMETRY': (W, H, bit_depth, 'BGGR'),
        'WB_CONFIG': {},
    }
    return img, metadata


class TestCacheContract:

    def test_cache_metadata_drops_arrays_keeps_rebuild_keys(self):
        _, metadata = _captured_metadata()
        cached = frame_builder.cache_metadata(metadata)
        assert 'RAW_RGB_16BIT' not in cached
        assert 'RAW_RGB_NO_WB' not in cached
        assert cached['RAW_BAYER'] is metadata['RAW_BAYER']  # referenced, not copied
        assert cached['RAW_GEOMETRY'] == (W, H, 16, 'BGGR')
        assert cached['FILENAME'] == 'capture.png'

    def test_strip_cache_keys_removes_all_three(self):
        _, metadata = _captured_metadata()
        stripped = frame_builder.strip_cache_keys(metadata)
        for key in frame_builder.CACHE_KEYS:
            assert key not in stripped
        assert stripped['RAW_RGB_16BIT'] is metadata['RAW_RGB_16BIT']

    def test_rebuild_is_pixel_identical_to_the_original_capture(self):
        original_img, metadata = _captured_metadata()
        cached = frame_builder.cache_metadata(metadata)

        rebuilt_img, rebuilt_meta = frame_builder.rebuild_frame(cached)

        assert rebuilt_img.tobytes() == original_img.tobytes()
        np.testing.assert_array_equal(
            rebuilt_meta['RAW_RGB_16BIT'], metadata['RAW_RGB_16BIT']
        )
        assert rebuilt_meta['FILENAME'] == 'capture.png'
        for key in frame_builder.CACHE_KEYS:
            assert key not in rebuilt_meta

    def test_rebuild_raw8_carries_the_no_wb_array(self):
        _, metadata = _captured_metadata(bit_depth=8)
        _, rebuilt_meta = frame_builder.rebuild_frame(frame_builder.cache_metadata(metadata))
        np.testing.assert_array_equal(
            rebuilt_meta['RAW_RGB_NO_WB'], metadata['RAW_RGB_NO_WB']
        )
        assert 'RAW_RGB_16BIT' not in rebuilt_meta

    def test_rebuild_of_non_camera_metadata_is_none(self):
        assert frame_builder.rebuild_frame({'FILENAME': 'x.png'}) == (None, None)
        assert frame_builder.rebuild_frame(None) == (None, None)
        assert not frame_builder.is_rebuildable({})

    def test_rebuild_failure_is_swallowed(self):
        bad = {'RAW_BAYER': b'\x00\x01', 'RAW_GEOMETRY': (W, H, 16, 'BGGR'), 'WB_CONFIG': {}}
        assert frame_builder.rebuild_frame(bad) == (None, None)


# ---------------------------------------------------------------------------
# on_image_captured / cached_raw_frame boundary
# ---------------------------------------------------------------------------

def _bind(win, name):
    setattr(win, name, types.MethodType(getattr(_MainWindowOutputMixin, name), win))


class _CacheHost(_MainWindowOutputMixin):
    """Minimal host exercising the real mixin methods without a Qt window."""

    def __init__(self):
        self._cached_raw_metadata = None
        self._cached_raw_image = None


class TestOnImageCapturedCache:

    def _window(self):
        win = MagicMock()
        win.config = {'auto_stretch': {'enabled': False}}
        _bind(win, 'on_image_captured')
        return win

    def test_processor_metadata_has_no_rebuild_keys(self):
        win = self._window()
        img, metadata = _captured_metadata()

        win.on_image_captured(img, metadata)

        (_, processor_meta), _ = win.image_processor.process_and_save.call_args
        for key in frame_builder.CACHE_KEYS:
            assert key not in processor_meta
        assert processor_meta['RAW_RGB_16BIT'] is metadata['RAW_RGB_16BIT']

    def test_cache_keeps_rebuild_keys_and_drops_arrays(self):
        win = self._window()
        img, metadata = _captured_metadata()

        win.on_image_captured(img, metadata)

        assert win._cached_raw_metadata['RAW_BAYER'] is metadata['RAW_BAYER']
        assert 'RAW_RGB_16BIT' not in win._cached_raw_metadata
        assert 'RAW_RGB_NO_WB' not in win._cached_raw_metadata
        # No PIL copy is retained in camera mode — the frame is rebuilt on demand.
        assert win._cached_raw_image is None

    def test_cached_raw_frame_rebuilds_in_camera_mode(self):
        host = _CacheHost()
        img, metadata = _captured_metadata()
        host._cached_raw_metadata = frame_builder.cache_metadata(metadata)

        rebuilt, rebuilt_meta = host.cached_raw_frame()

        assert rebuilt.tobytes() == img.tobytes()
        assert 'RAW_BAYER' not in rebuilt_meta
        assert host._cached_raw_image is None
        assert host.has_cached_frame()

    def test_cached_raw_frame_returns_stored_image_in_watch_mode(self):
        host = _CacheHost()
        img, _ = _captured_metadata()
        host._cached_raw_metadata = {'FILENAME': 'watched.png'}
        host._cached_raw_image = img

        stored, meta = host.cached_raw_frame()

        assert stored is img
        assert meta['FILENAME'] == 'watched.png'

    def test_cached_raw_frame_empty(self):
        assert _CacheHost().cached_raw_frame() == (None, None)


# ---------------------------------------------------------------------------
# debayer_raw_image dst= parameters (kept for API stability, unused by capture)
# ---------------------------------------------------------------------------

class TestDebayerDstBuffersStillSupported:

    def test_dst_rgb8_written_and_matches_no_dst_path(self):
        from services.camera.camera_utils import debayer_raw_image
        raw = _raw8()
        dst = np.zeros((H, W, 3), dtype=np.uint8)
        with_dst, _ = debayer_raw_image(raw, W, H, 'BGGR', bit_depth=8, dst_rgb8=dst)
        no_dst, _ = debayer_raw_image(raw, W, H, 'BGGR', bit_depth=8)
        assert with_dst is dst
        np.testing.assert_array_equal(with_dst, no_dst)

    def test_dst_rgb16_written_and_matches_no_dst_path(self):
        from services.camera.camera_utils import debayer_raw_image
        raw = _raw16()
        dst16 = np.zeros((H, W, 3), dtype=np.uint16)
        _, with_dst = debayer_raw_image(raw, W, H, 'BGGR', bit_depth=16,
                                        return_raw16=True, dst_rgb16=dst16)
        _, no_dst = debayer_raw_image(raw, W, H, 'BGGR', bit_depth=16, return_raw16=True)
        assert with_dst is dst16
        np.testing.assert_array_equal(with_dst, no_dst)


# ---------------------------------------------------------------------------
# Reprocess must not rebuild the frame on the GUI thread
# ---------------------------------------------------------------------------

class TestReprocessDefersRebuild:

    def _window(self):
        win = MagicMock()
        win.config = {'auto_stretch': {'enabled': False}}
        _bind(win, '_do_reprocess')
        _bind(win, 'has_cached_frame')
        return win

    def test_camera_mode_hands_the_processor_a_factory(self, monkeypatch):
        win = self._window()
        _, metadata = _captured_metadata()
        win._cached_raw_image = None
        win._cached_raw_metadata = frame_builder.cache_metadata(metadata)
        rebuilt_on_gui_thread = []
        real_rebuild = frame_builder.rebuild_frame
        monkeypatch.setattr(frame_builder, 'rebuild_frame',
                            lambda meta: (rebuilt_on_gui_thread.append(1), real_rebuild(meta))[1])

        win._do_reprocess()

        assert rebuilt_on_gui_thread == []
        (img, meta), kwargs = win.image_processor.process_and_save.call_args
        assert img is None
        assert meta is win._cached_raw_metadata
        factory = kwargs['frame_factory']
        pil, built = factory()  # what the worker thread will run
        assert rebuilt_on_gui_thread == [1]
        assert pil.size == (W, H) and 'RAW_BAYER' not in built

    def test_watch_mode_passes_the_stored_image_directly(self):
        win = self._window()
        img, _ = _captured_metadata()
        win._cached_raw_image = img
        win._cached_raw_metadata = {'FILENAME': 'watched.png'}

        win._do_reprocess()

        (passed_img, meta), kwargs = win.image_processor.process_and_save.call_args
        assert passed_img is img and 'frame_factory' not in kwargs

    def test_nothing_cached_is_a_no_op(self):
        win = self._window()
        win._cached_raw_image = None
        win._cached_raw_metadata = None

        win._do_reprocess()

        win.image_processor.process_and_save.assert_not_called()
