"""
Tabbed GUI for AllSky Overlay App with ZWO Camera support
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
from PIL import Image, ImageTk
from config import Config
from watcher import FileWatcher
from zwo_camera import ZWOCamera
from processor import process_image
from logger import app_logger


class OverlayFrame(ttk.LabelFrame):
    """Frame for a single overlay configuration"""
    
    def __init__(self, parent, overlay_data, on_delete):
        super().__init__(parent, text="Overlay", padding=10)
        self.overlay_data = overlay_data
        self.on_delete = on_delete
        
        # Text content
        ttk.Label(self, text="Overlay Text:").grid(row=0, column=0, sticky='nw', pady=5)
        self.text_widget = scrolledtext.ScrolledText(self, width=50, height=4)
        self.text_widget.grid(row=0, column=1, columnspan=3, sticky='ew', pady=5)
        self.text_widget.insert('1.0', overlay_data.get('text', ''))
        
        # Position anchor
        ttk.Label(self, text="Position:").grid(row=1, column=0, sticky='w', pady=5)
        self.anchor_var = tk.StringVar(value=overlay_data.get('anchor', 'Bottom-Left'))
        anchor_combo = ttk.Combobox(self, textvariable=self.anchor_var, width=20,
                                    values=['Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right', 'Center'])
        anchor_combo.grid(row=1, column=1, sticky='w', pady=5)
        
        # Offsets
        ttk.Label(self, text="X Offset:").grid(row=1, column=2, sticky='w', padx=(10, 0), pady=5)
        self.x_offset_var = tk.IntVar(value=overlay_data.get('x_offset', 10))
        ttk.Entry(self, textvariable=self.x_offset_var, width=8).grid(row=1, column=3, sticky='w', pady=5)
        
        ttk.Label(self, text="Y Offset:").grid(row=2, column=0, sticky='w', pady=5)
        self.y_offset_var = tk.IntVar(value=overlay_data.get('y_offset', 10))
        ttk.Entry(self, textvariable=self.y_offset_var, width=8).grid(row=2, column=1, sticky='w', pady=5)
        
        # Font size
        ttk.Label(self, text="Font Size:").grid(row=2, column=2, sticky='w', padx=(10, 0), pady=5)
        self.font_size_var = tk.IntVar(value=overlay_data.get('font_size', 28))
        ttk.Entry(self, textvariable=self.font_size_var, width=8).grid(row=2, column=3, sticky='w', pady=5)
        
        # Color
        ttk.Label(self, text="Color:").grid(row=3, column=0, sticky='w', pady=5)
        self.color_var = tk.StringVar(value=overlay_data.get('color', 'white'))
        color_combo = ttk.Combobox(self, textvariable=self.color_var, width=20,
                                   values=['white', 'black', 'red', 'green', 'blue', 'yellow', 'cyan', 'magenta'])
        color_combo.grid(row=3, column=1, sticky='w', pady=5)
        
        # Background box
        self.background_var = tk.BooleanVar(value=overlay_data.get('background', True))
        ttk.Checkbutton(self, text="Draw background box", variable=self.background_var).grid(
            row=3, column=2, columnspan=2, sticky='w', padx=(10, 0), pady=5)
        
        # Delete button
        ttk.Button(self, text="Delete Overlay", command=self._on_delete).grid(
            row=4, column=0, columnspan=4, pady=10)
    
    def _on_delete(self):
        """Handle delete button click"""
        if self.on_delete:
            self.on_delete(self)
    
    def get_data(self):
        """Get overlay configuration data"""
        return {
            'text': self.text_widget.get('1.0', 'end-1c'),
            'anchor': self.anchor_var.get(),
            'x_offset': self.x_offset_var.get(),
            'y_offset': self.y_offset_var.get(),
            'font_size': self.font_size_var.get(),
            'color': self.color_var.get(),
            'background': self.background_var.get()
        }


class AllSkyOverlayApp:
    """Main application with tabbed interface"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("AllSky Overlay Watchdog - ZWO Camera Edition")
        self.root.geometry("1000x800")
        
        self.config = Config()
        self.watcher = None
        self.zwo_camera = None
        self.overlay_frames = []
        self.last_processed_image = None
        
        self.create_gui()
        self.load_config()
        
        # Start log polling
        self.poll_logs()
        
        # Start status updates
        self.update_status_header()
    
    def create_status_header(self):
        """Create status header with session information"""
        header = ttk.Frame(self.root, relief='solid', borderwidth=1)
        header.pack(fill='x', padx=5, pady=(5, 0))
        
        # Left side - Mode and Status
        left_frame = ttk.Frame(header)
        left_frame.pack(side='left', padx=10, pady=5)
        
        self.mode_status_var = tk.StringVar(value="Mode: Not Started")
        ttk.Label(left_frame, textvariable=self.mode_status_var, font=('Arial', 10, 'bold')).pack(anchor='w')
        
        self.session_info_var = tk.StringVar(value="Session: None")
        ttk.Label(left_frame, textvariable=self.session_info_var, font=('Arial', 9)).pack(anchor='w')
        
        # Center - Camera/Watch info
        center_frame = ttk.Frame(header)
        center_frame.pack(side='left', padx=20, pady=5)
        
        self.capture_info_var = tk.StringVar(value="Idle")
        ttk.Label(center_frame, textvariable=self.capture_info_var, font=('Arial', 9)).pack(anchor='w')
        
        self.stats_var = tk.StringVar(value="Images Processed: 0")
        ttk.Label(center_frame, textvariable=self.stats_var, font=('Arial', 9)).pack(anchor='w')
        
        # Right side - Current settings
        right_frame = ttk.Frame(header)
        right_frame.pack(side='right', padx=10, pady=5)
        
        self.settings_info_var = tk.StringVar(value="Output: Not configured")
        ttk.Label(right_frame, textvariable=self.settings_info_var, font=('Arial', 9)).pack(anchor='e')
        
        self.cleanup_info_var = tk.StringVar(value="Cleanup: Disabled")
        ttk.Label(right_frame, textvariable=self.cleanup_info_var, font=('Arial', 9)).pack(anchor='e')
        
        # Image counter
        self.image_count = 0
    
    def create_gui(self):
        """Create the tabbed GUI layout"""
        # Create status header
        self.create_status_header()
        
        # Create live monitoring header
        self.create_live_monitoring_header()
        
        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Create tabs
        self.create_capture_tab()
        self.create_overlays_tab()
        self.create_settings_tab()
        self.create_preview_tab()
        self.create_logs_tab()
    
    def create_capture_tab(self):
        """Create Capture tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Capture")
        
        # Mode selection
        mode_frame = ttk.LabelFrame(tab, text="Capture Mode", padding=10)
        mode_frame.pack(fill='x', padx=10, pady=5)
        
        self.capture_mode_var = tk.StringVar(value='watch')
        ttk.Radiobutton(mode_frame, text="Directory Watch Mode", variable=self.capture_mode_var,
                       value='watch', command=self.on_mode_change).pack(anchor='w', pady=2)
        ttk.Radiobutton(mode_frame, text="ZWO Camera Capture Mode", variable=self.capture_mode_var,
                       value='camera', command=self.on_mode_change).pack(anchor='w', pady=2)
        
        # Directory Watch Mode Frame
        self.watch_mode_frame = ttk.LabelFrame(tab, text="Directory Watch Settings", padding=10)
        self.watch_mode_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        ttk.Label(self.watch_mode_frame, text="Watch Directory:").grid(row=0, column=0, sticky='w', pady=5)
        self.watch_dir_var = tk.StringVar()
        ttk.Entry(self.watch_mode_frame, textvariable=self.watch_dir_var, width=50).grid(
            row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Button(self.watch_mode_frame, text="Browse...", command=self.browse_watch_dir).grid(
            row=0, column=2, pady=5)
        
        self.watch_recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.watch_mode_frame, text="Watch subfolders (recursive)",
                       variable=self.watch_recursive_var).grid(row=1, column=0, columnspan=3, sticky='w', pady=5)
        
        # Watch mode buttons
        watch_btn_frame = ttk.Frame(self.watch_mode_frame)
        watch_btn_frame.grid(row=2, column=0, columnspan=3, pady=10)
        self.start_watch_button = ttk.Button(watch_btn_frame, text="Start Watching", command=self.start_watching)
        self.start_watch_button.pack(side='left', padx=5)
        self.stop_watch_button = ttk.Button(watch_btn_frame, text="Stop Watching", command=self.stop_watching, state='disabled')
        self.stop_watch_button.pack(side='left', padx=5)
        
        self.watch_mode_frame.columnconfigure(1, weight=1)
        
        # ZWO Camera Mode Frame
        self.camera_mode_frame = ttk.LabelFrame(tab, text="ZWO Camera Settings", padding=10)
        self.camera_mode_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        ttk.Label(self.camera_mode_frame, text="SDK DLL Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.sdk_path_var = tk.StringVar(value="ASICamera2.dll")
        ttk.Entry(self.camera_mode_frame, textvariable=self.sdk_path_var, width=50).grid(
            row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Button(self.camera_mode_frame, text="Browse...", command=self.browse_sdk_path).grid(
            row=0, column=2, pady=5)
        
        ttk.Button(self.camera_mode_frame, text="Detect Cameras", command=self.detect_cameras).grid(
            row=1, column=0, columnspan=3, pady=5)
        
        ttk.Label(self.camera_mode_frame, text="Camera:").grid(row=2, column=0, sticky='w', pady=5)
        self.camera_list_var = tk.StringVar()
        self.camera_combo = ttk.Combobox(self.camera_mode_frame, textvariable=self.camera_list_var, width=40, state='readonly')
        self.camera_combo.grid(row=2, column=1, columnspan=2, sticky='w', pady=5)
        self.camera_combo.bind('<<ComboboxSelected>>', self.on_camera_selected)
        
        ttk.Label(self.camera_mode_frame, text="Exposure (ms):").grid(row=3, column=0, sticky='w', pady=5)
        self.exposure_var = tk.DoubleVar(value=100.0)  # Default 100ms
        self.exposure_entry = ttk.Entry(self.camera_mode_frame, textvariable=self.exposure_var, width=15)
        self.exposure_entry.grid(row=3, column=1, sticky='w', pady=5, padx=5)
        ttk.Label(self.camera_mode_frame, text="(0.032ms - 3600000ms)", font=('TkDefaultFont', 8)).grid(
            row=3, column=2, sticky='w', pady=5)
        
        ttk.Label(self.camera_mode_frame, text="Gain:").grid(row=4, column=0, sticky='w', pady=5)
        self.gain_var = tk.IntVar(value=100)
        ttk.Entry(self.camera_mode_frame, textvariable=self.gain_var, width=15).grid(
            row=4, column=1, sticky='w', pady=5, padx=5)
        
        ttk.Label(self.camera_mode_frame, text="Capture Interval (seconds):").grid(row=5, column=0, sticky='w', pady=5)
        self.interval_var = tk.DoubleVar(value=5.0)
        ttk.Entry(self.camera_mode_frame, textvariable=self.interval_var, width=15).grid(
            row=5, column=1, sticky='w', pady=5, padx=5)
        
        # Auto Exposure
        self.auto_exposure_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.camera_mode_frame, text="Auto Exposure",
                       variable=self.auto_exposure_var, command=self.on_auto_exposure_toggle).grid(row=6, column=0, sticky='w', pady=5)
        
        ttk.Label(self.camera_mode_frame, text="Max Exposure (ms):").grid(row=6, column=1, sticky='w', pady=5, padx=(20, 0))
        self.max_exposure_var = tk.DoubleVar(value=30000.0)  # Default 30s = 30000ms
        ttk.Entry(self.camera_mode_frame, textvariable=self.max_exposure_var, width=10).grid(
            row=6, column=2, sticky='w', pady=5)
        
        # White Balance
        wb_frame = ttk.LabelFrame(self.camera_mode_frame, text="White Balance", padding=5)
        wb_frame.grid(row=7, column=0, columnspan=3, sticky='ew', pady=5)
        
        ttk.Label(wb_frame, text="Red:").grid(row=0, column=0, sticky='w', padx=5)
        self.wb_r_var = tk.IntVar(value=75)
        ttk.Scale(wb_frame, from_=1, to=99, variable=self.wb_r_var, orient='horizontal').grid(
            row=0, column=1, sticky='ew', padx=5)
        ttk.Label(wb_frame, textvariable=self.wb_r_var, width=3).grid(row=0, column=2)
        
        ttk.Label(wb_frame, text="Blue:").grid(row=1, column=0, sticky='w', padx=5)
        self.wb_b_var = tk.IntVar(value=99)
        ttk.Scale(wb_frame, from_=1, to=99, variable=self.wb_b_var, orient='horizontal').grid(
            row=1, column=1, sticky='ew', padx=5)
        ttk.Label(wb_frame, textvariable=self.wb_b_var, width=3).grid(row=1, column=2)
        
        wb_frame.columnconfigure(1, weight=1)
        
        # Other settings
        ttk.Label(self.camera_mode_frame, text="Offset (Brightness):").grid(row=8, column=0, sticky='w', pady=5)
        self.offset_var = tk.IntVar(value=20)
        ttk.Entry(self.camera_mode_frame, textvariable=self.offset_var, width=15).grid(
            row=8, column=1, sticky='w', pady=5, padx=5)
        
        ttk.Label(self.camera_mode_frame, text="Flip:").grid(row=9, column=0, sticky='w', pady=5)
        self.flip_var = tk.StringVar(value="None")
        ttk.Combobox(self.camera_mode_frame, textvariable=self.flip_var, width=15,
                    values=['None', 'Horizontal', 'Vertical', 'Both']).grid(
            row=9, column=1, sticky='w', pady=5, padx=5)
        
        # Camera status
        self.camera_status_var = tk.StringVar(value="Not connected")
        ttk.Label(self.camera_mode_frame, textvariable=self.camera_status_var, foreground='gray').grid(
            row=10, column=0, columnspan=3, pady=5)
        
        # Camera mode buttons
        camera_btn_frame = ttk.Frame(self.camera_mode_frame)
        camera_btn_frame.grid(row=11, column=0, columnspan=3, pady=10)
        self.start_capture_button = ttk.Button(camera_btn_frame, text="Start Capture", command=self.start_camera_capture)
        self.start_capture_button.pack(side='left', padx=5)
        self.stop_capture_button = ttk.Button(camera_btn_frame, text="Stop Capture", command=self.stop_camera_capture, state='disabled')
        self.stop_capture_button.pack(side='left', padx=5)
        
        self.camera_mode_frame.columnconfigure(1, weight=1)
        
        # Initially hide camera frame
        self.on_mode_change()
    
    def create_live_monitoring_header(self):
        """Create live monitoring section in header area"""
        # Create frame in header area (after status header)
        monitor_frame = ttk.LabelFrame(self.root, text="Live Monitoring", padding=5)
        monitor_frame.pack(fill='both', expand=False, padx=10, pady=5)
        
        # Compact layout: Preview on left, Histogram + Logs stacked on right
        # Left: Mini preview (200x200)
        left_frame = ttk.Frame(monitor_frame)
        left_frame.pack(side='left', padx=5)
        
        preview_label = ttk.Label(left_frame, text="Last Capture:", font=('TkDefaultFont', 9, 'bold'))
        preview_label.pack()
        self.mini_preview_label = ttk.Label(left_frame, text="No image yet", anchor='center', relief='sunken')
        self.mini_preview_label.pack()
        self.mini_preview_image = None
        self.last_captured_image = None
        
        # Right: Histogram and logs stacked vertically
        right_frame = ttk.Frame(monitor_frame)
        right_frame.pack(side='left', fill='both', expand=True, padx=5)
        
        # Histogram on top
        hist_label = ttk.Label(right_frame, text="Histogram:", font=('TkDefaultFont', 9, 'bold'))
        hist_label.pack()
        self.histogram_canvas = tk.Canvas(right_frame, width=500, height=100, bg='black')
        self.histogram_canvas.pack(fill='x')
        
        # Logs below histogram
        log_label = ttk.Label(right_frame, text="Recent Activity:", font=('TkDefaultFont', 9, 'bold'))
        log_label.pack(pady=(5, 0))
        self.mini_log_text = scrolledtext.ScrolledText(right_frame, height=2, wrap=tk.WORD, font=('TkDefaultFont', 8))
        self.mini_log_text.pack(fill='both', expand=True)
        self.mini_log_text.config(state='disabled')
    
    def create_overlays_tab(self):
        """Create Overlays tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Overlays")
        
        # Scrollable container for overlays
        canvas = tk.Canvas(tab)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        self.overlays_container = ttk.Frame(canvas)
        
        self.overlays_container.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.overlays_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y", pady=10)
        
        # Add overlay button at the bottom
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill='x', padx=10, pady=5)
        ttk.Button(btn_frame, text="+ Add Overlay", command=self.add_overlay).pack(side='left', padx=5)
        
        # Token reference
        token_info = ttk.Label(btn_frame, 
            text="Tokens: {CAMERA} {EXPOSURE} {GAIN} {TEMP} {RES} {FILENAME} {SESSION} {DATETIME}",
            font=('Arial', 8), foreground='gray')
        token_info.pack(side='left', padx=10)
    
    def create_settings_tab(self):
        """Create Settings tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Settings")
        
        # Output settings
        output_frame = ttk.LabelFrame(tab, text="Output Settings", padding=10)
        output_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(output_frame, text="Output Directory:").grid(row=0, column=0, sticky='w', pady=5)
        self.output_dir_var = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.output_dir_var, width=50).grid(
            row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Button(output_frame, text="Browse...", command=self.browse_output_dir).grid(
            row=0, column=2, pady=5)
        
        ttk.Label(output_frame, text="Filename Pattern:").grid(row=1, column=0, sticky='w', pady=5)
        self.output_pattern_var = tk.StringVar(value='{session}_{filename}')
        ttk.Entry(output_frame, textvariable=self.output_pattern_var, width=50).grid(
            row=1, column=1, sticky='ew', pady=5, padx=5)
        
        ttk.Label(output_frame, text="Tokens: {filename} {session} {timestamp}", 
                 font=('Arial', 8)).grid(row=2, column=0, columnspan=3, sticky='w', pady=2)
        
        ttk.Label(output_frame, text="Output Format:").grid(row=3, column=0, sticky='w', pady=5)
        self.output_format_var = tk.StringVar(value='JPG')
        format_frame = ttk.Frame(output_frame)
        format_frame.grid(row=3, column=1, sticky='w', pady=5)
        ttk.Combobox(format_frame, textvariable=self.output_format_var, width=10,
                    values=['PNG', 'JPG']).pack(side='left')
        ttk.Label(format_frame, text="JPG Quality:").pack(side='left', padx=(15, 5))
        self.jpg_quality_var = tk.IntVar(value=85)
        ttk.Entry(format_frame, textvariable=self.jpg_quality_var, width=8).pack(side='left')
        ttk.Label(format_frame, text="(1-100)").pack(side='left', padx=5)
        
        ttk.Label(output_frame, text="Resize Output:").grid(row=4, column=0, sticky='w', pady=5)
        self.resize_percent_var = tk.IntVar(value=50)
        resize_frame = ttk.Frame(output_frame)
        resize_frame.grid(row=4, column=1, sticky='w', pady=5)
        ttk.Entry(resize_frame, textvariable=self.resize_percent_var, width=8).pack(side='left')
        ttk.Label(resize_frame, text="% of original size (100 = no resize)").pack(side='left', padx=5)
        
        self.show_timestamp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(output_frame, text="Add timestamp to corner",
                       variable=self.show_timestamp_var).grid(row=5, column=0, columnspan=2, sticky='w', pady=5)
        
        ttk.Label(output_frame, text="Timestamp Corner:").grid(row=6, column=0, sticky='w', pady=5)
        self.timestamp_corner_var = tk.StringVar(value='Top-Right')
        ttk.Combobox(output_frame, textvariable=self.timestamp_corner_var, width=20,
                    values=['Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right']).grid(
            row=6, column=1, sticky='w', pady=5)
        
        output_frame.columnconfigure(1, weight=1)
        
        # Brightness settings
        brightness_frame = ttk.LabelFrame(tab, text="Brightness Settings", padding=10)
        brightness_frame.pack(fill='x', padx=10, pady=5)
        
        self.auto_brightness_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(brightness_frame, text="Auto Brightness (apply to preview and saved images)",
                       variable=self.auto_brightness_var, command=self.on_auto_brightness_toggle).grid(row=0, column=0, columnspan=3, sticky='w', pady=5)
        
        ttk.Label(brightness_frame, text="Brightness:").grid(row=1, column=0, sticky='w', pady=5, padx=(20, 0))
        self.brightness_var = tk.DoubleVar(value=1.5)
        self.brightness_scale = ttk.Scale(brightness_frame, from_=0.1, to=3.0, variable=self.brightness_var, 
                 orient='horizontal', length=200, command=self.on_brightness_change)
        self.brightness_scale.grid(row=1, column=1, sticky='w', pady=5)
        ttk.Label(brightness_frame, textvariable=self.brightness_var, width=4).grid(row=1, column=2, sticky='w', pady=5)
        
        # Cleanup settings
        cleanup_frame = ttk.LabelFrame(tab, text="Cleanup Options", padding=10)
        cleanup_frame.pack(fill='x', padx=10, pady=5)
        
        self.cleanup_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cleanup_frame, text="Enable cleanup of watch directory",
                       variable=self.cleanup_enabled_var).grid(row=0, column=0, columnspan=3, sticky='w', pady=5)
        
        ttk.Label(cleanup_frame, text="Maximum Size (GB):").grid(row=1, column=0, sticky='w', pady=5)
        self.cleanup_size_var = tk.IntVar(value=50)
        ttk.Entry(cleanup_frame, textvariable=self.cleanup_size_var, width=10).grid(
            row=1, column=1, sticky='w', pady=5, padx=5)
        
        ttk.Label(cleanup_frame, text="Strategy:").grid(row=2, column=0, sticky='w', pady=5)
        self.cleanup_strategy_var = tk.StringVar(value='Delete oldest files in watch directory')
        ttk.Combobox(cleanup_frame, textvariable=self.cleanup_strategy_var, width=40,
                    values=['Delete oldest files in watch directory', 'Delete oldest session folders']).grid(
            row=2, column=1, columnspan=2, sticky='w', pady=5, padx=5)
        
        # Save button
        ttk.Button(tab, text="Save All Settings", command=self.save_config).pack(pady=10)
    
    def create_preview_tab(self):
        """Create Preview tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Preview")
        
        # Preview controls
        ctrl_frame = ttk.Frame(tab)
        ctrl_frame.pack(fill='x', padx=10, pady=5)
        ttk.Button(ctrl_frame, text="Refresh Preview", command=self.refresh_preview).pack(side='left', padx=5)
        self.preview_status_var = tk.StringVar(value="No image processed yet")
        ttk.Label(ctrl_frame, textvariable=self.preview_status_var, foreground='gray').pack(side='left', padx=10)
        
        # Image canvas
        self.preview_canvas = tk.Canvas(tab, bg='black')
        self.preview_canvas.pack(fill='both', expand=True, padx=10, pady=10)
    
    def create_logs_tab(self):
        """Create Logs tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Logs")
        
        # Log controls
        ctrl_frame = ttk.Frame(tab)
        ctrl_frame.pack(fill='x', padx=10, pady=5)
        ttk.Button(ctrl_frame, text="Clear Logs", command=self.clear_logs).pack(side='left', padx=5)
        
        # Scrolled text for logs
        self.log_text = scrolledtext.ScrolledText(tab, height=30, state='disabled', wrap='word')
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)
    
    # Event handlers
    def on_mode_change(self):
        """Handle mode change between watch and camera"""
        mode = self.capture_mode_var.get()
        if mode == 'watch':
            self.watch_mode_frame.pack(fill='both', expand=True, padx=10, pady=5)
            self.camera_mode_frame.pack_forget()
        else:
            self.camera_mode_frame.pack(fill='both', expand=True, padx=10, pady=5)
            self.watch_mode_frame.pack_forget()
    
    def browse_watch_dir(self):
        directory = filedialog.askdirectory(title="Select Watch Directory")
        if directory:
            self.watch_dir_var.set(directory)
    
    def browse_output_dir(self):
        directory = filedialog.askdirectory(title="Select Output Directory")
        if directory:
            self.output_dir_var.set(directory)
    
    def browse_sdk_path(self):
        filename = filedialog.askopenfilename(title="Select ASICamera2.dll",
                                             filetypes=[("DLL Files", "*.dll"), ("All Files", "*.*")])
        if filename:
            self.sdk_path_var.set(filename)
    
    def detect_cameras(self):
        """Detect ZWO cameras"""
        app_logger.info("Detecting ZWO cameras...")
        
        if not self.zwo_camera:
            self.zwo_camera = ZWOCamera(self.sdk_path_var.get())
            self.zwo_camera.on_log_callback = app_logger.info
        else:
            self.zwo_camera.sdk_path = self.sdk_path_var.get()
        
        cameras = self.zwo_camera.detect_cameras()
        
        if cameras:
            camera_names = [f"{cam['index']}: {cam['name']}" for cam in cameras]
            self.camera_combo['values'] = camera_names
            
            # Try to restore previously selected camera
            saved_camera = self.config.get('zwo_camera_name', '')
            if saved_camera and saved_camera in camera_names:
                self.camera_combo.set(saved_camera)
                self.selected_camera_index = int(saved_camera.split(':')[0])
            elif camera_names:
                self.camera_combo.current(0)
                self.selected_camera_index = 0
        else:
            self.camera_combo['values'] = []
            messagebox.showwarning("No Cameras", "No ZWO cameras detected. Check SDK path and connections.")
    
    def on_camera_selected(self, event=None):
        """Handle camera selection"""
        selection = self.camera_combo.get()
        if selection:
            camera_index = int(selection.split(':')[0])
            self.selected_camera_index = camera_index
            # Save camera name to config
            self.config.set('zwo_camera_name', selection)
            self.config.save()
            app_logger.info(f"Selected camera index: {camera_index}")
    
    def start_watching(self):
        """Start directory watch mode"""
        self.save_config()
        
        if not self.watch_dir_var.get():
            messagebox.showerror("Error", "Please select a watch directory")
            return
        
        if not self.output_dir_var.get():
            messagebox.showerror("Error", "Please select an output directory")
            return
        
        try:
            self.watcher = FileWatcher(self.config, self.on_image_processed)
            self.watcher.start()
            
            self.start_watch_button.config(state='disabled')
            self.stop_watch_button.config(state='normal')
            app_logger.info("Started directory watching")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start watcher: {e}")
            app_logger.error(f"Failed to start watcher: {e}")
    
    def stop_watching(self):
        """Stop directory watch mode"""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        
        self.start_watch_button.config(state='normal')
        self.stop_watch_button.config(state='disabled')
        app_logger.info("Stopped directory watching")
    
    def start_camera_capture(self):
        """Start ZWO camera capture"""
        self.save_config()
        
        if not self.output_dir_var.get():
            messagebox.showerror("Error", "Please select an output directory")
            return
        
        if not self.zwo_camera:
            self.zwo_camera = ZWOCamera(self.sdk_path_var.get())
            self.zwo_camera.on_log_callback = app_logger.info
        
        # Get selected camera index
        selection = self.camera_combo.get()
        if not selection:
            messagebox.showerror("Error", "Please detect and select a camera first")
            return
        
        camera_index = int(selection.split(':')[0])
        
        # Connect to camera
        if not self.zwo_camera.connect_camera(camera_index):
            messagebox.showerror("Error", "Failed to connect to camera")
            return
        
        # Set camera parameters (convert ms to seconds)
        exposure_ms = self.exposure_var.get()
        self.zwo_camera.set_exposure(max(0.000032, min(3600, exposure_ms / 1000.0)))
        self.zwo_camera.set_gain(self.gain_var.get())
        self.zwo_camera.set_capture_interval(self.interval_var.get())
        self.zwo_camera.auto_exposure = self.auto_exposure_var.get()
        # Max exposure also in ms, convert to seconds
        max_exp_ms = self.max_exposure_var.get()
        self.zwo_camera.max_exposure = max(0.000032, min(3600, max_exp_ms / 1000.0))
        self.zwo_camera.white_balance_r = self.wb_r_var.get()
        self.zwo_camera.white_balance_b = self.wb_b_var.get()
        self.zwo_camera.offset = self.offset_var.get()
        
        # Set flip
        flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
        self.zwo_camera.flip = flip_map.get(self.flip_var.get(), 0)
        
        # Start capture
        if self.zwo_camera.start_capture(self.on_camera_frame, app_logger.info):
            self.start_capture_button.config(state='disabled')
            self.stop_capture_button.config(state='normal')
            self.camera_status_var.set("Capturing...")
            app_logger.info("Started camera capture")
        else:
            messagebox.showerror("Error", "Failed to start capture")
    
    def stop_camera_capture(self):
        """Stop ZWO camera capture"""
        if self.zwo_camera:
            self.zwo_camera.stop_capture()
        
        self.start_capture_button.config(state='normal')
        self.stop_capture_button.config(state='disabled')
        self.camera_status_var.set("Stopped")
        app_logger.info("Stopped camera capture")
    
    def on_camera_frame(self, img, metadata):
        """Called when a new frame is captured from camera"""
        # Update mini preview and histogram immediately
        self.root.after(0, lambda: self.update_mini_preview(img))
        self.root.after(0, lambda: self.update_histogram(img))
        
        # Process in background thread
        def process():
            try:
                success, output_path, error = process_image(img, self.config, metadata)
                if success:
                    app_logger.info(f"Saved camera capture: {os.path.basename(output_path)}")
                    self.last_processed_image = output_path
                    self.image_count += 1
                    self.root.after(100, self.refresh_preview)
                else:
                    app_logger.error(f"Failed to process camera frame: {error}")
            except Exception as e:
                app_logger.error(f"Error processing camera frame: {e}")
        
        threading.Thread(target=process, daemon=True).start()
    
    def on_image_processed(self, image_path):
        """Called when watch mode processes an image"""
        self.last_processed_image = image_path
        self.image_count += 1
        self.root.after(100, self.refresh_preview)
    
    def add_overlay(self, overlay_data=None):
        """Add a new overlay entry"""
        if overlay_data is None:
            overlay_data = {
                'text': 'Camera: {CAMERA}\nExposure: {EXPOSURE}\nGain: {GAIN}',
                'anchor': 'Bottom-Left',
                'x_offset': 10,
                'y_offset': 10,
                'font_size': 28,
                'color': 'white',
                'background': True
            }
        
        overlay_frame = OverlayFrame(self.overlays_container, overlay_data, self.delete_overlay)
        overlay_frame.pack(fill='x', pady=5)
        self.overlay_frames.append(overlay_frame)
    
    def delete_overlay(self, overlay_frame):
        """Delete an overlay entry"""
        if len(self.overlay_frames) <= 1:
            messagebox.showwarning("Warning", "You must have at least one overlay")
            return
        
        overlay_frame.destroy()
        self.overlay_frames.remove(overlay_frame)
    
    def load_config(self):
        """Load configuration and populate GUI"""
        self.capture_mode_var.set(self.config.get('capture_mode', 'watch'))
        self.watch_dir_var.set(self.config.get('watch_directory', ''))
        self.watch_recursive_var.set(self.config.get('watch_recursive', True))
        self.output_dir_var.set(self.config.get('output_directory', ''))
        self.output_pattern_var.set(self.config.get('output_pattern', '{session}_{filename}'))
        self.output_format_var.set(self.config.get('output_format', 'JPG'))
        self.jpg_quality_var.set(self.config.get('jpg_quality', 85))
        self.resize_percent_var.set(self.config.get('resize_percent', 50))
        self.show_timestamp_var.set(self.config.get('show_timestamp_corner', False))
        self.timestamp_corner_var.set(self.config.get('timestamp_corner', 'Top-Right'))
        
        self.sdk_path_var.set(self.config.get('zwo_sdk_path', 'ASICamera2.dll'))
        self.exposure_var.set(self.config.get('zwo_exposure', 100.0))  # milliseconds
        self.gain_var.set(self.config.get('zwo_gain', 100))
        self.interval_var.set(self.config.get('zwo_capture_interval', 5.0))
        self.auto_exposure_var.set(self.config.get('zwo_auto_exposure', False))
        self.max_exposure_var.set(self.config.get('zwo_max_exposure', 30000.0))  # milliseconds
        self.wb_r_var.set(self.config.get('zwo_wb_r', 75))
        self.wb_b_var.set(self.config.get('zwo_wb_b', 99))
        self.offset_var.set(self.config.get('zwo_offset', 20))
        self.flip_var.set(self.config.get('zwo_flip', 'None'))
        
        # Load brightness settings
        if hasattr(self, 'auto_brightness_var'):
            self.auto_brightness_var.set(self.config.get('auto_brightness', False))
        if hasattr(self, 'brightness_var'):
            self.brightness_var.set(self.config.get('brightness_factor', 1.5))
        
        self.cleanup_enabled_var.set(self.config.get('cleanup_enabled', False))
        self.cleanup_size_var.set(self.config.get('cleanup_max_size_gb', 50))
        self.cleanup_strategy_var.set(self.config.get('cleanup_strategy', 'Delete oldest files in watch directory'))
        
        # Load overlays
        overlays = self.config.get_overlays()
        if overlays:
            for overlay in overlays:
                self.add_overlay(overlay)
        else:
            self.add_overlay()
        
        # Update mode UI
        self.on_mode_change()
        
        # Update exposure entry state based on auto exposure setting
        if hasattr(self, 'on_auto_exposure_toggle'):
            self.on_auto_exposure_toggle()
        
        # Update brightness slider state based on auto brightness setting
        if hasattr(self, 'on_auto_brightness_toggle'):
            self.on_auto_brightness_toggle()
        
        app_logger.info("Configuration loaded")
    
    def save_config(self):
        """Save current GUI state to configuration"""
        self.config.set('capture_mode', self.capture_mode_var.get())
        self.config.set('watch_directory', self.watch_dir_var.get())
        self.config.set('watch_recursive', self.watch_recursive_var.get())
        self.config.set('output_directory', self.output_dir_var.get())
        self.config.set('output_pattern', self.output_pattern_var.get())
        self.config.set('output_format', self.output_format_var.get())
        self.config.set('jpg_quality', self.jpg_quality_var.get())
        self.config.set('resize_percent', self.resize_percent_var.get())
        self.config.set('show_timestamp_corner', self.show_timestamp_var.get())
        self.config.set('timestamp_corner', self.timestamp_corner_var.get())
        
        self.config.set('zwo_sdk_path', self.sdk_path_var.get())
        self.config.set('zwo_exposure', self.exposure_var.get())
        self.config.set('zwo_gain', self.gain_var.get())
        self.config.set('zwo_capture_interval', self.interval_var.get())
        self.config.set('zwo_auto_exposure', self.auto_exposure_var.get())
        self.config.set('zwo_max_exposure', self.max_exposure_var.get())
        self.config.set('zwo_wb_r', self.wb_r_var.get())
        self.config.set('zwo_wb_b', self.wb_b_var.get())
        self.config.set('zwo_offset', self.offset_var.get())
        self.config.set('zwo_flip', self.flip_var.get())
        
        # Save brightness settings
        if hasattr(self, 'auto_brightness_var'):
            self.config.set('auto_brightness', self.auto_brightness_var.get())
        if hasattr(self, 'brightness_var'):
            self.config.set('brightness_factor', self.brightness_var.get())
        
        self.config.set('cleanup_enabled', self.cleanup_enabled_var.get())
        self.config.set('cleanup_max_size_gb', self.cleanup_size_var.get())
        self.config.set('cleanup_strategy', self.cleanup_strategy_var.get())
        
        # Save overlays
        overlays = [frame.get_data() for frame in self.overlay_frames]
        self.config.set_overlays(overlays)
        
        if self.config.save():
            app_logger.info("Configuration saved")
        else:
            app_logger.error("Failed to save configuration")
    
    def refresh_preview(self):
        """Refresh the preview image"""
        if not self.last_processed_image or not os.path.exists(self.last_processed_image):
            return
        
        try:
            # Load image
            img = Image.open(self.last_processed_image)
            
            # Apply brightness if auto brightness enabled (same as mini preview)
            if hasattr(self, 'auto_brightness_var') and self.auto_brightness_var.get():
                if hasattr(self, 'brightness_var'):
                    from PIL import ImageEnhance
                    brightness = self.brightness_var.get()
                    if brightness != 1.0:
                        enhancer = ImageEnhance.Brightness(img)
                        img = enhancer.enhance(brightness)
            
            # Scale to fit canvas
            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()
            
            if canvas_width > 1 and canvas_height > 1:
                img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Update canvas
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(
                    canvas_width // 2,
                    canvas_height // 2,
                    image=photo
                )
                self.preview_canvas.image = photo  # Keep reference
                
                self.preview_status_var.set(f"Showing: {os.path.basename(self.last_processed_image)}")
        except Exception as e:
            app_logger.error(f"Error refreshing preview: {e}")
    
    def clear_logs(self):
        """Clear the log display"""
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')
    
    def poll_logs(self):
        """Poll for log messages and update GUI"""
        messages = app_logger.get_messages()
        if messages:
            # Update main logs tab
            self.log_text.config(state='normal')
            for msg in messages:
                self.log_text.insert('end', f"{msg}\n")
            self.log_text.see('end')
            self.log_text.config(state='disabled')
            
            # Update mini log in camera tab (last 10 lines)
            if hasattr(self, 'mini_log_text'):
                self.mini_log_text.config(state='normal')
                for msg in messages:
                    self.mini_log_text.insert(tk.END, msg + '\n')
                # Keep only last 10 lines
                lines = self.mini_log_text.get('1.0', tk.END).split('\n')
                if len(lines) > 10:
                    self.mini_log_text.delete('1.0', tk.END)
                    self.mini_log_text.insert('1.0', '\n'.join(lines[-11:]))
                self.mini_log_text.see(tk.END)
                self.mini_log_text.config(state='disabled')
        
        # Schedule next poll
        self.root.after(1000, self.poll_logs)
    
    def update_histogram(self, img):
        """Update histogram display from PIL Image"""
        if not hasattr(self, 'histogram_canvas'):
            return
        
        try:
            import numpy as np
            # Convert to numpy array
            img_array = np.array(img)
            
            # Clear canvas
            self.histogram_canvas.delete('all')
            width = 500
            height = 100
            
            # Calculate histograms for R, G, B
            colors = ['red', 'green', 'blue']
            for i, color in enumerate(colors):
                if len(img_array.shape) == 3 and img_array.shape[2] >= 3:
                    channel = img_array[:, :, i]
                else:
                    # Grayscale
                    channel = img_array if len(img_array.shape) == 2 else img_array[:, :, 0]
                
                hist, bins = np.histogram(channel, bins=256, range=(0, 256))
                # Normalize
                hist = hist / hist.max() if hist.max() > 0 else hist
                
                # Draw histogram bars
                bin_width = width / 256
                for j, val in enumerate(hist):
                    x = j * bin_width
                    bar_height = val * height
                    self.histogram_canvas.create_line(
                        x, height, x, height - bar_height,
                        fill=color, width=max(1, bin_width)
                    )
        except Exception as e:
            app_logger.error(f"Error updating histogram: {e}")
    
    def update_mini_preview(self, img):
        """Update mini preview from PIL Image"""
        if not hasattr(self, 'mini_preview_label'):
            return
        
        try:
            from PIL import ImageTk, ImageEnhance
            # Store original for brightness adjustment
            self.last_captured_image = img.copy()
            
            # Apply brightness adjustment if auto brightness enabled
            img_adjusted = img.copy()
            if self.auto_brightness_var.get():
                brightness = self.brightness_var.get()
                if brightness != 1.0:
                    enhancer = ImageEnhance.Brightness(img_adjusted)
                    img_adjusted = enhancer.enhance(brightness)
            
            # Resize to fit mini preview (200x200 for header)
            img_adjusted.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(img_adjusted)
            self.mini_preview_label.config(image=photo, text='')
            self.mini_preview_label.image = photo  # Keep reference
        except Exception as e:
            app_logger.error(f"Error updating mini preview: {e}")
    
    def on_brightness_change(self, value=None):
        """Called when brightness slider changes - refresh preview"""
        if hasattr(self, 'last_captured_image') and self.last_captured_image is not None:
            self.update_mini_preview(self.last_captured_image)
    
    def on_auto_exposure_toggle(self):
        """Toggle exposure entry state when auto exposure changes"""
        if hasattr(self, 'exposure_entry'):
            if self.auto_exposure_var.get():
                self.exposure_entry.config(state='disabled')
            else:
                self.exposure_entry.config(state='normal')
    
    def on_auto_brightness_toggle(self):
        """Toggle brightness slider state when auto brightness changes"""
        if hasattr(self, 'brightness_scale'):
            if self.auto_brightness_var.get():
                self.brightness_scale.config(state='normal')
            else:
                self.brightness_scale.config(state='disabled')
        # Refresh preview with new setting
        if hasattr(self, 'last_captured_image') and self.last_captured_image is not None:
            self.update_mini_preview(self.last_captured_image)
    
    def update_status_header(self):
        """Update the status header with current information"""
        # Mode and status
        mode = self.capture_mode_var.get()
        if self.watcher or (self.zwo_camera and self.zwo_camera.is_capturing):
            status = "Running"
            if mode == 'watch':
                self.mode_status_var.set(f"Mode: Directory Watch - {status}")
                self.capture_info_var.set(f"Watching: {os.path.basename(self.watch_dir_var.get()) if self.watch_dir_var.get() else 'N/A'}")
            else:
                self.mode_status_var.set(f"Mode: ZWO Camera - {status}")
                camera_name = self.camera_combo.get().split(':')[1].strip() if ':' in self.camera_combo.get() else 'N/A'
                exp = self.exposure_var.get()
                gain = self.gain_var.get()
                self.capture_info_var.set(f"Camera: {camera_name} | Exp: {exp}s | Gain: {gain}")
        else:
            self.mode_status_var.set(f"Mode: {mode.title()} - Idle")
            self.capture_info_var.set("Not capturing")
        
        # Session info
        from datetime import datetime
        session = datetime.now().strftime('%Y-%m-%d')
        self.session_info_var.set(f"Session: {session}")
        
        # Stats
        self.stats_var.set(f"Images Processed: {self.image_count}")
        
        # Settings info
        output_dir = self.output_dir_var.get()
        if output_dir:
            format_str = self.output_format_var.get()
            resize = self.resize_percent_var.get()
            self.settings_info_var.set(f"Output: {format_str} @ {resize}% → {os.path.basename(output_dir)}")
        else:
            self.settings_info_var.set("Output: Not configured")
        
        # Cleanup info
        if self.cleanup_enabled_var.get():
            size = self.cleanup_size_var.get()
            self.cleanup_info_var.set(f"Cleanup: Enabled ({size} GB limit)")
        else:
            self.cleanup_info_var.set("Cleanup: Disabled")
        
        # Schedule next update
        self.root.after(1000, self.update_status_header)
    
    def on_closing(self):
        """Handle window close event"""
        if self.watcher:
            self.watcher.stop()
        if self.zwo_camera:
            self.zwo_camera.stop_capture()
            self.zwo_camera.disconnect_camera()
        self.root.destroy()


def main():
    """Main entry point"""
    root = tk.Tk()
    app = AllSkyOverlayApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == '__main__':
    main()
