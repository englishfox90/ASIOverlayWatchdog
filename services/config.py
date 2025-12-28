"""
Configuration management for AllSky Overlay App
"""
import json
import os
from utils_paths import resource_path, get_exe_dir

DEFAULT_CONFIG = {
    # Window settings
    "window_geometry": "1280x1700",
    
    # Mode selection
    "capture_mode": "camera",  # "watch" or "camera"
    
    # Directory watch settings
    "watch_directory": "",
    "watch_recursive": True,
    
    # Output settings
    "output_directory": os.path.join(os.getenv('LOCALAPPDATA'), 'ASIOverlayWatchDog', 'Images'),
    "filename_pattern": "latestImage",
    "output_format": "jpg",
    "jpg_quality": 85,
    "resize_percent": 85,
    "timestamp_corner": False,
    
    # Output mode settings
    "output": {
        "mode": "file",  # "file" | "webserver" | "rtsp"
        
        # Webserver settings
        "webserver_enabled": False,
        "webserver_host": "127.0.0.1",
        "webserver_port": 8080,
        "webserver_path": "/latest",
        "webserver_status_path": "/status",
        
        # RTSP settings
        "rtsp_enabled": False,
        "rtsp_host": "127.0.0.1",
        "rtsp_port": 8554,
        "rtsp_stream_name": "asiwatchdog",
        "rtsp_fps": 1.0
    },
    
    # ZWO Camera settings
    "zwo_sdk_path": resource_path("ASICamera2.dll"),
    "zwo_camera_index": 0,
    "zwo_camera_name": "",  # Last selected camera name
    "zwo_exposure_ms": 100.0,  # milliseconds (100ms default)
    "zwo_gain": 100,
    "zwo_interval": 5.0,
    "zwo_auto_exposure": False,
    "zwo_max_exposure_ms": 30000.0,  # milliseconds (30 seconds default)
    "zwo_target_brightness": 100,  # Target mean brightness (0-255) for auto exposure
    "zwo_wb_r": 75,
    "zwo_wb_b": 99,
    "zwo_auto_wb": False,
    "zwo_offset": 20,
    "zwo_flip": 0,  # 0=None, 1=Horizontal, 2=Vertical, 3=Both
    "zwo_bayer_pattern": "BGGR",  # "RGGB", "BGGR", "GRBG", "GBRG"
    "zwo_selected_camera": 0,  # Last selected camera index
    
    # Scheduled capture settings
    "scheduled_capture_enabled": False,
    "scheduled_start_time": "17:00",  # 5:00 PM
    "scheduled_end_time": "09:00",    # 9:00 AM (next day for overnight captures)
    
    # White Balance configuration
    "white_balance": {
        "mode": "asi_auto",  # "asi_auto" | "manual" | "gray_world"
        "manual_red_gain": 1.0,
        "manual_blue_gain": 1.0,
        "gray_world_low_pct": 5,
        "gray_world_high_pct": 95
    },
    
    "auto_brightness": False,  # Automatically adjust brightness
    "brightness_factor": 1.0,  # Brightness multiplier (0.5 to 2.0, 1.0 = neutral)
    "saturation_factor": 1.0,  # Saturation multiplier (0.0 to 2.0, 1.0 = neutral)
    
    # Overlay settings
    "overlays": [
        {
            "text": "Camera: {CAMERA}\nExposure: {EXPOSURE}\nGain: {GAIN}\nTemp: {TEMP}",
            "anchor": "Bottom-Left",
            "offset_x": 10,
            "offset_y": 10,
            "font_size": 24,
            "font_style": "normal",
            "color": "white"
        }
    ],
    
    # Cleanup settings
    "cleanup_enabled": False,
    "cleanup_max_size_gb": 10.0,
    "cleanup_strategy": "oldest",
    
    # Weather settings (OpenWeatherMap)
    "weather": {
        "enabled": False,  # Set to True when API key and location configured
        "api_key": "",
        "location": "",  # City name fallback, e.g., "London" or "London,GB"
        "latitude": "",  # Preferred: direct coordinates (e.g., "51.5074")
        "longitude": "",  # Preferred: direct coordinates (e.g., "-0.1278")
        "units": "metric",  # "metric", "imperial", or "standard"
        "cache_duration": 600  # Cache weather data for 10 minutes
    },
    
    # Discord alerts
    "discord": {
        "enabled": False,
        "webhook_url": "",
        "embed_color_hex": "#0EA5E9",
        "post_errors": False,
        "post_startup_shutdown": False,
        "periodic_enabled": False,
        "periodic_interval_minutes": 60,
        "include_latest_image": True,
        "username_override": "",
        "avatar_url": ""
    }
}

class Config:
    def __init__(self, config_path=None):
        # Store config in user data directory for persistence across upgrades
        if config_path is None:
            user_data_dir = os.path.join(os.getenv('LOCALAPPDATA'), 'ASIOverlayWatchDog')
            os.makedirs(user_data_dir, exist_ok=True)
            config_path = os.path.join(user_data_dir, 'config.json')
            
            # Migrate old config.json from app directory if it exists
            old_config_path = 'config.json'
            if not os.path.exists(config_path) and os.path.exists(old_config_path):
                try:
                    import shutil
                    shutil.copy2(old_config_path, config_path)
                    print(f"Migrated config from {old_config_path} to {config_path}")
                except Exception as e:
                    print(f"Warning: Could not migrate old config: {e}")
        
        self.config_path = config_path
        self.data = self.load()
    
    def load(self):
        """Load configuration from JSON file or return defaults"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults to ensure new keys exist
                    config = DEFAULT_CONFIG.copy()
                    
                    # Deep merge for nested configs like discord, white_balance
                    for key, value in loaded.items():
                        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                            # Merge nested dict
                            config[key].update(value)
                        else:
                            config[key] = value
                    
                    return config
            except Exception as e:
                print(f"Error loading config: {e}")
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()
    
    def save(self):
        """Save current configuration to JSON file"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def get(self, key, default=None):
        """Get configuration value"""
        return self.data.get(key, default)
    
    def set(self, key, value):
        """Set configuration value"""
        self.data[key] = value
    
    def get_overlays(self):
        """Get overlay configurations"""
        return self.data.get("overlays", [])
    
    def set_overlays(self, overlays):
        """Set overlay configurations"""
        self.data["overlays"] = overlays
