"""
Weather service - OpenWeatherMap API integration
Fetches current weather data with caching to avoid excessive API calls
"""
import requests
import time
from datetime import datetime, timedelta
from services.logger import app_logger


class WeatherService:
    """
    OpenWeatherMap API integration with caching
    
    Features:
    - Fetches current weather data
    - Caches data for 10 minutes (600 calls/day for free tier)
    - Converts city name to coordinates
    - Downloads weather icons
    """
    
    def __init__(self, api_key, location, units='metric', latitude=None, longitude=None):
        """
        Initialize weather service
        
        Args:
            api_key: OpenWeatherMap API key
            location: City name fallback (e.g., "London", "London,GB")
            units: Temperature units ('metric', 'imperial', 'standard')
            latitude: Direct latitude coordinate (preferred over location)
            longitude: Direct longitude coordinate (preferred over location)
        """
        self.api_key = api_key
        self.location = location
        self.units = units
        self.base_url = "https://api.openweathermap.org/data/2.5"
        
        # Cache
        self.cache = {}
        self.cache_time = None
        self.cache_duration = 600  # 10 minutes (free tier: 1000 calls/day = ~1 call/90s)
        
        # Coordinates - use provided values if valid, otherwise resolve from city name
        self.lat = None
        self.lon = None
        
        # Set coordinates directly if provided and valid
        if latitude is not None and longitude is not None:
            try:
                lat_float = float(latitude) if isinstance(latitude, str) else latitude
                lon_float = float(longitude) if isinstance(longitude, str) else longitude
                if -90 <= lat_float <= 90 and -180 <= lon_float <= 180:
                    self.lat = lat_float
                    self.lon = lon_float
                    app_logger.info(f"Weather using direct coordinates: ({self.lat}, {self.lon})")
            except (ValueError, TypeError):
                pass  # Invalid coordinates, will fall back to location lookup
        
    def is_configured(self):
        """Check if weather service is properly configured"""
        # Configured if we have API key AND (coordinates OR location)
        has_coords = self.lat is not None and self.lon is not None
        has_location = bool(self.location)
        return bool(self.api_key and (has_coords or has_location))
    
    def resolve_location(self):
        """
        Convert city name to coordinates using OpenWeatherMap geocoding
        Only needed if coordinates weren't provided directly.
        
        Returns:
            bool: True if successful, False otherwise
        """
        # If coordinates already set (from constructor), no need to resolve
        if self.lat is not None and self.lon is not None:
            return True
        
        # Need location to resolve
        if not self.api_key or not self.location:
            return False
        
        try:
            # Use current weather API with city name (built-in geocoding)
            url = f"{self.base_url}/weather"
            params = {
                'q': self.location,
                'appid': self.api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self.lat = data['coord']['lat']
            self.lon = data['coord']['lon']
            
            app_logger.info(f"Weather location resolved: {self.location} -> ({self.lat}, {self.lon})")
            return True
            
        except requests.RequestException as e:
            app_logger.error(f"Failed to resolve weather location '{self.location}': {e}")
            return False
        except KeyError as e:
            app_logger.error(f"Unexpected weather API response format: {e}")
            return False
    
    def is_cache_valid(self):
        """Check if cached data is still valid"""
        if not self.cache or not self.cache_time:
            return False
        
        elapsed = time.time() - self.cache_time
        return elapsed < self.cache_duration
    
    def fetch_weather(self):
        """
        Fetch current weather data from OpenWeatherMap
        
        Returns:
            dict: Weather data with formatted fields, or None if error
        """
        if not self.is_configured():
            app_logger.warning("Weather service not configured (missing API key or location)")
            return None
        
        # Return cached data if valid
        if self.is_cache_valid():
            return self.cache
        
        # Resolve location if needed
        if not self.lat or not self.lon:
            if not self.resolve_location():
                return None
        
        try:
            # Fetch current weather
            url = f"{self.base_url}/weather"
            params = {
                'lat': self.lat,
                'lon': self.lon,
                'appid': self.api_key,
                'units': self.units
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Format weather data for tokens
            weather_data = self._format_weather_data(data)
            
            # Update cache
            self.cache = weather_data
            self.cache_time = time.time()
            
            app_logger.debug(f"Weather data fetched: {weather_data['description']}, {weather_data['temp']}")
            return weather_data
            
        except requests.RequestException as e:
            app_logger.error(f"Failed to fetch weather data: {e}")
            return None
        except (KeyError, ValueError) as e:
            app_logger.error(f"Error parsing weather data: {e}")
            return None
    
    def _format_weather_data(self, data):
        """
        Format OpenWeatherMap API response into token-friendly dict
        
        Args:
            data: Raw API response dict
            
        Returns:
            dict: Formatted weather data
        """
        # Temperature (already in configured units)
        temp = data['main']['temp']
        feels_like = data['main']['feels_like']
        temp_min = data['main']['temp_min']
        temp_max = data['main']['temp_max']
        
        # Temperature unit symbol
        unit_symbol = {
            'metric': '°C',
            'imperial': '°F',
            'standard': 'K'
        }.get(self.units, '°C')
        
        # Weather condition
        weather = data['weather'][0]  # Primary weather condition
        condition = weather['main']  # e.g., "Rain", "Clouds"
        description = weather['description']  # e.g., "light rain"
        icon_code = weather['icon']  # e.g., "10d"
        
        # Wind (m/s for metric, mph for imperial)
        wind_speed = data['wind']['speed']
        wind_deg = data['wind'].get('deg', 0)
        wind_unit = 'm/s' if self.units == 'metric' else 'mph'
        
        # Wind direction (degrees to compass)
        wind_dir = self._degrees_to_compass(wind_deg)
        
        # Other
        humidity = data['main']['humidity']
        pressure = data['main']['pressure']
        visibility = data.get('visibility', 0) / 1000  # meters to km
        clouds = data['clouds']['all']
        
        # Sunrise/sunset (Unix timestamp to datetime)
        sunrise = datetime.fromtimestamp(data['sys']['sunrise'])
        sunset = datetime.fromtimestamp(data['sys']['sunset'])
        
        return {
            # Temperature
            'temp': f"{temp:.1f}{unit_symbol}",
            'temp_raw': temp,
            'feels_like': f"{feels_like:.1f}{unit_symbol}",
            'temp_min': f"{temp_min:.1f}{unit_symbol}",
            'temp_max': f"{temp_max:.1f}{unit_symbol}",
            
            # Condition
            'condition': condition,
            'description': description.title(),
            'icon_code': icon_code,
            'icon_url': f"https://openweathermap.org/img/wn/{icon_code}@2x.png",
            
            # Wind
            'wind_speed': f"{wind_speed:.1f} {wind_unit}",
            'wind_deg': wind_deg,
            'wind_dir': wind_dir,
            
            # Atmosphere
            'humidity': f"{humidity}%",
            'pressure': f"{pressure} hPa",
            'visibility': f"{visibility:.1f} km",
            'clouds': f"{clouds}%",
            
            # Sun
            'sunrise': sunrise.strftime('%H:%M'),
            'sunset': sunset.strftime('%H:%M'),
            
            # Location
            'city': data['name'],
            'country': data['sys']['country']
        }
    
    def _degrees_to_compass(self, degrees):
        """
        Convert wind direction degrees to compass direction
        
        Args:
            degrees: Wind direction in degrees (0-360)
            
        Returns:
            str: Compass direction (N, NE, E, etc.)
        """
        compass = [
            'N', 'NNE', 'NE', 'ENE',
            'E', 'ESE', 'SE', 'SSE',
            'S', 'SSW', 'SW', 'WSW',
            'W', 'WNW', 'NW', 'NNW'
        ]
        index = round(degrees / 22.5) % 16
        return compass[index]
    
    def download_weather_icon(self, icon_code, save_path):
        """
        Download weather icon from OpenWeatherMap
        
        Args:
            icon_code: Icon code (e.g., "10d")
            save_path: Path to save the icon
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            url = f"https://openweathermap.org/img/wn/{icon_code}@2x.png"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                f.write(response.content)
            
            app_logger.debug(f"Weather icon downloaded: {icon_code} -> {save_path}")
            return True
            
        except requests.RequestException as e:
            app_logger.error(f"Failed to download weather icon '{icon_code}': {e}")
            return False
    
    def get_weather_icon_path(self):
        """
        Get path to current weather icon, downloading if necessary
        
        Returns:
            str: Path to weather icon file, or None if unavailable
        """
        try:
            import os
            
            # Get data directory (consistent with config.py pattern)
            from app_config import APP_DATA_FOLDER
            data_dir = os.path.join(os.getenv('LOCALAPPDATA'), APP_DATA_FOLDER)
            
            icon_dir = os.path.join(data_dir, "weather_icons")
            os.makedirs(icon_dir, exist_ok=True)
            
            # Fetch current weather to get icon code
            weather_data = self.fetch_weather()
            if not weather_data:
                return None
            
            icon_code = weather_data['icon_code']
            icon_path = os.path.join(icon_dir, f"{icon_code}.png")
            
            # Download if not exists or older than cache duration
            if not os.path.exists(icon_path) or (time.time() - os.path.getmtime(icon_path)) > self.cache_duration:
                if self.download_weather_icon(icon_code, icon_path):
                    return icon_path
                else:
                    return None
            
            return icon_path
            
        except Exception as e:
            app_logger.error(f"Failed to get weather icon path: {e}")
            return None
    
    def get_weather_tokens(self):
        """
        Get weather data formatted as tokens for overlay system
        
        Returns:
            dict: Token name -> value mapping, or empty dict if no data
        """
        weather_data = self.fetch_weather()
        if not weather_data:
            return {}
        
        # Get weather icon path (downloads if needed)
        icon_path = self.get_weather_icon_path()
        
        tokens = {
            'WEATHER_TEMP': weather_data['temp'],
            'WEATHER_FEELS_LIKE': weather_data['feels_like'],
            'WEATHER_CONDITION': weather_data['condition'],
            'WEATHER_DESC': weather_data['description'],
            'WEATHER_HUMIDITY': weather_data['humidity'],
            'WEATHER_PRESSURE': weather_data['pressure'],
            'WEATHER_WIND_SPEED': weather_data['wind_speed'],
            'WEATHER_WIND_DIR': weather_data['wind_dir'],
            'WEATHER_CLOUDS': weather_data['clouds'],
            'WEATHER_VISIBILITY': weather_data['visibility'],
            'WEATHER_SUNRISE': weather_data['sunrise'],
            'WEATHER_SUNSET': weather_data['sunset'],
            'WEATHER_CITY': weather_data['city'],
            'WEATHER_ICON_CODE': weather_data['icon_code'],
            'WEATHER_ICON_URL': weather_data['icon_url']
        }
        
        # Add icon path if available
        if icon_path:
            tokens['WEATHER_ICON_PATH'] = icon_path
        
        return tokens
