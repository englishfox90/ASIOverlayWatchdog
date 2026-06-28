"""
Image Processor for Qt UI
Handles image processing pipeline using services/processor.py functions
"""
from PySide6.QtCore import QObject, Signal, QThread
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
import gc
import numpy as np
import os
import queue
import traceback
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.logger import app_logger
from services.processor import add_overlays, auto_stretch_image
from services.sharpening import apply_unsharp_mask
from services.ml_service import get_ml_service, analyze_image_for_tokens
from services.allsky.overlay_renderer import render_allsky_for_preview as _render_allsky_for_preview
from .dev_mode_utils import dev_mode_saver, collect_ml_contribution_sample


class ImageProcessingTask:
    """Encapsulates an image processing task"""
    def __init__(self, img: Image.Image, metadata: dict, config: dict):
        self.img = img.copy()  # Copy to avoid race conditions
        self.metadata = metadata.copy() if metadata else {}
        self.config = config.copy() if config else {}


class ImageProcessorWorker(QThread):
    """Background worker for image processing"""

    # Signals
    processing_complete = Signal(object, object, dict, str)  # preview PIL Image, output PIL Image, metadata, output_path
    preview_ready = Signal(object, dict)  # clean pre-overlay PIL Image, histogram data
    error_occurred = Signal(str)
    timelapse_ready = Signal(object, object)  # (clean pre-overlay PIL Image, output PIL Image)
    detection_frame_ready = Signal(object, object)  # (grayscale PIL at detection scale, full-res clean PIL)
    processing_time = Signal(float)  # elapsed seconds for last frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue(maxsize=10)
        self._running = False
        self._weather_service = None
        self._main_window = None  # Reference to main window for camera access
        self._calibration_service = None  # Background calibration accumulation
        self._frame_count = 0
        # Roof status change tracking for Discord notifications
        self._confirmed_roof_open = None  # None until first ML result
        self._pending_roof_open = None
        self._pending_roof_count = 0
        # ASCOM safety-file write is gated by its own confirmation FSM (Policy A,
        # fail-safe). Kept separate from the Discord FSM above because the safety
        # verdict folds in the confidence gate: only a *confident* Open is
        # "safe"; Closed, N/A and low/None-confidence all confirm to UNSAFE.
        from services.ascom_safety_fsm import RoofSafetyFSM, UNSAFE_RESULT
        self._safety_fsm = RoofSafetyFSM(on_failure=self._on_safety_write_failure)
        self._unsafe_result = UNSAFE_RESULT

    def set_weather_service(self, weather_service):
        """Set weather service for overlay tokens"""
        self._weather_service = weather_service

    def set_calibration_service(self, service):
        """Set calibration service for background accumulation"""
        self._calibration_service = service
    
    def set_main_window(self, main_window):
        """Set main window reference for camera access"""
        self._main_window = main_window
    
    def run(self):
        """Main processing loop"""
        self._running = True
        app_logger.debug("Image processing worker started")
        
        while self._running:
            try:
                # Wait for task with timeout so we can check _running
                try:
                    task = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                if task is None:  # Sentinel to stop
                    break
                
                self._process_task(task)
                self._queue.task_done()

                self._frame_count += 1
                if self._frame_count % 100 == 0:
                    gc.collect()
                    self._trim_working_set()
                
            except Exception as e:
                app_logger.error(f"Processing worker error: {e}")
                app_logger.error(traceback.format_exc())
                from services.posthog_service import capture_error
                capture_error(e, context='image_processor_worker')
        
        app_logger.debug("Image processing worker stopped")
    
    def stop(self):
        """Stop the worker thread"""
        self._running = False
        try:
            self._queue.put_nowait(None)  # Sentinel
        except queue.Full:
            pass

    def _trim_working_set(self):
        # Ask Windows to page out idle memory — reduces Task Manager RSS without
        # freeing virtual address space. No-op on non-Windows.
        try:
            import ctypes
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetProcessWorkingSetSize(handle, -1, -1)
        except Exception:
            pass

    def queue_task(self, task: ImageProcessingTask):
        """Queue a processing task"""
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            app_logger.warning("Processing queue full, dropping task")
    
    def _process_task(self, task: ImageProcessingTask):
        """Process a single image task"""
        from services.performance import ProcessingTimer
        _timer = ProcessingTimer()
        _timer.__enter__()
        try:
            img = task.img
            metadata = task.metadata
            config = task.config
            
            # Extract config values
            output_dir = config.get('output_dir', '')
            output_format = config.get('output_format', 'PNG')
            jpg_quality = config.get('jpg_quality', 85)
            resize_percent = config.get('resize_percent', 100)
            auto_brightness = config.get('auto_brightness', False)
            brightness_factor = config.get('brightness_factor', 1.0)
            saturation_factor = config.get('saturation_factor', 1.0)
            timestamp_corner = config.get('timestamp_corner', False)
            filename_pattern = config.get('filename_pattern', '{filename}')
            overlays = config.get('overlays', [])
            auto_stretch_config = config.get('auto_stretch', {})
            dev_mode_config = config.get('dev_mode', {})
            
            # DEBUG: Log dev mode status
            app_logger.debug(f"Dev mode config: enabled={dev_mode_config.get('enabled', False)}, save_stats={dev_mode_config.get('save_histogram_stats', True)}")
            
            if not output_dir:
                app_logger.error("Output directory not configured")
                self.error_occurred.emit("Output directory not configured")
                return
            
            os.makedirs(output_dir, exist_ok=True)
            
            # Calculate RAW histogram before processing
            # For dev mode: prefer 16-bit raw if available, then 8-bit no-WB, then image
            raw_array = metadata.get('RAW_RGB_16BIT')  # Full 16-bit if RAW16 mode
            if raw_array is None:
                raw_array = metadata.get('RAW_RGB_NO_WB')  # 8-bit pre-WB fallback
            if raw_array is None:
                raw_array = np.asarray(img)  # Final fallback for watch mode
            
            # === DEV MODE: Save raw image and log detailed stats ===
            if dev_mode_config.get('enabled', False):
                dev_mode_saver.save_dev_mode_data(img, raw_array, output_dir, metadata, dev_mode_config)
            
            # === ML CONTRIBUTION: Collect sample if enabled (works in production) ===
            ml_contrib_config = config.get('ml_contribution', {})
            ml_enabled = ml_contrib_config.get('enabled', False)
            app_logger.debug(f"ML Contribution check: enabled={ml_enabled}")
            if ml_enabled:
                collect_ml_contribution_sample(raw_array, metadata, lambda: config)
            
            # Get auto-exposure settings for histogram display
            # Check if camera controller exists and has auto_exposure enabled
            zwo_auto_exposure = False
            target_brightness = 30
            
            if self._main_window:
                if hasattr(self._main_window, 'camera_controller') and self._main_window.camera_controller:
                    if hasattr(self._main_window.camera_controller, 'zwo_camera') and self._main_window.camera_controller.zwo_camera:
                        zwo_auto_exposure = self._main_window.camera_controller.zwo_camera.auto_exposure
                        target_brightness = self._main_window.camera_controller.zwo_camera.target_brightness
                        app_logger.debug(f"Histogram config from camera: auto_exposure={zwo_auto_exposure}, target={target_brightness}")
            
            # Calculate histogram - use appropriate range based on bit depth
            # 16-bit data needs to be scaled down for 256-bin histogram display
            if raw_array.dtype == np.uint16:
                # Scale 16-bit to 8-bit range for histogram display
                hist_array = (raw_array / 257).astype(np.uint8)
            else:
                hist_array = raw_array
            
            hist_data = {
                'r': np.histogram(hist_array[:, :, 0], bins=256, range=(0, 256))[0],
                'g': np.histogram(hist_array[:, :, 1], bins=256, range=(0, 256))[0],
                'b': np.histogram(hist_array[:, :, 2], bins=256, range=(0, 256))[0],
                'auto_exposure': zwo_auto_exposure,
                'target_brightness': target_brightness
            }
            del hist_array
            # Note: We keep metadata['RAW_RGB_16BIT'] alive for auto-stretch below
            
            # Resize if needed (only for 8-bit PIL image, 16-bit handled in stretch)
            if resize_percent < 100:
                new_width = int(img.width * resize_percent / 100)
                new_height = int(img.height * resize_percent / 100)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # === Detection frame for meteor stack (pre-stretch, linear, downscaled) ===
            # Derived here so it reflects the linear scene BEFORE per-frame MTF stretch.
            # A fixed linear scale means consecutive frames of a static scene are
            # photometrically stable, so their diff genuinely cancels.
            # Only computed when the meteor feature can actually consume it —
            # this is a full-frame LANCZOS resize on every capture otherwise.
            _det_frame = None
            _meteor_cfg = config.get('meteor', {})
            if _meteor_cfg.get('enabled', False):
                from services.dev_mode_config import is_dev_mode_available
                if is_dev_mode_available():
                    _det_long_side = int(_meteor_cfg.get('detection_long_side', 1280))
                    _det_factor = min(1.0, _det_long_side / max(img.width, img.height))
                    if _det_factor < 1.0:
                        _det_frame = img.resize(
                            (max(1, int(img.width * _det_factor)),
                             max(1, int(img.height * _det_factor))),
                            Image.Resampling.LANCZOS,
                        ).convert('L')
                    else:
                        _det_frame = img.convert('L')

            # Apply auto-stretch (MTF) if enabled
            # Use 16-bit raw data when available for higher precision stretching
            if auto_stretch_config.get('enabled', False):
                raw_16bit = metadata.get('RAW_RGB_16BIT')  # Will be None if RAW8 mode
                if raw_16bit is not None:
                    # Resize 16-bit data if needed to match PIL image size
                    if resize_percent < 100:
                        import cv2
                        new_height = int(raw_16bit.shape[0] * resize_percent / 100)
                        new_width = int(raw_16bit.shape[1] * resize_percent / 100)
                        raw_16bit = cv2.resize(raw_16bit, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
                img = auto_stretch_image(img, auto_stretch_config, raw_16bit=raw_16bit)
                app_logger.debug("Applied auto-stretch")
            
            # Cache stretched image for preview
            stretched_for_preview = img.copy()

            allsky_cfg = config.get('allsky_overlay', {})

            # Apply auto brightness
            if auto_brightness:
                gray_img = img.convert('L')
                img_array = np.asarray(gray_img)
                mean_brightness = np.mean(img_array)
                del gray_img
                
                target_brightness = 128
                auto_factor = target_brightness / max(mean_brightness, 10)
                auto_factor = max(0.5, min(auto_factor, 4.0))
                manual_factor = brightness_factor if brightness_factor else 1.0
                final_factor = auto_factor * manual_factor
                
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(final_factor)
                app_logger.debug(f"Auto brightness: mean={mean_brightness:.1f}, factor={final_factor:.2f}")
            
            # Apply saturation
            if saturation_factor != 1.0:
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(saturation_factor)
                app_logger.debug(f"Saturation adjusted: factor={saturation_factor:.2f}")
            
            # Add timestamp corner
            if timestamp_corner:
                draw = ImageDraw.Draw(img)
                timestamp_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    font = ImageFont.truetype("arial.ttf", 20)
                except (OSError, IOError):
                    font = ImageFont.load_default()
                draw.text((img.width - 200, 10), timestamp_text, fill='white', font=font)
            
            # Apply cosmetic star sharpening (unsharp mask, before overlays)
            sharpening_cfg = config.get('sharpening', {})
            if sharpening_cfg.get('enabled', False):
                img = apply_unsharp_mask(
                    img,
                    radius=float(sharpening_cfg.get('radius', 1.5)),
                    amount=int(sharpening_cfg.get('amount', 80)),
                    threshold=int(sharpening_cfg.get('threshold', 3)),
                )
                app_logger.debug(
                    f"Sharpening applied: radius={sharpening_cfg.get('radius', 1.5)}, "
                    f"amount={sharpening_cfg.get('amount', 80)}, "
                    f"threshold={sharpening_cfg.get('threshold', 3)}"
                )

            _ml_roof_status = None  # (roof_status_str, confidence) — set if ML runs

            # === ML Models: Add predictions to metadata for overlay tokens ===
            ml_config = config.get('ml_models', {})
            ascom_config = ml_config.get('ascom_safety_file', {})
            _ml_produced_result = False
            ml_results = None
            if ml_config.get('enabled', False):
                try:
                    ml_service = get_ml_service()
                    if not ml_service.is_available():
                        ml_service.initialize()

                    if ml_service.is_available():
                        # Get ML predictions formatted for overlay tokens
                        ml_tokens = analyze_image_for_tokens(raw_array, config=ml_config)
                        metadata.update(ml_tokens)

                        # Store full results for preview display and roof-gated timelapse
                        ml_results = ml_service.get_last_results()
                        metadata['_ML_RESULTS'] = ml_results
                        _ml_produced_result = True
                        _ml_roof_status = (
                            ml_results.get('roof_status'),
                            ml_results.get('roof_confidence', 0.0),
                        )
                        if self._main_window:
                            self._main_window.last_ml_results = ml_results

                        app_logger.debug(f"ML predictions: roof={ml_tokens.get('ROOF_STATUS')}, sky={ml_tokens.get('SKY_CONDITION')}")
                except Exception as e:
                    app_logger.debug(f"ML prediction skipped: {e}")

            # Update the ASCOM Safety Monitor file (if enabled) from a CONFIRMED
            # roof-safety verdict, never the raw per-frame result, so one noisy
            # frame can't flip it. When ML did not produce a usable result this
            # frame — disabled, model unavailable, or inference raised — feed
            # UNSAFE so the file can't freeze at a stale OPEN. Both routes go
            # through the same 2-frame-confirmation FSM.
            if ascom_config.get('enabled', False):
                try:
                    verdict = ml_results if _ml_produced_result else self._unsafe_result
                    self._safety_fsm.update(verdict, ascom_config)
                except Exception as e:
                    app_logger.debug(f"ASCOM safety update skipped: {e}")

            # Feed clean (pre-enhancement) frame to the background calibration
            # service. Runs AFTER ML so the is_observing_window roof gate sees
            # ROOF_STATUS — calibration and the all-sky overlay must both stay
            # suppressed when the roof is closed. It feeds the frozen pre-enhancement
            # copy (stretched_for_preview), so executing here (past brightness /
            # sharpening) does not change the pixels it detects on.
            if self._calibration_service and allsky_cfg.get('enabled', False):
                try:
                    from services.observing_window import is_observing_window
                    if is_observing_window(config, metadata, feature="All-sky calibration"):
                        weather_cfg = config.get('weather', {})
                        cal_lat = float(weather_cfg.get('latitude', 0) or 0)
                        cal_lon = float(weather_cfg.get('longitude', 0) or 0)
                        if cal_lat != 0 or cal_lon != 0:
                            from datetime import timezone as _tz
                            self._calibration_service.feed_frame(
                                stretched_for_preview, datetime.now(_tz.utc), cal_lat, cal_lon,
                            )
                except Exception as e:
                    app_logger.warning(f"Calibration feed skipped: {e}")

            # Star detection tokens (gated: sun below civil twilight, and roof open if ML enabled)
            try:
                from services.star_detection import analyze_stars, should_run_star_detection
                if should_run_star_detection(config, metadata):
                    star_tokens = analyze_stars(raw_array)
                    metadata.update(star_tokens)
                else:
                    metadata.update({'STAR_COUNT': 'N/A', 'FWHM': 'N/A', 'SEEING': 'N/A'})
            except Exception as e:
                app_logger.debug(f"Star detection skipped: {e}")

            del raw_array  # Last use above — release the 76 MB numpy array before overlay rendering

            # Base render — no all-sky overlay. This image is saved to disk and
            # pushed to all output sinks (file, web, Discord). Never contains
            # the all-sky overlay regardless of calibration state.
            output_img = add_overlays(img, overlays, metadata, weather_service=self._weather_service)

            # Preview render — all-sky overlay drawn on a copy, never leaves the app.
            preview_img = _render_allsky_for_preview(output_img, allsky_cfg, config, metadata)

            # Timelapse receives the clean output image.
            self.timelapse_ready.emit(stretched_for_preview, output_img)
            # Meteor stack receives the pre-stretch detection frame + full-res clean.
            if _det_frame is not None:
                self.detection_frame_ready.emit(_det_frame, stretched_for_preview)

            # Generate output path
            session = metadata.get('session', datetime.now().strftime('%Y-%m-%d'))
            original_filename = metadata.get('FILENAME', 'capture.png')
            base_filename = os.path.splitext(original_filename)[0]
            output_filename = filename_pattern.replace('{filename}', base_filename)
            output_filename = output_filename.replace('{session}', session)
            output_filename = output_filename.replace('{timestamp}', datetime.now().strftime('%Y%m%d_%H%M%S'))
            output_filename += '.png' if output_format.lower() == 'png' else '.jpg'
            output_path = os.path.join(output_dir, output_filename)
            
            # Save to disk (output_img — clean, no all-sky)
            if output_format.lower() == 'png':
                output_img.save(output_path, 'PNG')
            else:
                output_img.save(output_path, 'JPEG', quality=jpg_quality)

            app_logger.debug(f"Saved: {os.path.basename(output_path)}")

            if _ml_roof_status and _ml_roof_status[0] in ('Open', 'Closed'):
                self._check_roof_change(_ml_roof_status[0] == 'Open', _ml_roof_status[1], output_path)

            # Clean up large arrays from metadata before emitting (avoid memory leaks)
            metadata.pop('RAW_RGB_16BIT', None)
            metadata.pop('RAW_RGB_NO_WB', None)
            
            self.preview_ready.emit(stretched_for_preview, hist_data)
            self.processing_complete.emit(preview_img, output_img, metadata, output_path)

            # Emit processing time
            _timer.__exit__(None, None, None)
            self.processing_time.emit(_timer.elapsed)

        except Exception as e:
            app_logger.error(f"Image processing failed: {e}")
            app_logger.error(traceback.format_exc())
            from services.posthog_service import capture_error
            capture_error(e, context='image_processing')
            self.error_occurred.emit(str(e))

    def _check_roof_change(self, roof_open: bool, confidence: float, image_path: str):
        """Accumulate consecutive roof readings; fire alert on the 2nd consecutive change."""
        if self._confirmed_roof_open is None:
            self._confirmed_roof_open = roof_open
            return

        if roof_open == self._confirmed_roof_open:
            self._pending_roof_open = None
            self._pending_roof_count = 0
            return

        if self._pending_roof_open == roof_open:
            self._pending_roof_count += 1
        else:
            self._pending_roof_open = roof_open
            self._pending_roof_count = 1

        if self._pending_roof_count >= 2:
            self._confirmed_roof_open = roof_open
            self._pending_roof_open = None
            self._pending_roof_count = 0
            self._send_roof_alert(roof_open, confidence, image_path)

    def _send_roof_alert(self, roof_open: bool, confidence: float, image_path: str):
        """Post roof status change to Discord (called from worker thread)."""
        if not self._main_window:
            return
        try:
            from services.discord_alerts import DiscordAlerts
            alerts = DiscordAlerts(self._main_window.config)
            alerts.send_roof_status_change(roof_open, confidence, image_path)
        except Exception as e:
            app_logger.warning(f"Roof change Discord alert failed: {e}")

    def _on_safety_write_failure(self):
        """Surface a genuinely-failed safety-file write to operator-visible
        channels. Called by RoofSafetyFSM (already deduped per failure run)."""
        msg = ("ASCOM safety-file write FAILED - NINA may be reading a stale "
               "roof state. Check the safety-file path and disk.")
        app_logger.error(msg)

        try:
            from services.posthog_service import capture_error
            capture_error(RuntimeError("ascom_safety_write_failed"),
                          context='ascom_safety_write')
        except Exception as e:
            app_logger.debug(f"PostHog capture_error skipped: {e}")

        if self._main_window:
            try:
                from services.discord_alerts import DiscordAlerts
                alerts = DiscordAlerts(self._main_window.config)
                alerts.send_error_message(msg)
            except Exception as e:
                app_logger.warning(f"ASCOM safety failure Discord alert failed: {e}")


class ImageProcessor(QObject):
    """
    Image processor for Qt UI
    
    Uses a background thread for heavy image processing to keep UI responsive.
    Reuses functions from services/processor.py for actual processing.
    """
    
    # Signals forwarded from worker
    processing_complete = Signal(object, object, dict, str)  # preview PIL Image, output PIL Image, metadata, output_path
    preview_ready = Signal(object, dict)  # clean pre-overlay PIL Image, histogram data
    error_occurred = Signal(str)
    timelapse_ready = Signal(object, object)  # (clean pre-overlay PIL Image, output PIL Image)
    detection_frame_ready = Signal(object, object)  # (grayscale PIL at detection scale, full-res clean PIL)
    processing_time = Signal(float)  # elapsed seconds

    def __init__(self, parent=None):
        super().__init__(parent)

        # Worker thread
        self._worker = ImageProcessorWorker()
        self._worker.processing_complete.connect(self._on_processing_complete)
        self._worker.preview_ready.connect(self._on_preview_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.timelapse_ready.connect(self.timelapse_ready)
        self._worker.detection_frame_ready.connect(self.detection_frame_ready)
        self._worker.processing_time.connect(self.processing_time)
        
        # Reference to main window for config access
        self._main_window = None
        
    def set_main_window(self, main_window):
        """Set reference to main window for config access"""
        self._main_window = main_window

        # Pass main window to worker for camera access
        self._worker.set_main_window(main_window)

        # Pass weather service to worker
        if hasattr(main_window, 'weather_service'):
            self._worker.set_weather_service(main_window.weather_service)

    def set_calibration_service(self, service):
        """Pass calibration service to worker for background accumulation"""
        self._worker.set_calibration_service(service)
    
    def start(self):
        """Start the processing worker"""
        if not self._worker.isRunning():
            self._worker.start()
            app_logger.debug("Image processor started")
    
    def stop(self):
        """Stop the processing worker"""
        self._worker.stop()
        self._worker.wait(1000)
        app_logger.debug("Image processor stopped")
    
    def process_and_save(self, img: Image.Image, metadata: dict):
        """
        Process image and save to disk
        
        Gathers config from UI, then queues processing to background thread.
        
        Args:
            img: PIL Image to process
            metadata: Image metadata dict
        """
        if not self._main_window:
            app_logger.error("ImageProcessor: main_window not set")
            return
        
        try:
            # Gather config from UI
            config = self._gather_config()
            
            if not config.get('output_dir'):
                app_logger.error("Output directory not configured")
                return
            
            # Create task and queue it
            task = ImageProcessingTask(img, metadata, config)
            self._worker.queue_task(task)
            
        except Exception as e:
            app_logger.error(f"Failed to queue image processing: {e}")
            app_logger.error(traceback.format_exc())
    
    def _gather_config(self) -> dict:
        """Gather processing config from UI components"""
        mw = self._main_window
        
        # Get auto_stretch config - merge with defaults if missing keys
        auto_stretch_defaults = {
            'enabled': False,
            'target_median': 0.25,
            'linked_stretch': True,
            'preserve_blacks': True,
            'black_point': 0.0,
            'shadow_aggressiveness': 2.8,
            'saturation_boost': 1.5,
            'scnr_amount': 0.0,
        }
        auto_stretch_config = mw.config.get('auto_stretch', {})
        # Merge with defaults - saved config overrides defaults
        auto_stretch = auto_stretch_defaults.copy()
        auto_stretch.update(auto_stretch_config)
        
        app_logger.debug(f"Auto-stretch config: enabled={auto_stretch.get('enabled')}, target_median={auto_stretch.get('target_median')}")
        
        config = {
            'output_dir': mw.config.get('output_directory', ''),
            'output_format': mw.config.get('output_format', 'PNG'),
            'jpg_quality': mw.config.get('jpg_quality', 85),
            'resize_percent': mw.config.get('resize_percent', 100),
            'auto_brightness': mw.config.get('auto_brightness', False),
            'brightness_factor': mw.config.get('brightness_factor', 1.0),
            'saturation_factor': mw.config.get('saturation_factor', 1.0),
            'timestamp_corner': mw.config.get('timestamp_corner', False),
            'filename_pattern': mw.config.get('filename_pattern', '{filename}'),
            'auto_stretch': auto_stretch,
            'overlays': mw.config.get('overlays', []),
            'dev_mode': mw.config.get('dev_mode', {'enabled': False, 'raw_folder': 'raw_debug', 'save_histogram_stats': True}),
            'ml_models': mw.config.get('ml_models', {'enabled': False}),
            'ml_contribution': mw.config.get('ml_contribution', {'enabled': False}),
            'allsky_overlay': mw.config.get('allsky_overlay', {}),
            'weather': mw.config.get('weather', {}),
        }

        return config
    
    def _on_processing_complete(self, preview_img, output_img, metadata, output_path):
        self.processing_complete.emit(preview_img, output_img, metadata, output_path)
    
    def _on_preview_ready(self, img, hist_data):
        """Forward preview ready signal"""
        self.preview_ready.emit(img, hist_data)
    
    def _on_error(self, error_msg):
        """Forward error signal"""
        self.error_occurred.emit(error_msg)
