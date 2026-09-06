"""Overlay image cache — services/overlay_renderer.py.

Without a cache, add_overlays re-decoded the user's logo PNG on every frame
(~150 ms and ~37 MB for a 3000 px RGBA source) and repeated the identical
LANCZOS resize down to overlay size. These tests pin the cache's contract:
decode once, notice a replaced file, stay bounded, and never hand back an
object a later frame could have mutated.
"""
import os
import time

import pytest
from PIL import Image

from services import overlay_renderer
from services.overlay_renderer import add_overlays


@pytest.fixture
def count_opens(monkeypatch):
    """Wrap Image.open so tests can count real decodes."""
    calls = []
    real_open = Image.open

    def counting_open(fp, *args, **kwargs):
        calls.append(fp)
        return real_open(fp, *args, **kwargs)

    monkeypatch.setattr(overlay_renderer.Image, 'open', counting_open)
    return calls


def _logo(tmp_path, name='logo.png', size=(300, 200), colour=(255, 0, 0, 255)):
    path = tmp_path / name
    Image.new('RGBA', size, colour).save(path)
    return str(path)


def _overlay(path, **over):
    cfg = {'type': 'image', 'image_path': path, 'width': 100, 'height': 60,
           'anchor': 'Bottom-Right', 'offset_x': 5, 'offset_y': 5}
    cfg.update(over)
    return cfg


def _base():
    return Image.new('RGB', (400, 300), (10, 10, 10))


def test_cache_decodes_the_overlay_file_once_across_frames(tmp_path, count_opens):
    path = _logo(tmp_path)
    overlays = [_overlay(path)]
    cache = {}

    add_overlays(_base(), overlays, {}, image_cache=cache)
    opens_after_first = [c for c in count_opens if c == path]
    add_overlays(_base(), overlays, {}, image_cache=cache)

    assert len(opens_after_first) == 1
    assert [c for c in count_opens if c == path] == opens_after_first


def test_without_a_cache_every_frame_decodes(tmp_path, count_opens):
    path = _logo(tmp_path)
    overlays = [_overlay(path)]

    add_overlays(_base(), overlays, {})
    add_overlays(_base(), overlays, {})

    assert len([c for c in count_opens if c == path]) == 2


def test_replacing_the_file_invalidates_the_entry(tmp_path, count_opens):
    path = _logo(tmp_path, colour=(255, 0, 0, 255))
    overlays = [_overlay(path)]
    cache = {}

    first = add_overlays(_base(), overlays, {}, image_cache=cache)

    # Same path, different content — the overlay settings panel lets the user
    # replace a file in place, so mtime/size is all the cache has to go on.
    time.sleep(0.01)
    Image.new('RGBA', (300, 200), (0, 0, 255, 255)).save(path)
    os.utime(path, None)

    second = add_overlays(_base(), overlays, {}, image_cache=cache)

    assert len([c for c in count_opens if c == path]) == 2
    assert first.getpixel((350, 260)) != second.getpixel((350, 260))


def test_a_resized_variant_is_cached_per_target_size(tmp_path, count_opens):
    path = _logo(tmp_path)
    cache = {}

    add_overlays(_base(), [_overlay(path, width=100, height=60)], {}, image_cache=cache)
    add_overlays(_base(), [_overlay(path, width=50, height=30)], {}, image_cache=cache)
    add_overlays(_base(), [_overlay(path, width=100, height=60)], {}, image_cache=cache)

    # 2 decodes for 2 distinct sizes; the repeat of the first size is a hit.
    assert len([c for c in count_opens if c == path]) == 2
    assert len(cache[path]['resized']) == 2


def test_cache_is_bounded_by_path_count(tmp_path):
    cache = {}
    paths = [_logo(tmp_path, name=f'logo{i}.png') for i in range(10)]

    for path in paths:
        add_overlays(_base(), [_overlay(path)], {}, image_cache=cache)

    assert len(cache) <= overlay_renderer._OVERLAY_CACHE_MAX_PATHS


def test_cache_is_bounded_by_size_variants(tmp_path):
    path = _logo(tmp_path)
    cache = {}

    for width in range(20, 140, 10):
        add_overlays(_base(), [_overlay(path, width=width, height=width)], {},
                     image_cache=cache)

    assert len(cache[path]['resized']) <= overlay_renderer._OVERLAY_CACHE_MAX_SIZES


def test_opacity_does_not_mutate_the_cached_image(tmp_path):
    path = _logo(tmp_path)
    cache = {}

    add_overlays(_base(), [_overlay(path, opacity=50)], {}, image_cache=cache)
    cached = next(iter(cache[path]['resized'].values()))
    assert cached.split()[3].getextrema() == (255, 255), \
        "opacity was applied to the cached object — later frames would compound it"

    # Full opacity on the next frame must still land at full alpha.
    opaque = add_overlays(_base(), [_overlay(path, opacity=100)], {}, image_cache=cache)
    faded = add_overlays(_base(), [_overlay(path, opacity=50)], {}, image_cache=cache)
    assert opaque.getpixel((350, 260))[0] > faded.getpixel((350, 260))[0]


def test_weather_icon_is_keyed_by_the_resolved_path(tmp_path, count_opens):
    """WEATHER_ICON resolves to a file that changes with the forecast — the
    cache must key on what it resolved to, not the literal token."""
    sunny = _logo(tmp_path, name='sunny.png', colour=(255, 255, 0, 255))
    rainy = _logo(tmp_path, name='rainy.png', colour=(0, 0, 255, 255))

    class _Weather:
        def __init__(self):
            self.path = sunny

        def is_configured(self):
            return True

        def get_weather_icon_path(self):
            return self.path

        def get_weather_tokens(self):
            return {}

    weather = _Weather()
    cache = {}
    overlays = [_overlay('WEATHER_ICON')]

    a = add_overlays(_base(), overlays, {}, image_cache=cache, weather_service=weather)
    weather.path = rainy
    b = add_overlays(_base(), overlays, {}, image_cache=cache, weather_service=weather)

    assert set(cache) == {sunny, rainy}
    assert 'WEATHER_ICON' not in cache
    assert a.getpixel((350, 260)) != b.getpixel((350, 260))


def test_maintain_aspect_still_letterboxes_the_overlay(tmp_path):
    path = _logo(tmp_path, size=(300, 200))
    cache = {}

    add_overlays(_base(), [_overlay(path, width=100, height=100,
                                    maintain_aspect=True)], {}, image_cache=cache)

    assert list(cache[path]['resized']) == [(100, 66)]
