"""Tests for services/web_image_encode.py — the /latest encode path.

The bug these guard: the web push used to encode a full-resolution optimized
PNG (~1.4 s, ~15 MB) that the server then decoded, resized and re-encoded as
JPEG anyway. The encoder must resize FIRST and encode once.
"""
import io
import random

import pytest
from PIL import Image

from services.web_image_encode import (
    WEB_IMAGE_MAX_BYTES,
    WEB_IMAGE_MAX_DIM,
    encode_for_web,
)


def _image(width, height, mode='RGB'):
    """A noisy gradient — a flat colour compresses to nothing and hides size bugs."""
    img = Image.new(mode, (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            value = ((x * 7 + y * 13) % 256, (x * 3) % 256, (y * 5) % 256)
            px[x, y] = value if mode == 'RGB' else value + (255,)
    return img


def _noise(width, height):
    """Deterministic noise — incompressible enough to exercise the size cap."""
    rng = random.Random(1234)
    img = Image.new('RGB', (width, height))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                 for _ in range(width * height)])
    return img


def _decoded(data):
    return Image.open(io.BytesIO(data))


def test_small_jpeg_frame_honours_configured_format():
    data, content_type = encode_for_web(
        _image(64, 48), output_format='jpg', jpg_quality=85
    )
    assert content_type == 'image/jpeg'
    assert _decoded(data).size == (64, 48)


def test_small_png_frame_stays_png():
    data, content_type = encode_for_web(_image(64, 48), output_format='PNG')
    assert content_type == 'image/png'
    assert _decoded(data).format == 'PNG'
    assert _decoded(data).size == (64, 48)


def test_format_matching_is_case_and_alias_insensitive():
    for fmt in ('JPG', 'jpeg', 'Jpeg', ' jpg '):
        _, content_type = encode_for_web(_image(32, 32), output_format=fmt)
        assert content_type == 'image/jpeg', fmt


def test_missing_format_defaults_to_jpeg():
    _, content_type = encode_for_web(_image(32, 32), output_format=None)
    assert content_type == 'image/jpeg'


def test_jpg_quality_is_passed_through():
    frame = _image(160, 120)
    low, _ = encode_for_web(frame, output_format='jpg', jpg_quality=20)
    high, _ = encode_for_web(frame, output_format='jpg', jpg_quality=95)
    assert len(low) < len(high)


def test_oversized_frame_is_resized_before_encoding():
    data, content_type = encode_for_web(
        _image(600, 300), output_format='jpg', max_dim=200
    )
    assert content_type == 'image/jpeg'
    # Longest edge clamped, aspect ratio preserved.
    assert _decoded(data).size == (200, 100)


def test_oversized_png_request_is_downgraded_to_jpeg():
    """A full-res PNG is neither servable nor useful to the HTTP consumers."""
    data, content_type = encode_for_web(
        _image(600, 300), output_format='PNG', max_dim=200
    )
    assert content_type == 'image/jpeg'
    assert _decoded(data).format == 'JPEG'
    assert max(_decoded(data).size) <= 200


def test_frame_exactly_at_max_dim_is_not_resized():
    data, _ = encode_for_web(_image(WEB_IMAGE_MAX_DIM, 8), output_format='jpg')
    assert _decoded(data).size == (WEB_IMAGE_MAX_DIM, 8)


def test_result_fits_the_byte_cap():
    frame = _noise(400, 400)
    cap = 4 * 1024
    # Guard the guard: the PNG must actually breach the cap, or this proves nothing.
    assert len(encode_for_web(frame, output_format='PNG')[0]) > cap

    data, content_type = encode_for_web(frame, output_format='PNG', max_bytes=cap)
    assert len(data) <= cap
    # Falling back to fit the cap always yields JPEG.
    assert content_type == 'image/jpeg'


def test_default_caps_are_the_shipped_values():
    assert WEB_IMAGE_MAX_BYTES == 5 * 1024 * 1024
    assert WEB_IMAGE_MAX_DIM == 2048


def test_rgba_frame_encodes_as_jpeg_without_error():
    data, content_type = encode_for_web(
        _image(64, 64, mode='RGBA'), output_format='jpg'
    )
    assert content_type == 'image/jpeg'
    assert _decoded(data).mode == 'RGB'


@pytest.mark.parametrize('size', [(1, 1), (1, 4000)])
def test_degenerate_sizes_do_not_crash(size):
    data, content_type = encode_for_web(
        _image(*size), output_format='jpg', max_dim=100
    )
    assert data
    assert content_type == 'image/jpeg'
