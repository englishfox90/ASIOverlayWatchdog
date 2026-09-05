"""
Configuration management for AllSky Overlay App
"""
import copy
import json
import os
import threading
from .utils_paths import get_app_data_dir
from .config_defaults import DEFAULT_CAMERA_PROFILE, DEFAULT_CONFIG  # re-exported for existing callers


class Config:
    # Class-level flag to track if cleanup has been attempted this session
    _cleanup_attempted = False

    def __init__(self, config_path=None):
        self._lock = threading.RLock()
        # Store config in user data directory for persistence across upgrades
        if config_path is None:
            user_data_dir = get_app_data_dir()
            os.makedirs(user_data_dir, exist_ok=True)
            config_path = os.path.join(user_data_dir, 'config.json')
            
            # One-time migration from old ASIOverlayWatchDog location
            old_base = os.getenv('LOCALAPPDATA')
            old_appdata_dir = os.path.join(old_base, 'ASIOverlayWatchDog') if old_base else ''
            if os.path.exists(old_appdata_dir) and not os.path.exists(config_path):
                self._migrate_from_old_location(old_appdata_dir, user_data_dir, config_path)
            
            # Migrate old config.json from app directory if it exists (legacy)
            old_config_path = 'config.json'
            if not os.path.exists(config_path) and os.path.exists(old_config_path):
                try:
                    import shutil
                    shutil.copy2(old_config_path, config_path)
                    from services.logger import app_logger
                    app_logger.info(f"Migrated config from {old_config_path} to {config_path}")
                except Exception as e:
                    from services.logger import app_logger
                    app_logger.warning(f"Could not migrate old config: {e}")
        
        self.config_path = config_path
        self.data = self.load()
        
        # Migrate any paths that still reference old ASIOverlayWatchDog
        self._migrate_old_paths()
        
        # Always attempt to clean up old ASIOverlayWatchDog directory if it exists
        self._cleanup_old_directory()
    
    def _migrate_from_old_location(self, old_dir, new_dir, new_config_path):
        """Migrate config and data from old ASIOverlayWatchDog location to new PFR\\Sentinel location"""
        import shutil
        
        from services.logger import app_logger
        app_logger.info(f"Migrating data from {old_dir} to {new_dir}...")

        try:
            # Migrate config.json
            old_config = os.path.join(old_dir, 'config.json')
            if os.path.exists(old_config):
                shutil.copy2(old_config, new_config_path)
                app_logger.info("Migrated config.json")

            # Migrate overlay_images folder if it exists
            old_overlay_images = os.path.join(old_dir, 'overlay_images')
            new_overlay_images = os.path.join(new_dir, 'overlay_images')
            if os.path.exists(old_overlay_images) and not os.path.exists(new_overlay_images):
                shutil.copytree(old_overlay_images, new_overlay_images)
                app_logger.info("Migrated overlay_images/")

            # Migrate weather_icons folder if it exists
            old_weather_icons = os.path.join(old_dir, 'weather_icons')
            new_weather_icons = os.path.join(new_dir, 'weather_icons')
            if os.path.exists(old_weather_icons) and not os.path.exists(new_weather_icons):
                shutil.copytree(old_weather_icons, new_weather_icons)
                app_logger.info("Migrated weather_icons/")
            
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
                        app_logger.info(f"Updated SDK path: {sdk_path} -> {new_sdk_path}")
                except Exception as e:
                    app_logger.warning(f"Could not update SDK path: {e}")

            # Remove old directory after successful migration
            try:
                shutil.rmtree(old_dir)
                app_logger.info(f"Removed old directory: {old_dir}")
            except Exception as e:
                app_logger.warning(f"Could not remove old directory (may be in use): {e}")

            app_logger.info(f"Migration complete! New location: {new_dir}")

        except Exception as e:
            app_logger.error(f"Migration failed: {e}. You may need to manually copy config.json from {old_dir} to {new_dir}")
    
    def _migrate_old_paths(self):
        """Update any config paths that still reference old ASIOverlayWatchDog location"""
        from services.logger import app_logger
        import shutil
        
        paths_to_check = ['sdk_path', 'output_directory', 'watch_directory']
        updated = False
        
        for key in paths_to_check:
            value = self.data.get(key, '')
            if value and 'ASIOverlayWatchDog' in value:
                new_value = value.replace('ASIOverlayWatchDog', 'PFRSentinel')
                
                # For SDK path, also try to copy the DLL if it exists at old location but not new
                if key == 'sdk_path' and os.path.isfile(value):
                    new_dir = os.path.dirname(new_value)
                    if not os.path.exists(new_value) and os.path.exists(new_dir):
                        try:
                            shutil.copy2(value, new_value)
                            app_logger.info(f"Copied SDK DLL from {value} to {new_value}")
                        except Exception as e:
                            app_logger.warning(f"Could not copy SDK DLL: {e}")
                
                self.data[key] = new_value
                app_logger.info(f"Migrated {key}: {value} -> {new_value}")
                updated = True
        
        # Also check if sdk_path points to non-existent file - try to find it in new location
        sdk_path = self.data.get('sdk_path', '')
        if sdk_path and not os.path.isfile(sdk_path):
            # Try to find SDK in the new PFRSentinel _internal folder
            possible_locations = [
                os.path.join(os.getenv('PROGRAMFILES(X86)', ''), 'PFRSentinel', '_internal', 'ASICamera2.dll'),
                os.path.join(os.getenv('PROGRAMFILES', ''), 'PFRSentinel', '_internal', 'ASICamera2.dll'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), '_internal', 'ASICamera2.dll'),
            ]
            for loc in possible_locations:
                if os.path.isfile(loc):
                    self.data['sdk_path'] = loc
                    app_logger.info(f"SDK path was invalid, found SDK at: {loc}")
                    updated = True
                    break
            else:
                if sdk_path:
                    app_logger.warning(f"SDK path is invalid and could not find SDK: {sdk_path}")
        
        if updated:
            self.save()
        
        # Clean up old Program Files installation if it exists and is empty or only has _internal
        self._cleanup_old_program_files()
    
    def _cleanup_old_program_files(self):
        """Attempt to remove old ASIOverlayWatchDog from Program Files if it exists (once per session)"""
        # Only attempt cleanup once per application session
        if Config._cleanup_attempted:
            return
        Config._cleanup_attempted = True
        
        import shutil
        from services.logger import app_logger
        
        # Check both Program Files locations
        old_locations = [
            os.path.join(os.getenv('PROGRAMFILES', ''), 'ASIOverlayWatchDog'),
            os.path.join(os.getenv('PROGRAMFILES(X86)', ''), 'ASIOverlayWatchDog'),
        ]
        
        for old_dir in old_locations:
            if old_dir and os.path.exists(old_dir):
                try:
                    shutil.rmtree(old_dir)
                    app_logger.info(f"Cleaned up old Program Files directory: {old_dir}")
                except PermissionError:
                    app_logger.warning(f"Could not remove old Program Files directory (may need admin rights): {old_dir}")
                except Exception as e:
                    app_logger.warning(f"Could not remove old Program Files directory {old_dir}: {e}")
    
    def _cleanup_old_directory(self):
        """Attempt to remove old ASIOverlayWatchDog directory if it still exists"""
        import shutil
        from services.logger import app_logger
        
        old_base = os.getenv('LOCALAPPDATA')
        old_dir = os.path.join(old_base, 'ASIOverlayWatchDog') if old_base else ''
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
        with self._lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, 'r') as f:
                        loaded = json.load(f)

                        # Migrate legacy per-camera zwo_* keys into camera_profiles[active].
                        # Idempotent — safe no-op once the config is already clean.
                        from .config_migrate import migrate_legacy_camera_keys
                        loaded = migrate_legacy_camera_keys(loaded)

                        # Drop profile keys that are pre-serial name-bug
                        # artefacts ("Camera 0", "... (Index: 2)").
                        from .camera_profiles import prune_bogus_profiles
                        loaded = prune_bogus_profiles(loaded)

                        # Merge with defaults to ensure new keys exist
                        config = copy.deepcopy(DEFAULT_CONFIG)

                        # Deep merge for nested configs like discord, white_balance
                        for key, value in loaded.items():
                            if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                                # Merge nested dict
                                config[key].update(value)
                            else:
                                config[key] = value

                        # Back-compat: derive scheduled_capture_mode from legacy
                        # scheduled_capture_enabled if mode wasn't stored.
                        if 'scheduled_capture_mode' not in loaded:
                            config['scheduled_capture_mode'] = (
                                'gated' if config.get('scheduled_capture_enabled') else 'always'
                            )

                        # Back-compat (W1): legacy configs enabled the web server
                        # via output.mode == 'webserver'; the modern GUI uses
                        # output.webserver_enabled. Carry the old flag forward so
                        # the web server isn't silently dead on upgraded configs.
                        loaded_output = loaded.get('output', {})
                        if (isinstance(loaded_output, dict)
                                and 'webserver_enabled' not in loaded_output
                                and loaded_output.get('mode') == 'webserver'):
                            config['output']['webserver_enabled'] = True

                        return config
                except Exception as e:
                    try:
                        from .logger import app_logger
                        app_logger.error(f"Error loading config: {e}")
                    except Exception:
                        pass
                    return copy.deepcopy(DEFAULT_CONFIG)
            return copy.deepcopy(DEFAULT_CONFIG)
    
    def save(self):
        """Save current configuration to JSON file"""
        with self._lock:
            try:
                with open(self.config_path, 'w') as f:
                    json.dump(self.data, f, indent=2)
                return True
            except Exception as e:
                try:
                    from .logger import app_logger
                    app_logger.error(f"Error saving config: {e}")
                except Exception:
                    pass
                return False
    
    def validate(self):
        """Validate configuration and return a list of warnings.

        Checks critical paths, port ranges, and required keys.
        Returns a list of warning strings (empty list = all OK).
        Does not block startup — warnings only.
        """
        warnings = []

        # Check output directory exists and is writable
        output_dir = self.data.get('output_directory', '')
        if output_dir:
            if not os.path.isdir(output_dir):
                warnings.append(f"Output directory does not exist: {output_dir}")
            elif not os.access(output_dir, os.W_OK):
                warnings.append(f"Output directory is not writable: {output_dir}")

        # Check watch directory if in watch mode
        if self.data.get('capture_mode') == 'watch':
            watch_dir = self.data.get('watch_directory', '')
            if not watch_dir:
                warnings.append("Watch mode selected but no watch directory configured")
            elif not os.path.isdir(watch_dir):
                warnings.append(f"Watch directory does not exist: {watch_dir}")

        # Validate port ranges
        output = self.data.get('output', {})
        for port_key in ['webserver_port']:
            port = output.get(port_key)
            if port is not None and not (1 <= port <= 65535):
                warnings.append(f"Invalid {port_key}: {port} (must be 1-65535)")

        # Check required top-level keys exist
        required_keys = ['capture_mode', 'output_directory', 'output', 'overlays']
        for key in required_keys:
            if key not in self.data:
                warnings.append(f"Missing required config key: {key}")

        # Check Discord webhook URL format if enabled
        discord = self.data.get('discord', {})
        if discord.get('enabled'):
            url = discord.get('webhook_url', '')
            if not url:
                warnings.append("Discord enabled but webhook URL is empty")

        # Check Hermes webhook config if enabled
        hermes = self.data.get('hermes', {})
        if hermes.get('enabled'):
            if not hermes.get('url', ''):
                warnings.append("Hermes enabled but webhook URL is empty")
            if not hermes.get('secret', ''):
                warnings.append("Hermes enabled but webhook secret is empty")

        # Check YouTube upload config if enabled
        youtube = self.data.get('youtube', {})
        if youtube.get('enabled'):
            try:
                from .youtube_config import validate_youtube_config
                warnings.extend(validate_youtube_config(youtube, require_client_file=True))
            except Exception as e:
                warnings.append(f"YouTube config validation failed: {e}")

        return warnings

    def get(self, key, default=None):
        """Get configuration value"""
        with self._lock:
            return self.data.get(key, default)

    def set(self, key, value):
        """Set configuration value"""
        with self._lock:
            self.data[key] = value
    
    def get_overlays(self):
        """Get overlay configurations"""
        with self._lock:
            return self.data.get("overlays", [])

    def set_overlays(self, overlays):
        """Set overlay configurations"""
        with self._lock:
            self.data["overlays"] = overlays
    
    def get_camera_profile(self, camera_name, serial=None):
        """Get a camera's settings profile, keyed by hardware serial when known
        (falls back to model name). See services/camera_profiles.py."""
        from .camera_profiles import get_camera_profile
        return get_camera_profile(self, camera_name, serial)

    def save_camera_profile(self, camera_name, profile_data, serial=None):
        """Persist a full profile dict for a camera (serial-keyed when known)."""
        from .camera_profiles import save_camera_profile
        save_camera_profile(self, camera_name, profile_data, serial)

    def update_camera_profile(self, camera_name, serial=None, **kwargs):
        """Update individual keys in a camera's profile (e.g. gain=150)."""
        from .camera_profiles import update_camera_profile
        update_camera_profile(self, camera_name, serial=serial, **kwargs)

    def list_camera_profiles(self):
        """All profile keys (serials and/or legacy names)."""
        from .camera_profiles import list_camera_profiles
        return list_camera_profiles(self)

    def delete_camera_profile(self, camera_name, serial=None):
        """Delete a camera profile by serial (preferred) or name key."""
        from .camera_profiles import delete_camera_profile
        delete_camera_profile(self, camera_name, serial)
