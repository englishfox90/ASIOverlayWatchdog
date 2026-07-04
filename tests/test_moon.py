"""
Tests for services/moon.py — moon phase, illumination, rise/set, moon_is_up.
"""
from datetime import datetime, timezone

import services.moon as moon


class _FakeConfig:
    """Minimal stand-in for services.config.Config with a fixed 'weather' block."""

    def __init__(self, weather=None):
        self._weather = weather or {}

    def get(self, key, default=None):
        if key == 'weather':
            return self._weather
        return default


def _patch_fixed_now(monkeypatch, year, month, day, hour, minute, second=0):
    """Freeze moon.datetime.now() to a fixed naive local time.

    fromisoformat() must still work on the patched class for the moonrise/
    moonset round-trip inside compute_moon_context().
    """
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, hour, minute, second)

    monkeypatch.setattr(moon, 'datetime', _FixedDateTime)
    return _FixedDateTime


def _patch_moon_rise_set(monkeypatch, rise, set_):
    monkeypatch.setattr(moon, 'moonrise', lambda observer, date_: rise)
    monkeypatch.setattr(moon, 'moonset', lambda observer, date_: set_)


# ---------------------------------------------------------------------------
# parse_coordinate
# ---------------------------------------------------------------------------

def test_parse_coordinate_decimal():
    assert moon.parse_coordinate('31.55') == 31.55
    assert moon.parse_coordinate('-100.46') == -100.46


def test_parse_coordinate_dms_with_hemisphere():
    lat = moon.parse_coordinate('31 32 51 N')
    assert round(lat, 3) == round(31 + 32 / 60 + 51 / 3600, 3)

    lon = moon.parse_coordinate('100 27 25 W')
    assert lon < 0
    assert round(lon, 3) == round(-(100 + 27 / 60 + 25 / 3600), 3)


def test_parse_coordinate_invalid_returns_none():
    assert moon.parse_coordinate('') is None
    assert moon.parse_coordinate('not-a-coordinate') is None


# ---------------------------------------------------------------------------
# get_configured_location
# ---------------------------------------------------------------------------

def test_get_configured_location_returns_coords(monkeypatch):
    monkeypatch.setattr(moon, 'Config', lambda: _FakeConfig(
        {'latitude': '51.5', 'longitude': '-0.1', 'location': 'London'}))
    lat, lon, name = moon.get_configured_location()
    assert lat == 51.5
    assert lon == -0.1
    assert name == 'London'


def test_get_configured_location_missing_coords_returns_none(monkeypatch):
    monkeypatch.setattr(moon, 'Config', lambda: _FakeConfig({}))
    lat, lon, name = moon.get_configured_location()
    assert (lat, lon, name) == (None, None, None)


# ---------------------------------------------------------------------------
# compute_moon_context — phase classification
# ---------------------------------------------------------------------------

def test_compute_moon_context_no_location_omits_rise_set(monkeypatch):
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (None, None, None))
    result = moon.compute_moon_context()
    assert result['available'] is True
    assert 'moonrise' not in result
    assert 'moon_is_up' not in result


def test_compute_moon_context_full_moon_classification(monkeypatch):
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (None, None, None))
    monkeypatch.setattr(moon, 'moon_phase', lambda today: 14.0)
    result = moon.compute_moon_context()
    assert result['phase_name'] == 'full_moon'
    assert result['illumination_pct'] == 100.0
    assert result['is_bright_moon'] is True


def test_compute_moon_context_new_moon_classification(monkeypatch):
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (None, None, None))
    monkeypatch.setattr(moon, 'moon_phase', lambda today: 0.0)
    result = moon.compute_moon_context()
    assert result['phase_name'] == 'new_moon'
    assert result['illumination_pct'] == 0.0
    assert result['is_bright_moon'] is False


# ---------------------------------------------------------------------------
# compute_moon_context — moon_is_up
# ---------------------------------------------------------------------------

def test_moon_is_up_true_within_window(monkeypatch):
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (51.5, -0.1, 'London'))
    _patch_moon_rise_set(
        monkeypatch,
        rise=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        set_=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
    )
    # UK winter: no DST, UTC offset is 0 — local time == UTC time.
    monkeypatch.setattr(moon.time, 'daylight', 1)
    monkeypatch.setattr(moon.time, 'timezone', 0)
    monkeypatch.setattr(moon.time, 'altzone', -3600)
    monkeypatch.setattr(moon.time, 'localtime',
                         lambda: moon.time.struct_time((2026, 1, 15, 12, 0, 0, 3, 15, 0)))
    _patch_fixed_now(monkeypatch, 2026, 1, 15, 12, 0)

    result = moon.compute_moon_context()
    assert result['moon_is_up'] is True


def test_moon_is_up_false_outside_window(monkeypatch):
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (51.5, -0.1, 'London'))
    _patch_moon_rise_set(
        monkeypatch,
        rise=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        set_=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(moon.time, 'daylight', 1)
    monkeypatch.setattr(moon.time, 'timezone', 0)
    monkeypatch.setattr(moon.time, 'altzone', -3600)
    monkeypatch.setattr(moon.time, 'localtime',
                         lambda: moon.time.struct_time((2026, 1, 15, 18, 0, 0, 3, 15, 0)))
    _patch_fixed_now(monkeypatch, 2026, 1, 15, 18, 0)

    result = moon.compute_moon_context()
    assert result['moon_is_up'] is False


def test_moon_is_up_crosses_midnight(monkeypatch):
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (51.5, -0.1, 'London'))
    # Rises late, sets after midnight the next "day" label — code takes the
    # "rises after it sets" branch (rise_dt > set_dt).
    _patch_moon_rise_set(
        monkeypatch,
        rise=datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc),
        set_=datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(moon.time, 'daylight', 1)
    monkeypatch.setattr(moon.time, 'timezone', 0)
    monkeypatch.setattr(moon.time, 'altzone', -3600)
    monkeypatch.setattr(moon.time, 'localtime',
                         lambda: moon.time.struct_time((2026, 1, 15, 23, 0, 0, 3, 15, 0)))
    _patch_fixed_now(monkeypatch, 2026, 1, 15, 23, 0)

    result = moon.compute_moon_context()
    assert result['moon_is_up'] is True


def test_tz_offset_uses_current_dst_state_not_zone_capability(monkeypatch):
    """Regression test for the DST bug.

    time.daylight only says the *zone* observes DST at some point in the year
    (e.g. UK is always 1) — it says nothing about *right now*. The offset must
    come from time.localtime().tm_isdst (the actual current state), not
    time.daylight. Simulates UK in winter: daylight=1 (zone has a DST rule)
    but tm_isdst=0 (currently on standard time, so offset should be
    time.timezone == 0, not time.altzone == -3600).

    Local "now" is 15:00 with the moon window 10:00-14:00 UTC. With the
    correct offset (0), now_utc == 15:00 -> outside the window -> not up.
    The old bug (picking altzone because daylight != 0) would compute
    now_utc == 14:00 -> inside the window -> wrongly "up".
    """
    monkeypatch.setattr(moon, 'get_configured_location', lambda: (51.5, -0.1, 'London'))
    _patch_moon_rise_set(
        monkeypatch,
        rise=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        set_=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(moon.time, 'daylight', 1)     # zone observes DST at some point
    monkeypatch.setattr(moon.time, 'timezone', 0)      # standard-time UTC offset (seconds)
    monkeypatch.setattr(moon.time, 'altzone', -3600)   # DST UTC offset (seconds)
    monkeypatch.setattr(moon.time, 'localtime',
                         lambda: moon.time.struct_time((2026, 1, 15, 15, 0, 0, 3, 15, 0)))
    _patch_fixed_now(monkeypatch, 2026, 1, 15, 15, 0)

    result = moon.compute_moon_context()
    assert result['moon_is_up'] is False
