"""
Timelapse Controller
Owns the TimelapseWriter, wires it to the image processing pipeline,
and exposes status to the UI panel.
"""
import threading
import os
from PySide6.QtCore import QObject, Signal, QTimer
from services.timelapse_writer import TimelapseWriter
from services.timelapse_publishers import TimelapsePublishers, make_timelapse_metadata
from services.logger import app_logger


class TimelapseController(QObject):
    """
    Thin controller between the image processor and TimelapseWriter.

    Responsibilities:
    - Own the TimelapseWriter instance
    - Receive timelapse_ready signal from ImageProcessor
    - Pick clean or overlaid frame based on include_overlays config
    - Emit status updates for the panel to display
    """

    status_updated = Signal(dict)  # Emits get_status() dict periodically
    finalizing_started = Signal()          # Background ffmpeg finalization began
    finalizing_finished = Signal(str)      # Finalization done; arg is session path ('' if none)
    youtube_upload_status_changed = Signal(dict)

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._writer = TimelapseWriter()
        self._writer.on_session_finished = self._on_session_finished
        self._finalize_thread = None
        self._publishers = TimelapsePublishers(
            self._main_window.config,
            youtube_status_callback=self._emit_youtube_status,
        )

        # Status timer: update panel every 5 seconds while recording
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._emit_status)
        self._status_timer.start()

    # ------------------------------------------------------------------ #
    #  Frame handling (connected to image_processor.timelapse_ready)      #
    # ------------------------------------------------------------------ #

    def on_timelapse_ready(self, clean_image, overlaid_image):
        """
        Called by ImageProcessor.timelapse_ready signal on every processed frame.
        Picks the right image version and delegates to TimelapseWriter.
        """
        cfg = self._get_timelapse_config()
        if not cfg.get('enabled', False):
            return

        # Inject current roof state for roof-gated window mode
        if cfg.get('window_mode') == 'roof':
            ml_results = getattr(self._main_window, 'last_ml_results', None) or {}
            cfg['roof_open'] = ml_results.get('roof_status') == 'Open'

        self._writer.configure(cfg)
        frame = overlaid_image if cfg.get('include_overlays', False) else clean_image
        self._writer.add_frame(frame)

    # ------------------------------------------------------------------ #
    #  Lifecycle (called by main_window on capture start/stop)            #
    # ------------------------------------------------------------------ #

    def on_capture_stopped(self):
        """Stop the active session when capture is stopped.

        Finalizing flushes ffmpeg's final frames and joins the process. With
        fragmented MP4 the file is already playable, so this is usually quick —
        but a large buffered session on a slow disk can still take a few seconds,
        so we offload it to a background thread to keep the Stop button
        responsive; UI feedback comes via finalizing_started / finalizing_finished.
        """
        if not self._writer.get_status().get('recording'):
            # Fast path — no active session to finalize.
            self._writer.stop()
            self._emit_status()
            return

        session_path = self._writer.get_status().get('session_path') or ''
        app_logger.info("Timelapse: capture stopped, finalizing in background")
        self.finalizing_started.emit()
        self._finalize_thread = threading.Thread(
            target=self._finalize_async,
            args=(session_path,),
            daemon=True,
        )
        self._finalize_thread.start()

    def _finalize_async(self, session_path: str):
        try:
            self._writer.stop()
        except Exception as e:
            app_logger.error(f"Timelapse: finalization error: {e}")
        finally:
            self.finalizing_finished.emit(session_path)
            self._emit_status()

    def is_finalizing(self) -> bool:
        """True while a background finalization is still running."""
        return bool(self._finalize_thread and self._finalize_thread.is_alive())

    def shutdown(self):
        """Graceful shutdown — wait for any in-flight finalization.

        Called on app close. We must not kill ffmpeg mid-finalization or the
        mp4 will be truncated, so we block here (bounded) until it's done.
        """
        app_logger.debug("Timelapse: controller shutdown")
        thread = self._finalize_thread
        if thread and thread.is_alive():
            app_logger.info("Timelapse: waiting for finalization before exit…")
            thread.join(timeout=75)
            if thread.is_alive():
                app_logger.warning("Timelapse: finalization did not complete within 75s")
        else:
            self._writer.stop()
        if hasattr(self, '_publishers') and self._publishers:
            self._publishers.shutdown(timeout=10)

    # ------------------------------------------------------------------ #
    #  Status                                                              #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict:
        return self._writer.get_status()

    def _emit_status(self):
        self.status_updated.emit(self._writer.get_status())

    def _emit_youtube_status(self, status: dict):
        self.youtube_upload_status_changed.emit(status)

    def authenticate_youtube(self):
        """Start UI-triggered YouTube OAuth."""
        self._publishers.authenticate_youtube()

    def upload_latest_youtube(self):
        """Manually upload the newest completed timelapse video."""
        path = self._find_latest_completed_video()
        if not path:
            self._emit_youtube_status({
                'provider': 'youtube',
                'status': 'validation_failed',
                'message': 'No completed timelapse video was found.',
                'success': False,
            })
            return
        metadata = make_timelapse_metadata(path, frame_count=0, elapsed_seconds=0)
        self._publishers.enqueue_youtube_upload(metadata, manual=True)

    def _find_latest_completed_video(self) -> str:
        """Newest timelapse MP4 excluding the active recording session."""
        tl_cfg = self._get_timelapse_config()
        output_dir = tl_cfg.get('output_dir', '')
        if not output_dir:
            from services.utils_paths import get_app_data_dir
            output_dir = os.path.join(get_app_data_dir(), 'timelapse')
        if not output_dir or not os.path.isdir(output_dir):
            return ''

        status = self.get_status()
        active_path = ''
        if status.get('recording'):
            active_path = os.path.normcase(os.path.abspath(status.get('session_path') or ''))

        candidates = []
        for name in os.listdir(output_dir):
            if not name.lower().endswith('.mp4'):
                continue
            path = os.path.join(output_dir, name)
            if active_path and os.path.normcase(os.path.abspath(path)) == active_path:
                continue
            if os.path.isfile(path):
                candidates.append(path)
        if not candidates:
            return ''
        return max(candidates, key=lambda p: os.path.getmtime(p))

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_timelapse_config(self) -> dict:
        cfg = dict(self._main_window.config.get('timelapse', {}))
        # The sun-window location is always the global weather location — there
        # is no separate timelapse coordinate UI. Inject it here so the writer
        # gets the live value regardless of which settings panel was saved last.
        weather = self._main_window.config.get('weather', {})
        cfg['sun_latitude'] = weather.get('latitude') or None
        cfg['sun_longitude'] = weather.get('longitude') or None
        return cfg

    def _on_session_finished(self, path: str, frame_count: int, elapsed_seconds: int):
        """
        Called by TimelapseWriter after each session finalizes.
        Delegates post-finalization delivery to publisher services.
        """
        mins, secs = divmod(elapsed_seconds, 60)
        app_logger.info(
            f"Timelapse: session finished — {frame_count} frames  {mins}m{secs:02d}s"
        )

        from services.posthog_service import capture_event
        metadata = make_timelapse_metadata(path, frame_count, elapsed_seconds)
        file_size_mb = round(metadata.file_size_bytes / (1024 * 1024), 1) if metadata.file_size_bytes else None

        discord_cfg = self._main_window.config.get('discord', {})
        discord_delivery = discord_cfg.get('enabled', False) and discord_cfg.get('post_timelapse', False)
        youtube_cfg = self._main_window.config.get('youtube', {})
        youtube_delivery = youtube_cfg.get('enabled', False)

        capture_event('timelapse_session_finished', {
            'frame_count': frame_count,
            'duration_seconds': elapsed_seconds,
            'file_size_mb': file_size_mb,
            'discord_delivery': discord_delivery,
            'youtube_delivery': youtube_delivery,
        })

        self._publishers.publish_finished(metadata)
