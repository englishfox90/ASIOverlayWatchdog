"""
Settings manager for loading, saving, and applying configuration.
Handles all config persistence and validation.
"""

from services.logger import app_logger
from tkinter import messagebox


class SettingsManager:
    """Manages application settings and configuration"""
    
    def __init__(self, app):
        """
        Initialize settings manager.
        
        Args:
            app: Main application instance
        """
        self.app = app
        self.is_loading_config = False
        
    # ===== CONFIGURATION LOADING =====
    
    def load_config(self):
        """Load configuration into GUI"""
        self.is_loading_config = True  # Prevent saves during load
        
        self.app.capture_mode_var.set(self.app.config.get('capture_mode', 'watch'))
        self.app.watch_dir_var.set(self.app.config.get('watch_directory', ''))
        self.app.watch_recursive_var.set(self.app.config.get('watch_recursive', True))
        self.app.output_dir_var.set(self.app.config.get('output_directory', ''))
        
        # Handle old config keys
        filename_pattern = self.app.config.get('filename_pattern', self.app.config.get('output_pattern', '{session}_{filename}'))
        self.app.filename_pattern_var.set(filename_pattern)
        
        output_format = self.app.config.get('output_format', 'png')
        if output_format.upper() == 'JPG':
            output_format = 'jpg'
        elif output_format.upper() == 'PNG':
            output_format = 'png'
        self.app.output_format_var.set(output_format.lower())
        
        self.app.jpg_quality_var.set(int(round(self.app.config.get('jpg_quality', 95))))
        self.app.resize_percent_var.set(int(round(self.app.config.get('resize_percent', 100))))
        self.app.auto_brightness_var.set(self.app.config.get('auto_brightness', False))
        
        # Handle old brightness keys
        brightness = self.app.config.get('brightness_factor', 
                                    self.app.config.get('auto_brightness_factor',
                                                   self.app.config.get('preview_brightness', 1.5)))
        self.app.brightness_var.set(brightness)
        
        # Saturation
        self.app.saturation_var.set(self.app.config.get('saturation_factor', 1.0))
        
        # Auto Stretch (MTF) settings
        auto_stretch = self.app.config.get('auto_stretch', {})
        self.app.auto_stretch_var.set(auto_stretch.get('enabled', False))
        self.app.stretch_median_var.set(auto_stretch.get('target_median', 0.25))
        self.app.stretch_linked_var.set(auto_stretch.get('linked_stretch', True))
        self.app.stretch_preserve_blacks_var.set(auto_stretch.get('preserve_blacks', True))
        self.app.stretch_shadow_var.set(auto_stretch.get('shadow_aggressiveness', 2.8))
        self.app.stretch_saturation_var.set(auto_stretch.get('saturation_boost', 1.5))
        
        # Handle old timestamp corner key
        timestamp = self.app.config.get('timestamp_corner', False)
        if isinstance(timestamp, bool):
            self.app.timestamp_corner_var.set(timestamp)
        else:
            self.app.timestamp_corner_var.set(self.app.config.get('show_timestamp_corner', False))
        
        self.app.cleanup_enabled_var.set(self.app.config.get('cleanup_enabled', False))
        self.app.cleanup_max_size_var.set(self.app.config.get('cleanup_max_size_gb', 10.0))
        
        # ZWO settings
        from utils_paths import resource_path
        self.app.sdk_path_var.set(self.app.config.get('zwo_sdk_path', resource_path('ASICamera2.dll')))
        
        # Handle exposure in both ms and seconds - default to seconds for better UX
        exposure_ms = self.app.config.get('zwo_exposure_ms', self.app.config.get('zwo_exposure', 100.0))
        self.app.exposure_var.set(exposure_ms / 1000.0)
        self.app.exposure_unit_var.set('s')
        self.app.capture_tab.set_exposure_unit('s')
        
        self.app.gain_var.set(self.app.config.get('zwo_gain', 100))
        self.app.wb_r_var.set(self.app.config.get('zwo_wb_r', 75))
        self.app.wb_b_var.set(self.app.config.get('zwo_wb_b', 99))
        
        # Load white balance config (replaces old auto_wb_var)
        wb_config = self.app.config.get('white_balance', {
            'mode': 'asi_auto',
            'manual_red_gain': 1.0,
            'manual_blue_gain': 1.0,
            'gray_world_low_pct': 5,
            'gray_world_high_pct': 95
        })
        self.app.wb_mode_var.set(wb_config.get('mode', 'asi_auto'))
        self.app.wb_gw_low_var.set(wb_config.get('gray_world_low_pct', 5))
        self.app.wb_gw_high_var.set(wb_config.get('gray_world_high_pct', 95))
        
        self.app.offset_var.set(self.app.config.get('zwo_offset', 20))
        self.app.bayer_pattern_var.set(self.app.config.get('zwo_bayer_pattern', 'BGGR'))
        
        # Handle flip - convert string to int if needed
        flip_val = self.app.config.get('zwo_flip', 0)
        flip_map_reverse = {'None': 'None', 0: 'None', 1: 'Horizontal', 2: 'Vertical', 3: 'Both'}
        if isinstance(flip_val, str):
            self.app.flip_var.set(flip_val)
        else:
            self.app.flip_var.set(flip_map_reverse.get(flip_val, 'None'))
        
        # Handle interval
        interval = self.app.config.get('zwo_interval', self.app.config.get('zwo_capture_interval', 5.0))
        self.app.interval_var.set(interval)
        
        # Load scheduled capture settings
        self.app.scheduled_capture_var.set(self.app.config.get('scheduled_capture_enabled', False))
        self.app.schedule_start_var.set(self.app.config.get('scheduled_start_time', '17:00'))
        self.app.schedule_end_var.set(self.app.config.get('scheduled_end_time', '09:00'))
        
        self.app.auto_exposure_var.set(self.app.config.get('zwo_auto_exposure', False))
        
        # Handle max exposure - convert from ms to seconds for new UI
        max_exp_ms = self.app.config.get('zwo_max_exposure_ms', self.app.config.get('zwo_max_exposure', 30000.0))
        self.app.max_exposure_var.set(max_exp_ms / 1000.0)
        
        # Load target brightness
        self.app.target_brightness_var.set(self.app.config.get('zwo_target_brightness', 100))
        
        # Update UI states
        self.app.on_mode_change()
        self.app.camera_controller.on_auto_exposure_toggle()
        self.app.on_auto_brightness_toggle()
        self.app.settings_tab._on_auto_stretch_toggle()  # Set initial auto-stretch UI state
        self.app.on_wb_mode_change()  # Set initial WB mode UI state
        self.app.on_scheduled_capture_toggle()  # Set initial scheduled capture UI state
        
        # Update mode button styling
        self.app.capture_tab.update_mode_button_styling()
        
        # Load overlays - handle old field names
        overlays = self.app.config.get('overlays', [])
        for overlay in overlays:
            if 'x_offset' in overlay and 'offset_x' not in overlay:
                overlay['offset_x'] = overlay['x_offset']
            if 'y_offset' in overlay and 'offset_y' not in overlay:
                overlay['offset_y'] = overlay['y_offset']
            if 'font_style' not in overlay:
                overlay['font_style'] = 'normal'
            # Add default name if missing
            if 'name' not in overlay:
                overlay['name'] = overlay.get('text', 'Overlay')[:30]
        
        self.app.overlay_manager.rebuild_overlay_list()
        
        # Load Discord settings
        discord_config = self.app.config.get('discord', {})
        app_logger.info(f"Loading Discord webhook: {discord_config.get('webhook_url', '')[:50]}..." if len(discord_config.get('webhook_url', '')) > 50 else f"Loading Discord webhook: {discord_config.get('webhook_url', '')}")
        app_logger.info(f"Discord enabled: {discord_config.get('enabled', False)}")
        
        self.app.discord_enabled_var.set(discord_config.get('enabled', False))
        self.app.discord_webhook_var.set(discord_config.get('webhook_url', ''))
        self.app.discord_color_var.set(discord_config.get('embed_color_hex', '#0EA5E9'))
        self.app.discord_post_errors_var.set(discord_config.get('post_errors', False))
        self.app.discord_post_lifecycle_var.set(discord_config.get('post_startup_shutdown', False))
        self.app.discord_periodic_enabled_var.set(discord_config.get('periodic_enabled', False))
        self.app.discord_interval_var.set(discord_config.get('periodic_interval_minutes', 60))
        self.app.discord_include_image_var.set(discord_config.get('include_latest_image', True))
        self.app.discord_username_var.set(discord_config.get('username_override', ''))
        self.app.discord_avatar_var.set(discord_config.get('avatar_url', ''))
        
        # Update Discord UI state
        self.app.on_discord_enabled_change()
        self.app.on_discord_periodic_change()
        
        # Load weather settings
        weather_config = self.app.config.get('weather', {})
        if hasattr(self.app, 'weather_api_key_var'):
            self.app.weather_api_key_var.set(weather_config.get('api_key', ''))
        if hasattr(self.app, 'weather_location_var'):
            self.app.weather_location_var.set(weather_config.get('location', ''))
        if hasattr(self.app, 'weather_lat_var'):
            self.app.weather_lat_var.set(weather_config.get('latitude', ''))
        if hasattr(self.app, 'weather_lon_var'):
            self.app.weather_lon_var.set(weather_config.get('longitude', ''))
        if hasattr(self.app, 'weather_units_var'):
            self.app.weather_units_var.set(weather_config.get('units', 'metric'))
        if hasattr(self.app, 'weather_status_var'):
            if weather_config.get('enabled'):
                # Show coords if available, otherwise location
                lat = weather_config.get('latitude', '')
                lon = weather_config.get('longitude', '')
                if lat and lon:
                    self.app.weather_status_var.set(f"✓ Configured: ({lat}, {lon})")
                else:
                    self.app.weather_status_var.set(f"✓ Configured: {weather_config.get('location', '')}")
            else:
                self.app.weather_status_var.set("Not configured")
        
        # Load output mode settings
        output_config = self.app.config.get('output', {})
        self.app.output_mode_var.set(output_config.get('mode', 'file'))
        self.app.webserver_host_var.set(output_config.get('webserver_host', '127.0.0.1'))
        self.app.webserver_port_var.set(output_config.get('webserver_port', 8080))
        self.app.webserver_path_var.set(output_config.get('webserver_path', '/latest'))
        self.app.rtsp_host_var.set(output_config.get('rtsp_host', '127.0.0.1'))
        self.app.rtsp_port_var.set(output_config.get('rtsp_port', 8554))
        self.app.rtsp_stream_name_var.set(output_config.get('rtsp_stream_name', 'asiwatchdog'))
        self.app.rtsp_fps_var.set(output_config.get('rtsp_fps', 1.0))
        
        # Update output mode UI state
        self.app.on_output_mode_change()
        
        # Start periodic Discord scheduler
        self.app.discord_periodic_job = None
        self.app.output_manager.schedule_discord_periodic()
        
        # Send startup message if enabled
        if discord_config.get('enabled') and discord_config.get('post_startup_shutdown'):
            self.app.root.after(2000, self.app.discord_alerts.send_startup_message)  # Delay 2s to let UI settle
        
        self.is_loading_config = False  # Config loading complete
    
    # ===== CONFIGURATION SAVING =====
    
    def save_config(self):
        """Save current configuration"""
        # Don't save during initial config load
        if self.is_loading_config:
            return
        
        self.app.config.set('capture_mode', self.app.capture_mode_var.get())
        self.app.config.set('watch_directory', self.app.watch_dir_var.get())
        self.app.config.set('watch_recursive', self.app.watch_recursive_var.get())
        self.app.config.set('output_directory', self.app.output_dir_var.get())
        self.app.config.set('filename_pattern', self.app.filename_pattern_var.get())
        self.app.config.set('output_format', self.app.output_format_var.get())
        self.app.config.set('jpg_quality', self.app.jpg_quality_var.get())
        self.app.config.set('resize_percent', self.app.resize_percent_var.get())
        self.app.config.set('auto_brightness', self.app.auto_brightness_var.get())
        self.app.config.set('brightness_factor', self.app.brightness_var.get())
        self.app.config.set('saturation_factor', self.app.saturation_var.get())
        
        # Auto Stretch (MTF) settings
        self.app.config.set('auto_stretch', {
            'enabled': self.app.auto_stretch_var.get(),
            'target_median': self.app.stretch_median_var.get(),
            'linked_stretch': self.app.stretch_linked_var.get(),
            'preserve_blacks': self.app.stretch_preserve_blacks_var.get(),
            'shadow_aggressiveness': self.app.stretch_shadow_var.get(),
            'saturation_boost': self.app.stretch_saturation_var.get()
        })
        
        self.app.config.set('timestamp_corner', self.app.timestamp_corner_var.get())
        self.app.config.set('cleanup_enabled', self.app.cleanup_enabled_var.get())
        self.app.config.set('cleanup_max_size_gb', self.app.cleanup_max_size_var.get())
        
        # ZWO settings - save exposure in milliseconds for consistency
        self.app.config.set('zwo_sdk_path', self.app.sdk_path_var.get())
        
        # Convert exposure to ms for storage
        exposure_value = self.app.exposure_var.get()
        if self.app.exposure_unit_var.get() == 's':
            exposure_ms = exposure_value * 1000.0
        else:
            exposure_ms = exposure_value
        self.app.config.set('zwo_exposure_ms', exposure_ms)
        
        self.app.config.set('zwo_gain', self.app.gain_var.get())
        self.app.config.set('zwo_wb_r', self.app.wb_r_var.get())
        self.app.config.set('zwo_wb_b', self.app.wb_b_var.get())
        
        # Save white balance config structure (replaces old zwo_auto_wb)
        self.app.config.set('white_balance', {
            'mode': self.app.wb_mode_var.get(),
            'manual_red_gain': 1.0,  # Not used in current UI, but kept for future
            'manual_blue_gain': 1.0,
            'gray_world_low_pct': self.app.wb_gw_low_var.get(),
            'gray_world_high_pct': self.app.wb_gw_high_var.get()
        })
        
        self.app.config.set('zwo_offset', self.app.offset_var.get())
        self.app.config.set('zwo_bayer_pattern', self.app.bayer_pattern_var.get())
        flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
        self.app.config.set('zwo_flip', flip_map.get(self.app.flip_var.get(), 0))
        self.app.config.set('zwo_interval', self.app.interval_var.get())
        self.app.config.set('zwo_auto_exposure', self.app.auto_exposure_var.get())
        
        # Save scheduled capture settings
        self.app.config.set('scheduled_capture_enabled', self.app.scheduled_capture_var.get())
        self.app.config.set('scheduled_start_time', self.app.schedule_start_var.get())
        self.app.config.set('scheduled_end_time', self.app.schedule_end_var.get())
        
        # Max exposure is now in seconds in UI
        max_exp_value = self.app.max_exposure_var.get()
        self.app.config.set('zwo_max_exposure_ms', max_exp_value * 1000.0)
        
        # Save target brightness
        self.app.config.set('zwo_target_brightness', self.app.target_brightness_var.get())
        
        # Save weather settings
        api_key = self.app.weather_api_key_var.get() if hasattr(self.app, 'weather_api_key_var') else ''
        location = self.app.weather_location_var.get() if hasattr(self.app, 'weather_location_var') else ''
        latitude = self.app.weather_lat_var.get() if hasattr(self.app, 'weather_lat_var') else ''
        longitude = self.app.weather_lon_var.get() if hasattr(self.app, 'weather_lon_var') else ''
        
        # Validate coordinates if provided
        lat_valid, lon_valid = False, False
        if latitude:
            try:
                lat_float = float(latitude)
                lat_valid = -90 <= lat_float <= 90
            except ValueError:
                lat_valid = False
        if longitude:
            try:
                lon_float = float(longitude)
                lon_valid = -180 <= lon_float <= 180
            except ValueError:
                lon_valid = False
        
        # Enabled if API key AND (valid coords OR location)
        has_valid_coords = lat_valid and lon_valid
        is_enabled = bool(api_key and (has_valid_coords or location))
        
        self.app.config.set('weather', {
            'enabled': is_enabled,
            'api_key': api_key,
            'location': location,
            'latitude': latitude if lat_valid else '',
            'longitude': longitude if lon_valid else '',
            'units': self.app.weather_units_var.get() if hasattr(self.app, 'weather_units_var') else 'metric',
            'cache_duration': 600
        })
        
        # Save Discord settings
        self.app.config.set('discord', {
            'enabled': self.app.discord_enabled_var.get(),
            'webhook_url': self.app.discord_webhook_var.get(),
            'embed_color_hex': self.app.discord_color_var.get(),
            'post_errors': self.app.discord_post_errors_var.get(),
            'post_startup_shutdown': self.app.discord_post_lifecycle_var.get(),
            'periodic_enabled': self.app.discord_periodic_enabled_var.get(),
            'periodic_interval_minutes': self.app.discord_interval_var.get(),
            'include_latest_image': self.app.discord_include_image_var.get(),
            'username_override': self.app.discord_username_var.get(),
            'avatar_url': self.app.discord_avatar_var.get()
        })
        
        # Save output mode settings
        self.app.config.set('output', {
            'mode': self.app.output_mode_var.get(),
            'webserver_enabled': self.app.output_mode_var.get() == 'webserver',
            'webserver_host': self.app.webserver_host_var.get(),
            'webserver_port': self.app.webserver_port_var.get(),
            'webserver_path': self.app.webserver_path_var.get(),
            'webserver_status_path': self.app.config.get('output', {}).get('webserver_status_path', '/status'),
            'rtsp_enabled': self.app.output_mode_var.get() == 'rtsp',
            'rtsp_host': self.app.rtsp_host_var.get(),
            'rtsp_port': self.app.rtsp_port_var.get(),
            'rtsp_stream_name': self.app.rtsp_stream_name_var.get(),
            'rtsp_fps': self.app.rtsp_fps_var.get()
        })
        
        # Debug: Verify it's in self.config.data before saving
        app_logger.info(f"Before save - webhook in config.data: {self.app.config.data.get('discord', {}).get('webhook_url', '')[:50]}...")
        
        self.app.config.save()
        app_logger.info("Configuration saved")
    
    # ===== SETTINGS APPLICATION =====
    
    def apply_settings(self):
        """Apply all settings"""
        self.save_config()
        
        # Reinitialize weather service with new settings
        self.app._init_weather_service()
        
        # Update running camera's schedule settings if active
        if hasattr(self.app.camera_controller, 'zwo_camera') and self.app.camera_controller.zwo_camera:
            self.app.camera_controller.zwo_camera.scheduled_capture_enabled = self.app.scheduled_capture_var.get()
            self.app.camera_controller.zwo_camera.scheduled_start_time = self.app.schedule_start_var.get()
            self.app.camera_controller.zwo_camera.scheduled_end_time = self.app.schedule_end_var.get()
            app_logger.info(f"Updated camera scheduled capture settings: enabled={self.app.scheduled_capture_var.get()}, window={self.app.schedule_start_var.get()}-{self.app.schedule_end_var.get()}")
        
        # Apply output mode changes (start/stop servers as needed)
        self.app.output_manager.apply_output_mode()
        messagebox.showinfo("Success", "Settings applied and saved")
