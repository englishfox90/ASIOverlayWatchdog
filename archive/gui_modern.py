"""
Modern GUI for AllSky Overlay Watchdog
Using ttkbootstrap for modern theming
"""
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageEnhance
import os
import threading
from datetime import datetime

from config import Config
from watcher import FileWatcher
from zwo_camera import ZWOCamera
from processor import process_image, add_overlays
from logger import app_logger

# Application version
APP_VERSION = "2.0.0"
APP_AUTHOR = "Paul Fox-Reeks"


class OverlayListItem(ttk.Frame):
    """A single overlay item in the list"""
    
    def __init__(self, parent, overlay_data, index, on_select, on_delete):
        super().__init__(parent, bootstyle="secondary")
        self.overlay_data = overlay_data
        self.index = index
        self.on_select = on_select
        self.on_delete = on_delete
        self.selected = False
        
        self.pack(fill='x', padx=2, pady=2)
        
        # Create clickable frame
        self.bind("<Button-1>", lambda e: self.select())
        
        # Overlay info
        text_preview = overlay_data.get('text', '')[:30] + "..." if len(overlay_data.get('text', '')) > 30 else overlay_data.get('text', '')
        
        info_frame = ttk.Frame(self)
        info_frame.pack(fill='x', expand=True, padx=5, pady=5)
        info_frame.bind("<Button-1>", lambda e: self.select())
        
        ttk.Label(info_frame, text=f"Overlay #{index+1}", font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        ttk.Label(info_frame, text=text_preview, font=('Segoe UI', 8)).pack(anchor='w')
        ttk.Label(info_frame, text=f"{overlay_data.get('anchor', 'Bottom-Left')} • {overlay_data.get('color', 'white')}", 
                 font=('Segoe UI', 7), bootstyle="secondary").pack(anchor='w')
        
        # Delete button
        ttk.Button(info_frame, text="✕", width=3, bootstyle="danger-link",
                  command=lambda: self.on_delete(self)).pack(side='right')
    
    def select(self):
        self.on_select(self)
    
    def set_selected(self, selected):
        self.selected = selected
        if selected:
            self.configure(bootstyle="primary")
        else:
            self.configure(bootstyle="secondary")


class ModernOverlayApp:
    """Modern themed AllSky Overlay application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("AllSky Overlay Watchdog - ZWO Camera Edition")
        
        # Load config
        self.config = Config()
        
        # Set window geometry
        geometry = self.config.get('window_geometry', '1280x1700')
        self.root.geometry(geometry)
        self.root.minsize(1024, 1750)
        
        # Save geometry on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Initialize state
        self.watcher = None
        self.zwo_camera = None
        self.last_processed_image = None
        self.last_captured_image = None
        self.image_count = 0
        self.selected_camera_index = 0
        self.selected_overlay_index = None
        self.overlay_list_items = []
        
        # Create GUI
        self.create_gui()
        
        # Load configuration
        self.load_config()
        
        # Start log polling
        self.poll_logs()
        
        # Start status updates
        self.update_status_header()
    
    def create_tooltip(self, widget, text):
        """Helper to create tooltips"""
        ToolTip(widget, text=text, bootstyle="info-inverse")
    
    def create_gui(self):
        """Create the modern tabbed GUI layout"""
        # Create status header
        self.create_status_header()
        
        # Create live monitoring header
        self.create_live_monitoring_header()
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root, bootstyle="dark")
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Create tabs
        self.create_capture_tab()
        self.create_overlays_tab()
        self.create_settings_tab()
        self.create_preview_tab()
        self.create_logs_tab()
        
        # Create menu bar
        self.create_menu()
    
    def create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save Settings", command=self.save_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
    
    def show_about(self):
        """Show about dialog"""
        about_text = f"""AllSky Overlay Watchdog
ZWO Camera Edition

Version: {APP_VERSION}
Author: {APP_AUTHOR}

A modern astrophotography tool for adding
metadata overlays to sky images.

Supports:
• ZWO ASI cameras (direct capture)
• Directory watching (auto-processing)
• Customizable text overlays
• Auto brightness adjustment
• Automated cleanup"""
        
        messagebox.showinfo("About", about_text)
    
    def create_status_header(self):
        """Create status header with session information"""
        header_frame = ttk.Frame(self.root, bootstyle="secondary", padding=10)
        header_frame.pack(fill='x', padx=10, pady=(10, 0))
        
        # Left side - mode and capture info
        left_frame = ttk.Frame(header_frame, bootstyle="secondary")
        left_frame.pack(side='left', fill='both', expand=True)
        
        self.mode_status_var = tk.StringVar(value="Mode: Not Running")
        ttk.Label(left_frame, textvariable=self.mode_status_var, font=('Segoe UI', 10, 'bold'),
                 bootstyle="inverse-light").pack(anchor='w')
        
        self.capture_info_var = tk.StringVar(value="No active session")
        ttk.Label(left_frame, textvariable=self.capture_info_var, font=('Segoe UI', 9),
                 bootstyle="light").pack(anchor='w')
        
        # Right side - session stats
        right_frame = ttk.Frame(header_frame, bootstyle="secondary")
        right_frame.pack(side='right')
        
        stats_frame = ttk.Frame(right_frame, bootstyle="secondary")
        stats_frame.pack()
        
        ttk.Label(stats_frame, text="Session:", font=('Segoe UI', 8),
                 bootstyle="light").grid(row=0, column=0, sticky='e', padx=5)
        self.session_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        ttk.Label(stats_frame, textvariable=self.session_var, font=('Segoe UI', 8, 'bold'),
                 bootstyle="inverse-light").grid(row=0, column=1, sticky='w')
        
        ttk.Label(stats_frame, text="Images:", font=('Segoe UI', 8),
                 bootstyle="light").grid(row=0, column=2, sticky='e', padx=5)
        self.image_count_var = tk.StringVar(value="0")
        ttk.Label(stats_frame, textvariable=self.image_count_var, font=('Segoe UI', 8, 'bold'),
                 bootstyle="success").grid(row=0, column=3, sticky='w')
        
        ttk.Label(stats_frame, text="Output:", font=('Segoe UI', 8),
                 bootstyle="light").grid(row=1, column=0, sticky='e', padx=5)
        self.output_info_var = tk.StringVar(value="Not configured")
        ttk.Label(stats_frame, textvariable=self.output_info_var, font=('Segoe UI', 8),
                 bootstyle="light").grid(row=1, column=1, columnspan=3, sticky='w')
    
    def create_live_monitoring_header(self):
        """Create live monitoring section in header area"""
        monitor_frame = ttk.Labelframe(self.root, text="  Live Monitoring  ", bootstyle="info", padding=10)
        monitor_frame.pack(fill='both', padx=10, pady=5)
        
        # Layout: Preview on left, Histogram + Logs stacked on right
        left_frame = ttk.Frame(monitor_frame)
        left_frame.pack(side='left', padx=10)
        
        ttk.Label(left_frame, text="Last Capture", font=('Segoe UI', 9, 'bold')).pack()
        self.mini_preview_label = ttk.Label(left_frame, text="No image yet", relief='sunken', width=25)
        self.mini_preview_label.pack()
        self.mini_preview_image = None
        
        # Right side: Histogram and logs stacked
        right_frame = ttk.Frame(monitor_frame)
        right_frame.pack(side='left', fill='both', expand=True, padx=10)
        
        # Histogram on top
        ttk.Label(right_frame, text="Histogram", font=('Segoe UI', 9, 'bold')).pack()
        self.histogram_canvas = tk.Canvas(right_frame, width=600, height=100, bg='#1a1a1a', highlightthickness=1)
        self.histogram_canvas.pack(fill='x')
        
        # Logs below
        ttk.Label(right_frame, text="Recent Activity", font=('Segoe UI', 9, 'bold')).pack(pady=(5, 0))
        self.mini_log_text = scrolledtext.ScrolledText(right_frame, height=2, wrap=tk.WORD, font=('Consolas', 8))
        self.mini_log_text.pack(fill='both', expand=True)
        self.mini_log_text.config(state='disabled')
    
    def create_capture_tab(self):
        """Create modern Capture tab with collapsible sections"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Capture  ")
        
        # Scrollable frame
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview, bootstyle="round")
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Mode selection
        mode_frame = ttk.Labelframe(scrollable_frame, text="  Capture Mode  ", bootstyle="primary", padding=15)
        mode_frame.pack(fill='x', padx=10, pady=10)
        
        self.capture_mode_var = tk.StringVar(value='watch')
        ttk.Radiobutton(mode_frame, text="📁 Directory Watch Mode", variable=self.capture_mode_var,
                       value='watch', command=self.on_mode_change, bootstyle="primary-toolbutton").pack(anchor='w', pady=5)
        ttk.Radiobutton(mode_frame, text="📷 ZWO Camera Capture Mode", variable=self.capture_mode_var,
                       value='camera', command=self.on_mode_change, bootstyle="primary-toolbutton").pack(anchor='w', pady=5)
        
        # Directory Watch Settings
        self.watch_frame = ttk.Labelframe(scrollable_frame, text="  Directory Watch Settings  ", bootstyle="success", padding=15)
        self.watch_frame.pack(fill='x', padx=10, pady=10)
        
        watch_grid = ttk.Frame(self.watch_frame)
        watch_grid.pack(fill='x')
        
        ttk.Label(watch_grid, text="Watch Directory:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky='w', pady=5)
        self.watch_dir_var = tk.StringVar()
        ttk.Entry(watch_grid, textvariable=self.watch_dir_var, width=50).grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Button(watch_grid, text="Browse...", command=self.browse_watch_dir, bootstyle="info-outline").grid(row=0, column=2, pady=5)
        
        self.watch_recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(watch_grid, text="Watch subdirectories recursively", variable=self.watch_recursive_var).grid(
            row=1, column=0, columnspan=3, sticky='w', pady=5)
        
        watch_grid.columnconfigure(1, weight=1)
        
        # Watch buttons
        watch_btn_frame = ttk.Frame(self.watch_frame)
        watch_btn_frame.pack(pady=10)
        self.start_watch_button = ttk.Button(watch_btn_frame, text="▶ Start Watching", command=self.start_watching, bootstyle="success")
        self.start_watch_button.pack(side='left', padx=5)
        self.stop_watch_button = ttk.Button(watch_btn_frame, text="⏸ Stop Watching", command=self.stop_watching, 
                                            bootstyle="danger", state='disabled')
        self.stop_watch_button.pack(side='left', padx=5)
        
        # ZWO Camera Settings
        self.camera_frame = ttk.Labelframe(scrollable_frame, text="  ZWO Camera Settings  ", bootstyle="info", padding=15)
        self.camera_frame.pack(fill='x', padx=10, pady=10)
        
        # SDK and camera selection
        sdk_frame = ttk.Frame(self.camera_frame)
        sdk_frame.pack(fill='x', pady=5)
        
        ttk.Label(sdk_frame, text="SDK DLL Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.sdk_path_var = tk.StringVar(value="ASICamera2.dll")
        sdk_entry = ttk.Entry(sdk_frame, textvariable=self.sdk_path_var, width=40)
        sdk_entry.grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Button(sdk_frame, text="Browse...", command=self.browse_sdk_path, bootstyle="secondary-outline").grid(row=0, column=2, pady=5)
        self.create_tooltip(sdk_entry, "Path to ASICamera2.dll (ZWO ASI SDK)")
        
        ttk.Button(sdk_frame, text="🔍 Detect Cameras", command=self.detect_cameras, bootstyle="info").grid(
            row=1, column=0, columnspan=3, pady=10)
        
        ttk.Label(sdk_frame, text="Camera:").grid(row=2, column=0, sticky='w', pady=5)
        self.camera_list_var = tk.StringVar()
        self.camera_combo = ttk.Combobox(sdk_frame, textvariable=self.camera_list_var, width=40, state='readonly')
        self.camera_combo.grid(row=2, column=1, columnspan=2, sticky='ew', pady=5, padx=5)
        self.camera_combo.bind('<<ComboboxSelected>>', self.on_camera_selected)
        
        sdk_frame.columnconfigure(1, weight=1)
        
        # Camera parameters
        params_frame = ttk.Frame(self.camera_frame)
        params_frame.pack(fill='x', pady=10)
        
        # Left column
        left_params = ttk.Frame(params_frame)
        left_params.pack(side='left', fill='both', expand=True, padx=5)
        
        ttk.Label(left_params, text="Exposure (ms):", font=('Segoe UI', 9)).grid(row=0, column=0, sticky='w', pady=5)
        self.exposure_var = tk.DoubleVar(value=100.0)
        self.exposure_entry = ttk.Entry(left_params, textvariable=self.exposure_var, width=15)
        self.exposure_entry.grid(row=0, column=1, sticky='w', pady=5, padx=5)
        ttk.Label(left_params, text="(0.032 - 3600000)", font=('Segoe UI', 7)).grid(row=0, column=2, sticky='w')
        self.create_tooltip(self.exposure_entry, "Exposure time in milliseconds (32µs to 1 hour)")
        
        ttk.Label(left_params, text="Gain:", font=('Segoe UI', 9)).grid(row=1, column=0, sticky='w', pady=5)
        self.gain_var = tk.IntVar(value=100)
        gain_entry = ttk.Entry(left_params, textvariable=self.gain_var, width=15)
        gain_entry.grid(row=1, column=1, sticky='w', pady=5, padx=5)
        self.create_tooltip(gain_entry, "Camera gain (0-600, higher = brighter but noisier)")
        
        ttk.Label(left_params, text="Capture Interval (s):", font=('Segoe UI', 9)).grid(row=2, column=0, sticky='w', pady=5)
        self.interval_var = tk.DoubleVar(value=5.0)
        interval_entry = ttk.Entry(left_params, textvariable=self.interval_var, width=15)
        interval_entry.grid(row=2, column=1, sticky='w', pady=5, padx=5)
        self.create_tooltip(interval_entry, "Time between captures in seconds")
        
        # Right column
        right_params = ttk.Frame(params_frame)
        right_params.pack(side='right', fill='both', expand=True, padx=5)
        
        self.auto_exposure_var = tk.BooleanVar(value=False)
        auto_exp_check = ttk.Checkbutton(right_params, text="🔆 Auto Exposure", variable=self.auto_exposure_var,
                                         command=self.on_auto_exposure_toggle, bootstyle="success-round-toggle")
        auto_exp_check.grid(row=0, column=0, sticky='w', pady=5)
        self.create_tooltip(auto_exp_check, "Automatically adjust exposure based on image brightness")
        
        ttk.Label(right_params, text="Max Exposure (ms):", font=('Segoe UI', 9)).grid(row=0, column=1, sticky='w', pady=5, padx=(20, 0))
        self.max_exposure_var = tk.DoubleVar(value=30000.0)
        max_exp_entry = ttk.Entry(right_params, textvariable=self.max_exposure_var, width=12)
        max_exp_entry.grid(row=0, column=2, sticky='w', pady=5, padx=5)
        self.create_tooltip(max_exp_entry, "Maximum exposure for auto mode (in milliseconds)")
        
        # White balance
        wb_frame = ttk.Labelframe(right_params, text="White Balance", padding=5, bootstyle="secondary")
        wb_frame.grid(row=1, column=0, columnspan=3, sticky='ew', pady=5)
        
        ttk.Label(wb_frame, text="Red:").grid(row=0, column=0, sticky='w', padx=5)
        self.wb_r_var = tk.IntVar(value=75)
        ttk.Scale(wb_frame, from_=1, to=99, variable=self.wb_r_var, orient='horizontal', length=150, bootstyle="danger").grid(
            row=0, column=1, sticky='ew', padx=5)
        ttk.Label(wb_frame, textvariable=self.wb_r_var, width=3).grid(row=0, column=2)
        
        ttk.Label(wb_frame, text="Blue:").grid(row=1, column=0, sticky='w', padx=5)
        self.wb_b_var = tk.IntVar(value=99)
        ttk.Scale(wb_frame, from_=1, to=99, variable=self.wb_b_var, orient='horizontal', length=150, bootstyle="info").grid(
            row=1, column=1, sticky='ew', padx=5)
        ttk.Label(wb_frame, textvariable=self.wb_b_var, width=3).grid(row=1, column=2)
        
        wb_frame.columnconfigure(1, weight=1)
        
        # Additional settings
        ttk.Label(left_params, text="Offset:", font=('Segoe UI', 9)).grid(row=3, column=0, sticky='w', pady=5)
        self.offset_var = tk.IntVar(value=20)
        ttk.Entry(left_params, textvariable=self.offset_var, width=15).grid(row=3, column=1, sticky='w', pady=5, padx=5)
        
        ttk.Label(left_params, text="Flip:", font=('Segoe UI', 9)).grid(row=4, column=0, sticky='w', pady=5)
        self.flip_var = tk.StringVar(value="None")
        ttk.Combobox(left_params, textvariable=self.flip_var, width=12,
                    values=['None', 'Horizontal', 'Vertical', 'Both'], state='readonly').grid(
            row=4, column=1, sticky='w', pady=5, padx=5)
        
        # Camera status and buttons
        self.camera_status_var = tk.StringVar(value="Not connected")
        ttk.Label(self.camera_frame, textvariable=self.camera_status_var, font=('Segoe UI', 9, 'italic'),
                 bootstyle="secondary").pack(pady=5)
        
        camera_btn_frame = ttk.Frame(self.camera_frame)
        camera_btn_frame.pack(pady=10)
        self.start_capture_button = ttk.Button(camera_btn_frame, text="▶ Start Capture", command=self.start_camera_capture,
                                              bootstyle="success")
        self.start_capture_button.pack(side='left', padx=5)
        self.stop_capture_button = ttk.Button(camera_btn_frame, text="⏸ Stop Capture", command=self.stop_camera_capture,
                                             bootstyle="danger", state='disabled')
        self.stop_capture_button.pack(side='left', padx=5)
        
        # Initially show correct frame
        self.on_mode_change()
    
    def create_overlays_tab(self):
        """Create modern Overlays tab with master/detail layout"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Overlays  ")
        
        # Split into left (list) and right (editor + preview)
        paned = ttk.Panedwindow(tab, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Left panel - overlay list
        left_panel = ttk.Labelframe(paned, text="  Overlay List  ", bootstyle="primary", padding=10)
        paned.add(left_panel, weight=1)
        
        # Toolbar
        toolbar = ttk.Frame(left_panel)
        toolbar.pack(fill='x', pady=(0, 10))
        ttk.Button(toolbar, text="➕ Add Overlay", command=self.add_new_overlay, bootstyle="success").pack(side='left', padx=2)
        ttk.Button(toolbar, text="📋 Duplicate", command=self.duplicate_overlay, bootstyle="info-outline").pack(side='left', padx=2)
        ttk.Button(toolbar, text="🗑 Delete All", command=self.clear_all_overlays, bootstyle="danger-outline").pack(side='left', padx=2)
        
        # Scrollable list
        list_canvas = tk.Canvas(left_panel, highlightthickness=0)
        list_scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=list_canvas.yview, bootstyle="round")
        self.overlay_list_frame = ttk.Frame(list_canvas)
        
        self.overlay_list_frame.bind(
            "<Configure>",
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all"))
        )
        
        list_canvas.create_window((0, 0), window=self.overlay_list_frame, anchor="nw")
        list_canvas.configure(yscrollcommand=list_scrollbar.set)
        
        list_canvas.pack(side="left", fill="both", expand=True)
        list_scrollbar.pack(side="right", fill="y")
        
        # Right panel - editor
        right_panel = ttk.Frame(paned)
        paned.add(right_panel, weight=2)
        
        # Editor section
        editor_frame = ttk.Labelframe(right_panel, text="  Overlay Editor  ", bootstyle="info", padding=15)
        editor_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        # Text with token insertion
        text_frame = ttk.Frame(editor_frame)
        text_frame.pack(fill='x', pady=5)
        
        ttk.Label(text_frame, text="Text:", font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        
        token_toolbar = ttk.Frame(text_frame)
        token_toolbar.pack(fill='x', pady=(5, 0))
        ttk.Label(token_toolbar, text="Insert Token:", font=('Segoe UI', 8)).pack(side='left', padx=5)
        
        self.token_var = tk.StringVar()
        token_combo = ttk.Combobox(token_toolbar, textvariable=self.token_var, width=20, state='readonly',
                                   values=['{CAMERA}', '{EXPOSURE}', '{GAIN}', '{TEMP}', '{RES}', 
                                          '{FILENAME}', '{SESSION}', '{DATETIME}'])
        token_combo.pack(side='left', padx=5)
        ttk.Button(token_toolbar, text="Insert", command=self.insert_token, bootstyle="info-outline").pack(side='left', padx=5)
        self.create_tooltip(token_combo, "Select a metadata token to insert into the overlay text")
        
        self.overlay_text = scrolledtext.ScrolledText(text_frame, height=4, wrap=tk.WORD, font=('Consolas', 10))
        self.overlay_text.pack(fill='x', pady=5)
        self.overlay_text.bind('<KeyRelease>', lambda e: self.on_overlay_edit())
        
        # Position and appearance settings
        settings_grid = ttk.Frame(editor_frame)
        settings_grid.pack(fill='x', pady=10)
        
        row = 0
        ttk.Label(settings_grid, text="Position:", font=('Segoe UI', 9, 'bold')).grid(row=row, column=0, sticky='w', pady=5)
        self.anchor_var = tk.StringVar(value="Bottom-Left")
        ttk.Combobox(settings_grid, textvariable=self.anchor_var, width=15, state='readonly',
                    values=['Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right', 'Center']).grid(
            row=row, column=1, sticky='w', pady=5, padx=5)
        self.anchor_var.trace('w', lambda *args: self.on_overlay_edit())
        
        ttk.Label(settings_grid, text="Color:", font=('Segoe UI', 9, 'bold')).grid(row=row, column=2, sticky='w', pady=5, padx=(20, 0))
        self.color_var = tk.StringVar(value="white")
        ttk.Combobox(settings_grid, textvariable=self.color_var, width=12, state='readonly',
                    values=['white', 'black', 'red', 'green', 'blue', 'yellow', 'cyan', 'magenta']).grid(
            row=row, column=3, sticky='w', pady=5, padx=5)
        self.color_var.trace('w', lambda *args: self.on_overlay_edit())
        
        row += 1
        ttk.Label(settings_grid, text="Font Size:", font=('Segoe UI', 9, 'bold')).grid(row=row, column=0, sticky='w', pady=5)
        self.font_size_var = tk.IntVar(value=24)
        ttk.Spinbox(settings_grid, from_=8, to=200, textvariable=self.font_size_var, width=13,
                   command=self.on_overlay_edit).grid(row=row, column=1, sticky='w', pady=5, padx=5)
        
        ttk.Label(settings_grid, text="Offset X:", font=('Segoe UI', 9, 'bold')).grid(row=row, column=2, sticky='w', pady=5, padx=(20, 0))
        self.offset_x_var = tk.IntVar(value=10)
        ttk.Spinbox(settings_grid, from_=-500, to=500, textvariable=self.offset_x_var, width=10,
                   command=self.on_overlay_edit).grid(row=row, column=3, sticky='w', pady=5, padx=5)
        
        row += 1
        ttk.Label(settings_grid, text="Font Style:", font=('Segoe UI', 9, 'bold')).grid(row=row, column=0, sticky='w', pady=5)
        self.font_style_var = tk.StringVar(value="normal")
        ttk.Combobox(settings_grid, textvariable=self.font_style_var, width=12, state='readonly',
                    values=['normal', 'bold', 'italic']).grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.font_style_var.trace('w', lambda *args: self.on_overlay_edit())
        
        ttk.Label(settings_grid, text="Offset Y:", font=('Segoe UI', 9, 'bold')).grid(row=row, column=2, sticky='w', pady=5, padx=(20, 0))
        self.offset_y_var = tk.IntVar(value=10)
        ttk.Spinbox(settings_grid, from_=-500, to=500, textvariable=self.offset_y_var, width=10,
                   command=self.on_overlay_edit).grid(row=row, column=3, sticky='w', pady=5, padx=5)
        
        # Apply/Reset buttons
        btn_frame = ttk.Frame(editor_frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="✓ Apply Changes", command=self.apply_overlay_changes, bootstyle="success").pack(side='left', padx=5)
        ttk.Button(btn_frame, text="↺ Reset", command=self.reset_overlay_editor, bootstyle="warning-outline").pack(side='left', padx=5)
        
        # Preview section
        preview_frame = ttk.Labelframe(right_panel, text="  Preview  ", bootstyle="secondary", padding=10)
        preview_frame.pack(fill='both', pady=(0, 0))
        
        self.overlay_preview_label = ttk.Label(preview_frame, text="Select or create an overlay to see preview",
                                              relief='sunken', anchor='center')
        self.overlay_preview_label.pack(fill='both', expand=True)
        self.overlay_preview_image = None
    
    def create_settings_tab(self):
        """Create modern Settings tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Settings  ")
        
        # Scrollable frame
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview, bootstyle="round")
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Output Settings
        output_frame = ttk.Labelframe(scrollable_frame, text="  Output Settings  ", bootstyle="success", padding=15)
        output_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(output_frame, text="Output Directory:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky='w', pady=5)
        self.output_dir_var = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.output_dir_var, width=50).grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Button(output_frame, text="Browse...", command=self.browse_output_dir, bootstyle="info-outline").grid(row=0, column=2, pady=5)
        
        ttk.Label(output_frame, text="Filename Pattern:", font=('Segoe UI', 9)).grid(row=1, column=0, sticky='w', pady=5)
        self.filename_pattern_var = tk.StringVar(value="{session}_{filename}")
        ttk.Entry(output_frame, textvariable=self.filename_pattern_var, width=50).grid(row=1, column=1, sticky='ew', pady=5, padx=5)
        ttk.Label(output_frame, text="Tokens: {filename}, {session}, {timestamp}", font=('Segoe UI', 7)).grid(
            row=1, column=2, sticky='w', padx=5)
        
        ttk.Label(output_frame, text="Output Format:", font=('Segoe UI', 9)).grid(row=2, column=0, sticky='w', pady=5)
        self.output_format_var = tk.StringVar(value="png")
        format_frame = ttk.Frame(output_frame)
        format_frame.grid(row=2, column=1, sticky='w', pady=5)
        ttk.Radiobutton(format_frame, text="PNG (Lossless)", variable=self.output_format_var, value="png",
                       bootstyle="success-toolbutton").pack(side='left', padx=5)
        ttk.Radiobutton(format_frame, text="JPG", variable=self.output_format_var, value="jpg",
                       bootstyle="success-toolbutton").pack(side='left', padx=5)
        
        ttk.Label(output_frame, text="JPG Quality:", font=('Segoe UI', 9)).grid(row=3, column=0, sticky='w', pady=5)
        self.jpg_quality_var = tk.IntVar(value=95)
        quality_frame = ttk.Frame(output_frame)
        quality_frame.grid(row=3, column=1, sticky='ew', pady=5, padx=5)
        ttk.Scale(quality_frame, from_=1, to=100, variable=self.jpg_quality_var, orient='horizontal',
                 bootstyle="success").pack(side='left', fill='x', expand=True)
        ttk.Label(quality_frame, textvariable=self.jpg_quality_var, width=4).pack(side='left', padx=5)
        
        output_frame.columnconfigure(1, weight=1)
        
        # Image Processing
        process_frame = ttk.Labelframe(scrollable_frame, text="  Image Processing  ", bootstyle="info", padding=15)
        process_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(process_frame, text="Resize:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky='w', pady=5)
        self.resize_percent_var = tk.IntVar(value=100)
        resize_frame = ttk.Frame(process_frame)
        resize_frame.grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Scale(resize_frame, from_=10, to=100, variable=self.resize_percent_var, orient='horizontal',
                 bootstyle="info").pack(side='left', fill='x', expand=True)
        ttk.Label(resize_frame, textvariable=self.resize_percent_var, width=4).pack(side='left')
        ttk.Label(resize_frame, text="%").pack(side='left', padx=(0, 5))
        
        self.auto_brightness_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(process_frame, text="🔆 Auto Brightness Adjustment", variable=self.auto_brightness_var,
                       command=self.on_auto_brightness_toggle, bootstyle="info-round-toggle").grid(
            row=1, column=0, columnspan=2, sticky='w', pady=5)
        
        ttk.Label(process_frame, text="Brightness Factor:", font=('Segoe UI', 9)).grid(row=2, column=0, sticky='w', pady=5)
        self.brightness_var = tk.DoubleVar(value=1.5)
        self.brightness_scale_frame = ttk.Frame(process_frame)
        self.brightness_scale_frame.grid(row=2, column=1, sticky='ew', pady=5, padx=5)
        self.brightness_scale = ttk.Scale(self.brightness_scale_frame, from_=1.0, to=3.0, variable=self.brightness_var,
                                         orient='horizontal', bootstyle="warning")
        self.brightness_scale.pack(side='left', fill='x', expand=True)
        ttk.Label(self.brightness_scale_frame, textvariable=self.brightness_var, width=4).pack(side='left', padx=5)
        
        self.timestamp_corner_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(process_frame, text="Add timestamp to corner", variable=self.timestamp_corner_var,
                       bootstyle="info-square-toggle").grid(row=3, column=0, columnspan=2, sticky='w', pady=5)
        
        process_frame.columnconfigure(1, weight=1)
        
        # Cleanup Settings
        cleanup_frame = ttk.Labelframe(scrollable_frame, text="  Cleanup Settings  ", bootstyle="warning", padding=15)
        cleanup_frame.pack(fill='x', padx=10, pady=10)
        
        self.cleanup_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cleanup_frame, text="🗑 Enable automatic cleanup", variable=self.cleanup_enabled_var,
                       bootstyle="warning-round-toggle").grid(row=0, column=0, columnspan=3, sticky='w', pady=5)
        
        ttk.Label(cleanup_frame, text="Max Size (GB):", font=('Segoe UI', 9)).grid(row=1, column=0, sticky='w', pady=5)
        self.cleanup_max_size_var = tk.DoubleVar(value=10.0)
        ttk.Spinbox(cleanup_frame, from_=1.0, to=1000.0, increment=1.0, textvariable=self.cleanup_max_size_var,
                   width=10).grid(row=1, column=1, sticky='w', pady=5, padx=5)
        
        ttk.Label(cleanup_frame, text="Strategy:", font=('Segoe UI', 9)).grid(row=2, column=0, sticky='w', pady=5)
        self.cleanup_strategy_var = tk.StringVar(value="oldest")
        strategy_combo = ttk.Combobox(cleanup_frame, textvariable=self.cleanup_strategy_var, width=30, state='readonly',
                                     values=['oldest - Delete oldest files in watch directory'])
        strategy_combo.grid(row=2, column=1, sticky='w', pady=5, padx=5)
        self.create_tooltip(strategy_combo, "Only 'oldest' strategy supported - deletes files by modification time (never deletes folders)")
        
        cleanup_frame.columnconfigure(1, weight=1)
        
        # Apply button
        ttk.Button(scrollable_frame, text="✓ Apply All Settings", command=self.apply_settings,
                  bootstyle="success", width=20).pack(pady=20)
    
    def create_preview_tab(self):
        """Create modern Preview tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Preview  ")
        
        # Controls at top
        controls = ttk.Frame(tab, padding=10)
        controls.pack(fill='x')
        
        ttk.Button(controls, text="🔄 Refresh", command=self.refresh_preview, bootstyle="info").pack(side='left', padx=5)
        ttk.Label(controls, text="Zoom:", font=('Segoe UI', 9)).pack(side='left', padx=(20, 5))
        
        self.preview_zoom_var = tk.IntVar(value=100)
        ttk.Scale(controls, from_=10, to=200, variable=self.preview_zoom_var, orient='horizontal',
                 length=200, command=lambda v: self.refresh_preview(), bootstyle="info").pack(side='left', padx=5)
        ttk.Label(controls, textvariable=self.preview_zoom_var).pack(side='left')
        ttk.Label(controls, text="%").pack(side='left', padx=5)
        
        # Preview area with scrollbars
        preview_container = ttk.Frame(tab)
        preview_container.pack(fill='both', expand=True, padx=10, pady=10)
        
        v_scroll = ttk.Scrollbar(preview_container, orient='vertical', bootstyle="round")
        h_scroll = ttk.Scrollbar(preview_container, orient='horizontal', bootstyle="round")
        
        self.preview_canvas = tk.Canvas(preview_container, bg='#2b2b2b', 
                                       yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        
        v_scroll.config(command=self.preview_canvas.yview)
        h_scroll.config(command=self.preview_canvas.xview)
        
        v_scroll.pack(side='right', fill='y')
        h_scroll.pack(side='bottom', fill='x')
        self.preview_canvas.pack(side='left', fill='both', expand=True)
        
        self.preview_image = None
        self.preview_photo = None
    
    def create_logs_tab(self):
        """Create modern Logs tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Logs  ")
        
        # Controls at top
        controls = ttk.Frame(tab, padding=10)
        controls.pack(fill='x')
        
        ttk.Button(controls, text="🗑 Clear Logs", command=self.clear_logs, bootstyle="danger-outline").pack(side='left', padx=5)
        ttk.Button(controls, text="💾 Save Logs...", command=self.save_logs, bootstyle="info-outline").pack(side='left', padx=5)
        
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Auto-scroll", variable=self.auto_scroll_var,
                       bootstyle="info-round-toggle").pack(side='left', padx=20)
        
        # Log display
        log_frame = ttk.Frame(tab)
        log_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=('Consolas', 9),
                                                  bg='#1e1e1e', fg='#d4d4d4', insertbackground='white')
        self.log_text.pack(fill='both', expand=True)
        self.log_text.config(state='disabled')
        
        # Configure tags for different log levels
        self.log_text.tag_config('ERROR', foreground='#f44747')
        self.log_text.tag_config('WARNING', foreground='#ff8c00')
        self.log_text.tag_config('INFO', foreground='#4ec9b0')
        self.log_text.tag_config('DEBUG', foreground='#858585')
    
    # ===== EVENT HANDLERS =====
    
    def on_closing(self):
        """Handle window close event"""
        # Save window geometry
        self.config.set('window_geometry', self.root.geometry())
        self.save_config()
        
        # Stop any active processes
        self.stop_watching()
        self.stop_camera_capture()
        
        self.root.destroy()
    
    def on_mode_change(self):
        """Handle capture mode change"""
        mode = self.capture_mode_var.get()
        
        if mode == 'watch':
            self.watch_frame.pack(fill='x', padx=10, pady=10, after=self.watch_frame.master.winfo_children()[0])
            self.camera_frame.pack_forget()
        else:
            self.camera_frame.pack(fill='x', padx=10, pady=10, after=self.camera_frame.master.winfo_children()[0])
            self.watch_frame.pack_forget()
    
    def on_auto_exposure_toggle(self):
        """Handle auto exposure checkbox"""
        auto = self.auto_exposure_var.get()
        if auto:
            self.exposure_entry.config(state='disabled')
        else:
            self.exposure_entry.config(state='normal')
    
    def on_auto_brightness_toggle(self):
        """Handle auto brightness checkbox"""
        enabled = self.auto_brightness_var.get()
        if enabled:
            self.brightness_scale.config(state='normal')
        else:
            self.brightness_scale.config(state='disabled')
    
    def on_camera_selected(self, event=None):
        """Handle camera selection"""
        selection = self.camera_combo.current()
        if selection >= 0:
            self.selected_camera_index = selection
            app_logger.info(f"Selected camera index: {selection}")
    
    def on_overlay_edit(self):
        """Handle overlay editor changes - update preview"""
        if self.selected_overlay_index is not None:
            self.update_overlay_preview()
    
    # ===== DIRECTORY/FILE BROWSING =====
    
    def browse_watch_dir(self):
        """Browse for watch directory"""
        dir_path = filedialog.askdirectory(title="Select directory to watch")
        if dir_path:
            self.watch_dir_var.set(dir_path)
    
    def browse_output_dir(self):
        """Browse for output directory"""
        dir_path = filedialog.askdirectory(title="Select output directory")
        if dir_path:
            self.output_dir_var.set(dir_path)
    
    def browse_sdk_path(self):
        """Browse for SDK DLL"""
        file_path = filedialog.askopenfilename(
            title="Select ASICamera2.dll",
            filetypes=[("DLL files", "*.dll"), ("All files", "*.*")]
        )
        if file_path:
            self.sdk_path_var.set(file_path)
    
    # ===== CAMERA OPERATIONS =====
    
    def detect_cameras(self):
        """Detect connected ZWO cameras"""
        sdk_path = self.sdk_path_var.get()
        
        try:
            import zwoasi as asi
            asi.init(sdk_path)
            
            num_cameras = asi.get_num_cameras()
            if num_cameras == 0:
                messagebox.showwarning("No Cameras", "No ZWO cameras detected. Check USB connection and SDK path.")
                self.camera_combo['values'] = []
                return
            
            camera_list = []
            for i in range(num_cameras):
                # Create camera object to get properties
                cam = asi.Camera(i)
                info = cam.get_camera_property()
                camera_list.append(f"{info['Name']} (ID: {info['CameraID']})")
            
            self.camera_combo['values'] = camera_list
            self.camera_combo.current(0)
            self.selected_camera_index = 0
            
            app_logger.info(f"Detected {num_cameras} camera(s)")
            messagebox.showinfo("Success", f"Found {num_cameras} camera(s)")
            
        except Exception as e:
            app_logger.error(f"Camera detection failed: {e}")
            messagebox.showerror("Error", f"Failed to detect cameras:\n{str(e)}")
    
    def start_camera_capture(self):
        """Start ZWO camera capture"""
        try:
            # Get settings
            sdk_path = self.sdk_path_var.get()
            exposure_ms = self.exposure_var.get()
            gain = self.gain_var.get()
            wb_r = self.wb_r_var.get()
            wb_b = self.wb_b_var.get()
            offset = self.offset_var.get()
            flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
            flip = flip_map.get(self.flip_var.get(), 0)
            interval = self.interval_var.get()
            auto_exp = self.auto_exposure_var.get()
            max_exp_ms = self.max_exposure_var.get()
            
            # Initialize camera
            self.zwo_camera = ZWOCamera(
                sdk_path=sdk_path,
                camera_index=self.selected_camera_index,
                exposure_sec=exposure_ms / 1000.0,  # Convert to seconds
                gain=gain,
                white_balance_r=wb_r,
                white_balance_b=wb_b,
                offset=offset,
                flip=flip,
                auto_exposure=auto_exp,
                max_exposure_sec=max_exp_ms / 1000.0  # Convert to seconds
            )
            
            if not self.zwo_camera.connect_camera(self.selected_camera_index):
                raise Exception("Failed to connect to camera")
            
            # Start capture thread
            self.capture_thread = threading.Thread(
                target=self.camera_capture_loop,
                args=(interval,),
                daemon=True
            )
            self.capture_thread.start()
            
            # Update UI
            self.start_capture_button.config(state='disabled')
            self.stop_capture_button.config(state='normal')
            self.camera_status_var.set("Capturing...")
            app_logger.info("Camera capture started")
            
        except Exception as e:
            app_logger.error(f"Failed to start camera: {e}")
            messagebox.showerror("Error", f"Failed to start camera:\n{str(e)}")
    
    def stop_camera_capture(self):
        """Stop camera capture"""
        if self.zwo_camera:
            self.zwo_camera.disconnect_camera()
            self.zwo_camera = None
        
        self.start_capture_button.config(state='normal')
        self.stop_capture_button.config(state='disabled')
        self.camera_status_var.set("Not connected")
        app_logger.info("Camera capture stopped")
    
    def camera_capture_loop(self, interval):
        """Camera capture background thread"""
        while self.zwo_camera and self.zwo_camera.camera:
            try:
                # Capture frame
                img, metadata = self.zwo_camera.capture_single_frame()
                
                if img:
                    self.last_captured_image = img.copy()
                    
                    # Update live preview
                    self.root.after(0, self.update_mini_preview, img)
                    
                    # Process image
                    self.process_and_save_image(img, metadata)
                    
                    # Increment counter
                    self.image_count += 1
                    self.root.after(0, lambda: self.image_count_var.set(str(self.image_count)))
                
                # Wait for next capture
                import time
                time.sleep(interval)
                
            except Exception as e:
                app_logger.error(f"Capture error: {e}")
                break
    
    # ===== DIRECTORY WATCHING =====
    
    def start_watching(self):
        """Start directory watching"""
        watch_dir = self.watch_dir_var.get()
        
        if not watch_dir or not os.path.exists(watch_dir):
            messagebox.showerror("Error", "Please select a valid directory to watch")
            return
        
        try:
            overlays = self.get_overlays_config()
            output_dir = self.output_dir_var.get()
            recursive = self.watch_recursive_var.get()
            
            self.watcher = FileWatcher(
                watch_directory=watch_dir,
                output_directory=output_dir,
                overlays=overlays,
                recursive=recursive,
                callback=self.on_image_processed
            )
            
            self.watcher.start()
            
            # Update UI
            self.start_watch_button.config(state='disabled')
            self.stop_watch_button.config(state='normal')
            app_logger.info(f"Started watching: {watch_dir}")
            
        except Exception as e:
            app_logger.error(f"Failed to start watching: {e}")
            messagebox.showerror("Error", f"Failed to start watching:\n{str(e)}")
    
    def stop_watching(self):
        """Stop directory watching"""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
            
            self.start_watch_button.config(state='normal')
            self.stop_watch_button.config(state='disabled')
            app_logger.info("Stopped watching")
    
    def on_image_processed(self):
        """Callback when watcher processes an image"""
        self.image_count += 1
        self.root.after(0, lambda: self.image_count_var.set(str(self.image_count)))
    
    # ===== IMAGE PROCESSING =====
    
    def process_and_save_image(self, img, metadata):
        """Process image with overlays and save"""
        try:
            # Get config
            overlays = self.get_overlays_config()
            output_dir = self.output_dir_var.get()
            output_format = self.output_format_var.get()
            jpg_quality = self.jpg_quality_var.get()
            resize_percent = self.resize_percent_var.get()
            auto_brightness = self.auto_brightness_var.get()
            brightness_factor = self.brightness_var.get() if auto_brightness else None
            timestamp_corner = self.timestamp_corner_var.get()
            filename_pattern = self.filename_pattern_var.get()
            
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
            
            # Apply auto brightness if enabled
            if auto_brightness and brightness_factor:
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(brightness_factor)
            
            # Add timestamp corner if enabled
            if timestamp_corner:
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(img)
                timestamp_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    font = ImageFont.truetype("arial.ttf", 20)
                except:
                    font = ImageFont.load_default()
                # Top-right corner
                draw.text((img.width - 200, 10), timestamp_text, fill='white', font=font)
            
            # Add overlays
            img = add_overlays(img, overlays, metadata)
            
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
            
            self.last_processed_image = output_path
            self.preview_image = img  # Store for preview
            app_logger.info(f"Saved: {os.path.basename(output_path)}")
            
        except Exception as e:
            app_logger.error(f"Processing failed: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
    
    # ===== OVERLAY MANAGEMENT =====
    
    def get_overlays_config(self):
        """Get current overlays configuration"""
        return self.config.get('overlays', [])
    
    def rebuild_overlay_list(self):
        """Rebuild the overlay list UI"""
        # Clear existing
        for item in self.overlay_list_items:
            item.destroy()
        self.overlay_list_items.clear()
        
        # Get overlays
        overlays = self.get_overlays_config()
        
        # Create items
        for i, overlay in enumerate(overlays):
            item = OverlayListItem(
                self.overlay_list_frame,
                overlay,
                i,
                self.select_overlay,
                self.delete_overlay
            )
            self.overlay_list_items.append(item)
        
        # Select first if available
        if self.overlay_list_items:
            self.select_overlay(self.overlay_list_items[0])
    
    def select_overlay(self, item):
        """Select an overlay for editing"""
        # Deselect all
        for overlay_item in self.overlay_list_items:
            overlay_item.set_selected(False)
        
        # Select this one
        item.set_selected(True)
        self.selected_overlay_index = item.index
        
        # Load into editor
        overlay = item.overlay_data
        self.overlay_text.delete('1.0', 'end')
        self.overlay_text.insert('1.0', overlay.get('text', ''))
        self.anchor_var.set(overlay.get('anchor', 'Bottom-Left'))
        self.color_var.set(overlay.get('color', 'white'))
        self.font_size_var.set(overlay.get('font_size', 24))
        self.font_style_var.set(overlay.get('font_style', 'normal'))
        self.offset_x_var.set(overlay.get('offset_x', 10))
        self.offset_y_var.set(overlay.get('offset_y', 10))
        
        # Update preview
        self.update_overlay_preview()
    
    def add_new_overlay(self):
        """Add new overlay"""
        overlays = self.get_overlays_config()
        overlays.append({
            'text': 'New Overlay {CAMERA}',
            'anchor': 'Bottom-Left',
            'color': 'white',
            'font_size': 24,
            'font_style': 'normal',
            'offset_x': 10,
            'offset_y': 10
        })
        self.config.set('overlays', overlays)
        self.rebuild_overlay_list()
        
        # Select the new overlay
        if self.overlay_list_items:
            self.select_overlay(self.overlay_list_items[-1])
    
    def duplicate_overlay(self):
        """Duplicate selected overlay"""
        if self.selected_overlay_index is not None:
            overlays = self.get_overlays_config()
            if 0 <= self.selected_overlay_index < len(overlays):
                overlay_copy = overlays[self.selected_overlay_index].copy()
                overlays.append(overlay_copy)
                self.config.set('overlays', overlays)
                self.rebuild_overlay_list()
    
    def delete_overlay(self, item):
        """Delete an overlay"""
        if messagebox.askyesno("Confirm", "Delete this overlay?"):
            overlays = self.get_overlays_config()
            if 0 <= item.index < len(overlays):
                overlays.pop(item.index)
                self.config.set('overlays', overlays)
                self.selected_overlay_index = None
                self.rebuild_overlay_list()
    
    def clear_all_overlays(self):
        """Clear all overlays"""
        if messagebox.askyesno("Confirm", "Delete ALL overlays?"):
            self.config.set('overlays', [])
            self.selected_overlay_index = None
            self.rebuild_overlay_list()
            self.overlay_text.delete('1.0', 'end')
            self.overlay_preview_label.config(image='', text="No overlays")
    
    def insert_token(self):
        """Insert selected token into overlay text"""
        token = self.token_var.get()
        if token:
            self.overlay_text.insert('insert', token)
            self.on_overlay_edit()
    
    def apply_overlay_changes(self):
        """Apply changes from editor to selected overlay"""
        if self.selected_overlay_index is not None:
            overlays = self.get_overlays_config()
            if 0 <= self.selected_overlay_index < len(overlays):
                overlays[self.selected_overlay_index] = {
                    'text': self.overlay_text.get('1.0', 'end-1c'),
                    'anchor': self.anchor_var.get(),
                    'color': self.color_var.get(),
                    'font_size': self.font_size_var.get(),
                    'font_style': self.font_style_var.get(),
                    'offset_x': self.offset_x_var.get(),
                    'offset_y': self.offset_y_var.get()
                }
                self.config.set('overlays', overlays)
                self.rebuild_overlay_list()
                app_logger.info("Overlay changes applied")
    
    def reset_overlay_editor(self):
        """Reset editor to selected overlay's saved state"""
        if self.selected_overlay_index is not None:
            item = self.overlay_list_items[self.selected_overlay_index]
            self.select_overlay(item)
    
    def update_overlay_preview(self):
        """Update the overlay preview"""
        try:
            # Create sample image
            preview_img = Image.new('RGB', (400, 300), color='#1a1a2e')
            
            # Add sample text
            draw = ImageDraw.Draw(preview_img)
            draw.text((200, 150), "Sample Sky Image", fill='white', anchor='mm')
            
            # Get current editor values
            overlay_config = {
                'text': self.overlay_text.get('1.0', 'end-1c'),
                'anchor': self.anchor_var.get(),
                'color': self.color_var.get(),
                'font_size': self.font_size_var.get(),
                'font_style': self.font_style_var.get(),
                'offset_x': self.offset_x_var.get(),
                'offset_y': self.offset_y_var.get()
            }
            
            # Sample metadata
            metadata = {
                'CAMERA': 'ASI676MC',
                'EXPOSURE': '100ms',
                'GAIN': '150',
                'TEMP': '-5.2°C',
                'RES': '3840x2160',
                'FILENAME': 'sample.fits',
                'SESSION': datetime.now().strftime('%Y-%m-%d'),
                'DATETIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Apply overlay
            preview_img = add_overlays(preview_img, [overlay_config], metadata)
            
            # Display
            photo = ImageTk.PhotoImage(preview_img)
            self.overlay_preview_label.config(image=photo, text='')
            self.overlay_preview_image = photo  # Keep reference
            
        except Exception as e:
            app_logger.error(f"Preview update failed: {e}")
    
    # ===== PREVIEW TAB =====
    
    def load_preview_image(self):
        """Load image for preview"""
        file_path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.fits *.fit"), ("All files", "*.*")]
        )
        if file_path:
            try:
                self.preview_image = Image.open(file_path)
                self.refresh_preview()
                app_logger.info(f"Loaded preview: {os.path.basename(file_path)}")
            except Exception as e:
                app_logger.error(f"Failed to load image: {e}")
                messagebox.showerror("Error", f"Failed to load image:\n{str(e)}")
    
    def refresh_preview(self):
        """Refresh preview display"""
        # Use the last processed image or last captured image
        if not self.preview_image:
            # Try to load the last processed image file
            if self.last_processed_image and os.path.exists(self.last_processed_image):
                try:
                    self.preview_image = Image.open(self.last_processed_image)
                except Exception as e:
                    app_logger.error(f"Failed to load preview: {e}")
                    return
            else:
                return
        
        try:
            zoom = self.preview_zoom_var.get() / 100.0
            new_size = (int(self.preview_image.width * zoom), int(self.preview_image.height * zoom))
            display_img = self.preview_image.resize(new_size, Image.Resampling.LANCZOS)
            
            self.preview_photo = ImageTk.PhotoImage(display_img)
            self.preview_canvas.delete('all')
            self.preview_canvas.create_image(0, 0, anchor='nw', image=self.preview_photo)
            self.preview_canvas.config(scrollregion=self.preview_canvas.bbox('all'))
        except Exception as e:
            app_logger.error(f"Preview refresh failed: {e}")
    
    # ===== LIVE MONITORING =====
    
    def update_mini_preview(self, img):
        """Update mini preview in header"""
        try:
            # Resize to fit
            thumb = img.copy()
            thumb.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(thumb)
            self.mini_preview_label.config(image=photo, text='')
            self.mini_preview_image = photo  # Keep reference
            
            # Update histogram
            self.update_histogram(img)
            
        except Exception as e:
            app_logger.error(f"Mini preview update failed: {e}")
    
    def update_histogram(self, img):
        """Update RGB histogram"""
        try:
            import numpy as np
            
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
            self.histogram_canvas.delete('all')
            
            # Draw histograms
            width = self.histogram_canvas.winfo_width()
            if width <= 1:
                width = 600
            bin_width = width / 256
            
            for i in range(256):
                x = i * bin_width
                # Red
                self.histogram_canvas.create_line(x, 100, x, 100 - hist_r[i], fill='#ff6b6b', width=bin_width)
                # Green (with transparency effect)
                self.histogram_canvas.create_line(x, 100, x, 100 - hist_g[i], fill='#51cf66', width=bin_width)
                # Blue
                self.histogram_canvas.create_line(x, 100, x, 100 - hist_b[i], fill='#339af0', width=bin_width)
            
        except Exception as e:
            app_logger.error(f"Histogram update failed: {e}")
    
    # ===== STATUS UPDATES =====
    
    def update_status_header(self):
        """Update status header periodically"""
        try:
            # Mode status
            if self.watcher and self.watcher.observer.is_alive():
                mode = "Directory Watch - Running"
                info = f"Watching: {self.watch_dir_var.get()}"
            elif self.zwo_camera and self.zwo_camera.camera:
                mode = "ZWO Camera - Capturing"
                cam_name = self.camera_list_var.get().split(' (')[0] if self.camera_list_var.get() else "Unknown"
                exp_ms = self.exposure_var.get()
                info = f"{cam_name} • Exposure: {exp_ms}ms • Gain: {self.gain_var.get()}"
            else:
                mode = "Idle"
                info = "No active session"
            
            self.mode_status_var.set(f"Mode: {mode}")
            self.capture_info_var.set(info)
            
            # Output info
            output_dir = self.output_dir_var.get()
            if output_dir:
                self.output_info_var.set(output_dir)
            else:
                self.output_info_var.set("Not configured")
            
        except Exception as e:
            app_logger.error(f"Status update failed: {e}")
        finally:
            # Schedule next update
            self.root.after(1000, self.update_status_header)
    
    # ===== LOG MANAGEMENT =====
    
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
                self.log_text.config(state='normal')
                self.log_text.insert('end', f"{message}\n", level_part)
                if self.auto_scroll_var.get():
                    self.log_text.see('end')
                self.log_text.config(state='disabled')
                
                # Update mini log (keep last 10 lines)
                self.mini_log_text.config(state='normal')
                content = self.mini_log_text.get('1.0', 'end')
                lines = content.strip().split('\n')
                if len(lines) >= 10:
                    lines = lines[-9:]
                lines.append(msg_part if msg_part else message)
                self.mini_log_text.delete('1.0', 'end')
                self.mini_log_text.insert('1.0', '\n'.join(lines))
                self.mini_log_text.see('end')
                self.mini_log_text.config(state='disabled')
                    
        except Exception as e:
            print(f"Log polling error: {e}")
        finally:
            self.root.after(100, self.poll_logs)
    
    def clear_logs(self):
        """Clear log display"""
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')
    
    def save_logs(self):
        """Save logs to file"""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                content = self.log_text.get('1.0', 'end-1c')
                with open(file_path, 'w') as f:
                    f.write(content)
                app_logger.info(f"Logs saved to: {file_path}")
            except Exception as e:
                app_logger.error(f"Failed to save logs: {e}")
                messagebox.showerror("Error", f"Failed to save logs:\n{str(e)}")
    
    # ===== CONFIGURATION =====
    
    def load_config(self):
        """Load configuration into GUI"""
        self.capture_mode_var.set(self.config.get('capture_mode', 'watch'))
        self.watch_dir_var.set(self.config.get('watch_directory', ''))
        self.watch_recursive_var.set(self.config.get('watch_recursive', True))
        self.output_dir_var.set(self.config.get('output_directory', ''))
        
        # Handle old config keys
        filename_pattern = self.config.get('filename_pattern', self.config.get('output_pattern', '{session}_{filename}'))
        self.filename_pattern_var.set(filename_pattern)
        
        output_format = self.config.get('output_format', 'png')
        if output_format.upper() == 'JPG':
            output_format = 'jpg'
        elif output_format.upper() == 'PNG':
            output_format = 'png'
        self.output_format_var.set(output_format.lower())
        
        self.jpg_quality_var.set(self.config.get('jpg_quality', 95))
        self.resize_percent_var.set(self.config.get('resize_percent', 100))
        self.auto_brightness_var.set(self.config.get('auto_brightness', False))
        
        # Handle old brightness keys
        brightness = self.config.get('brightness_factor', 
                                    self.config.get('auto_brightness_factor',
                                                   self.config.get('preview_brightness', 1.5)))
        self.brightness_var.set(brightness)
        
        # Handle old timestamp corner key
        timestamp = self.config.get('timestamp_corner', False)
        if isinstance(timestamp, bool):
            self.timestamp_corner_var.set(timestamp)
        else:
            # It's a string like "Top-Right", convert to boolean
            self.timestamp_corner_var.set(self.config.get('show_timestamp_corner', False))
        
        self.cleanup_enabled_var.set(self.config.get('cleanup_enabled', False))
        self.cleanup_max_size_var.set(self.config.get('cleanup_max_size_gb', 10.0))
        
        # ZWO settings - handle old key names
        self.sdk_path_var.set(self.config.get('zwo_sdk_path', 'ASICamera2.dll'))
        
        # Handle exposure in both ms and seconds
        exposure = self.config.get('zwo_exposure_ms', self.config.get('zwo_exposure', 100.0))
        self.exposure_var.set(exposure)
        
        self.gain_var.set(self.config.get('zwo_gain', 100))
        self.wb_r_var.set(self.config.get('zwo_wb_r', 75))
        self.wb_b_var.set(self.config.get('zwo_wb_b', 99))
        self.offset_var.set(self.config.get('zwo_offset', 20))
        
        # Handle flip - convert string to int if needed
        flip_val = self.config.get('zwo_flip', 0)
        flip_map_reverse = {'None': 'None', 0: 'None', 1: 'Horizontal', 2: 'Vertical', 3: 'Both'}
        if isinstance(flip_val, str):
            self.flip_var.set(flip_val)
        else:
            self.flip_var.set(flip_map_reverse.get(flip_val, 'None'))
        
        # Handle interval
        interval = self.config.get('zwo_interval', self.config.get('zwo_capture_interval', 5.0))
        self.interval_var.set(interval)
        
        self.auto_exposure_var.set(self.config.get('zwo_auto_exposure', False))
        
        # Handle max exposure
        max_exp = self.config.get('zwo_max_exposure_ms', self.config.get('zwo_max_exposure', 30000.0))
        self.max_exposure_var.set(max_exp)
        
        # Update UI states
        self.on_mode_change()
        self.on_auto_exposure_toggle()
        self.on_auto_brightness_toggle()
        
        # Load overlays - handle old field names
        overlays = self.config.get('overlays', [])
        # Convert old overlay format to new format
        for overlay in overlays:
            if 'x_offset' in overlay and 'offset_x' not in overlay:
                overlay['offset_x'] = overlay['x_offset']
            if 'y_offset' in overlay and 'offset_y' not in overlay:
                overlay['offset_y'] = overlay['y_offset']
            if 'font_style' not in overlay:
                overlay['font_style'] = 'normal'
        
        self.rebuild_overlay_list()
    
    def save_config(self):
        """Save current configuration"""
        self.config.set('capture_mode', self.capture_mode_var.get())
        self.config.set('watch_directory', self.watch_dir_var.get())
        self.config.set('watch_recursive', self.watch_recursive_var.get())
        self.config.set('output_directory', self.output_dir_var.get())
        self.config.set('filename_pattern', self.filename_pattern_var.get())
        self.config.set('output_format', self.output_format_var.get())
        self.config.set('jpg_quality', self.jpg_quality_var.get())
        self.config.set('resize_percent', self.resize_percent_var.get())
        self.config.set('auto_brightness', self.auto_brightness_var.get())
        self.config.set('brightness_factor', self.brightness_var.get())
        self.config.set('timestamp_corner', self.timestamp_corner_var.get())
        self.config.set('cleanup_enabled', self.cleanup_enabled_var.get())
        self.config.set('cleanup_max_size_gb', self.cleanup_max_size_var.get())
        
        # ZWO settings
        self.config.set('zwo_sdk_path', self.sdk_path_var.get())
        self.config.set('zwo_exposure_ms', self.exposure_var.get())
        self.config.set('zwo_gain', self.gain_var.get())
        self.config.set('zwo_wb_r', self.wb_r_var.get())
        self.config.set('zwo_wb_b', self.wb_b_var.get())
        self.config.set('zwo_offset', self.offset_var.get())
        flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
        self.config.set('zwo_flip', flip_map.get(self.flip_var.get(), 0))
        self.config.set('zwo_interval', self.interval_var.get())
        self.config.set('zwo_auto_exposure', self.auto_exposure_var.get())
        self.config.set('zwo_max_exposure_ms', self.max_exposure_var.get())
        
        self.config.save()
        app_logger.info("Configuration saved")
    
    def apply_settings(self):
        """Apply all settings"""
        self.save_config()
        messagebox.showinfo("Success", "Settings applied and saved")


def main():
    """Main entry point"""
    # Create root window with ttkbootstrap theme
    root = ttk.Window(themename="darkly")  # Options: darkly, cyborg, superhero, solar, cosmo, etc.
    
    # Create app
    app = ModernOverlayApp(root)
    
    # Run
    root.mainloop()


if __name__ == "__main__":
    main()

