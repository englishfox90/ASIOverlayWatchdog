"""
Constants for overlay system
"""

# Token definitions with friendly labels - organized with headers
# Format: ("Label", "Token") or ("HEADER", None) for section headers
TOKENS = [
    # Camera tokens
    ("━━━ Camera ━━━", None),  # Header (not selectable)
    ("Camera", "{CAMERA}"),
    ("Exposure", "{EXPOSURE}"),
    ("Gain", "{GAIN}"),
    ("Temperature", "{TEMP}"),
    ("Temp (Celsius)", "{TEMP_C}"),
    ("Temp (Fahrenheit)", "{TEMP_F}"),
    ("Resolution", "{RES}"),
    ("Session", "{SESSION}"),
    ("Date & Time", "{DATETIME}"),
    ("Filename", "{FILENAME}"),
    
    # Image statistics tokens
    ("━━━ Image Stats ━━━", None),  # Header
    ("Brightness/Mean", "{BRIGHTNESS}"),
    ("Median", "{MEDIAN}"),
    ("Min Pixel", "{MIN}"),
    ("Max Pixel", "{MAX}"),
    ("Std Deviation", "{STD_DEV}"),
    ("25th Percentile", "{P25}"),
    ("75th Percentile", "{P75}"),
    ("95th Percentile", "{P95}"),
    
    # Weather tokens (only shown if weather service is configured)
    ("━━━ Weather ━━━", None),  # Header
    ("Weather Temp", "{WEATHER_TEMP}"),
    ("Feels Like", "{WEATHER_FEELS_LIKE}"),
    ("Condition", "{WEATHER_CONDITION}"),
    ("Description", "{WEATHER_DESC}"),
    ("Humidity", "{WEATHER_HUMIDITY}"),
    ("Pressure", "{WEATHER_PRESSURE}"),
    ("Wind Speed", "{WEATHER_WIND_SPEED}"),
    ("Wind Direction", "{WEATHER_WIND_DIR}"),
    ("Clouds", "{WEATHER_CLOUDS}"),
    ("Visibility", "{WEATHER_VISIBILITY}"),
    ("Sunrise", "{WEATHER_SUNRISE}"),
    ("Sunset", "{WEATHER_SUNSET}"),
    ("City", "{WEATHER_CITY}"),
]

# Position presets
POSITION_PRESETS = [
    'Top-Left',
    'Top-Right', 
    'Bottom-Left',
    'Bottom-Right',
    'Center',
    'Custom (X/Y)'
]

# DateTime format presets
DATETIME_FORMATS = {
    'full': '%Y-%m-%d %H:%M:%S',
    'date': '%Y-%m-%d',
    'time': '%H:%M:%S',
    'custom': '%Y-%m-%d %H:%M:%S'  # Default for custom
}

# Locale-specific date formats
LOCALE_FORMATS = {
    'ISO (YYYY-MM-DD)': {'date': '%Y-%m-%d', 'time': '%H:%M:%S', 'datetime': '%Y-%m-%d %H:%M:%S'},
    'US (MM/DD/YYYY)': {'date': '%m/%d/%Y', 'time': '%I:%M:%S %p', 'datetime': '%m/%d/%Y %I:%M:%S %p'},
    'EU (DD.MM.YYYY)': {'date': '%d.%m.%Y', 'time': '%H:%M:%S', 'datetime': '%d.%m.%Y %H:%M:%S'},
    'UK (DD/MM/YYYY)': {'date': '%d/%m/%Y', 'time': '%H:%M:%S', 'datetime': '%d/%m/%Y %H:%M:%S'},
    'Short (MM-DD-YY)': {'date': '%m-%d-%y', 'time': '%H:%M:%S', 'datetime': '%m-%d-%y %H:%M:%S'},
}

# Default overlay configuration
DEFAULT_TEXT_OVERLAY = {
    'id': None,  # Will be assigned
    'name': 'New Overlay',
    'type': 'text',
    'text': 'New Overlay {CAMERA}',
    'anchor': 'Bottom-Left',
    'color': 'white',
    'font_size': 24,
    'font_style': 'normal',
    'offset_x': 10,
    'offset_y': 10,
    'background_enabled': False,
    'background_color': 'black',
    'datetime_mode': 'full',
    'datetime_format': '%Y-%m-%d %H:%M:%S'
}

DEFAULT_IMAGE_OVERLAY = {
    'id': None,
    'name': 'New Image Overlay',
    'type': 'image',
    'image_path': '',
    'anchor': 'Bottom-Right',
    'offset_x': 10,
    'offset_y': 10,
    'width': 100,
    'height': 100,
    'maintain_aspect': True,
    'opacity': 100
}
