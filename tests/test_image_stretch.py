"""Equivalence and memory tests for the chunked auto-stretch.

``services/image_stretch.py`` evaluates the linked-RGB stretch in row bands
(see ``services/image_stretch_chunked.py``). These tests pin the rewrite to
``tests/reference/image_stretch_v371.py``, a frozen copy of the full-frame
implementation it replaced: every supported code path must produce a
byte-identical PIL image.
"""
import gc
import time
import tracemalloc

import numpy as np
import pytest
from PIL import Image

import services.image_stretch as stretch
import services.image_stretch_chunked as chunked
from services.image_stretch import auto_stretch_image
from services.logger import app_logger
from tests.reference.image_stretch_v371 import auto_stretch_image as reference_stretch

MB = 1024 * 1024

BASE_CONFIG = {
    'target_median': 0.25,
    'linked_stretch': True,
    'preserve_blacks': True,
    'black_point': 0.0,
    'shadow_aggressiveness': 2.8,
    'saturation_boost': 1.5,
    'normalize_channels': False,
    'dark_scene_threshold': 0.05,
    'scnr_amount': 0.0,
}


@pytest.fixture(autouse=True)
def quiet_stretch_logging(monkeypatch):
    """The stretch logs several debug lines per call; the matrix runs thousands."""
    monkeypatch.setattr(app_logger, 'debug', lambda *args, **kwargs: None)


@pytest.fixture
def single_row_bands(monkeypatch):
    """Force one-row bands so every chunk boundary falls inside the image."""
    monkeypatch.setattr(chunked, 'BAND_TARGET_BYTES', 1)


def _config(**overrides):
    cfg = dict(BASE_CONFIG)
    cfg.update(overrides)
    return cfg


def dark_sky_frame(height, width, seed=1):
    """Noisy dark sky with a sprinkling of saturated stars."""
    rng = np.random.default_rng(seed)
    frame = rng.normal(700, 90, (height, width, 3)).clip(0, 65535)
    for _ in range(max(1, (height * width) // 400)):
        y = int(rng.integers(0, height))
        x = int(rng.integers(0, width))
        frame[y, x] = rng.integers(20000, 65535, 3)
    return frame.astype(np.uint16)


def bright_frame(height, width, seed=2):
    rng = np.random.default_rng(seed)
    return rng.integers(40000, 65535, (height, width, 3), dtype=np.uint16)


def zero_frame(height, width, seed=3):
    return np.zeros((height, width, 3), dtype=np.uint16)


def saturated_frame(height, width, seed=4):
    return np.full((height, width, 3), 65535, dtype=np.uint16)


def midtone_frame(height, width, seed=5):
    rng = np.random.default_rng(seed)
    return rng.normal(16000, 3000, (height, width, 3)).clip(0, 65535).astype(np.uint16)


FRAME_MAKERS = [dark_sky_frame, bright_frame, zero_frame, saturated_frame, midtone_frame]
SMALL_SIZES = [(7, 13), (33, 17), (61, 97), (64, 64)]


def _as_pil(raw):
    return Image.fromarray((raw // 257).astype(np.uint8), 'RGB')


def assert_identical(img, config, raw_16bit=None):
    """Run both implementations on identical inputs and compare exactly."""
    ref_raw = None if raw_16bit is None else raw_16bit.copy()
    new_raw = None if raw_16bit is None else raw_16bit.copy()

    expected = reference_stretch(img, config, raw_16bit=ref_raw)
    actual = auto_stretch_image(img, config, raw_16bit=new_raw)

    assert actual.mode == expected.mode
    assert actual.size == expected.size
    assert np.array_equal(np.asarray(actual), np.asarray(expected))

    if raw_16bit is not None:
        assert np.array_equal(new_raw, raw_16bit), "auto_stretch_image mutated raw_16bit"
    return actual


@pytest.mark.parametrize('maker', FRAME_MAKERS, ids=[m.__name__ for m in FRAME_MAKERS])
@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize('preserve_blacks', [True, False])
@pytest.mark.parametrize('black_point', [0.0, 0.02])
def test_16bit_linked_matches_reference(maker, size, preserve_blacks, black_point):
    raw = maker(*size)
    config = _config(preserve_blacks=preserve_blacks, black_point=black_point)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)


@pytest.mark.parametrize('maker', FRAME_MAKERS, ids=[m.__name__ for m in FRAME_MAKERS])
@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize('preserve_blacks', [True, False])
@pytest.mark.parametrize('black_point', [0.0, 0.02])
def test_8bit_linked_matches_reference(maker, size, preserve_blacks, black_point):
    raw = maker(*size)
    config = _config(preserve_blacks=preserve_blacks, black_point=black_point)
    assert_identical(_as_pil(raw), config)


@pytest.mark.parametrize('maker', FRAME_MAKERS, ids=[m.__name__ for m in FRAME_MAKERS])
@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_unlinked_stretch_matches_reference(maker, size):
    raw = maker(*size)
    config = _config(linked_stretch=False)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)
    assert_identical(_as_pil(raw), config)


@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_dark_scene_channel_normalisation_matches_reference(size):
    raw = dark_sky_frame(*size)
    config = _config(normalize_channels=True, dark_scene_threshold=0.05)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)


@pytest.mark.parametrize('scnr_amount', [0.0, 0.5])
@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_scnr_matches_reference(scnr_amount, size):
    raw = dark_sky_frame(*size)
    config = _config(scnr_amount=scnr_amount)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)


@pytest.mark.parametrize('saturation_boost', [1.0, 1.5])
def test_saturation_boost_matches_reference(saturation_boost):
    raw = dark_sky_frame(33, 17)
    config = _config(saturation_boost=saturation_boost)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)


@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize('linked_stretch', [True, False])
def test_mono_image_matches_reference(size, linked_stretch):
    rng = np.random.default_rng(11)
    img = Image.fromarray(rng.integers(0, 30, size, dtype=np.uint8), 'L')
    assert_identical(img, _config(linked_stretch=linked_stretch))


@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize('linked_stretch', [True, False])
def test_rgba_image_matches_reference(size, linked_stretch):
    rng = np.random.default_rng(12)
    img = Image.fromarray(rng.integers(0, 30, (*size, 4), dtype=np.uint8), 'RGBA')
    assert_identical(img, _config(linked_stretch=linked_stretch))


def test_already_bright_image_returns_the_input_object():
    raw = saturated_frame(33, 17)
    img = _as_pil(raw)
    config = _config()

    assert reference_stretch(img, config, raw_16bit=raw.copy()) is img
    assert auto_stretch_image(img, config, raw_16bit=raw.copy()) is img


def test_mtf_skipped_path_matches_reference(monkeypatch):
    """Targeting the frame's own post-clip median takes the 'already at target' branch."""
    rng = np.random.default_rng(13)
    raw = rng.integers(0, 26214, (61, 97, 3), dtype=np.uint16)

    # Only the new implementation resolves _calculate_mtf_midtone through this
    # module at call time, so the spy leaves the frozen reference untouched.
    calls = []
    real_midtone = stretch._calculate_mtf_midtone

    def spy(current_median, target_median):
        calls.append(float(current_median))
        return real_midtone(current_median, target_median)

    monkeypatch.setattr(stretch, '_calculate_mtf_midtone', spy)

    auto_stretch_image(_as_pil(raw), _config(), raw_16bit=raw.copy())
    post_clip_median = calls[0]
    calls.clear()

    # The shadow clip is independent of target_median, so post_clip_median is
    # unchanged by this second run.
    config = _config(target_median=post_clip_median, saturation_boost=1.0)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)
    assert not calls, "expected the MTF-skipped branch, but a midtone was computed"


def test_below_threshold_channel_count_returns_input():
    rng = np.random.default_rng(14)
    raw = rng.integers(0, 3000, (20, 20, 2), dtype=np.uint16)
    img = Image.fromarray(np.zeros((20, 20), np.uint8), 'L')
    config = _config()

    assert reference_stretch(img, config, raw_16bit=raw.copy()) is img
    assert auto_stretch_image(img, config, raw_16bit=raw.copy()) is img


@pytest.mark.usefixtures('single_row_bands')
@pytest.mark.parametrize('maker', FRAME_MAKERS, ids=[m.__name__ for m in FRAME_MAKERS])
@pytest.mark.parametrize('size', SMALL_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize('black_point', [0.0, 0.02])
def test_single_row_bands_match_reference(maker, size, black_point):
    raw = maker(*size)
    config = _config(black_point=black_point)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)
    assert_identical(_as_pil(raw), config)


@pytest.mark.slow
@pytest.mark.parametrize('size', [(1001, 999), (1200, 1200)], ids=['1001x999', '1200x1200'])
@pytest.mark.parametrize('black_point', [0.0, 0.02])
def test_large_frames_match_reference(size, black_point):
    raw = dark_sky_frame(*size)
    config = _config(black_point=black_point)
    assert_identical(_as_pil(raw), config, raw_16bit=raw)


def _production_frame(side=3552):
    rng = np.random.default_rng(7)
    frame = rng.normal(700, 90, (side, side, 3)).clip(0, 65535).astype(np.uint16)
    ys = rng.integers(0, side, 4000)
    xs = rng.integers(0, side, 4000)
    frame[ys, xs] = rng.integers(20000, 65535, (4000, 3))
    return frame


def _traced(fn, img, config, raw):
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    out = fn(img, config, raw_16bit=raw)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = np.asarray(out).copy()
    del out
    gc.collect()
    return result, peak / MB, elapsed


@pytest.mark.slow
def test_full_frame_peak_memory_and_runtime():
    """A full ASI676MC frame must fit the memory ceiling and stay fast."""
    raw = _production_frame()
    img = Image.new('RGB', (raw.shape[1], raw.shape[0]))
    config = _config()

    expected, ref_peak, ref_time = _traced(reference_stretch, img, config, raw)
    actual, new_peak, new_time = _traced(auto_stretch_image, img, config, raw)

    assert np.array_equal(actual, expected)
    assert new_peak <= 320, (
        f"chunked peak {new_peak:.0f} MB exceeds the 320 MB ceiling "
        f"(reference peak {ref_peak:.0f} MB)"
    )
    assert new_time <= 1.5 * ref_time, (
        f"chunked run {new_time:.2f}s exceeds 1.5x the reference {ref_time:.2f}s"
    )
