"""
Status and monitoring module
Handles status updates, logging, and live monitoring
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
    
    def update_mini_preview(self, img):
        """Update mini preview in header"""
        try:
            # Apply auto brightness if enabled
            preview_img = img.copy()
            if self.app.auto_brightness_var.get():
                from PIL import ImageEnhance
                import numpy as np
                
                # Analyze brightness
                img_array = np.array(preview_img.convert('L'))
                mean_brightness = np.mean(img_array)
                target_brightness = 128
                auto_factor = target_brightness / max(mean_brightness, 10)
                auto_factor = max(0.5, min(auto_factor, 4.0))
                
                # Apply manual multiplier
                manual_factor = self.app.brightness_var.get()
                final_factor = auto_factor * manual_factor
                
                enhancer = ImageEnhance.Brightness(preview_img)
                preview_img = enhancer.enhance(final_factor)
            
            # Resize to fit
            thumb = preview_img
            thumb.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(thumb)
            self.app.mini_preview_label.config(image=photo, text='')
            self.app.mini_preview_image = photo  # Keep reference
            
            # Update histogram
            self.update_histogram(img)
            
        except Exception as e:
            app_logger.error(f"Mini preview update failed: {e}")
    
    def update_histogram(self, img):
        """Update RGB histogram"""
        try:
            # Get RGB data
            img_array = np.array(img)
            
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
            
            # Draw histograms
            width = self.app.histogram_canvas.winfo_width()
            if width <= 1:
                width = 600
            bin_width = width / 256
            
            for i in range(256):
                x = i * bin_width
                # Red
                self.app.histogram_canvas.create_line(x, 100, x, 100 - hist_r[i], fill='#ff6b6b', width=bin_width)
                # Green (with transparency effect)
                self.app.histogram_canvas.create_line(x, 100, x, 100 - hist_g[i], fill='#51cf66', width=bin_width)
                # Blue
                self.app.histogram_canvas.create_line(x, 100, x, 100 - hist_b[i], fill='#339af0', width=bin_width)
            
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
            self.app.root.after(100, self.poll_logs)
    
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
