"""Moon phase / visibility via astral.

The single source of truth for moon context, used both when building calibration
JSON (training data) and at inference time (ml_service), so the sky model is fed
the same moon features it was trained on. Lives in services/ so services can use
it without importing up into ui/controllers.
"""
from datetime import datetime, date, timedelta
import time

from services.logger import app_logger
from services.config import Config

try:
    from astral import LocationInfo
    from astral.moon import phase as moon_phase, moonrise, moonset
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False


def parse_coordinate(value):
    """Parse a coordinate that may be decimal ('31.55', '-100.46') or DMS
    ('31 32 51', '100 27 25 W'). Returns float degrees, or None if unparseable."""
    s = str(value).strip().upper()
    if not s:
        return None
    sign = -1 if (s.startswith('-') or 'S' in s or 'W' in s) else 1
    for ch in "NSEW°'\":,-":
        s = s.replace(ch, ' ')
    parts = [p for p in s.split() if p]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if not nums:
        return None
    mag = nums[0] + (nums[1] if len(nums) > 1 else 0) / 60 + (nums[2] if len(nums) > 2 else 0) / 3600
    return sign * abs(mag)


def get_configured_location():
    """Return (latitude, longitude, name) from weather config, or (None, None, None).

    Accepts decimal or DMS coordinates (the settings UI allows either)."""
    try:
        config = Config()
        weather_config = config.get('weather', {})

        lat = parse_coordinate(weather_config.get('latitude', ''))
        lon = parse_coordinate(weather_config.get('longitude', ''))
        location_name = weather_config.get('location', 'Observatory')

        if lat is not None and lon is not None:
            return lat, lon, location_name

        return None, None, None
    except Exception as e:
        app_logger.debug(f"Could not get location from config: {e}")
        return None, None, None


def compute_moon_context():
    """Moon phase, illumination, rise/set, and whether it's currently up.

    Returns a dict with: available, phase_value, phase_name, illumination_pct,
    is_bright_moon, and (when a location is configured) moonrise/moonset/moon_is_up.
    """
    if not ASTRAL_AVAILABLE:
        return {'available': False, 'reason': 'astral not installed'}

    try:
        now = datetime.now()
        today = date.today()

        # Moon phase 0-27.99 (0=new, ~14=full)
        phase_value = moon_phase(today)

        # Approximate illumination: full (phase=14) = 100%, new (phase=0) = 0%
        illumination = (1 - abs(phase_value - 14) / 14) * 100

        if phase_value < 1:
            phase_name = 'new_moon'
        elif phase_value < 7:
            phase_name = 'waxing_crescent'
        elif phase_value < 8:
            phase_name = 'first_quarter'
        elif phase_value < 14:
            phase_name = 'waxing_gibbous'
        elif phase_value < 15:
            phase_name = 'full_moon'
        elif phase_value < 21:
            phase_name = 'waning_gibbous'
        elif phase_value < 22:
            phase_name = 'last_quarter'
        else:
            phase_name = 'waning_crescent'

        result = {
            'available': True,
            'phase_value': round(phase_value, 2),
            'phase_name': phase_name,
            'illumination_pct': round(illumination, 1),
            'is_bright_moon': illumination > 50,
        }

        lat, lon, location_name = get_configured_location()
        if lat is not None and lon is not None:
            try:
                loc = LocationInfo(name=location_name, region="", timezone="UTC",
                                   latitude=lat, longitude=lon)
                try:
                    rise = moonrise(loc.observer, today)
                    result['moonrise'] = rise.isoformat() if rise else None
                except ValueError:
                    result['moonrise'] = None
                try:
                    set_time = moonset(loc.observer, today)
                    result['moonset'] = set_time.isoformat() if set_time else None
                except ValueError:
                    result['moonset'] = None

                # Is the moon currently above the horizon?
                local_tz_offset = time.altzone if time.localtime().tm_isdst > 0 else time.timezone
                now_utc = now + timedelta(seconds=local_tz_offset)
                moon_rise_naive = result.get('moonrise')
                moon_set_naive = result.get('moonset')
                if moon_rise_naive and moon_set_naive:
                    rise_dt = datetime.fromisoformat(moon_rise_naive.replace('+00:00', ''))
                    set_dt = datetime.fromisoformat(moon_set_naive.replace('+00:00', ''))
                    if rise_dt < set_dt:
                        result['moon_is_up'] = rise_dt <= now_utc <= set_dt
                    else:  # rises after it sets (crosses midnight)
                        result['moon_is_up'] = now_utc >= rise_dt or now_utc <= set_dt
                else:
                    result['moon_is_up'] = None
            except Exception as e:
                app_logger.debug(f"Could not get moonrise/moonset: {e}")

        return result

    except Exception as e:
        app_logger.debug(f"Moon context calculation failed: {e}")
        return {'available': False, 'reason': str(e)}
