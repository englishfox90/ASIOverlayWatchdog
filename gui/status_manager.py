"""
Status and monitoring module
Handles status updates, logging, and live monitoring

SINGLE-STRETCH ARCHITECTURE: Mini preview is updated from image_processor
after the single stretch operation, avoiding redundant processing.
"""
import numpy as np
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from pathlib import Path
from datetime import datetime
from services.logger import app_logger


class StatusManager:
    """Manages status updates, logging, and live monitoring"""
    
    def __init__(self, app):
        self.app = app
        # Track if a mini preview update is pending to avoid queue buildup
        self._mini_preview_pending = False
    
    def update_status_header(self):
        """Update status header periodically"""
        try:
            # Mode status with color indicator
            if self.app.watcher and self.app.watcher.observer.is_alive():
                mode = "Directory Watch - Running"
                info = f"Watching: {self.app.watch_dir_var.get()}"
                self.app.status_header.set_status_color('capturing')
            elif self.app.camera_controller.zwo_camera and self.app.camera_controller.zwo_camera.camera:
                mode = "ZWO Camera - Capturing"
                cam_name = self.app.camera_list_var.get().split(' (')[0] if self.app.camera_list_var.get() else "Unknown"
                # Get actual exposure from camera (auto-exposure may have changed it)
                zwo = self.app.camera_controller.zwo_camera
                actual_exp_sec = zwo.exposure_seconds
                
                # Format exposure intelligently
                if actual_exp_sec >= 60:
                    exp_display = f"{actual_exp_sec / 60:.2f}m"
                elif actual_exp_sec >= 1:
                    exp_display = f"{actual_exp_sec:.2f}s"
                else:
                    exp_display = f"{actual_exp_sec * 1000:.2f}ms"
                
                # Show countdown if exposing
                if zwo.exposure_start_time and zwo.exposure_remaining > 0:
                    if zwo.exposure_remaining >= 60:
                        countdown = f" ({zwo.exposure_remaining / 60:.2f}m left)"
                    elif zwo.exposure_remaining >= 1:
                        countdown = f" ({zwo.exposure_remaining:.1f}s left)"
                    else:
                        countdown = f" ({zwo.exposure_remaining * 1000:.0f}ms left)"
                else:
                    countdown = ""
                
                info = f"{cam_name} • Exposure: {exp_display}{countdown} • Gain: {self.app.gain_var.get()}"
                self.app.status_header.set_status_color('capturing')
                
                # Update exposure progress bar
                self.app.status_header.update_exposure_progress(
                    actual_exp_sec, 
                    zwo.exposure_remaining
                )
            else:
                mode = "Idle"
                info = "No active session"
                self.app.status_header.set_status_color('idle')
            
            self.app.mode_status_var.set(mode)
            self.app.capture_info_var.set(info)
            
            # Output info with truncation
            output_dir = self.app.output_dir_var.get()
            if output_dir:
                self.app.status_header.update_output_path(output_dir)
            else:
                self.app.status_header.update_output_path("Not configured")
            
        except Exception as e:
            app_logger.error(f"Status update failed: {e}")
            self.app.status_header.set_status_color('error')
        finally:
            # Update faster during camera capture for smoother countdown
            is_capturing = (self.app.camera_controller.zwo_camera and 
                          self.app.camera_controller.zwo_camera.camera)
            update_interval = 200 if is_capturing else 1000  # 200ms when capturing, 1s otherwise
            self.app.root.after(update_interval, self.update_status_header)
    
    def _do_mini_preview_gui_update(self, photo, hist_data):
        """Update GUI with processed mini preview - runs on UI thread
        
        Called from image_processor._update_mini_preview_from_stretched()
        """
        try:
            # Clean up old image references to prevent memory leak
            if hasattr(self.app, 'mini_preview_image') and self.app.mini_preview_image:
                try:
                    del self.app.mini_preview_image
                except:
                    pass
            
            self.app.mini_preview_label.config(image=photo, text='')
            self.app.mini_preview_image = photo  # Keep reference
            
            # Update histogram from pre-calculated data
            self._draw_histogram(hist_data)
            
            self._mini_preview_pending = False
            
        except Exception as e:
            app_logger.error(f"Mini preview GUI update failed: {e}")
            self._mini_preview_pending = False
    
    def _draw_histogram(self, hist_data):
        """Draw pre-calculated histogram data to canvas - runs on UI thread"""
        try:
            hist_r, hist_g, hist_b = hist_data['r'], hist_data['g'], hist_data['b']
            auto_exposure = hist_data.get('auto_exposure', False)
            target_brightness = hist_data.get('target_brightness', 100)
            
            # Clear canvas
            self.app.histogram_canvas.delete('all')
            
            # Calculate bin width
            width = self.app.histogram_canvas.winfo_width()
            if width <= 1:
                width = 600
            bin_width = width / 256
            
            # Build coordinate lists for each channel
            red_coords = []
            green_coords = []
            blue_coords = []
            
            for i in range(256):
                x = i * bin_width
                red_coords.extend([x, 100 - hist_r[i]])
                green_coords.extend([x, 100 - hist_g[i]])
                blue_coords.extend([x, 100 - hist_b[i]])
            
            # Draw as smooth lines
            if len(red_coords) >= 4:
                self.app.histogram_canvas.create_line(red_coords, fill='#ff6b6b', width=2, smooth=False)
                self.app.histogram_canvas.create_line(green_coords, fill='#51cf66', width=2, smooth=False)
                self.app.histogram_canvas.create_line(blue_coords, fill='#339af0', width=2, smooth=False)
            
            # Draw target brightness line if auto exposure is enabled
            if auto_exposure:
                target_x = (target_brightness / 255.0) * width
                
                self.app.histogram_canvas.create_line(
                    target_x, 0, target_x, 100,
                    fill='#ffd700', width=2, dash=(4, 2)
                )
                
                self.app.histogram_canvas.create_text(
                    target_x, 5,
                    text=f'Target: {int(target_brightness)}',
                    fill='#ffd700',
                    font=('Segoe UI', 8, 'bold'),
                    anchor='n'
                )
                
                # Draw clipping threshold line (245)
                clip_x = (245 / 255.0) * width
                self.app.histogram_canvas.create_line(
                    clip_x, 0, clip_x, 100,
                    fill='#ff4444', width=1, dash=(2, 2)
                )
                
                self.app.histogram_canvas.create_text(
                    clip_x, 15,
                    text='Clip',
                    fill='#ff4444',
                    font=('Segoe UI', 7),
                    anchor='n'
                )
                
        except Exception as e:
            app_logger.error(f"Histogram draw failed: {e}")
    
    def update_histogram(self, img):
        """Update RGB histogram - legacy method, prefer using mini_preview queue
        
        This is kept for backwards compatibility and manual histogram updates.
        During camera capture, histogram is updated via the background thread.
        """
        try:
            # PERF-001: Use asarray for view (no copy) - histogram is read-only
            img_array = np.asarray(img)
            
            # Calculate histograms
            hist_r = np.histogram(img_array[:, :, 0], bins=256, range=(0, 256))[0]
            hist_g = np.histogram(img_array[:, :, 1], bins=256, range=(0, 256))[0]
            hist_b = np.histogram(img_array[:, :, 2], bins=256, range=(0, 256))[0]
            
            # Normalize
            max_val = max(hist_r.max(), hist_g.max(), hist_b.max())
            if max_val > 0:
                hist_r = (hist_r / max_val * 90).astype(int)
                hist_g = (hist_g / max_val * 90).astype(int)
                hist_b = (hist_b / max_val * 90).astype(int)
            
            # Clear canvas
            self.app.histogram_canvas.delete('all')
            
            # Draw histograms as line graphs
            width = self.app.histogram_canvas.winfo_width()
            if width <= 1:
                width = 600
            bin_width = width / 256
            
            # Build coordinate lists for each channel
            red_coords = []
            green_coords = []
            blue_coords = []
            
            for i in range(256):
                x = i * bin_width
                red_coords.extend([x, 100 - hist_r[i]])
                green_coords.extend([x, 100 - hist_g[i]])
                blue_coords.extend([x, 100 - hist_b[i]])
            
            # Draw as smooth lines (red first so it's in back, blue last so it's on top)
            if len(red_coords) >= 4:  # Need at least 2 points
                self.app.histogram_canvas.create_line(red_coords, fill='#ff6b6b', width=2, smooth=False)
                self.app.histogram_canvas.create_line(green_coords, fill='#51cf66', width=2, smooth=False)
                self.app.histogram_canvas.create_line(blue_coords, fill='#339af0', width=2, smooth=False)
            
            # Draw target brightness line if auto exposure is enabled
            if hasattr(self.app, 'auto_exposure_var') and self.app.auto_exposure_var.get():
                target = self.app.target_brightness_var.get() if hasattr(self.app, 'target_brightness_var') else 100
                # Convert target brightness (0-255) to x position
                target_x = (target / 255.0) * width
                
                # Draw vertical line at target position
                self.app.histogram_canvas.create_line(
                    target_x, 0, target_x, 100,
                    fill='#ffd700',  # Gold color
                    width=2,
                    dash=(4, 2)  # Dashed line
                )
                
                # Add label above the line
                self.app.histogram_canvas.create_text(
                    target_x, 5,
                    text=f'Target: {int(target)}',
                    fill='#ffd700',
                    font=('Segoe UI', 8, 'bold'),
                    anchor='n'
                )
                
                # Draw clipping threshold line (245)
                clip_x = (245 / 255.0) * width
                self.app.histogram_canvas.create_line(
                    clip_x, 0, clip_x, 100,
                    fill='#ff4444',  # Red color for warning
                    width=1,
                    dash=(2, 2)  # Shorter dashed line
                )
                
                # Add small label for clipping threshold
                self.app.histogram_canvas.create_text(
                    clip_x, 15,
                    text='Clip',
                    fill='#ff4444',
                    font=('Segoe UI', 7),
                    anchor='n'
                )
            
        except Exception as e:
            app_logger.error(f"Histogram update failed: {e}")
    
    def poll_logs(self):
        """Poll log queue and update displays"""
        try:
            messages = app_logger.get_messages()
            for message in messages:
                # Parse level from message format: "[HH:MM:SS] LEVEL: message"
                parts = message.split(':', 2)
                if len(parts) >= 3:
                    level_part = parts[1].strip()
                    msg_part = parts[2].strip() if len(parts) > 2 else message
                else:
                    level_part = "INFO"
                    msg_part = message
                
                # Update main log
                self.app.log_text.config(state='normal')
                self.app.log_text.insert('end', f"{message}\n", level_part)
                if self.app.auto_scroll_var.get():
                    self.app.log_text.see('end')
                self.app.log_text.config(state='disabled')
                
                # Update mini log (keep last 10 lines)
                self.app.mini_log_text.config(state='normal')
                content = self.app.mini_log_text.get('1.0', 'end')
                lines = content.strip().split('\n')
                if len(lines) >= 10:
                    lines = lines[-9:]
                lines.append(msg_part if msg_part else message)
                self.app.mini_log_text.delete('1.0', 'end')
                self.app.mini_log_text.insert('1.0', '\n'.join(lines))
                self.app.mini_log_text.see('end')
                self.app.mini_log_text.config(state='disabled')
                    
        except Exception as e:
            print(f"Log polling error: {e}")
        finally:
            # Poll at 250ms (4 times/second) - sufficient for log updates, reduces CPU usage
            self.app.root.after(250, self.poll_logs)
    
    def clear_logs(self):
        """Clear log display"""
        self.app.log_text.config(state='normal')
        self.app.log_text.delete('1.0', 'end')
        self.app.log_text.config(state='disabled')
    
    def save_logs(self):
        """Save consolidated logs from file to a user-selected location"""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Read all log files from the log directory and concatenate
                log_dir = Path(app_logger.get_log_dir())
                log_files = sorted(log_dir.glob('watchdog.log*'))
                
                if not log_files:
                    messagebox.showwarning("No Logs", "No log files found to save.")
                    return
                
                # Concatenate all log files (oldest to newest)
                with open(file_path, 'w', encoding='utf-8') as out_file:
                    out_file.write("=== ASIOverlayWatchDog - Consolidated Logs ===\n")
                    out_file.write(f"Saved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    out_file.write(f"Log Directory: {log_dir}\n")
                    out_file.write("=" * 60 + "\n\n")
                    
                    for log_file in log_files:
                        out_file.write(f"\n--- {log_file.name} ---\n")
                        try:
                            with open(log_file, 'r', encoding='utf-8') as in_file:
                                out_file.write(in_file.read())
                        except Exception as e:
                            out_file.write(f"[Error reading {log_file.name}: {e}]\n")
                
                app_logger.info(f"Logs saved to: {file_path} ({len(log_files)} files)")
                messagebox.showinfo("Success", f"Saved {len(log_files)} log file(s) to:\n{file_path}")
            except Exception as e:
                app_logger.error(f"Failed to save logs: {e}")
                messagebox.showerror("Error", f"Failed to save logs:\n{str(e)}")
