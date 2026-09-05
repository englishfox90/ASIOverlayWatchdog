import io
import os
import queue
import random
import threading
import time
import traceback
from datetime import datetime, timezone

from PySide6.QtCore import QTimer

from services import api_auth
from services.camera import frame_builder
from services.logger import app_logger
from services.notifications import ERROR, LIFECYCLE, PERIODIC_IMAGE, NotificationEvent
from services.web_output import WebOutputServer
from ui.controllers.capture_command_bridge import CaptureCommandBridge


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

    def _on_test_hermes(self):
        hermes_config = self.config.get('hermes', {})
        if not hermes_config.get('url', ''):
            self.output_panel.set_hermes_test_result(False, "Webhook URL required")
            return

        try:
            ok, status = self.notifier.test('hermes')
            self.output_panel.set_hermes_test_result(ok, status)
            if ok:
                app_logger.info("Hermes test message sent successfully")
            else:
                app_logger.warning(f"Hermes test failed: {status}")
        except Exception as e:
            app_logger.error(f"Hermes test error: {e}")
            self.output_panel.set_hermes_test_result(False, str(e)[:50])

    def _send_discord_startup(self):
        # startup_enabled has no backend-side equivalent (it isn't one of the
        # per-event flags DiscordBackend/HermesBackend check) — it's a
        # call-site-level "don't even emit this" switch, so it stays here.
        discord_config = self.config.get('discord', {})
        if not discord_config.get('startup_enabled', True):
            return

        mode = self.config.get('capture_mode', 'camera')
        mode_text = "ZWO Camera Capture" if mode == 'camera' else "Directory Watch"
        output_path = self.config.get('output_directory', 'Not configured')
        self.notifier.notify(NotificationEvent(
            type=LIFECYCLE,
            title=f"{self.config.get('app_name', 'PFR Sentinel')} Started",
            body=f"Mode: {mode_text}\nOutput Path: {output_path}",
            data={'phase': 'startup', 'mode': mode, 'output_path': output_path},
        ))

    def _send_discord_error(self, error_msg: str):
        self.notifier.notify(NotificationEvent(type=ERROR, body=error_msg, level='error'))

    def _send_discord_shutdown(self):
        self.notifier.notify(NotificationEvent(
            type=LIFECYCLE,
            title=f"{self.config.get('app_name', 'PFR Sentinel')} Stopped",
            body="Application has been closed.",
            data={
                'phase': 'shutdown',
                'mode': self.config.get('capture_mode', 'camera'),
                'output_path': self.config.get('output_directory', ''),
            },
        ))

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

        # Cache what REBUILDS the frame (the ~25 MB of SDK Bayer bytes) rather
        # than the decoded frame itself — the old deep copies of the PIL image
        # and the uint16 array kept ~125 MB resident forever. The queued task is
        # then the only holder of this frame's arrays, so they free the moment
        # processing finishes, and nothing can overwrite them mid-stretch.
        self._cached_raw_time = datetime.now(timezone.utc)
        if frame_builder.is_rebuildable(metadata):
            self._cached_raw_image = None
            self._cached_raw_metadata = frame_builder.cache_metadata(metadata)
            # RAW_BAYER must not reach the processor: it only pops the two
            # decoded arrays, so the bytes would ride on into preview_metadata.
            metadata = frame_builder.strip_cache_keys(metadata)
        else:
            self._cached_raw_image = pil_image.copy()
            self._cached_raw_metadata = metadata.copy()

        auto_stretch_enabled = self.config.get('auto_stretch', {}).get('enabled', False)
        if auto_stretch_enabled:
            self.app_bar.set_status('stretching')
        else:
            self.app_bar.set_status('processing')

        self.image_processor.process_and_save(pil_image, metadata)

        self.image_captured.emit(pil_image)

    def cached_raw_frame(self):
        """(pil_image, metadata) of the last clean frame, or (None, None).

        Camera mode caches only the raw Bayer bytes and rebuilds on demand;
        watch mode caches the clean (no all-sky) output frame directly.
        """
        if frame_builder.is_rebuildable(self._cached_raw_metadata):
            return frame_builder.rebuild_frame(self._cached_raw_metadata)
        if self._cached_raw_image is None:
            return None, None
        return self._cached_raw_image, self._cached_raw_metadata

    def has_cached_frame(self) -> bool:
        """True if a frame exists to reprocess/calibrate, without rebuilding it."""
        return (self._cached_raw_image is not None
                or frame_builder.is_rebuildable(self._cached_raw_metadata))

    def reprocess_last_frame(self):
        """Reprocess the cached raw frame with current settings.

        Called when image-processing or overlay settings change so the user
        sees the effect immediately instead of waiting for the next exposure.
        Debounced to 500ms so slider drags don't queue dozens of reprocesses.
        """
        if not self.has_cached_frame():
            return

        # Debounce: restart the timer on every call, fire only once after 500ms idle
        if not hasattr(self, '_reprocess_timer'):
            self._reprocess_timer = QTimer(self)
            self._reprocess_timer.setSingleShot(True)
            self._reprocess_timer.timeout.connect(self._do_reprocess)
        self._reprocess_timer.start(500)

    def _do_reprocess(self):
        if not self.has_cached_frame():
            return

        app_logger.debug("Reprocessing last frame with updated settings")

        auto_stretch_enabled = self.config.get('auto_stretch', {}).get('enabled', False)
        if auto_stretch_enabled:
            self.app_bar.set_status('stretching')
        else:
            self.app_bar.set_status('processing')

        # Camera mode rebuilds the 12.6 MP frame from the cached Bayer bytes
        # (~0.9 s) — on the processor's worker thread, never here.
        if frame_builder.is_rebuildable(self._cached_raw_metadata):
            cached = self._cached_raw_metadata
            self.image_processor.process_and_save(
                None, cached,
                frame_factory=lambda: frame_builder.rebuild_frame(cached),
            )
        else:
            self.image_processor.process_and_save(
                self._cached_raw_image, self._cached_raw_metadata
            )

    def _on_image_processed(self, preview_image, output_image, metadata: dict, output_path: str,
                             dispatch_image=None):
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
            # output_image is always clean — the watch-mode cache above and any
            # future consumer of the "clean" frame can rely on that.
            # dispatch_image feeds the web server + Image Library; it is
            # output_image unless allsky_overlay.burn_into_output.web opted in
            # (falls back to output_image for callers that don't supply it).
            if dispatch_image is None:
                dispatch_image = output_image
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
            # frame. dispatch_image is never mutated after the processor emits it,
            # so the worker can own it without a defensive copy on this thread.
            self._dispatch_outputs(output_path, dispatch_image, metadata, has_outputs)

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
        self._set_capture_error(error_msg)
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

        control_path = output_config.get('webserver_control_path', '/capture')

        self.web_server = WebOutputServer(
            host, port, image_path, status_path, docs_path,
            library_path=library_path, image_library=self.image_library,
            control_path=control_path,
            control_token=api_auth.resolve_control_token(self.config),
            control_allowed_hosts=api_auth.allowed_control_hosts(self.config),
        )
        # Capture control must never run on the HTTP thread — the bridge queues
        # it onto the GUI thread. See ui/controllers/capture_command_bridge.py.
        self.web_server.register_capture_command_handler(self._capture_command_bridge())
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

    def _capture_command_bridge(self):
        """The GUI-thread marshaller the HTTP control routes hand commands to.

        Built once and kept, so repeated web-server restarts reuse the same
        QObject rather than accumulating children on the window.
        """
        if getattr(self, '_command_bridge', None) is None:
            self._command_bridge = CaptureCommandBridge(self)
        return self._command_bridge

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

    def _set_capture_error(self, message):
        """Record a capture error, and when it happened.

        The timestamp is what lets the control API tell a NEW failure from the
        same fault reported again. Comparing the message cannot: a repeated
        fault reads identically, which is exactly the retry-a-disconnected-
        camera case.
        """
        self._last_capture_error = message
        self._last_capture_error_epoch = time.time() if message else None

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
                last_error=self._last_capture_error,
                last_error_epoch=self._last_capture_error_epoch, recovery=recovery,
            )

        if mode_cfg == 'watch':
            running = bool(self.watch_controller and getattr(self.watch_controller, 'is_watching', False))
            state = "capturing" if running else "stopped"
            return api_status.build_capture_snapshot(
                mode="watch", enabled=True, running=running, state=state,
                last_error=self._last_capture_error,
                last_error_epoch=self._last_capture_error_epoch, recovery=recovery,
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
            last_error=self._last_capture_error,
            last_error_epoch=self._last_capture_error_epoch, recovery=recovery,
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

    def _dispatch_outputs(self, output_path, dispatch_image, metadata, has_outputs):
        """Queue the library archive + server push for the background worker.

        Non-blocking. Drops the oldest pending job if the worker has fallen
        behind, so a slow encode never stalls the capture/GUI thread.
        """
        self._put_dispatch_job((output_path, dispatch_image, metadata, has_outputs))

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
            output_path, dispatch_image, metadata, has_outputs = job
            try:
                if self.image_library:
                    self.image_library.enqueue(dispatch_image, metadata)
                if has_outputs:
                    self._push_to_output_servers(output_path, dispatch_image, metadata)
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
            hermes_config = self.config.get('hermes', {})
            discord_periodic = discord_config.get('enabled', False) and discord_config.get('periodic_enabled', False)
            hermes_periodic = hermes_config.get('enabled', False) and hermes_config.get('periodic_enabled', False)

            if discord_periodic or hermes_periodic:
                should_post = False

                if not hasattr(self, 'first_image_posted_to_discord'):
                    self.first_image_posted_to_discord = False
                if not hasattr(self, '_discord_jitter_seconds'):
                    self._discord_jitter_seconds = 0

                if not self.first_image_posted_to_discord:
                    should_post = True
                    app_logger.info(f"Posting first periodic image update: {image_path}")
                else:
                    # Check interval with jitter to reduce network load. Hermes has
                    # no interval field of its own — one shared cadence drives both
                    # backends, sourced from Discord's setting.
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
                                f"Posting periodic update "
                                f"(interval: {interval_minutes}m, jitter: -{self._discord_jitter_seconds}s, "
                                f"actual: {actual_min:.1f}m)"
                            )

                if should_post:
                    # Delivery is async (each backend owns its own queue), so
                    # update scheduling state optimistically here rather than
                    # waiting for a per-backend success callback.
                    self.last_discord_post_time = datetime.now()
                    self.first_image_posted_to_discord = True
                    self._discord_jitter_seconds = random.randint(0, 300)
                    self._send_discord_periodic_update(image_path)

        except Exception as e:
            app_logger.error(f"Error scheduling periodic update: {e}")

    def _build_periodic_body(self) -> str:
        """Token-formatted description shared by the periodic-image event."""
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

        return (
            f"**Periodic Status Update**\n\n"
            f"**Mode:** {mode}\n"
            f"**Images Processed:** {count}{camera_info}\n"
            f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _send_discord_periodic_update(self, image_path: str):
        metadata = getattr(self, 'preview_metadata', None) or {}
        title = f"{self.config.get('app_name', 'PFR Sentinel')} - Status Update"

        self.notifier.notify(NotificationEvent(
            type=PERIODIC_IMAGE,
            title=title,
            body=self._build_periodic_body(),
            image_path=image_path,
            data={
                'exposure': metadata.get('EXPOSURE', 'N/A'),
                'gain': metadata.get('GAIN', 'N/A'),
                'temp': metadata.get('TEMP', 'N/A'),
                'resolution': metadata.get('RES', 'N/A'),
            },
        ))
