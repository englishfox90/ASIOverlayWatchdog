import io
import os
import queue
import random
import threading
import traceback
from datetime import datetime, timezone

from PySide6.QtCore import QTimer

from services.logger import app_logger
from services.web_output import WebOutputServer


class _MainWindowOutputMixin:

    # =========================================================================
    # DISCORD HELPERS
    # =========================================================================

    def _on_test_discord(self):
        discord_config = self.config.get('discord', {})
        webhook_url = discord_config.get('webhook_url', '')

        if not webhook_url:
            self.output_panel.set_discord_test_result(False, "Webhook URL required")
            return

        try:
            from services.discord_alerts import DiscordAlerts

            test_config = {
                'discord': {
                    'enabled': True,
                    'webhook_url': webhook_url,
                    'embed_color_hex': discord_config.get('embed_color_hex', '#0EA5E9'),
                    'username_override': discord_config.get('username_override', ''),
                    'avatar_url': discord_config.get('avatar_url', ''),
                    'include_latest_image': False
                }
            }
            alerts = DiscordAlerts(test_config)

            success = alerts.send_discord_message(
                title="🧪 Webhook Test",
                description="PFR Sentinel webhook test successful!",
                level="success"
            )

            if success:
                self.output_panel.set_discord_test_result(True, "Test message sent!")
                app_logger.info("Discord test message sent successfully")
            else:
                self.output_panel.set_discord_test_result(False, alerts.last_send_status)
                app_logger.warning(f"Discord test failed: {alerts.last_send_status}")

        except Exception as e:
            app_logger.error(f"Discord test error: {e}")
            self.output_panel.set_discord_test_result(False, str(e)[:50])

    def _send_discord_startup(self):
        discord_config = self.config.get('discord', {})
        if not discord_config.get('enabled', False):
            return
        if not discord_config.get('startup_enabled', True):
            return

        def _send():
            try:
                from services.discord_alerts import DiscordAlerts
                alerts = DiscordAlerts(self.config)
                if alerts.is_enabled():
                    alerts.send_startup_message()
                    app_logger.info("Discord startup notification sent")
            except Exception as e:
                app_logger.error(f"Failed to send Discord startup notification: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def _send_discord_error(self, error_msg: str):
        discord_config = self.config.get('discord', {})
        if not discord_config.get('enabled', False):
            return
        if not discord_config.get('post_errors', False):
            return

        def _send():
            try:
                from services.discord_alerts import DiscordAlerts
                alerts = DiscordAlerts(self.config)
                if alerts.is_enabled():
                    alerts.send_error_message(error_msg)
                    app_logger.debug("Discord error notification sent")
            except Exception as e:
                app_logger.error(f"Failed to send Discord error notification: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def _send_discord_shutdown(self):
        discord_config = self.config.get('discord', {})
        if not discord_config.get('enabled', False):
            return
        if not discord_config.get('post_startup_shutdown', False):
            return

        def _send():
            try:
                from services.discord_alerts import DiscordAlerts
                alerts = DiscordAlerts(self.config)
                if alerts.is_enabled():
                    alerts.send_shutdown_message()
                    app_logger.info("Discord shutdown notification sent")
            except Exception as e:
                app_logger.error(f"Failed to send Discord shutdown notification: {e}")

        threading.Thread(target=_send, daemon=True).start()

    # =========================================================================
    # IMAGE HANDLING
    # =========================================================================

    def on_image_captured(self, pil_image, metadata: dict):
        """Handle new captured image from camera or watch mode

        This receives RAW images and sends them to the image processor
        for auto-stretch, brightness, overlays, and saving.
        """
        self.image_count += 1
        self.app_bar.update_image_count(self.image_count)
        # A fresh frame clears any prior capture error for /status health.
        self._last_capture_error = None

        # Cache raw frame for reprocessing on settings changes.
        # Deep-copy the large numpy arrays so the camera's ping-pong buffer
        # is free for the next frame as soon as this method returns.
        # Queue tasks then share this one stable copy via shallow metadata.copy().
        self._cached_raw_image = pil_image.copy()
        self._cached_raw_time = datetime.now(timezone.utc)
        meta_copy = metadata.copy()
        for _k in ('RAW_RGB_16BIT', 'RAW_RGB_NO_WB'):
            if meta_copy.get(_k) is not None:
                meta_copy[_k] = meta_copy[_k].copy()
        self._cached_raw_metadata = meta_copy

        auto_stretch_enabled = self.config.get('auto_stretch', {}).get('enabled', False)
        if auto_stretch_enabled:
            self.app_bar.set_status('stretching')
        else:
            self.app_bar.set_status('processing')

        self.image_processor.process_and_save(pil_image, metadata)

        self.image_captured.emit(pil_image)

    def reprocess_last_frame(self):
        """Reprocess the cached raw frame with current settings.

        Called when image-processing or overlay settings change so the user
        sees the effect immediately instead of waiting for the next exposure.
        Debounced to 500ms so slider drags don't queue dozens of reprocesses.
        """
        if self._cached_raw_image is None:
            return

        # Debounce: restart the timer on every call, fire only once after 500ms idle
        if not hasattr(self, '_reprocess_timer'):
            self._reprocess_timer = QTimer(self)
            self._reprocess_timer.setSingleShot(True)
            self._reprocess_timer.timeout.connect(self._do_reprocess)
        self._reprocess_timer.start(500)

    def _do_reprocess(self):
        if self._cached_raw_image is None:
            return

        app_logger.debug("Reprocessing last frame with updated settings")

        auto_stretch_enabled = self.config.get('auto_stretch', {}).get('enabled', False)
        if auto_stretch_enabled:
            self.app_bar.set_status('stretching')
        else:
            self.app_bar.set_status('processing')

        self.image_processor.process_and_save(
            self._cached_raw_image, self._cached_raw_metadata
        )

    def _on_image_processed(self, preview_image, output_image, metadata: dict, output_path: str):
        try:
            self.last_processed_image = output_path
            self.preview_metadata = metadata

            # Watch mode never passes through on_image_captured, so cache the
            # clean (no all-sky) output frame here for manual "Calibrate Now".
            # Camera mode already cached a superior RAW pre-overlay frame in
            # on_image_captured — don't clobber it with the overlaid output.
            if self.config.get('capture_mode', 'camera') == 'watch':
                self._cached_raw_image = output_image.copy()
                self._cached_raw_time = datetime.now(timezone.utc)
                self._cached_raw_metadata = metadata

            # preview_image may carry the all-sky overlay (GUI only).
            # output_image is always clean — sent to file sinks and servers.
            self.live_panel.update_preview(preview_image, metadata)
            self.status_strip.update_from_metadata(metadata)
            self.telemetry_bar.update_from_metadata(metadata)

            output_config = self.config.get('output', {})
            discord_config = self.config.get('discord', {})
            has_outputs = (
                output_config.get('webserver_enabled', False) or
                discord_config.get('enabled', False)
            )

            # Hand the heavy output work to a background thread. The library
            # archive (a full-res PIL copy), the web push (a full-res PNG encode
            # then decode + LANCZOS downsize), and Discord all used to run here,
            # synchronously, on the GUI thread — a multi-hundred-ms freeze every
            # frame. output_image is never mutated after the processor emits it,
            # so the worker can own it without a defensive copy on this thread.
            self._dispatch_outputs(output_path, output_image, metadata, has_outputs)

            if has_outputs:
                self.app_bar.set_status('sending')
                if self.is_capturing:
                    QTimer.singleShot(300, lambda: self.app_bar.set_status('waiting'))
                else:
                    QTimer.singleShot(300, lambda: self.app_bar.set_status(None))
            else:
                if self.is_capturing:
                    self.app_bar.set_status('waiting')
                else:
                    self.app_bar.set_status(None)

            app_logger.debug(f"Image processed: {os.path.basename(output_path)}")
        except Exception as e:
            app_logger.error(f"_on_image_processed crashed: {e}")
            app_logger.error(traceback.format_exc())

    def _on_preview_ready(self, preview_image, hist_data: dict):
        try:
            if hist_data:
                app_logger.debug(f"Histogram data received: r={len(hist_data.get('r', []))}, auto_exposure={hist_data.get('auto_exposure')}, target={hist_data.get('target_brightness')}")
                self.live_panel.histogram.update_from_data(hist_data)
            else:
                app_logger.warning("No histogram data received from processor")
        except Exception as e:
            app_logger.error(f"_on_preview_ready crashed: {e}")
            app_logger.error(traceback.format_exc())

    def _on_processing_error(self, error_msg: str):
        self.app_bar.set_status(None)
        self._last_capture_error = error_msg
        self.push_capture_status()
        app_logger.error(f"Image processing error: {error_msg}")

    def on_calibration_status(self, is_calibrating: bool):
        """Handle calibration status change from camera

        Args:
            is_calibrating: True when calibration starts, False when complete
        """
        if is_calibrating:
            self.app_bar.set_status('calibrating')
            app_logger.debug("Calibration started")
        else:
            self.app_bar.set_status('waiting')
            app_logger.debug("Calibration complete")

    # =========================================================================
    # OUTPUT SERVER MANAGEMENT
    # =========================================================================

    # Re-attempt cadence for a web server that failed to bind. At logon
    # autostart the configured bind address (a Tailscale/LAN IP) may not be up
    # on any interface yet, so the one-shot start fails; without a retry the
    # web output stays off for the whole session even though Discord — which
    # binds nothing — keeps working.
    _WEB_SERVER_RETRY_MS = 15000

    def _ensure_output_servers_started(self):
        """Reconcile the web server against config: idempotent, so it's safe to
        call on capture start AND on a runtime settings change. Starting when
        enabled and stopping when disabled is what makes the GUI toggle take
        effect live instead of only at the next app launch (W8)."""
        output_config = self.config.get('output', {})

        if output_config.get('webserver_enabled', False):
            if not self.web_server or not self.web_server.running:
                self._start_web_server()
        else:
            if self.web_server:
                self._stop_web_server()
            else:
                self._cancel_web_server_retry()

    def _start_web_server(self):
        output_config = self.config.get('output', {})

        host = output_config.get('webserver_host', '127.0.0.1')
        port = output_config.get('webserver_port', 8080)
        image_path = output_config.get('webserver_path', '/latest')
        status_path = output_config.get('webserver_status_path', '/status')
        docs_path = output_config.get('webserver_docs_path', '/docs')
        library_path = output_config.get('webserver_library_path', '/library')

        self.web_server = WebOutputServer(
            host, port, image_path, status_path, docs_path,
            library_path=library_path, image_library=self.image_library,
        )
        if self.web_server.start():
            url = self.web_server.get_url()
            status_url = self.web_server.get_status_url()
            app_logger.info(f"Web server started: {url}")
            app_logger.info(f"Status endpoint: {status_url}")
            self._notify(f"Web server started: {url}")
            self.app_bar.set_web_status(True, True)
            self._cancel_web_server_retry()
            self._start_capture_status_timer()
            self.push_capture_status()
        else:
            app_logger.error("Failed to start web server")
            self._notify("Web server failed to start", "error")
            self.web_server = None
            self.app_bar.set_web_status(True, False)
            self._schedule_web_server_retry()

    def _schedule_web_server_retry(self):
        """Queue another web-server start attempt. The bind may fail at logon
        autostart because the bind address (Tailscale/LAN IP) isn't up yet;
        keep retrying until it binds rather than giving up for the session."""
        if self._web_server_retry_timer is None:
            self._web_server_retry_timer = QTimer(self)
            self._web_server_retry_timer.setSingleShot(True)
            self._web_server_retry_timer.timeout.connect(self._retry_web_server)
        if not self._web_server_retry_timer.isActive():
            app_logger.info(
                f"Web server start failed — retrying in "
                f"{self._WEB_SERVER_RETRY_MS // 1000}s"
            )
            self._web_server_retry_timer.start(self._WEB_SERVER_RETRY_MS)

    def _cancel_web_server_retry(self):
        if self._web_server_retry_timer is not None and self._web_server_retry_timer.isActive():
            self._web_server_retry_timer.stop()

    def _retry_web_server(self):
        output_config = self.config.get('output', {})
        if not output_config.get('webserver_enabled', False):
            return
        if self.web_server and self.web_server.running:
            return
        app_logger.info("Retrying web server start...")
        self._start_web_server()

    def _stop_web_server(self):
        self._cancel_web_server_retry()
        self._stop_capture_status_timer()
        if self.web_server:
            try:
                self.web_server.stop()
                self.web_server = None
                app_logger.info("Web server stopped")
                self.app_bar.set_web_status(False, False)
            except Exception as e:
                app_logger.error(f"Error stopping web server: {e}")

    # =========================================================================
    # CAPTURE STATUS FEED (/status capture + health blocks)
    # =========================================================================

    def _start_capture_status_timer(self):
        """Periodically push a fresh capture snapshot so /status reflects live
        state (recovery, schedule window) even between frames."""
        if self._capture_status_timer is None:
            self._capture_status_timer = QTimer(self)
            self._capture_status_timer.timeout.connect(self.push_capture_status)
        if not self._capture_status_timer.isActive():
            self._capture_status_timer.start(3000)

    def _stop_capture_status_timer(self):
        if self._capture_status_timer is not None and self._capture_status_timer.isActive():
            self._capture_status_timer.stop()

    def push_capture_status(self):
        """Build and push the current capture snapshot to the web server.

        Safe to call from any capture state-change handler; no-ops when the web
        server isn't running.
        """
        if not self.web_server or not self.web_server.running:
            return
        try:
            self.web_server.update_capture_status(self._build_capture_status())
        except Exception as e:
            app_logger.error(f"Error pushing capture status: {e}")

    def _build_capture_status(self) -> dict:
        """Assemble the discrete capture snapshot for the status API.

        Reads only plain attributes / config (no widgets) so it is safe to run
        on the GUI thread and hand to the HTTP server thread. Time-relative
        fields (ages, next-frame countdown, health) are derived server-side in
        services/api_status.py.
        """
        from services import api_status

        cc = self.camera_controller
        mode_cfg = self.config.get('capture_mode', 'camera')
        recovery = cc.recovery_state() if cc else None
        recovery = recovery or {"in_progress": False, "attempts": 0, "unrecoverable": False}

        # "enabled" means capture is meant to be running — including while
        # auto-recovery is grinding (main is_capturing drops to False then).
        enabled = bool(
            self.is_capturing or recovery["in_progress"] or recovery["unrecoverable"]
        )
        if not enabled:
            return api_status.build_capture_snapshot(
                mode="idle", enabled=False, running=False, state="stopped",
                last_error=self._last_capture_error, recovery=recovery,
            )

        if mode_cfg == 'watch':
            running = bool(self.watch_controller and getattr(self.watch_controller, 'is_watching', False))
            state = "capturing" if running else "stopped"
            return api_status.build_capture_snapshot(
                mode="watch", enabled=True, running=running, state=state,
                last_error=self._last_capture_error, recovery=recovery,
            )

        # Camera mode
        zwo = cc.zwo_camera if cc else None
        running = bool(cc and cc.is_capturing)
        sched_mode = self.config.get('scheduled_capture_mode', 'always')
        in_window = True
        if zwo is not None and sched_mode != 'always':
            try:
                in_window = zwo.is_in_time_window()
            except Exception:
                in_window = True
        schedule = {
            "mode": sched_mode,
            "start_time": self.config.get('scheduled_start_time', '17:00'),
            "end_time": self.config.get('scheduled_end_time', '09:00'),
            "in_window": in_window,
            "window_interval_seconds": (
                self.config.get('scheduled_window_interval', 5.0)
                if sched_mode == 'variable' else None
            ),
        }
        interval = self.config.get('zwo_interval', 5.0)
        effective_interval = interval
        if zwo is not None:
            try:
                effective_interval = zwo.effective_capture_interval
            except Exception:
                effective_interval = interval

        if recovery["unrecoverable"]:
            state = "error"
        elif recovery["in_progress"]:
            state = "recovering"
        elif not running:
            state = "stopped"
        elif sched_mode == 'gated' and not in_window:
            state = "outside_window"
        else:
            state = "capturing"

        return api_status.build_capture_snapshot(
            mode="camera", enabled=True, running=running, state=state,
            interval_seconds=interval, effective_interval_seconds=effective_interval,
            schedule=schedule,
            last_capture_epoch=(cc.last_successful_frame_epoch() if cc else None),
            last_error=self._last_capture_error, recovery=recovery,
        )

    # =========================================================================
    # OUTPUT DISPATCH (off the GUI thread)
    # =========================================================================

    # Small bound — the processor emits one frame at a time, so the dispatcher
    # is normally idle; this is burst headroom for fast (daytime) cadence. If it
    # ever fills, the oldest pending frame is dropped (newest /latest wins).
    _OUTPUT_QUEUE_MAXSIZE = 4
    _OUTPUT_STOP = object()

    def _start_output_dispatcher(self):
        """Create the dispatch queue and start its worker. Called once at init."""
        self._output_dispatch_queue = queue.Queue(maxsize=self._OUTPUT_QUEUE_MAXSIZE)
        self._output_dispatch_thread = threading.Thread(
            target=self._output_dispatch_loop, name="OutputDispatch", daemon=True
        )
        self._output_dispatch_thread.start()

    def _dispatch_outputs(self, output_path, output_image, metadata, has_outputs):
        """Queue the library archive + server push for the background worker.

        Non-blocking. Drops the oldest pending job if the worker has fallen
        behind, so a slow encode never stalls the capture/GUI thread.
        """
        self._put_dispatch_job((output_path, output_image, metadata, has_outputs))

    def _put_dispatch_job(self, job):
        """Put a job on the dispatch queue, dropping the oldest if it is full."""
        try:
            self._output_dispatch_queue.put_nowait(job)
        except queue.Full:
            try:
                self._output_dispatch_queue.get_nowait()  # drop oldest
                self._output_dispatch_queue.put_nowait(job)
            except (queue.Empty, queue.Full):
                pass

    def _output_dispatch_loop(self):
        while True:
            job = self._output_dispatch_queue.get()
            if job is self._OUTPUT_STOP:
                break
            output_path, output_image, metadata, has_outputs = job
            try:
                if self.image_library:
                    self.image_library.enqueue(output_image, metadata)
                if has_outputs:
                    self._push_to_output_servers(output_path, output_image, metadata)
            except Exception as e:
                app_logger.error(f"Output dispatch failed: {e}")
                app_logger.error(traceback.format_exc())

    def _stop_output_dispatcher(self):
        """Stop the dispatch worker, letting an in-flight push finish."""
        thread = getattr(self, '_output_dispatch_thread', None)
        if not thread or not thread.is_alive():
            return
        self._put_dispatch_job(self._OUTPUT_STOP)  # drop-oldest guarantees it lands
        thread.join(timeout=5.0)

    def _push_to_output_servers(self, image_path: str, processed_img, metadata: dict = None):
        # metadata is the per-job metadata for THIS frame. Optional/back-compat:
        # external callers that omit it fall back to the last preview metadata.
        # Tagging /latest with the job's own metadata keeps /status and /latest
        # describing the same frame on bursts (W9).
        push_metadata = metadata if metadata is not None else getattr(self, 'preview_metadata', None)

        # Snapshot to a local: this runs on the OutputDispatch worker thread
        # while the GUI thread's _stop_web_server() can set self.web_server to
        # None at any point. Binding once here (mirrors web_output's
        # _serve_image) closes the check-then-use race between the "running"
        # check and update_image() below.
        web_server = self.web_server

        # Web and Discord are independent sinks — keep them in separate
        # try/except blocks so a failed web encode/push can't skip the Discord
        # post (and vice-versa) (W7).
        try:
            if web_server and web_server.running:
                img_bytes = io.BytesIO()

                output_config = self.config.get('output', {})
                output_format = output_config.get('output_format', 'PNG').upper()

                if output_format in ('JPG', 'JPEG'):
                    quality = output_config.get('jpg_quality', 85)
                    processed_img.save(img_bytes, format='JPEG', quality=quality, optimize=True)
                    content_type = 'image/jpeg'
                else:
                    processed_img.save(img_bytes, format='PNG', optimize=True)
                    content_type = 'image/png'

                web_server.update_image(
                    image_path,
                    img_bytes.getvalue(),
                    metadata=push_metadata,
                    content_type=content_type
                )
                app_logger.debug(f"Pushed image to web server ({content_type})")
        except Exception as e:
            app_logger.error(f"Error pushing image to web server: {e}")

        try:
            discord_config = self.config.get('discord', {})
            discord_enabled = discord_config.get('enabled', False)
            periodic_enabled = discord_config.get('periodic_enabled', False)

            if discord_enabled and periodic_enabled:
                should_post = False

                if not hasattr(self, 'first_image_posted_to_discord'):
                    self.first_image_posted_to_discord = False
                if not hasattr(self, '_discord_jitter_seconds'):
                    self._discord_jitter_seconds = 0

                if not self.first_image_posted_to_discord:
                    should_post = True
                    app_logger.info(f"Posting first image to Discord: {image_path}")
                else:
                    # Check interval with jitter to reduce network load
                    interval_minutes = max(30, discord_config.get('periodic_interval_minutes', 30))

                    if not hasattr(self, 'last_discord_post_time'):
                        self.last_discord_post_time = None

                    if self.last_discord_post_time is None:
                        should_post = True
                    else:
                        elapsed_seconds = (datetime.now() - self.last_discord_post_time).total_seconds()
                        target_seconds = (interval_minutes * 60) - self._discord_jitter_seconds
                        if elapsed_seconds >= target_seconds:
                            should_post = True
                            actual_min = elapsed_seconds / 60
                            app_logger.info(
                                f"Posting periodic Discord update "
                                f"(interval: {interval_minutes}m, jitter: -{self._discord_jitter_seconds}s, "
                                f"actual: {actual_min:.1f}m)"
                            )

                if should_post:
                    self._send_discord_periodic_update(image_path)

        except Exception as e:
            app_logger.error(f"Error scheduling Discord post: {e}")

    def _send_discord_periodic_update(self, image_path: str):
        from services.discord_alerts import DiscordAlerts
        alerts = DiscordAlerts(self.config)
        if not alerts.is_enabled():
            return

        # Collect UI state on the main thread before handing off to worker.
        mode = "ZWO Camera" if self.is_capturing else "Directory Watch"
        count = self.image_count

        camera_info = ""
        if self.is_capturing and self.camera_controller and self.camera_controller.zwo_camera:
            from services.discord_alerts import format_exposure_time
            exposure_seconds = self.camera_controller.zwo_camera.exposure_seconds
            gain = self.camera_controller.zwo_camera.gain
            camera_info = (
                f"\n**Exposure:** {format_exposure_time(exposure_seconds)}"
                f"\n**Gain:** {gain}"
            )

        message = (
            f"**Periodic Status Update**\n\n"
            f"**Mode:** {mode}\n"
            f"**Images Processed:** {count}{camera_info}\n"
            f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        discord_config = self.config.get('discord', {})
        include_image = discord_config.get('include_image', True)
        interval_minutes = discord_config.get('periodic_interval_minutes', 30)
        attach_image = image_path if include_image else None
        title = f"{self.config.get('app_name', 'PFRSentinel')} - Status Update"

        def _send():
            try:
                success = alerts.send_discord_message(
                    title=title, description=message, level="info", image_path=attach_image
                )
                if success:
                    self.last_discord_post_time = datetime.now()
                    self.first_image_posted_to_discord = True
                    self._discord_jitter_seconds = random.randint(0, 300)
                    app_logger.info("Discord update sent successfully")
                    app_logger.debug(f"Next Discord jitter: -{self._discord_jitter_seconds}s")
                    from services.posthog_service import capture_event
                    capture_event('discord_post_sent', {
                        'interval_minutes': interval_minutes,
                        'include_image': include_image,
                    })
                else:
                    app_logger.warning(f"Discord update failed: {alerts.last_send_status}")
            except Exception as e:
                app_logger.error(f"Discord periodic update failed: {e}")

        threading.Thread(target=_send, daemon=True).start()
