from PySide6.QtCore import QTimer

from services.logger import app_logger


class _MainWindowSettingsMixin:

    # =========================================================================
    # CAPTURE CONTROL API TOKEN
    # =========================================================================

    def ensure_control_token(self) -> str:
        """Mint the capture-control token if the API is enabled, and return it.

        Owned by the window rather than the panel: panels stay layout-only, and
        pushing the token to a live server is app state, not presentation.
        Returns "" when the control API is disabled — which is what keeps the
        control routes failing closed.
        """
        from services import api_auth
        token = api_auth.resolve_control_token(self.config)
        self._apply_control_token(token)
        return token

    def regenerate_control_token(self) -> str:
        """Replace the control token, invalidating the previous one."""
        from services import api_auth
        output = dict(self.config.get('output', {}) or {})
        output['api_token'] = api_auth.generate_token()
        self.config.set('output', output)
        self.config.save()
        return self.ensure_control_token()

    def _apply_control_token(self, token):
        """Push a token change to an already-running server.

        _ensure_output_servers_started() only reconciles the *enabled* flag, so
        without this a toggle or a regenerate would not take effect until the
        next restart — the classic "I changed it and nothing happened" bug.
        """
        if getattr(self, 'web_server', None) is not None:
            try:
                self.web_server.set_control_token(token)
            except Exception as e:
                app_logger.error(f"Could not apply control token to web server: {e}")

    # =========================================================================
    # SETTINGS
    # =========================================================================

    def _on_settings_changed(self):
        if self.is_loading_config:
            return
        self.save_config()

        self._init_weather_service(from_settings_save=True)

        self._update_service_status()

        # W8: apply a runtime webserver_enabled toggle live (reconciler is idempotent).
        # Reconcile while capturing, OR whenever a server is already up so an idle
        # disable actually stops it (the server outlives stop_capture by design).
        if self.is_capturing or self.web_server is not None:
            self._ensure_output_servers_started()

        self._update_start_button()

        # Live update camera settings if capturing (e.g., target brightness, auto-exposure)
        # Debounced to avoid spamming SDK calls during slider drags
        if self.is_capturing and self.camera_controller:
            if not hasattr(self, '_settings_update_timer'):
                self._settings_update_timer = QTimer(self)
                self._settings_update_timer.setSingleShot(True)
                self._settings_update_timer.timeout.connect(
                    self.camera_controller.update_settings
                )
            self._settings_update_timer.start(300)

        self.config_changed.emit()

    def _on_allsky_panel_changed(self, cfg: dict) -> None:
        if cfg.get('_action') == 'calibrate':
            self.allsky_controller.start_calibration()
            return
        if cfg.get('_action') == 'guided_calibrate':
            self._open_guided_calibration()
            return
        if cfg.get('_action') == 'reset_calibration':
            self.allsky_controller.reset_calibration()
            return
        # Preserve calibration_file from existing config
        existing = self.config.get('allsky_overlay', {})
        cfg['calibration_file'] = existing.get('calibration_file', '')
        self.config.set('allsky_overlay', cfg)
        self.save_config()

    def _open_guided_calibration(self) -> None:
        """Prepare data and open the guided-calibration dialog."""
        prep = self.allsky_controller.prepare_guided_calibration()
        if not prep:
            return  # controller already emitted a status explaining why
        try:
            from ui.panels.allsky_guided_dialog import GuidedCalibrationDialog
            dlg = GuidedCalibrationDialog(prep, parent=self)
            if dlg.exec() and dlg.anchors:
                self.allsky_controller.start_guided_calibration(dlg.anchors, prep)
        except Exception as e:
            app_logger.error(f"Guided calibration dialog failed: {e}")

    def _on_allsky_settings_changed(self) -> None:
        try:
            self.allsky_panel.load_from_config(self.config.get('allsky_overlay', {}))
        except Exception as e:
            app_logger.error(f"_on_allsky_settings_changed crashed: {e}")

    def save_config(self):
        if self.is_loading_config:
            return
        try:
            self.config.save()
            app_logger.debug("Configuration saved")
        except Exception as e:
            app_logger.error(f"Failed to save config: {e}")

    def load_config(self):
        self.is_loading_config = True
        try:
            self.capture_panel.load_from_config(self.config)
            self.output_panel.load_from_config(self.config)
            self.processing_panel.load_from_config(self.config)
            self.overlay_panel.load_from_config(self.config)
            self.timelapse_panel.load_from_config(self.config)
            self.allsky_panel.load_from_config(self.config.get('allsky_overlay', {}))
            self.meteor_panel.load_from_config(self.config.get('meteor', {}))
            self.allsky_controller.load_from_config()
            self.settings_panel.load_from_config(self.config)
            self.logs_panel.load_from_config(self.config)

            output_dir = self.config.get('output_directory', '')
            self.live_panel.set_output_directory(output_dir)

            self._update_service_status()

            self._init_weather_service()

            app_logger.debug("Configuration loaded")
        except Exception as e:
            app_logger.error(f"Failed to load config: {e}")
        finally:
            self.is_loading_config = False
            self._update_start_button()

    def _init_weather_service(self, from_settings_save=False):
        try:
            from services.weather import WeatherService

            weather_config = self.config.get('weather', {})
            api_key = weather_config.get('api_key', '')
            location = weather_config.get('location', '')
            latitude = weather_config.get('latitude', '')
            longitude = weather_config.get('longitude', '')
            units = weather_config.get('units', 'metric')

            has_coords = bool(latitude and longitude)
            has_location = bool(location)

            if api_key and (has_coords or has_location):
                self.weather_service = WeatherService(
                    api_key, location, units,
                    latitude=latitude if latitude else None,
                    longitude=longitude if longitude else None
                )
                loc_info = f"({latitude}, {longitude})" if has_coords else location
                app_logger.info(f"Weather service initialized: {loc_info}, {units} units")
                if from_settings_save:
                    from services.posthog_service import capture_event
                    capture_event('weather_configured', {'units': units})
            else:
                self.weather_service = None
                app_logger.debug("Weather service not configured (missing API key or location/coordinates)")
        except Exception as e:
            app_logger.error(f"Failed to initialize weather service: {e}")
            self.weather_service = None

    def _update_service_status(self):
        output_config = self.config.get('output', {})
        web_enabled = output_config.get('webserver_enabled', False)
        web_running = self.web_server is not None and self.web_server.running
        self.app_bar.set_web_status(web_enabled, web_running)

        discord_config = self.config.get('discord', {})
        discord_enabled = discord_config.get('enabled', False)
        self.app_bar.set_discord_status(discord_enabled)
