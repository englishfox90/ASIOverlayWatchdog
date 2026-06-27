"""
Context fetching utilities for calibration data.

Fetches moon phase, roof state (from NINA), and weather data
for inclusion in calibration JSON files.
"""
from datetime import datetime, date, timedelta
import time

from services.logger import app_logger

# Moon math moved to services/moon.py so services can use it without importing
# up into ui/controllers. Re-exported here for existing callers.
from services.moon import get_configured_location, compute_moon_context  # noqa: F401

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


def fetch_roof_state(nina_url="http://localhost:1888"):
    """
    Fetch roof/safety monitor state from NINA API.
    
    Calls: {nina_url}/v2/api/equipment/safetymonitor/info
    
    Args:
        nina_url: Base URL for NINA Advanced API
    
    Returns:
        dict with roof state info or error
    """
    if not REQUESTS_AVAILABLE:
        return {'available': False, 'reason': 'requests not installed'}
    
    url = f"{nina_url}/v2/api/equipment/safetymonitor/info"
    
    try:
        response = requests.get(url, timeout=2)  # Short timeout
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('Success') and data.get('Response'):
            resp = data['Response']
            return {
                'available': True,
                'source': 'nina_api',
                'is_safe': resp.get('IsSafe'),  # True = roof open
                'is_connected': resp.get('Connected'),
                'device_name': resp.get('Name'),
                'display_name': resp.get('DisplayName'),
                'description': resp.get('Description'),
                # Derived
                'roof_open': resp.get('IsSafe', False),  # Alias for clarity
            }
        else:
            return {
                'available': False,
                'reason': data.get('Error', 'Unknown error'),
                'status_code': data.get('StatusCode'),
            }
            
    except requests.exceptions.ConnectionError:
        return {'available': False, 'reason': 'NINA not running or API not accessible'}
    except requests.exceptions.Timeout:
        return {'available': False, 'reason': 'NINA API timeout'}
    except Exception as e:
        return {'available': False, 'reason': str(e)}


def fetch_weather_context():
    """
    Fetch current weather data for calibration.
    
    Uses the existing WeatherService if configured.
    
    Returns:
        dict with weather data or unavailable status
    """
    try:
        config = Config()
        weather_config = config.get('weather', {})
        
        api_key = weather_config.get('api_key')
        if not api_key:
            return {'available': False, 'reason': 'No API key configured'}
        
        # Import and use weather service
        from services.weather import WeatherService
        
        weather_svc = WeatherService(
            api_key=api_key,
            location=weather_config.get('location', ''),
            units=weather_config.get('units', 'metric'),
            latitude=weather_config.get('latitude'),
            longitude=weather_config.get('longitude')
        )
        
        weather_data = weather_svc.fetch_weather()
        
        if not weather_data:
            return {'available': False, 'reason': 'Weather fetch failed'}
        
        # Extract relevant fields for ML training
        return {
            'available': True,
            'source': 'openweathermap',
            # Temperature
            'temperature_c': weather_data.get('temp_raw'),
            'feels_like': weather_data.get('feels_like'),
            # Conditions
            'condition': weather_data.get('condition'),
            'description': weather_data.get('description'),
            'cloud_coverage_pct': int(weather_data.get('clouds', '0%').replace('%', '')),
            # Atmosphere
            'humidity_pct': int(weather_data.get('humidity', '0%').replace('%', '')),
            'pressure_hpa': int(weather_data.get('pressure', '0 hPa').replace(' hPa', '')),
            'visibility_km': float(weather_data.get('visibility', '0 km').replace(' km', '')),
            # Wind
            'wind_speed': weather_data.get('wind_speed'),
            'wind_dir': weather_data.get('wind_dir'),
            # Derived flags useful for ML
            'is_cloudy': int(weather_data.get('clouds', '0%').replace('%', '')) > 50,
            'is_clear': int(weather_data.get('clouds', '0%').replace('%', '')) < 20,
            'low_visibility': float(weather_data.get('visibility', '10 km').replace(' km', '')) < 5,
        }
        
    except Exception as e:
        app_logger.debug(f"Weather context fetch failed: {e}")
        return {'available': False, 'reason': str(e)}


def calculate_dew_point(temp_c, humidity_pct):
    """
    Calculate dew point from temperature and relative humidity.
    
    Uses Magnus formula approximation.
    
    Args:
        temp_c: Temperature in Celsius
        humidity_pct: Relative humidity percentage (0-100)
    
    Returns:
        Dew point in Celsius, or None if inputs invalid
    """
    if temp_c is None or humidity_pct is None:
        return None
    
    if humidity_pct <= 0:
        return None
    
    # Magnus formula constants
    a, b = 17.27, 237.7
    
    alpha = ((a * temp_c) / (b + temp_c)) + (humidity_pct / 100.0)
    dew_point = (b * alpha) / (a - alpha)
    
    return round(dew_point, 1)


def fetch_allsky_snapshot(output_dir: str = None, timestamp: str = None):
    """
    Fetch snapshot from all-sky camera for visual sky reference.
    
    The pier camera can't see the sky when the roof is closed, but the
    all-sky camera provides ground truth of actual sky conditions.
    
    Args:
        output_dir: Directory to save snapshot (optional, saves to raw_debug)
        timestamp: Timestamp string for filename (optional, uses current time)
    
    Returns:
        dict with snapshot info and optional local path
    """
    if not REQUESTS_AVAILABLE:
        return {'available': False, 'reason': 'requests not installed'}
    
    try:
        config = Config()
        
        # Get all-sky URL from config, with default
        allsky_config = config.get('allsky', {})
        allsky_url = allsky_config.get(
            'url',
            'https://zyssufjepmbhqznfuwcw.supabase.co/storage/v1/object/public/status-assets-public/building-0009/allsky/images/image.jpg'
        )
        
        if not allsky_url:
            return {'available': False, 'reason': 'No all-sky URL configured'}
        
        # Fetch the image
        response = requests.get(allsky_url, timeout=10)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        image_bytes = response.content
        
        result = {
            'available': True,
            'source': 'allsky_camera',
            'url': allsky_url,
            'fetched_at': datetime.now().isoformat(),
            'size_bytes': len(image_bytes),
            'content_type': content_type,
        }
        
        # Optionally save to disk
        if output_dir:
            import os
            
            # Determine extension from content type
            ext = 'jpg' if 'jpeg' in content_type else 'png'
            
            if timestamp is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            filename = f"allsky_{timestamp}.{ext}"
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(image_bytes)
            
            result['saved_path'] = filepath
            result['filename'] = filename
            app_logger.info(f"DEV MODE: ✓ Saved all-sky snapshot to {filename}")
        
        return result
        
    except requests.exceptions.ConnectionError:
        return {'available': False, 'reason': 'All-sky camera not accessible'}
    except requests.exceptions.Timeout:
        return {'available': False, 'reason': 'All-sky camera timeout'}
    except Exception as e:
        app_logger.debug(f"All-sky snapshot fetch failed: {e}")
        return {'available': False, 'reason': str(e)}


def estimate_seeing_conditions(weather_context):
    """
    Estimate astronomical seeing conditions from weather data.
    
    Factors affecting seeing:
    - High humidity = poor seeing (thermal turbulence)
    - High wind = variable seeing
    - Low visibility = poor transparency
    - Temperature near dew point = fog/dew risk
    
    Args:
        weather_context: Dict from fetch_weather_context()
    
    Returns:
        dict with seeing estimates
    """
    if not weather_context.get('available'):
        return {'available': False}
    
    # Extract values with defaults
    humidity = weather_context.get('humidity_pct', 50)
    visibility = weather_context.get('visibility_km', 10)
    cloud_pct = weather_context.get('cloud_coverage_pct', 0)
    temp_c = weather_context.get('temperature_c')
    
    # Calculate scores (0-1, higher is better)
    humidity_score = max(0, 1 - (humidity - 40) / 60)  # Best below 40%, worst above 100%
    visibility_score = min(1, visibility / 10)  # Best at 10km+
    cloud_score = max(0, 1 - cloud_pct / 100)  # Best at 0%
    
    # Calculate dew risk
    dew_point = calculate_dew_point(temp_c, humidity)
    if temp_c and dew_point:
        dew_margin = temp_c - dew_point
        dew_risk = dew_margin < 3  # Risk if within 3°C
        dew_score = min(1, max(0, dew_margin / 10))
    else:
        dew_risk = None
        dew_score = 0.5  # Unknown
    
    # Overall seeing score (weighted average)
    overall = (
        humidity_score * 0.3 +
        visibility_score * 0.2 +
        cloud_score * 0.4 +
        dew_score * 0.1
    )
    
    # Classify
    if overall > 0.8:
        quality = 'excellent'
    elif overall > 0.6:
        quality = 'good'
    elif overall > 0.4:
        quality = 'fair'
    elif overall > 0.2:
        quality = 'poor'
    else:
        quality = 'very_poor'
    
    return {
        'available': True,
        'overall_score': round(overall, 2),
        'quality': quality,
        'humidity_score': round(humidity_score, 2),
        'visibility_score': round(visibility_score, 2),
        'cloud_score': round(cloud_score, 2),
        'dew_score': round(dew_score, 2),
        'dew_point_c': dew_point,
        'dew_risk': dew_risk,
    }
