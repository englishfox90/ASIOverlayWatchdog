"""
Image processing module
Handles image processing, overlays, and preview generation
"""
import os
import random
from datetime import datetime
from tkinter import TclError
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageTk
from services.processor import add_overlays, auto_stretch_image
from services.logger import app_logger
import traceback


class ImageProcessor:
    """Manages image processing and preview generation"""
    
    def __init__(self, app):
        self.app = app        # Preview caching to avoid re-reading from disk
        self.preview_cache = None
        self.preview_cache_path = None
        # Cache for overlay images with size limit
        self.overlay_image_cache = {}
        self.overlay_cache_max_size = 10  # Limit cache to 10 images
        self.preview_update_pending = False
    
    def _cleanup_overlay_cache(self):
        """Remove oldest entries from overlay cache if it exceeds size limit"""
        if len(self.overlay_image_cache) > self.overlay_cache_max_size:
            # Remove excess entries (FIFO)
            excess = len(self.overlay_image_cache) - self.overlay_cache_max_size
            keys_to_remove = list(self.overlay_image_cache.keys())[:excess]
            for key in keys_to_remove:
                del self.overlay_image_cache[key]
            app_logger.debug(f"Cleaned up overlay cache: removed {excess} entries")    
    def process_and_save_image(self, img, metadata):
        """Process image with overlays and save"""
        try:
            # Get config
            overlays = self.app.overlay_manager.get_overlays_config()
            output_dir = self.app.output_dir_var.get()
            output_format = self.app.output_format_var.get()
            jpg_quality = self.app.jpg_quality_var.get()
            resize_percent = self.app.resize_percent_var.get()
            auto_brightness = self.app.auto_brightness_var.get()
            brightness_factor = self.app.brightness_var.get() if auto_brightness else None
            timestamp_corner = self.app.timestamp_corner_var.get()
            filename_pattern = self.app.filename_pattern_var.get()
            
            if not output_dir:
                app_logger.error("Output directory not configured")
                return
            
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Resize if needed
            if resize_percent < 100:
                new_width = int(img.width * resize_percent / 100)
                new_height = int(img.height * resize_percent / 100)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Apply auto-stretch (MTF) if enabled - BEFORE brightness/saturation/overlays
            auto_stretch_config = self.app.config.get('auto_stretch', {})
            if auto_stretch_config.get('enabled', False):
                img = auto_stretch_image(img, auto_stretch_config)
                app_logger.debug("Applied auto-stretch to camera capture")
            
            # Apply auto brightness if enabled (with proper analysis)
            if auto_brightness:
                from PIL import ImageEnhance
                import numpy as np
                
                # PERF-001: Analyze brightness using view (no copy)
                gray_img = img.convert('L')  # Grayscale for analysis
                img_array = np.asarray(gray_img)  # View, not copy
                mean_brightness = np.mean(img_array)
                del gray_img  # Release grayscale image early
                
                # Calculate adaptive enhancement factor
                # Target brightness: 128 (mid-gray)
                target_brightness = 128
                auto_factor = target_brightness / max(mean_brightness, 10)  # Avoid division by zero
                
                # Clamp factor to reasonable range (0.5 - 4.0)
                auto_factor = max(0.5, min(auto_factor, 4.0))
                
                # Apply manual brightness factor as additional adjustment
                manual_factor = brightness_factor if brightness_factor else 1.0
                final_factor = auto_factor * manual_factor
                
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(final_factor)
                
                app_logger.debug(f"Auto brightness: mean={mean_brightness:.1f}, auto={auto_factor:.2f}, manual={manual_factor:.2f}, final={final_factor:.2f}")
            
            # Apply saturation adjustment
            saturation_factor = self.app.saturation_var.get()
            if saturation_factor != 1.0:
                from PIL import ImageEnhance
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
                # Top-right corner
                draw.text((img.width - 200, 10), timestamp_text, fill='white', font=font)
            
            # Add overlays (pass weather_service for weather tokens)
            img = add_overlays(img, overlays, metadata, weather_service=self.app.weather_service)
            
            # Generate output filename
            session = metadata.get('session', datetime.now().strftime('%Y-%m-%d'))
            original_filename = metadata.get('FILENAME', 'capture.png')
            base_filename = os.path.splitext(original_filename)[0]
            
            # Replace tokens in filename pattern
            output_filename = filename_pattern.replace('{filename}', base_filename)
            output_filename = output_filename.replace('{session}', session)
            output_filename = output_filename.replace('{timestamp}', datetime.now().strftime('%Y%m%d_%H%M%S'))
            
            # Add extension
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
            
            self.app.last_processed_image = output_path
            
            # Clean up old preview image to prevent memory accumulation
            if hasattr(self.app, 'preview_image') and self.app.preview_image:
                try:
                    del self.app.preview_image
                except:
                    pass
            
            # Store the ORIGINAL image before brightness/saturation for preview
            # Preview will apply adjustments on top of this clean base
            if resize_percent < 100:
                new_width = int(self.app.last_captured_image.width * resize_percent / 100)
                new_height = int(self.app.last_captured_image.height * resize_percent / 100)
                self.app.preview_image = self.app.last_captured_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            else:
                self.app.preview_image = self.app.last_captured_image.copy()
            
            # Store metadata for preview overlay rendering
            self.app.preview_metadata = metadata.copy()
            
            app_logger.info(f"Saved: {os.path.basename(output_path)}")
            
            # Push to output servers if active - pass the processed image directly
            # to avoid re-reading from disk and double-compressing JPGs
            self.app._push_to_output_servers(output_path, img)
            
            # Clean up the processed image object (we only need the file path now)
            del img
            
            # Check if Discord periodic update should be sent
            self.app.check_discord_periodic_send(output_path)
            
            # Auto-refresh preview if enabled
            if self.app.auto_refresh_var.get():
                self.app.root.after(0, lambda: self.refresh_preview(auto_fit=True))
            
            # Periodically cleanup overlay cache to prevent memory growth
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
            from PIL import ImageEnhance
            
            # Apply auto-stretch (MTF) if enabled - BEFORE brightness/saturation (same as save pipeline)
            auto_stretch_config = self.app.config.get('auto_stretch', {})
            if auto_stretch_config.get('enabled', False):
                display_base = auto_stretch_image(display_base, auto_stretch_config)
            
            # Apply brightness adjustment
            if self.app.auto_brightness_var.get():
                import numpy as np
                
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
