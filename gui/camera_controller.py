"""
Camera controller module
Handles ZWO camera operations
"""
import os
import threading
import tkinter as tk
from services.logger import app_logger
from services.zwo_camera import ZWOCamera
from .camera_settings import CameraSettings


class CameraController:
    """Manages ZWO camera detection and capture"""
    
    def __init__(self, app):
        self.app = app
        self.zwo_camera = None
    
    def detect_cameras(self):
        """Detect connected ZWO cameras (non-blocking)"""
        app_logger.info("=== Camera Detection Initiated ===")
        
        # Show spinner
        self.app.capture_tab.show_detection_spinner()
        self.app.capture_tab.clear_detection_error()
        
        # Run detection in thread to avoid blocking UI
        def detect_thread():
            sdk_path = self.app.sdk_path_var.get()
            
            # Validate SDK path first
            if not sdk_path:
                app_logger.error("Detection failed: SDK path not specified")
                self.app.root.after(0, lambda: self._on_detection_complete([], "SDK path not specified"))
                return
            
            if not os.path.exists(sdk_path):
                app_logger.error(f"Detection failed: SDK file not found at: {sdk_path}")
                self.app.root.after(0, lambda: self._on_detection_complete([], f"SDK file not found: {sdk_path}"))
                return
            
            try:
                import zwoasi as asi
                app_logger.info("zwoasi module imported successfully")
                app_logger.info("Starting camera detection...")
                
                # Initialize SDK
                try:
                    app_logger.debug(f"Initializing ASI SDK from: {sdk_path}")
                    asi.init(sdk_path)
                    app_logger.info(f"✓ ASI SDK initialized successfully: {sdk_path}")
                except Exception as init_error:
                    # SDK already initialized or initialization failed
                    if "already" not in str(init_error).lower():
                        error_msg = f"SDK initialization failed: {str(init_error)}"
                        app_logger.error(error_msg)
                        import traceback
                        app_logger.debug(f"Stack trace: {traceback.format_exc()}")
                        self.app.root.after(0, lambda: self._on_detection_complete([], error_msg))
                        return
                    else:
                        app_logger.debug("SDK already initialized (reusing existing instance)")
                
                app_logger.debug("Querying SDK for number of connected cameras...")
                num_cameras = asi.get_num_cameras()
                app_logger.info(f"SDK reports {num_cameras} camera(s) connected")
                
                if num_cameras == 0:
                    app_logger.warning("No cameras detected - check USB connection")
                    self.app.root.after(0, lambda: self._on_detection_complete([], "No cameras detected. Check USB connection."))
                    return
                
                camera_list = []
                # Use asi.list_cameras() to retrieve camera info WITHOUT opening them
                for i in range(num_cameras):
                    try:
                        camera_name = asi.list_cameras()[i]
                        camera_list.append(f"{camera_name} (Index: {i})")
                        app_logger.info(f"Camera {i}: {camera_name}")
                    except Exception as cam_error:
                        app_logger.warning(f"Could not retrieve name for camera {i}: {cam_error}")
                        camera_list.append(f"Camera {i}")
                
                if camera_list:
                    app_logger.info(f"Camera detection complete: {len(camera_list)} camera(s) found")
                    self.app.root.after(0, lambda: self._on_detection_complete(camera_list, None))
                else:
                    self.app.root.after(0, lambda: self._on_detection_complete([], "No valid cameras found"))
                
            except Exception as e:
                error_msg = f"Detection error: {str(e)}"
                app_logger.error(f"Camera detection failed: {error_msg}")
                import traceback
                app_logger.debug(f"Stack trace: {traceback.format_exc()}")
                self.app.root.after(0, lambda: self._on_detection_complete([], error_msg))
        
        # Start detection thread with timeout
        detection_thread = threading.Thread(target=detect_thread, daemon=True)
        detection_thread.start()
        
        def timeout_monitor():
            detection_thread.join(timeout=10.0)
            if detection_thread.is_alive():
                app_logger.error("Camera detection timed out after 10 seconds")
                self.app.root.after(0, lambda: self._on_detection_complete(
                    [], "Detection timed out. Camera may be in use."))
        
        threading.Thread(target=timeout_monitor, daemon=True).start()
    
    def _on_detection_complete(self, camera_list, error_msg):
        """Handle camera detection completion"""
        self.app.capture_tab.hide_detection_spinner()
        
        if error_msg:
            self.app.capture_tab.show_detection_error(error_msg)
            app_logger.error(f"Camera detection failed: {error_msg}")
            self.app.camera_combo['values'] = []
            self.app.start_capture_button.config(state='disabled', cursor='')
        else:
            self.app.camera_combo['values'] = camera_list
            if camera_list:
                self.app.camera_combo.current(0)
                self.app.selected_camera_index = 0
                app_logger.debug("Selected first camera by default")
            
            # Try to restore previously selected camera (prefer name match for stability)
            saved_camera_name = self.app.config.get('zwo_selected_camera_name', '')
            saved_index = self.app.config.get('zwo_selected_camera', 0)
            
            # First try to match by name (most reliable with multiple cameras)
            matched_by_name = False
            if saved_camera_name:
                for idx, camera in enumerate(camera_list):
                    if saved_camera_name == camera:  # Exact match: "ASI676MC (Index: 0)"
                        self.app.camera_combo.current(idx)
                        self.app.selected_camera_index = idx
                        app_logger.info(f"✓ Restored camera by name: {saved_camera_name}")
                        matched_by_name = True
                        break
            
            # Fallback to index if name match fails (handles camera list changes)
            if not matched_by_name and saved_index < len(camera_list):
                self.app.camera_combo.current(saved_index)
                self.app.selected_camera_index = saved_index
                app_logger.info(f"Restored camera by index: {saved_index} ({camera_list[saved_index]})")
            
            if camera_list:
                self.app.start_capture_button.config(state='normal', cursor='hand2')
                self.app.capture_tab.clear_detection_error()
                app_logger.info(f"✓ Camera detection successful: {len(camera_list)} camera(s) ready")
    
    def start_camera_capture(self):
        """Start ZWO camera capture"""
        app_logger.info("=== Starting Camera Capture ===")
        
        try:
            # Ensure output servers are started if configured
            self.app.ensure_output_mode_started()
            
            # Show connecting status
            self.app.camera_status_var.set("Connecting...")
            self.set_camera_status_dot('connecting')
            self.app.status_header.set_status_color('connecting')
            
            # Validate camera selection
            if not self.app.camera_combo.get():
                app_logger.error("Cannot start capture: No camera selected")
                self.app.status_header.set_status_color('error')
                return
            
            selected_camera = self.app.camera_combo.get()
            app_logger.info(f"Selected camera: {selected_camera}")
            app_logger.info(f"Camera index: {self.app.selected_camera_index}")
            
            # Get settings using CameraSettings dataclass (MAINT-002)
            sdk_path = self.app.sdk_path_var.get()
            app_logger.info(f"SDK path: {sdk_path}")
            
            settings = CameraSettings.from_app(self.app)
            settings.log_summary(app_logger)
            
            # Initialize camera
            app_logger.info("Initializing ZWOCamera instance...")
            
            self.zwo_camera = ZWOCamera(
                sdk_path=sdk_path,
                camera_index=self.app.selected_camera_index,
                exposure_sec=settings.exposure_sec,
                gain=settings.gain,
                white_balance_r=settings.wb_r,
                white_balance_b=settings.wb_b,
                offset=settings.offset,
                flip=settings.flip,
                auto_exposure=settings.auto_exposure,
                max_exposure_sec=settings.max_exposure_sec,
                auto_wb=False,  # Legacy parameter, WB now controlled by wb_mode
                wb_mode=settings.wb_config.get('mode', 'asi_auto'),
                wb_config=settings.wb_config,
                bayer_pattern=settings.bayer_pattern,
                scheduled_capture_enabled=settings.scheduled_capture_enabled,
                scheduled_start_time=settings.scheduled_start_time,
                scheduled_end_time=settings.scheduled_end_time,
                status_callback=self.app.update_camera_status_for_schedule,
                camera_name=settings.saved_camera_name,
                config_callback=lambda key, value: self._save_camera_config(key, value)
            )
            
            # Set target brightness
            self.zwo_camera.target_brightness = settings.target_brightness
            
            app_logger.info(f"Connecting to camera at index {self.app.selected_camera_index}...")
            if not self.zwo_camera.connect_camera(self.app.selected_camera_index):
                raise Exception("Failed to connect to camera (see above logs for details)")
            
            # Set capture interval
            self.zwo_camera.set_capture_interval(settings.interval)
            app_logger.info(f"Set capture interval to {settings.interval}s")
            
            # Set error callback for disconnect recovery
            self.zwo_camera.on_error_callback = self.on_camera_error
            
            # Start capture using built-in capture loop
            app_logger.info("Starting capture loop...")
            self.zwo_camera.start_capture(
                on_frame_callback=self.on_camera_frame,
                on_log_callback=lambda msg: app_logger.info(msg)
            )
            
            # Update UI
            self.app.is_capturing = True
            self.app.first_image_posted_to_discord = False  # Reset flag for new capture session
            self.app.start_capture_button.config(state='disabled', cursor='')
            self.app.stop_capture_button.config(state='normal', cursor='hand2')
            
            # Show camera name in status (retrieved during connection)
            camera_name = getattr(self.zwo_camera, 'camera_name', f'Camera {self.app.selected_camera_index}')
            self.app.camera_status_var.set(f"Capturing - {camera_name}")
            self.set_camera_status_dot('capturing')
            
            # Schedule Discord periodic updates with initial message
            self.app.output_manager.schedule_discord_periodic(send_initial=True)
            
            app_logger.info(f"✓ Camera capture started successfully: {camera_name}")
            
        except Exception as e:
            self.app.is_capturing = False
            app_logger.error(f"✗ Failed to start camera capture: {e}")
            import traceback
            app_logger.debug(f"Stack trace: {traceback.format_exc()}")
            app_logger.info("Troubleshooting: Check logs above for specific error details")
            self.app.camera_status_var.set(f"Error: {str(e)[:50]}...")
            self.set_camera_status_dot('error')
            self.app.status_header.set_status_color('error')
            self.app.start_capture_button.config(state='normal', cursor='hand2')
            self.app.stop_capture_button.config(state='disabled', cursor='')
    
    def stop_camera_capture(self):
        """Stop camera capture with proper cleanup and error handling"""
        app_logger.info("=== Stopping Camera Capture ===")
        self.app.is_capturing = False
        
        if self.zwo_camera:
            try:
                app_logger.info("Initiating camera disconnect sequence...")
                
                # Disconnect camera gracefully (includes stop_capture call)
                self.zwo_camera.disconnect_camera()
                
                # Wait briefly for cleanup to complete
                import time
                app_logger.debug("Waiting for cleanup to complete...")
                time.sleep(0.2)
                
                app_logger.info("✓ Camera disconnected successfully")
                
            except Exception as e:
                app_logger.error(f"✗ Error during camera disconnect: {e}")
                import traceback
                app_logger.debug(f"Stack trace: {traceback.format_exc()}")
            finally:
                # Always clear reference even if disconnect failed
                self.zwo_camera = None
                app_logger.debug("Camera controller reference cleared")
        
        # Only enable start button if camera is selected
        if self.app.camera_combo.get():
            self.app.start_capture_button.config(state='normal', cursor='hand2')
        else:
            self.app.start_capture_button.config(state='disabled', cursor='')
        
        self.app.stop_capture_button.config(state='disabled', cursor='')
        self.app.camera_status_var.set("Not Connected")
        self.set_camera_status_dot('disconnected')
        app_logger.info("Camera capture stopped")
    
    def on_camera_frame(self, img, metadata):
        """Callback when camera captures a frame - called from camera thread
        
        SINGLE-STRETCH ARCHITECTURE: Image is processed once in the save pipeline,
        which also updates mini preview and caches result for preview tab.
        """
        try:
            # Store reference for other components
            self.app.last_captured_image = img
            
            # Queue image processing - handles save, mini preview, and caching
            self.app.image_processor.process_and_save_image(img, metadata)
            
            # Increment counter on UI thread
            self.app.image_count += 1
            self.app.root.after(0, lambda: self.app.image_count_var.set(str(self.app.image_count)))
            
        except Exception as e:
            app_logger.error(f"Error processing camera frame: {e}")
    
    def on_camera_error(self, error_msg):
        """Handle camera disconnection/error from capture loop"""
        app_logger.error(f"✗ Camera error received: {error_msg}")
        app_logger.warning("Camera appears to have disconnected or encountered critical error")
        app_logger.info("Manual restart may be required - check camera USB connection and power")
        
        # Update UI on main thread
        def update_ui():
            self.app.is_capturing = False
            self.app.camera_status_var.set(f"Disconnected: {error_msg[:40]}...")
            self.set_camera_status_dot('error')
            self.app.status_header.set_status_color('error')
            self.app.start_capture_button.config(state='normal', cursor='hand2')
            self.app.stop_capture_button.config(state='disabled', cursor='')
        
        self.app.root.after(0, update_ui)
    
    def set_camera_status_dot(self, status):
        """Update camera status dot color"""
        if hasattr(self.app, 'camera_status_dot'):
            colors = {
                'disconnected': '#888888',
                'connecting': '#FFA500',
                'capturing': '#00FF00',
                'error': '#DC3545'
            }
            color = colors.get(status, '#888888')
            self.app.camera_status_dot.delete('all')
            self.app.camera_status_dot.create_oval(2, 2, 8, 8, fill=color, outline='')
    
    def on_camera_selected(self, event=None):
        """Handle camera selection"""
        selection = self.app.camera_combo.current()
        if selection >= 0:
            camera_name = self.app.camera_combo.get()
            self.app.selected_camera_index = selection
            # Save both index (for backward compatibility) and name (for multi-camera stability)
            self.app.config.set('zwo_selected_camera', selection)
            self.app.config.set('zwo_selected_camera_name', camera_name)
            self.app.config.save()
            self.app.start_capture_button.config(state='normal', cursor='hand2')
            self.app.capture_tab.clear_detection_error()
            app_logger.info(f"Camera selected: Index {selection} - {camera_name}")
        else:
            self.app.start_capture_button.config(state='disabled', cursor='')
            app_logger.warning("Invalid camera selection")
    
    def _safe_get(self, var, default, var_type=float):
        """Safely get a value from a tkinter variable, returning default if invalid.
        
        This handles cases where user clears a field while typing a new value.
        """
        try:
            value = var.get()
            # For numeric types, validate the value is reasonable
            if var_type in (int, float) and value == '':
                return default
            return var_type(value)
        except (tk.TclError, ValueError):
            return default
    
    def update_live_settings(self):
        """Update camera settings during active capture without restarting"""
        if not self.zwo_camera or not self.zwo_camera.camera:
            return
        
        try:
            # Update exposure (convert from UI to seconds) and apply immediately to camera
            exposure_value = self._safe_get(self.app.exposure_var, 1.0, float)
            if self.app.exposure_unit_var.get() == 's':
                exposure_sec = exposure_value
            else:
                exposure_sec = exposure_value / 1000.0
            
            # Use the new update_exposure method which applies to camera immediately
            self.zwo_camera.update_exposure(exposure_sec)
            
            # Update other settings (with safe defaults)
            self.zwo_camera.gain = self._safe_get(self.app.gain_var, 100, int)
            self.zwo_camera.white_balance_r = self._safe_get(self.app.wb_r_var, 75, int)
            self.zwo_camera.white_balance_b = self._safe_get(self.app.wb_b_var, 99, int)
            self.zwo_camera.offset = self._safe_get(self.app.offset_var, 20, int)
            self.zwo_camera.target_brightness = self._safe_get(self.app.target_brightness_var, 100, int)
            self.zwo_camera.bayer_pattern = self.app.bayer_pattern_var.get()
            
            # Update auto exposure settings
            self.zwo_camera.auto_exposure = self.app.auto_exposure_var.get()
            self.zwo_camera.max_exposure = self._safe_get(self.app.max_exposure_var, 30.0, float)
            
            # Update flip
            flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
            self.zwo_camera.flip = flip_map.get(self.app.flip_var.get(), 0)
            
            # Update white balance config
            wb_config = self.app.config.get('white_balance', {})
            self.zwo_camera.wb_config = wb_config
            self.zwo_camera.wb_mode = wb_config.get('mode', 'asi_auto')
            
            app_logger.info("Live settings updated during capture")
        except Exception as e:
            app_logger.error(f"Failed to update live settings: {e}")
    
    def on_auto_exposure_toggle(self):
        """Handle auto exposure checkbox"""
        auto = self.app.auto_exposure_var.get()
        if auto:
            self.app.exposure_entry.config(state='disabled')
            if hasattr(self.app, 'max_exposure_entry'):
                self.app.max_exposure_entry.config(state='normal')
            if hasattr(self.app, 'target_brightness_scale'):
                self.app.target_brightness_scale.config(state='normal')
            app_logger.info("Auto exposure enabled")
        else:
            self.app.exposure_entry.config(state='normal')
            if hasattr(self.app, 'max_exposure_entry'):
                self.app.max_exposure_entry.config(state='disabled')
            if hasattr(self.app, 'target_brightness_scale'):
                self.app.target_brightness_scale.config(state='disabled')
            app_logger.info("Auto exposure disabled")
    
    def is_sdk_available(self):
        """Check if ASI SDK is available (path exists and module importable)
        
        NOTE: This does NOT initialize the SDK, to avoid breaking existing connections.
        """
        sdk_path = self.app.sdk_path_var.get()
        if not sdk_path or not os.path.exists(sdk_path):
            return False
        try:
            # Only check if module is importable, do NOT call init()
            # Calling init() can break existing camera connections from other apps
            import zwoasi
            return True
        except ImportError:
            return False
    
    # ===== SCHEDULED CAPTURE METHODS =====
    
    def on_scheduled_capture_toggle(self):
        """Enable/disable scheduled capture time inputs"""
        enabled = self.app.scheduled_capture_var.get()
        state = 'normal' if enabled else 'disabled'
        self.app.schedule_start_entry.config(state=state)
        self.app.schedule_end_entry.config(state=state)
        
        # Auto-save to config
        self.app.config.set('scheduled_capture_enabled', enabled)
        self.app.config.set('scheduled_start_time', self.app.schedule_start_var.get())
        self.app.config.set('scheduled_end_time', self.app.schedule_end_var.get())
        self.app.config.save()
        
        # If camera is running, update its settings
        if self.zwo_camera:
            self.zwo_camera.scheduled_capture_enabled = enabled
            self.zwo_camera.scheduled_start_time = self.app.schedule_start_var.get()
            self.zwo_camera.scheduled_end_time = self.app.schedule_end_var.get()
            
            status = "enabled" if enabled else "disabled"
            if enabled:
                app_logger.info(f"Scheduled capture {status}: {self.app.schedule_start_var.get()} - {self.app.schedule_end_var.get()}")
            else:
                app_logger.info(f"Scheduled capture {status}")
    
    def on_schedule_time_change(self, *args):
        """Called when schedule time entries are modified - auto-save to config"""
        # Only save if scheduled capture is enabled
        if self.app.scheduled_capture_var.get():
            self.app.config.set('scheduled_start_time', self.app.schedule_start_var.get())
            self.app.config.set('scheduled_end_time', self.app.schedule_end_var.get())
            self.app.config.save()
            
            # If camera is running, update its settings
            if self.zwo_camera:
                self.zwo_camera.scheduled_start_time = self.app.schedule_start_var.get()
                self.zwo_camera.scheduled_end_time = self.app.schedule_end_var.get()
                app_logger.info(f"Schedule times updated: {self.app.schedule_start_var.get()} - {self.app.schedule_end_var.get()}")
    
    def update_camera_status_for_schedule(self, status_text):
        """Update camera status when schedule state changes (called from camera thread)"""
        def update_ui():
            self.app.camera_status_var.set(status_text)
            if "Idle" in status_text or "off-peak" in status_text:
                self.set_camera_status_dot('idle')
            elif "Reconnecting" in status_text:
                self.set_camera_status_dot('connecting')
        
        self.app.root.after(0, update_ui)
    
    # ===== WHITE BALANCE METHODS =====
    
    def on_wb_mode_change(self):
        """Handle white balance mode change - show/hide appropriate controls"""
        mode = self.app.wb_mode_var.get()
        
        # Update hint label
        hints = {
            'asi_auto': '(SDK Auto WB)',
            'manual': '(Manual R/B gains)',
            'gray_world': '(Software algorithm)'
        }
        self.app.wb_mode_hint_label.config(text=hints.get(mode, ''))
        
        # Show/hide appropriate control frames
        if mode == 'manual':
            self.app.wb_manual_frame.pack(fill='x', pady=(0, 0))
            self.app.wb_gray_world_frame.pack_forget()
        elif mode == 'gray_world':
            self.app.wb_manual_frame.pack_forget()
            self.app.wb_gray_world_frame.pack(fill='x', pady=(0, 0))
        else:  # asi_auto
            self.app.wb_manual_frame.pack_forget()
            self.app.wb_gray_world_frame.pack_forget()
        
        # Save to config
        self.app.settings_manager.save_config()
    
    def _save_camera_config(self, key, value):
        """Helper method to save camera config from ZWOCamera callbacks"""
        self.app.config.set(key, value)
        self.app.config.save()
