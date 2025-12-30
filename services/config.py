"""
Configuration management for AllSky Overlay App
"""
import json
import os
from utils_paths import resource_path, get_exe_dir
from app_config import APP_DATA_FOLDER, DEFAULT_OUTPUT_SUBFOLDER

DEFAULT_CONFIG = {
    # Window settings
    "window_geometry": "1280x1700",
    
    # Mode selection
    "capture_mode": "camera",  # "watch" or "camera"
    
    # Directory watch settings
    "watch_directory": "",
    "watch_recursive": True,
    
    # Output settings
    "output_directory": os.path.join(os.getenv('LOCALAPPDATA'), APP_DATA_FOLDER, DEFAULT_OUTPUT_SUBFOLDER),
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
    
    # Auto Stretch settings (MTF - Midtone Transfer Function)
    "auto_stretch": {
        "enabled": False,
        "target_median": 0.25,  # Target median value (0.0-1.0, default 0.25 = quarter brightness)
        "linked_stretch": True  # Apply same stretch to all RGB channels (False = per-channel MAD clipping)
    },
    
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
            user_data_dir = os.path.join(os.getenv('LOCALAPPDATA'), APP_DATA_FOLDER)
            os.makedirs(user_data_dir, exist_ok=True)
            config_path = os.path.join(user_data_dir, 'config.json')
            
            # One-time migration from old ASIOverlayWatchDog location
            old_appdata_dir = os.path.join(os.getenv('LOCALAPPDATA'), 'ASIOverlayWatchDog')
            if os.path.exists(old_appdata_dir) and not os.path.exists(config_path):
                self._migrate_from_old_location(old_appdata_dir, user_data_dir, config_path)
            
            # Migrate old config.json from app directory if it exists (legacy)
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
        
        # Always attempt to clean up old ASIOverlayWatchDog directory if it exists
        self._cleanup_old_directory()
    
    def _migrate_from_old_location(self, old_dir, new_dir, new_config_path):
        """Migrate config and data from old ASIOverlayWatchDog location to new PFR\\Sentinel location"""
        import shutil
        
        print(f"Migrating data from {old_dir} to {new_dir}...")
        
        try:
            # Migrate config.json
            old_config = os.path.join(old_dir, 'config.json')
            if os.path.exists(old_config):
                shutil.copy2(old_config, new_config_path)
                print(f"  ✓ Migrated config.json")
            
            # Migrate overlay_images folder if it exists
            old_overlay_images = os.path.join(old_dir, 'overlay_images')
            new_overlay_images = os.path.join(new_dir, 'overlay_images')
            if os.path.exists(old_overlay_images) and not os.path.exists(new_overlay_images):
                shutil.copytree(old_overlay_images, new_overlay_images)
                print(f"  ✓ Migrated overlay_images/")
            
            # Migrate weather_icons folder if it exists
            old_weather_icons = os.path.join(old_dir, 'weather_icons')
            new_weather_icons = os.path.join(new_dir, 'weather_icons')
            if os.path.exists(old_weather_icons) and not os.path.exists(new_weather_icons):
                shutil.copytree(old_weather_icons, new_weather_icons)
                print(f"  ✓ Migrated weather_icons/")
            
            # Don't migrate Images/ folder (can be large) or Logs/ (not critical)
            # User can manually copy if needed
            
            # Update SDK path in migrated config if it points to old location
            if os.path.exists(new_config_path):
                try:
                    with open(new_config_path, 'r') as f:
                        import json
                        migrated_config = json.load(f)
                    
                    sdk_path = migrated_config.get('sdk_path', '')
                    if 'ASIOverlayWatchDog' in sdk_path:
                        # Update to new PFRSentinel path
                        new_sdk_path = sdk_path.replace('ASIOverlayWatchDog', 'PFRSentinel')
                        migrated_config['sdk_path'] = new_sdk_path
                        
                        with open(new_config_path, 'w') as f:
                            json.dump(migrated_config, f, indent=4)
                        print(f"  ✓ Updated SDK path: {sdk_path} -> {new_sdk_path}")
                except Exception as e:
                    print(f"  ⚠ Could not update SDK path: {e}")
            
            # Remove old directory after successful migration
            try:
                shutil.rmtree(old_dir)
                print(f"  ✓ Removed old directory: {old_dir}")
            except Exception as e:
                print(f"  ⚠ Could not remove old directory (may be in use): {e}")
            
            print(f"Migration complete! New location: {new_dir}")
            
        except Exception as e:
            print(f"Warning: Migration failed: {e}")
            print("You may need to manually copy config.json from:")
            print(f"  {old_dir}")
            print(f"to:")
            print(f"  {new_dir}")
    
    def _cleanup_old_directory(self):
        """Attempt to remove old ASIOverlayWatchDog directory if it still exists"""
        import shutil
        from services.logger import app_logger
        
        old_dir = os.path.join(os.getenv('LOCALAPPDATA'), 'ASIOverlayWatchDog')
        if os.path.exists(old_dir):
            try:
                shutil.rmtree(old_dir)
                app_logger.info(f"Cleaned up old directory: {old_dir}")
            except PermissionError as e:
                app_logger.warning(f"Could not remove old directory (files may be in use): {old_dir}")
            except Exception as e:
                app_logger.warning(f"Could not remove old directory {old_dir}: {e}")
    
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
