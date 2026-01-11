"""
Image Processor for Qt UI
Handles image processing pipeline using services/processor.py functions
"""
from PySide6.QtCore import QObject, Signal, QThread
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
import numpy as np
import os
import queue
import traceback
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.logger import app_logger
from services.processor import add_overlays, auto_stretch_image
from services.ml_service import get_ml_service, analyze_image_for_tokens
from .dev_mode_utils import dev_mode_saver


class ImageProcessingTask:
    """Encapsulates an image processing task"""
    def __init__(self, img: Image.Image, metadata: dict, config: dict):
        self.img = img.copy()  # Copy to avoid race conditions
        self.metadata = metadata.copy() if metadata else {}
        self.config = config.copy() if config else {}


class ImageProcessorWorker(QThread):
    """Background worker for image processing"""
    
    # Signals
    processing_complete = Signal(object, dict, str)  # processed PIL Image, metadata, output_path
    preview_ready = Signal(object, dict)  # PIL Image for preview, histogram data
    error_occurred = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue(maxsize=10)
        self._running = False
        self._weather_service = None
        self._main_window = None  # Reference to main window for camera access
    
    def set_weather_service(self, weather_service):
        """Set weather service for overlay tokens"""
        self._weather_service = weather_service
    
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
                
            except Exception as e:
                app_logger.error(f"Processing worker error: {e}")
                app_logger.error(traceback.format_exc())
        
        app_logger.debug("Image processing worker stopped")
    
    def stop(self):
        """Stop the worker thread"""
        self._running = False
        try:
            self._queue.put_nowait(None)  # Sentinel
        except queue.Full:
            pass
    
    def queue_task(self, task: ImageProcessingTask):
        """Queue a processing task"""
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            app_logger.warning("Processing queue full, dropping task")
    
    def _process_task(self, task: ImageProcessingTask):
        """Process a single image task"""
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
                except:
                    font = ImageFont.load_default()
                draw.text((img.width - 200, 10), timestamp_text, fill='white', font=font)
            
            # === ML Models: Add predictions to metadata for overlay tokens ===
            ml_config = config.get('ml_models', {})
            if ml_config.get('enabled', False):
                try:
                    ml_service = get_ml_service()
                    if not ml_service.is_available():
                        ml_service.initialize()
                    
                    if ml_service.is_available():
                        # Get ML predictions formatted for overlay tokens
                        ml_tokens = analyze_image_for_tokens(raw_array, config=ml_config)
                        metadata.update(ml_tokens)
                        
                        # Store full results for preview display
                        ml_results = ml_service.get_last_results()
                        metadata['_ML_RESULTS'] = ml_results
                        
                        app_logger.debug(f"ML predictions: roof={ml_tokens.get('ROOF_STATUS')}, sky={ml_tokens.get('SKY_CONDITION')}")
                except Exception as e:
                    app_logger.debug(f"ML prediction skipped: {e}")
            
            # Add overlays using services/processor.py function
            img = add_overlays(img, overlays, metadata, weather_service=self._weather_service)
            
            # Generate output path
            session = metadata.get('session', datetime.now().strftime('%Y-%m-%d'))
            original_filename = metadata.get('FILENAME', 'capture.png')
            base_filename = os.path.splitext(original_filename)[0]
            output_filename = filename_pattern.replace('{filename}', base_filename)
            output_filename = output_filename.replace('{session}', session)
            output_filename = output_filename.replace('{timestamp}', datetime.now().strftime('%Y%m%d_%H%M%S'))
            output_filename += '.png' if output_format.lower() == 'png' else '.jpg'
            output_path = os.path.join(output_dir, output_filename)
            
            # Save to disk
            if output_format.lower() == 'png':
                img.save(output_path, 'PNG')
            else:
                img.save(output_path, 'JPEG', quality=jpg_quality)
            
            app_logger.info(f"Saved: {os.path.basename(output_path)}")
            
            # Clean up large arrays from metadata before emitting (avoid memory leaks)
            metadata.pop('RAW_RGB_16BIT', None)
            metadata.pop('RAW_RGB_NO_WB', None)
            
            # Emit preview signal with stretched image and histogram
            self.preview_ready.emit(stretched_for_preview, hist_data)
            
            # Emit completion signal
            self.processing_complete.emit(img, metadata, output_path)
            
        except Exception as e:
            app_logger.error(f"Image processing failed: {e}")
            app_logger.error(traceback.format_exc())
            self.error_occurred.emit(str(e))


class ImageProcessor(QObject):
    """
    Image processor for Qt UI
    
    Uses a background thread for heavy image processing to keep UI responsive.
    Reuses functions from services/processor.py for actual processing.
    """
    
    # Signals forwarded from worker
    processing_complete = Signal(object, dict, str)  # PIL Image, metadata, output_path
    preview_ready = Signal(object, dict)  # PIL Image for preview, histogram data
    error_occurred = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Worker thread
        self._worker = ImageProcessorWorker()
        self._worker.processing_complete.connect(self._on_processing_complete)
        self._worker.preview_ready.connect(self._on_preview_ready)
        self._worker.error_occurred.connect(self._on_error)
        
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
    
    def start(self):
        """Start the processing worker"""
        if not self._worker.isRunning():
            self._worker.start()
            app_logger.debug("Image processor started")
    
    def stop(self):
        """Stop the processing worker"""
        self._worker.stop()
        self._worker.wait(5000)  # Wait up to 5 seconds
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
            'saturation_boost': 1.5
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
        }
        
        return config
    
    def _on_processing_complete(self, img, metadata, output_path):
        """Forward processing complete signal"""
        self.processing_complete.emit(img, metadata, output_path)
    
    def _on_preview_ready(self, img, hist_data):
        """Forward preview ready signal"""
        self.preview_ready.emit(img, hist_data)
    
    def _on_error(self, error_msg):
        """Forward error signal"""
        self.error_occurred.emit(error_msg)
