"""
Tests for services.timelapse_window — recording-window schedule maths.

Covers:
- T1: the sun window must be naive LOCAL wall-clock, not UTC with tzinfo
  merely stripped (which shifted the window by the host's UTC offset).
- WindowCache: astral's solar geometry ran twice per captured frame; the cache
  must collapse that to one computation per day AND recompute when the window
  config changes.
"""
from datetime import date, datetime, timedelta, timezone

import astral.sun as astral_sun

from services.timelapse_window import WindowCache, sun_window
from services.timelapse_writer import TimelapseWriter


_SUN_CONFIG = {
    'enabled': True, 'window_mode': 'sun', 'sun_mode': 'sunset_sunrise',
    'sun_latitude': 51.5, 'sun_longitude': 0.0,
}

_PLUS5 = timezone(timedelta(hours=5))
_FAKE_SUNSET = datetime(2026, 1, 1, 18, 0, tzinfo=_PLUS5)    # 13:00 UTC
_FAKE_SUNRISE = datetime(2026, 1, 2, 6, 0, tzinfo=_PLUS5)    # 01:00 UTC


def _patch_sun(monkeypatch, calls=None):
    def fake_sun(observer, date=None):
        # s_today supplies 'sunset'; s_tomorrow supplies 'sunrise'.
        if calls is not None:
            calls.append(date)
        return {'sunset': _FAKE_SUNSET, 'sunrise': _FAKE_SUNRISE}
    monkeypatch.setattr(astral_sun, 'sun', fake_sun)


def test_sun_window_converts_utc_to_local_naive(monkeypatch):
    """astral returns tz-aware UTC; the window must be naive LOCAL wall-clock,
    not UTC with tzinfo merely stripped."""
    _patch_sun(monkeypatch)

    ws, we = sun_window(_SUN_CONFIG, date(2026, 1, 1))

    assert ws == _FAKE_SUNSET.astimezone().replace(tzinfo=None)
    assert we == _FAKE_SUNRISE.astimezone().replace(tzinfo=None)
    # On any host whose local offset isn't +5h, the buggy .replace(tzinfo=None)
    # (→ 18:00 naive) differs from the correct local instant.
    if datetime.now().astimezone().utcoffset() != timedelta(hours=5):
        assert ws != _FAKE_SUNSET.replace(tzinfo=None)


def test_writer_delegates_sun_window(monkeypatch):
    """The writer's _sun_window delegate must keep working for existing callers."""
    _patch_sun(monkeypatch)
    writer = TimelapseWriter()
    writer.configure(dict(_SUN_CONFIG))

    assert writer._sun_window(date(2026, 1, 1)) == sun_window(_SUN_CONFIG, date(2026, 1, 1))


def test_cache_computes_the_sun_window_once_per_day(monkeypatch):
    """The per-frame window check ran astral twice per captured frame; the
    cache must reduce repeat checks for the same day to zero recomputation."""
    calls = []
    _patch_sun(monkeypatch, calls)
    cache = WindowCache()

    first = cache.window_for_day(_SUN_CONFIG, date(2026, 1, 1))
    n_after_first = len(calls)
    assert n_after_first > 0

    for _ in range(50):
        assert cache.window_for_day(_SUN_CONFIG, date(2026, 1, 1)) == first
    assert len(calls) == n_after_first          # no recomputation

    cache.window_for_day(_SUN_CONFIG, date(2026, 1, 2))
    assert len(calls) > n_after_first           # a new day does recompute


def test_cache_recomputes_when_window_config_changes(monkeypatch):
    """A settings edit (mode, sun mode, coordinates, fixed times) must not be
    served a stale window."""
    calls = []
    _patch_sun(monkeypatch, calls)
    cache = WindowCache()
    day = date(2026, 1, 1)

    fixed = dict(_SUN_CONFIG, window_mode='fixed', fixed_start='18:00', fixed_end='06:00')
    assert cache.window_for_day(fixed, day) == (
        datetime(2026, 1, 1, 18, 0), datetime(2026, 1, 2, 6, 0))

    edited = dict(fixed, fixed_start='20:00')
    assert cache.window_for_day(edited, day) == (
        datetime(2026, 1, 1, 20, 0), datetime(2026, 1, 2, 6, 0))

    cache.window_for_day(_SUN_CONFIG, day)
    n = len(calls)
    moved = dict(_SUN_CONFIG, sun_latitude=-33.9, sun_longitude=151.2)
    cache.window_for_day(moved, day)
    assert len(calls) > n            # relocating the site recomputes the window
