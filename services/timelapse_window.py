"""
Recording-window schedule maths for the timelapse writer.

Pure functions over the ``timelapse`` config section: given a calendar day and
the configured window mode, return the (start, end) datetimes of that day's
recording window. Extracted from ``timelapse_writer`` so the writer keeps to
session/process management; ``WindowCache`` exists because the sun modes run
astral's solar geometry, which used to be recomputed twice per captured frame.
"""
from datetime import datetime, date, timedelta
from typing import Tuple

from .logger import app_logger


def to_local_naive(dt: datetime) -> datetime:
    """Convert a tz-aware datetime to naive local time.

    astral returns tz-aware UTC; the rest of the writer compares against
    datetime.now(), which is naive LOCAL. Stripping tzinfo without converting
    (the old bug) shifted the window by the host's UTC offset — hours wrong off
    the prime meridian. astimezone() with no argument converts to the system's
    local zone first, so the naive result lines up with datetime.now().
    """
    return dt.astimezone().replace(tzinfo=None)


def window_for_day(config: dict, day: date) -> Tuple[datetime, datetime]:
    """
    Return (window_start, window_end) for the given day.

    For overnight windows (e.g. 18:00 → 06:00) the window_end is on the
    following day. The current time is tested against windows anchored on both
    today and yesterday so sessions started yesterday are still considered
    active.
    """
    mode = config.get('window_mode', 'sun')

    if mode == 'always':
        # Full day: midnight to next midnight
        start = datetime.combine(day, datetime.min.time())
        end = datetime.combine(day + timedelta(days=1), datetime.min.time())
        return start, end

    if mode == 'fixed':
        return fixed_window(config, day)

    # Default: sun-based
    return sun_window(config, day)


def fixed_window(config: dict, day: date) -> Tuple[datetime, datetime]:
    """Parse fixed HH:MM start/end into datetimes, handling midnight crossing."""
    def parse_time(s: str, fallback: str) -> datetime:
        try:
            h, m = map(int, s.split(':'))
        except Exception:
            h, m = map(int, fallback.split(':'))
        return datetime.combine(day, datetime.strptime(f"{h}:{m}", "%H:%M").time())

    start = parse_time(config.get('fixed_start', '18:00'), '18:00')
    end = parse_time(config.get('fixed_end', '06:00'), '06:00')

    # If end is earlier than start, it crosses midnight → add a day
    if end <= start:
        end = end + timedelta(days=1)

    return start, end


def sun_window(config: dict, day: date) -> Tuple[datetime, datetime]:
    """Calculate sunset→sunrise window using the astral library."""
    try:
        from astral import LocationInfo
        from astral.sun import sun, time_at_elevation, SunDirection

        lat = config.get('sun_latitude')
        lon = config.get('sun_longitude')
        if lat is None or lon is None:
            raise ValueError("No coordinates configured for sun mode")

        loc = LocationInfo(latitude=float(lat), longitude=float(lon))
        sun_mode = config.get('sun_mode', 'astronomical')
        tomorrow = day + timedelta(days=1)

        if sun_mode == 'sunset_sunrise':
            s_today = sun(loc.observer, date=day)
            s_tomorrow = sun(loc.observer, date=tomorrow)
            window_start = to_local_naive(s_today['sunset'])
            window_end = to_local_naive(s_tomorrow['sunrise'])

        elif sun_mode == 'civil':
            s_today = sun(loc.observer, date=day)
            s_tomorrow = sun(loc.observer, date=tomorrow)
            window_start = to_local_naive(s_today['dusk'])
            window_end = to_local_naive(s_tomorrow['dawn'])

        elif sun_mode == 'nautical':
            window_start = to_local_naive(time_at_elevation(
                loc.observer, -12, date=day, direction=SunDirection.SETTING))
            window_end = to_local_naive(time_at_elevation(
                loc.observer, -12, date=tomorrow, direction=SunDirection.RISING))

        else:  # astronomical
            window_start = to_local_naive(time_at_elevation(
                loc.observer, -18, date=day, direction=SunDirection.SETTING))
            window_end = to_local_naive(time_at_elevation(
                loc.observer, -18, date=tomorrow, direction=SunDirection.RISING))

        return window_start, window_end

    except ImportError:
        app_logger.warning("Timelapse: astral not available, falling back to fixed window")
        return fixed_window(config, day)
    except Exception as e:
        app_logger.warning(f"Timelapse: sun window error ({e}), falling back to fixed window")
        return fixed_window(config, day)


class WindowCache:
    """Memoize window_for_day() per calendar day and window config.

    The window check runs on the frame-delivery thread for every captured
    frame, and in sun mode it evaluated astral's solar geometry twice per frame
    (today's window, then yesterday's). The result only changes when the day or
    the window settings change, so key on exactly that: a config edit or a
    coordinate change produces a different key and recomputes.

    Not internally synchronised — TimelapseWriter only ever calls it with its
    own lock held.
    """

    _MAX_ENTRIES = 8

    def __init__(self):
        self._cache = {}

    @staticmethod
    def _key(config: dict, day: date) -> tuple:
        return (
            day,
            config.get('window_mode', 'sun'),
            config.get('sun_mode', 'astronomical'),
            config.get('sun_latitude'),
            config.get('sun_longitude'),
            config.get('fixed_start', '18:00'),
            config.get('fixed_end', '06:00'),
        )

    def window_for_day(self, config: dict, day: date) -> Tuple[datetime, datetime]:
        key = self._key(config, day)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        window = window_for_day(config, day)
        # Only ever holds today's/yesterday's windows for the live config; a
        # wholesale clear beats tracking LRU order for a two-entry working set.
        if len(self._cache) >= self._MAX_ENTRIES:
            self._cache.clear()
        self._cache[key] = window
        return window
