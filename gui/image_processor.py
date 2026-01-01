"""
Image processing module
Handles image processing, overlays, and preview generation

Threading Architecture (PERF-002):
- Heavy image processing runs on a dedicated background worker thread
- Only lightweight GUI updates (PhotoImage, label.config) happen on UI thread
- Processing queue with throttling prevents backlog during slow operations
"""
import os
import random
import threading
import queue
import numpy as np
from datetime import datetime
from tkinter import TclError
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageTk
from services.processor import add_overlays, auto_stretch_image
from services.logger import app_logger
import traceback


class ImageProcessor:
    """Manages image processing and preview generation
    
    Uses a background processing thread to keep the UI responsive.
    Heavy operations (auto-stretch, overlays, histograms) run off the UI thread.
    """
    
    def __init__(self, app):
        self.app = app
        
        # Preview caching to avoid re-reading from disk
        self.preview_cache = None
        self.preview_cache_path = None
        
        # Cache for overlay images with size limit
        self.overlay_image_cache = {}
        self.overlay_cache_max_size = 10  # Limit cache to 10 images
        self.preview_update_pending = False
        
        # PERF-002: Background processing thread for heavy operations
        self._processing_queue = queue.Queue(maxsize=2)  # Small queue to prevent backlog
        self._processing_thread = None
        self._stop_processing = threading.Event()
        self._start_processing_thread()
    
    def _cleanup_overlay_cache(self):
        """Remove oldest entries from overlay cache if it exceeds size limit"""
        if len(self.overlay_image_cache) > self.overlay_cache_max_size:
            # Remove excess entries (FIFO)
            excess = len(self.overlay_image_cache) - self.overlay_cache_max_size
            keys_to_remove = list(self.overlay_image_cache.keys())[:excess]
            for key in keys_to_remove:
                del self.overlay_image_cache[key]
            app_logger.debug(f"Cleaned up overlay cache: removed {excess} entries")
    
    # =========================================================================
    # PERF-002: Background Processing Thread
    # =========================================================================
    
    def _start_processing_thread(self):
        """Start the background processing thread"""
        if self._processing_thread is not None and self._processing_thread.is_alive():
            return
        
        self._stop_processing.clear()
        self._processing_thread = threading.Thread(
            target=self._processing_worker,
            name="ImageProcessorWorker",
            daemon=True
        )
        self._processing_thread.start()
        app_logger.debug("Background image processing thread started")
    
    def _stop_processing_thread(self):
        """Stop the background processing thread gracefully"""
        self._stop_processing.set()
        # Put a sentinel to wake up the thread if it's waiting
        try:
            self._processing_queue.put_nowait(None)
        except queue.Full:
            pass
        
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=2.0)
        self._processing_thread = None
    
    def _processing_worker(self):
        """Background worker thread that processes images"""
        app_logger.debug("Image processing worker started")
        
        while not self._stop_processing.is_set():
            try:
                # Wait for work with timeout (allows checking stop flag)
                try:
                    task = self._processing_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                if task is None:  # Sentinel value to stop
                    break
                
                task_type = task.get('type')
                
                if task_type == 'save_image':
                    self._do_process_and_save(task)
                elif task_type == 'mini_preview':
                    self._do_update_mini_preview(task)
                elif task_type == 'refresh_preview':
                    self._do_refresh_preview(task)
                
                self._processing_queue.task_done()
                
            except Exception as e:
                app_logger.error(f"Processing worker error: {e}")
                app_logger.error(traceback.format_exc())
        
        app_logger.debug("Image processing worker stopped")
    
    def _queue_task(self, task):
        """Queue a processing task, dropping old tasks if queue is full"""
        try:
            # Non-blocking put - if queue is full, skip this frame
            self._processing_queue.put_nowait(task)
        except queue.Full:
            # Queue is full - processing is backed up, skip this frame
            app_logger.debug(f"Processing queue full, skipping {task.get('type')} task")
    
    def _do_update_mini_preview(self, task):
        """Process mini preview and histogram on background thread
        
        Heavy operations (auto-stretch, brightness, histogram) run here,
        then we schedule lightweight GUI updates to the main thread.
        """
        try:
            img = task['img']
            auto_stretch_config = task['auto_stretch_config']
            auto_brightness = task['auto_brightness']
            brightness_factor = task['brightness_factor']
            auto_exposure = task.get('auto_exposure', False)
            target_brightness = task.get('target_brightness', 100)
            
            # Apply auto-stretch if enabled
            if auto_stretch_config.get('enabled', False):
                stretch_config = {
                    'target_median': auto_stretch_config.get('target_median', 0.25),
                    'linked_stretch': auto_stretch_config.get('linked_stretch', True),
                    'preserve_blacks': auto_stretch_config.get('preserve_blacks', True),
                    'shadow_aggressiveness': auto_stretch_config.get('shadow_aggressiveness', 2.8),
                    'saturation_boost': auto_stretch_config.get('saturation_boost', 1.5),
                }
                preview_img = auto_stretch_image(img, stretch_config)
            else:
                preview_img = img
            
            # Apply auto brightness if enabled
            if auto_brightness:
                gray_img = preview_img.convert('L')
                img_array = np.asarray(gray_img)
                mean_brightness = np.mean(img_array)
                del gray_img
                target_br = 128
                auto_factor = target_br / max(mean_brightness, 10)
                auto_factor = max(0.5, min(auto_factor, 4.0))
                
                manual_factor = brightness_factor if brightness_factor else 1.0
                final_factor = auto_factor * manual_factor
                
                enhancer = ImageEnhance.Brightness(preview_img)
                preview_img = enhancer.enhance(final_factor)
            
            # Resize to fit (200x200 thumbnail)
            preview_img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # Calculate histogram from original image (before stretch/brightness)
            img_array = np.asarray(img)
            hist_r = np.histogram(img_array[:, :, 0], bins=256, range=(0, 256))[0]
            hist_g = np.histogram(img_array[:, :, 1], bins=256, range=(0, 256))[0]
            hist_b = np.histogram(img_array[:, :, 2], bins=256, range=(0, 256))[0]
            
            # Normalize histograms
            max_val = max(hist_r.max(), hist_g.max(), hist_b.max())
            if max_val > 0:
                hist_r = (hist_r / max_val * 90).astype(int)
                hist_g = (hist_g / max_val * 90).astype(int)
                hist_b = (hist_b / max_val * 90).astype(int)
            
            hist_data = {
                'r': hist_r,
                'g': hist_g,
                'b': hist_b,
                'auto_exposure': auto_exposure,
                'target_brightness': target_brightness,
            }
            
            # Create PhotoImage on main thread (required by tkinter)
            def update_gui():
                try:
                    photo = ImageTk.PhotoImage(preview_img)
                    self.app.status_manager._do_mini_preview_gui_update(photo, hist_data)
                except Exception as e:
                    app_logger.error(f"Mini preview GUI update failed: {e}")
                    self.app.status_manager._mini_preview_pending = False
            
            self.app.root.after(0, update_gui)
            
            # Clean up
            del img
            
        except Exception as e:
            app_logger.error(f"Mini preview processing failed: {e}")
            # Reset pending flag on error
            self.app.root.after(0, lambda: setattr(self.app.status_manager, '_mini_preview_pending', False))
    
    def _do_refresh_preview(self, task):
        """Process preview refresh on background thread - placeholder for future optimization"""
        # For now, this delegates to the existing refresh_preview method
        # which runs on the UI thread. Full optimization would move the heavy
        # processing here similar to _do_update_mini_preview.
        auto_fit = task.get('auto_fit', True)
        self.app.root.after(0, lambda: self.refresh_preview(auto_fit=auto_fit))

    def process_and_save_image(self, img, metadata):
        """Process image with overlays and save - queues work to background thread
        
        This method is called from the camera thread. It gathers configuration
        from GUI variables (fast) then queues the heavy processing work to
        a background thread to avoid blocking.
        """
        try:
            # PERF-002: Gather config from GUI (fast - just variable reads)
            # This must happen on the calling thread while we have valid references
            config = {
                'overlays': self.app.overlay_manager.get_overlays_config(),
                'output_dir': self.app.output_dir_var.get(),
                'output_format': self.app.output_format_var.get(),
                'jpg_quality': self.app.jpg_quality_var.get(),
                'resize_percent': self.app.resize_percent_var.get(),
                'auto_brightness': self.app.auto_brightness_var.get(),
                'brightness_factor': self.app.brightness_var.get() if self.app.auto_brightness_var.get() else None,
                'saturation_factor': self.app.saturation_var.get(),
                'timestamp_corner': self.app.timestamp_corner_var.get(),
                'filename_pattern': self.app.filename_pattern_var.get(),
                'auto_stretch': self.app.config.get('auto_stretch', {}),
                'auto_refresh': self.app.auto_refresh_var.get(),
            }
            
            if not config['output_dir']:
                app_logger.error("Output directory not configured")
                return
            
            # Queue heavy processing to background thread
            self._queue_task({
                'type': 'save_image',
                'img': img.copy(),  # Copy to avoid race conditions
                'metadata': metadata.copy(),
                'config': config,
            })
            
        except Exception as e:
            app_logger.error(f"Failed to queue image processing: {e}")
            app_logger.error(traceback.format_exc())
    
    def _do_process_and_save(self, task):
        """Actually process and save image - runs on background thread"""
        try:
            img = task['img']
            metadata = task['metadata']
            config = task['config']
            
            output_dir = config['output_dir']
            output_format = config['output_format']
            jpg_quality = config['jpg_quality']
            resize_percent = config['resize_percent']
            auto_brightness = config['auto_brightness']
            brightness_factor = config['brightness_factor']
            saturation_factor = config['saturation_factor']
            timestamp_corner = config['timestamp_corner']
            filename_pattern = config['filename_pattern']
            overlays = config['overlays']
            auto_stretch_config = config['auto_stretch']
            
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Resize if needed
            if resize_percent < 100:
                new_width = int(img.width * resize_percent / 100)
                new_height = int(img.height * resize_percent / 100)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Apply auto-stretch (MTF) if enabled - BEFORE brightness/saturation/overlays
            if auto_stretch_config.get('enabled', False):
                img = auto_stretch_image(img, auto_stretch_config)
                app_logger.debug("Applied auto-stretch to camera capture")
            
            # Apply auto brightness if enabled (with proper analysis)
            if auto_brightness:
                # Analyze brightness using view (no copy)
                gray_img = img.convert('L')
                img_array = np.asarray(gray_img)
                mean_brightness = np.mean(img_array)
                del gray_img
                
                # Calculate adaptive enhancement factor
                target_brightness = 128
                auto_factor = target_brightness / max(mean_brightness, 10)
                auto_factor = max(0.5, min(auto_factor, 4.0))
                
                manual_factor = brightness_factor if brightness_factor else 1.0
                final_factor = auto_factor * manual_factor
                
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(final_factor)
                
                app_logger.debug(f"Auto brightness: mean={mean_brightness:.1f}, auto={auto_factor:.2f}, manual={manual_factor:.2f}, final={final_factor:.2f}")
            
            # Apply saturation adjustment
            if saturation_factor != 1.0:
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(saturation_factor)
                app_logger.debug(f"Saturation adjusted: factor={saturation_factor:.2f}")
            
            # Add timestamp corner if enabled
            if timestamp_corner:
                draw = ImageDraw.Draw(img)
                timestamp_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    font = ImageFont.truetype("arial.ttf", 20)
                except:
                    font = ImageFont.load_default()
                draw.text((img.width - 200, 10), timestamp_text, fill='white', font=font)
            
            # Add overlays (pass weather_service for weather tokens)
            img = add_overlays(img, overlays, metadata, weather_service=self.app.weather_service)
            
            # Generate output filename
            session = metadata.get('session', datetime.now().strftime('%Y-%m-%d'))
            original_filename = metadata.get('FILENAME', 'capture.png')
            base_filename = os.path.splitext(original_filename)[0]
            
            output_filename = filename_pattern.replace('{filename}', base_filename)
            output_filename = output_filename.replace('{session}', session)
            output_filename = output_filename.replace('{timestamp}', datetime.now().strftime('%Y%m%d_%H%M%S'))
            
            if output_format.lower() == 'png':
                output_filename += '.png'
            else:
                output_filename += '.jpg'
            
            output_path = os.path.join(output_dir, output_filename)
            
            # Save
            if output_format.lower() == 'png':
                img.save(output_path, 'PNG')
            else:
                img.save(output_path, 'JPEG', quality=jpg_quality)
            
            # Schedule GUI updates on main thread
            def update_gui():
                try:
                    self.app.last_processed_image = output_path
                    
                    # Store preview image (already resized)
                    if hasattr(self.app, 'preview_image') and self.app.preview_image:
                        try:
                            del self.app.preview_image
                        except:
                            pass
                    
                    # Store a copy for preview (without overlays for clean preview base)
                    if resize_percent < 100 and self.app.last_captured_image:
                        new_width = int(self.app.last_captured_image.width * resize_percent / 100)
                        new_height = int(self.app.last_captured_image.height * resize_percent / 100)
                        self.app.preview_image = self.app.last_captured_image.resize(
                            (new_width, new_height), Image.Resampling.LANCZOS)
                    elif self.app.last_captured_image:
                        self.app.preview_image = self.app.last_captured_image.copy()
                    
                    self.app.preview_metadata = metadata.copy()
                    
                    # Auto-refresh preview if enabled
                    if config['auto_refresh']:
                        self.refresh_preview(auto_fit=True)
                except Exception as e:
                    app_logger.error(f"GUI update error: {e}")
            
            self.app.root.after(0, update_gui)
            
            app_logger.info(f"Saved: {os.path.basename(output_path)}")
            
            # Push to output servers (can be slow, but runs on background thread)
            self.app._push_to_output_servers(output_path, img)
            
            # Clean up the processed image object
            del img
            
            # Update last_processed_image and check for Discord posts
            # This sets the path BEFORE checking for Discord, ensuring it's available
            def update_discord_state():
                self.app.last_processed_image = output_path
                
                # Post first image to Discord (only once per session)
                if not self.app.first_image_posted_to_discord and self.app.discord_enabled_var.get() and self.app.discord_periodic_enabled_var.get():
                    self.app.first_image_posted_to_discord = True
                    app_logger.info(f"Posting first image to Discord: {output_path}")
                    self.app.output_manager._post_periodic_discord_update()
            
            self.app.root.after(0, update_discord_state)
            
            # Periodically cleanup overlay cache
            self._cleanup_overlay_cache()
            
        except Exception as e:
            app_logger.error(f"Processing failed: {e}")
            app_logger.error(traceback.format_exc())
    
    def refresh_preview(self, auto_fit=True):
        """Refresh preview display"""
        # Use the last processed image or last captured image
        if not self.app.preview_image:
            # Try to load the last processed image file
            if self.app.last_processed_image and os.path.exists(self.app.last_processed_image):
                try:
                    self.app.preview_image = Image.open(self.app.last_processed_image)
                except Exception as e:
                    app_logger.error(f"Failed to load preview: {e}")
                    return
            else:
                return
        
        try:
            # Apply auto brightness and saturation adjustments (for display only)
            display_base = self.app.preview_image.copy()
            
            # Apply auto-stretch (MTF) if enabled - BEFORE brightness/saturation (same as save pipeline)
            auto_stretch_config = self.app.config.get('auto_stretch', {})
            if auto_stretch_config.get('enabled', False):
                display_base = auto_stretch_image(display_base, auto_stretch_config)
            
            # Apply brightness adjustment
            if self.app.auto_brightness_var.get():
                # Analyze brightness
                img_array = np.array(display_base.convert('L'))
                mean_brightness = np.mean(img_array)
                target_brightness = 128
                auto_factor = target_brightness / max(mean_brightness, 10)
                auto_factor = max(0.5, min(auto_factor, 4.0))
                
                # Apply manual multiplier
                manual_factor = self.app.brightness_var.get()
                final_factor = auto_factor * manual_factor
                
                enhancer = ImageEnhance.Brightness(display_base)
                display_base = enhancer.enhance(final_factor)
            
            # Apply saturation adjustment
            saturation_factor = self.app.saturation_var.get()
            if saturation_factor != 1.0:
                enhancer = ImageEnhance.Color(display_base)
                display_base = enhancer.enhance(saturation_factor)
            
            # Add overlays for preview (same as saved image)
            from services.processor import add_overlays
            overlays = self.app.overlay_manager.get_overlays_config()
            # Use real metadata if available, otherwise create empty metadata
            if hasattr(self.app, 'preview_metadata') and self.app.preview_metadata:
                preview_metadata = self.app.preview_metadata
            else:
                # Fallback for when no image has been captured yet
                preview_metadata = {
                    'CAMERA': 'No Image',
                    'EXPOSURE': '0',
                    'GAIN': '0',
                    'TEMP': '0',
                    'RES': f'{display_base.width}x{display_base.height}',
                    'FILENAME': 'preview.jpg',
                    'SESSION': 'preview',
                    'DATETIME': ''
                }
            display_base = add_overlays(display_base, overlays, preview_metadata, weather_service=self.app.weather_service)
            
            # Auto-fit: calculate zoom to fit image in canvas
            if auto_fit:
                canvas_width = self.app.preview_canvas.winfo_width()
                canvas_height = self.app.preview_canvas.winfo_height()
                
                # Only auto-fit if canvas has been sized (not 1x1)
                if canvas_width > 1 and canvas_height > 1:
                    # Calculate zoom to fit while maintaining aspect ratio
                    zoom_x = (canvas_width - 20) / display_base.width
                    zoom_y = (canvas_height - 20) / display_base.height
                    zoom = min(zoom_x, zoom_y, 1.0)  # Don't zoom beyond 100%
                    
                    # Update the zoom slider
                    zoom_percent = int(zoom * 100)
                    if zoom_percent >= 10:  # Ensure it's within slider range
                        self.app.preview_zoom_var.set(zoom_percent)
            
            zoom = self.app.preview_zoom_var.get() / 100.0
            new_size = (int(display_base.width * zoom), int(display_base.height * zoom))
            display_img = display_base.resize(new_size, Image.Resampling.LANCZOS)
            
            # Clean up old preview photo to prevent memory leak
            if hasattr(self.app, 'preview_photo') and self.app.preview_photo:
                try:
                    del self.app.preview_photo
                except:
                    pass
            
            self.app.preview_photo = ImageTk.PhotoImage(display_img)
            self.app.preview_canvas.delete('all')
            self.app.preview_canvas.create_image(0, 0, anchor='nw', image=self.app.preview_photo)
            self.app.preview_canvas.config(scrollregion=self.app.preview_canvas.bbox('all'))
            
            # Clean up temporary images
            del display_img
            del display_base
        except Exception as e:
            app_logger.error(f"Preview refresh failed: {e}")
    
    def update_overlay_preview(self):
        """Update the overlay preview with debouncing"""
        # Prevent recursive/multiple simultaneous updates
        if self.preview_update_pending:
            return
        
        self.preview_update_pending = True
        
        try:
            # Create sample sky image
            preview_img = Image.new('RGB', (600, 400), color='#0a0e27')
            draw = ImageDraw.Draw(preview_img)
            
            # Add some stars
            random.seed(42)
            for _ in range(50):
                x = random.randint(0, 600)
                y = random.randint(0, 400)
                brightness = random.randint(150, 255)
                draw.ellipse([x-1, y-1, x+1, y+1], fill=(brightness, brightness, brightness))
            
            # Get current overlay config from editor
            if self.app.selected_overlay_index is not None:
                overlays = self.app.overlay_manager.get_overlays_config()
                if 0 <= self.app.selected_overlay_index < len(overlays):
                    current_overlay = overlays[self.app.selected_overlay_index]
                    overlay_type = current_overlay.get('type', 'text')
                    
                    if overlay_type == 'image':
                        # Use saved overlay config with live editor updates
                        overlay_config = current_overlay.copy()
                        # Override with current editor values for live preview
                        try:
                            overlay_config['width'] = self.app.overlay_image_width_var.get() if hasattr(self.app, 'overlay_image_width_var') else overlay_config.get('width', 100)
                        except:
                            overlay_config['width'] = overlay_config.get('width', 100)
                        try:
                            overlay_config['height'] = self.app.overlay_image_height_var.get() if hasattr(self.app, 'overlay_image_height_var') else overlay_config.get('height', 100)
                        except:
                            overlay_config['height'] = overlay_config.get('height', 100)
                        try:
                            overlay_config['opacity'] = self.app.overlay_image_opacity_var.get() if hasattr(self.app, 'overlay_image_opacity_var') else overlay_config.get('opacity', 100)
                        except:
                            overlay_config['opacity'] = overlay_config.get('opacity', 100)
                        
                        overlay_config['anchor'] = self.app.anchor_var.get()
                        # Handle empty offset values (default to 0 or existing value)
                        try:
                            offset_x_str = self.app.offset_x_var.get()
                            overlay_config['offset_x'] = int(offset_x_str) if offset_x_str else overlay_config.get('offset_x', 0)
                        except (ValueError, TclError):
                            overlay_config['offset_x'] = overlay_config.get('offset_x', 0)
                        try:
                            offset_y_str = self.app.offset_y_var.get()
                            overlay_config['offset_y'] = int(offset_y_str) if offset_y_str else overlay_config.get('offset_y', 0)
                        except (ValueError, TclError):
                            overlay_config['offset_y'] = overlay_config.get('offset_y', 0)
                    else:
                        # Get datetime format from editor
                        mode = self.app.datetime_mode_var.get()
                        if mode == 'custom':
                            datetime_format = self.app.datetime_custom_var.get()
                        elif hasattr(self.app, 'datetime_locale_var'):
                            # Use locale-specific formats
                            from .overlays.constants import LOCALE_FORMATS
                            locale = self.app.datetime_locale_var.get()
                            locale_data = LOCALE_FORMATS.get(locale, {'date': '%Y-%m-%d', 'time': '%H:%M:%S', 'datetime': '%Y-%m-%d %H:%M:%S'})
                            if mode == 'date':
                                datetime_format = locale_data['date']
                            elif mode == 'time':
                                datetime_format = locale_data['time']
                            else:  # full
                                datetime_format = locale_data['datetime']
                        else:
                            from .overlays.constants import DATETIME_FORMATS
                            datetime_format = DATETIME_FORMATS.get(mode, '%Y-%m-%d %H:%M:%S')
                        
                        # Handle empty offset values for text overlays
                        try:
                            offset_x_str = self.app.offset_x_var.get()
                            offset_x = int(offset_x_str) if offset_x_str else current_overlay.get('offset_x', 10)
                        except (ValueError, TclError):
                            offset_x = current_overlay.get('offset_x', 10)
                        try:
                            offset_y_str = self.app.offset_y_var.get()
                            offset_y = int(offset_y_str) if offset_y_str else current_overlay.get('offset_y', 10)
                        except (ValueError, TclError):
                            offset_y = current_overlay.get('offset_y', 10)
                        
                        overlay_config = {
                            'type': 'text',
                            'text': self.app.overlay_text.get('1.0', 'end-1c'),
                            'anchor': self.app.anchor_var.get(),
                            'color': self.app.color_var.get(),
                            'font_size': self.app.font_size_var.get(),
                            'font_style': self.app.font_style_var.get(),
                            'offset_x': offset_x,
                            'offset_y': offset_y,
                            'background_enabled': self.app.background_enabled_var.get(),
                            'background_color': self.app.bg_color_var.get(),
                            'datetime_format': datetime_format
                        }
                    
                    # Sample metadata for token replacement
                    metadata = {
                        'CAMERA': 'ASI676MC',
                        'EXPOSURE': '100ms',
                        'GAIN': '150',
                        'TEMP': '-5.2°C',
                        'RES': '3840x2160',
                        'FILENAME': 'preview.fits',
                        'SESSION': datetime.now().strftime('%Y-%m-%d')
                    }
                    
                    # Apply overlay
                    preview_img = add_overlays(preview_img, [overlay_config], metadata, image_cache=self.overlay_image_cache, weather_service=self.app.weather_service)
            
            # Resize to fit canvas
            preview_img.thumbnail((580, 380), Image.Resampling.LANCZOS)
            
            # Clean up old overlay preview photo to prevent memory leak
            if hasattr(self.app, 'overlay_preview_photo') and self.app.overlay_preview_photo:
                try:
                    del self.app.overlay_preview_photo
                except:
                    pass
            
            # Display in canvas
            photo = ImageTk.PhotoImage(preview_img)
            self.app.overlay_preview_canvas.delete('all')
            self.app.overlay_preview_canvas.create_image(290, 190, image=photo, anchor='center')
            self.app.overlay_preview_photo = photo  # Keep reference
            
            # Clean up temporary image
            del preview_img
            
        except Exception as e:
            app_logger.error(f"Preview update failed: {e}")
            app_logger.error(traceback.format_exc())
        finally:
            # Reset pending flag after a short delay
            self.app.root.after(100, lambda: setattr(self, 'preview_update_pending', False))
