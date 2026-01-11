"""
Time Context for Dev Mode

Computes time-of-day context (day/night/twilight) for mode classification.
Uses astral library for accurate sun position calculations when available.
"""
from datetime import datetime, date

try:
    from astral import LocationInfo
    from astral.sun import sun
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False

from services.logger import app_logger
from services.config import Config


def compute_time_context() -> dict:
    """
    Compute time-of-day context for mode classification using astral.
    
    Uses configured latitude/longitude from weather settings to calculate
    accurate sunrise, sunset, and twilight times.
    
    Twilight phases:
    - Civil twilight: Sun 0° to -6° below horizon (enough light for outdoor activities)
    - Nautical twilight: Sun -6° to -12° (horizon still visible at sea)
    - Astronomical twilight: Sun -12° to -18° (sky dark enough for astronomy)
    - Night: Sun below -18° (true astronomical darkness)
    
    Returns:
        dict with time context information including accurate twilight phases
    """
    now = datetime.now()
    
    # Try to get location from config for accurate calculations
    lat, lon, location_name = _get_configured_location()
    
    # If astral available and location configured, use accurate calculations
    if ASTRAL_AVAILABLE and lat is not None and lon is not None:
        return _compute_astral_time_context(now, lat, lon, location_name)
    
    # Fallback to simple hour-based classification
    return _compute_simple_time_context(now)


def _get_configured_location():
    """
    Get latitude/longitude from weather config.
    
    Returns:
        tuple: (latitude, longitude, location_name) or (None, None, None) if not configured
    """
    try:
        config = Config()
        weather_config = config.get('weather', {})
        
        lat_str = weather_config.get('latitude', '')
        lon_str = weather_config.get('longitude', '')
        location_name = weather_config.get('location', 'Observatory')
        
        if lat_str and lon_str:
            return float(lat_str), float(lon_str), location_name
        
        return None, None, None
    except Exception as e:
        app_logger.debug(f"Could not get location from config: {e}")
        return None, None, None


def _compute_astral_time_context(now, lat, lon, location_name):
    """
    Compute accurate twilight times using astral package.
    
    Args:
        now: Current datetime (naive local time)
        lat: Latitude in degrees
        lon: Longitude in degrees  
        location_name: Name of location for logging
        
    Returns:
        dict with accurate sun position and twilight phase
    """
    try:
        # Create location (timezone will be inferred or use local)
        loc = LocationInfo(
            name=location_name,
            region="",
            timezone="UTC",  # astral returns UTC times
            latitude=lat,
            longitude=lon
        )
        
        # Get sun times for today (returns UTC)
        today = date.today()
        s = sun(loc.observer, date=today)
        
        # Convert now to UTC for comparison with astral times
        # Assume naive datetime is local time
        import time
        local_tz_offset = time.timezone if time.daylight == 0 else time.altzone
        from datetime import timedelta
        now_utc = now + timedelta(seconds=local_tz_offset)
        
        # Extract times (all in UTC, strip tzinfo for comparison)
        dawn = s.get('dawn')
        sunrise = s.get('sunrise')
        noon = s.get('noon')
        sunset = s.get('sunset')
        dusk = s.get('dusk')
        
        # Strip timezone for easier comparison
        def strip_tz(dt):
            return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt
        
        dawn_naive = strip_tz(dawn)
        sunrise_naive = strip_tz(sunrise)
        noon_naive = strip_tz(noon)
        sunset_naive = strip_tz(sunset)
        dusk_naive = strip_tz(dusk)
        
        # Create dict with naive UTC times for classification
        sun_times_naive = {
            'dawn': dawn_naive,
            'sunrise': sunrise_naive,
            'noon': noon_naive,
            'sunset': sunset_naive,
            'dusk': dusk_naive,
        }
        
        # Determine current period based on sun position (now_utc vs UTC sun times)
        period, detailed_period = _classify_time_period(now_utc, sun_times_naive)
        
        # Is it astronomical night? (sun more than 18° below horizon)
        is_astro_night = False
        try:
            # Get astronomical twilight times (sun at -18°)
            from astral.sun import twilight
            astro_twilight = twilight(loc.observer, date=today, direction=1)  # Dawn
            astro_dusk = twilight(loc.observer, date=today, direction=-1)  # Dusk
            
            if astro_twilight and astro_dusk:
                astro_dawn_start = strip_tz(astro_twilight[0])
                astro_dusk_end = strip_tz(astro_dusk[1])
                # Astronomical night: before dawn starts OR after dusk ends
                is_astro_night = now_utc < astro_dawn_start or now_utc > astro_dusk_end
        except Exception as e:
            app_logger.debug(f"Could not get astronomical twilight: {e}")
            # Fallback: use civil twilight as proxy
            if dawn_naive and dusk_naive:
                is_astro_night = now_utc < dawn_naive or now_utc > dusk_naive
        
        return {
            'hour': now.hour,
            'minute': now.minute,
            'period': period,
            'detailed_period': detailed_period,
            'is_daylight': period == 'day',
            'is_astronomical_night': is_astro_night,
            'location': {
                'name': location_name,
                'latitude': lat,
                'longitude': lon,
            },
            'sun_times': {
                'dawn': dawn.isoformat() if dawn else None,
                'sunrise': sunrise.isoformat() if sunrise else None,
                'noon': noon.isoformat() if noon else None,
                'sunset': sunset.isoformat() if sunset else None,
                'dusk': dusk.isoformat() if dusk else None,
            },
            'calculation_method': 'astral',
        }
        
    except Exception as e:
        app_logger.warning(f"Astral calculation failed, using fallback: {e}")
        return _compute_simple_time_context(now)


def _classify_time_period(now, sun_times):
    """
    Classify current time into period and detailed_period.
    
    Args:
        now: Current datetime (naive, local time)
        sun_times: Dict from astral.sun.sun() with dawn/sunrise/sunset/dusk
        
    Returns:
        tuple: (period, detailed_period)
    """
    # Make times comparable (strip timezone for comparison)
    def to_naive(dt):
        if dt is None:
            return None
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    
    dawn = to_naive(sun_times.get('dawn'))
    sunrise = to_naive(sun_times.get('sunrise'))
    noon = to_naive(sun_times.get('noon'))
    sunset = to_naive(sun_times.get('sunset'))
    dusk = to_naive(sun_times.get('dusk'))
    
    # Determine period
    if sunrise and sunset and sunrise <= now <= sunset:
        period = 'day'
    elif (dawn and sunrise and dawn <= now < sunrise) or \
         (sunset and dusk and sunset < now <= dusk):
        period = 'twilight'
    else:
        period = 'night'
    
    # Determine detailed period
    if dawn and now < dawn:
        detailed_period = 'night'
    elif dawn and sunrise and dawn <= now < sunrise:
        detailed_period = 'dawn'
    elif sunrise and noon and sunrise <= now < noon:
        detailed_period = 'morning'
    elif noon and sunset:
        # Afternoon until ~2 hours before sunset
        afternoon_end = sunset.replace(
            hour=max(0, sunset.hour - 2),
            minute=sunset.minute
        )
        if noon <= now < afternoon_end:
            detailed_period = 'afternoon'
        elif afternoon_end <= now < sunset:
            detailed_period = 'evening'
        elif sunset <= now:
            if dusk and now <= dusk:
                detailed_period = 'dusk'
            else:
                detailed_period = 'night'
        else:
            detailed_period = 'afternoon'
    else:
        # Fallback based on hour
        detailed_period = _hour_to_detailed_period(now.hour)
    
    return period, detailed_period


def _hour_to_detailed_period(hour: int) -> str:
    """Simple hour-based detailed period (fallback)."""
    if 5 <= hour < 8:
        return 'dawn'
    elif 8 <= hour < 12:
        return 'morning'
    elif 12 <= hour < 17:
        return 'afternoon'
    elif 17 <= hour < 20:
        return 'evening'
    elif 20 <= hour < 22:
        return 'dusk'
    else:
        return 'night'


def _compute_simple_time_context(now):
    """
    Fallback: Simple hour-based time classification.
    
    Used when astral is not available or location not configured.
    """
    hour = now.hour
    
    # Simple day/night classification
    if 6 <= hour < 18:
        period = 'day'
    elif 18 <= hour < 21 or 5 <= hour < 6:
        period = 'twilight'
    else:
        period = 'night'
    
    detailed_period = _hour_to_detailed_period(hour)
    
    return {
        'hour': hour,
        'minute': now.minute,
        'period': period,
        'detailed_period': detailed_period,
        'is_daylight': 6 <= hour < 20,
        'is_astronomical_night': hour >= 22 or hour < 5,
        'calculation_method': 'simple_hour_based',
    }
