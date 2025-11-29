"""
Settings tab component - output, processing, and cleanup settings
Modern dark theme with consistent styling matching Capture tab
"""
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip
from .theme import COLORS, FONTS, SPACING, LAYOUT, configure_dark_input_styles, create_card, create_secondary_button


class SettingsTab:
    """Settings tab for output, processing, and cleanup configuration"""
    
    def __init__(self, notebook, app):
        self.app = app
        self.tab = ttk.Frame(notebook)
        notebook.add(self.tab, text="  Settings  ")
        
        # Configure dark theme styles for inputs (if not already done)
        configure_dark_input_styles()
        
        self.create_ui()
    
    
    def create_ui(self):
        """Create the settings tab UI with full-width layout"""
        # Main container - full width with same margins as Capture tab
        container = tk.Frame(self.tab, bg=COLORS['bg_primary'])
        container.pack(fill='both', expand=True, 
                      padx=SPACING['card_margin_x'], 
                      pady=SPACING['card_margin_y'])
        
        # Output Mode Card - NEW: Select File/Webserver/RTSP streaming
        output_mode_card_frame = create_card(container, title="Output Mode")
        output_mode_card_frame.master.pack(fill='x', pady=(0, SPACING['section_gap']))
        self.create_output_mode_selector(output_mode_card_frame)
        
        # Image Processing Card - full width
        processing_card = create_card(container, title="Image Processing")
        processing_card.master.pack(fill='x', pady=(0, SPACING['section_gap']))
        self.create_processing_settings(processing_card)
        
        # Cleanup Settings Card - full width
        cleanup_card = create_card(container, title="Cleanup Settings")
        cleanup_card.master.pack(fill='x', pady=(0, SPACING['section_gap']))
        self.create_cleanup_settings(cleanup_card)
        
        # Apply button - right-aligned with card edge
        btn_container = tk.Frame(container, bg=COLORS['bg_primary'])
        btn_container.pack(fill='x', pady=(SPACING['element_gap'], 0))
        
        from .theme import create_primary_button
        apply_btn = create_primary_button(
            btn_container, "✓ Apply All Settings",
            self.app.apply_settings
        )
        apply_btn.pack(side='right')
    
    
    def create_output_mode_selector(self, parent):
        """Create output mode selector (File/Webserver/RTSP)"""
        # Mode selector buttons
        btn_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        btn_frame.pack(fill='x', pady=(0, SPACING['section_gap']))
        
        # Initialize output mode var if not exists
        if not hasattr(self.app, 'output_mode_var'):
            self.app.output_mode_var = tk.StringVar(value='file')
        
        modes = [
            ('file', '💾 Save to File', 'Save processed images to output directory (default)'),
            ('webserver', '🌐 Web Server', 'Serve latest image via HTTP (for NINA, browsers)'),
            ('rtsp', '📡 RTSP Stream', 'Stream via RTSP protocol (for VLC, viewers)')
        ]
        
        # Check if ffmpeg is available for RTSP
        ffmpeg_available = self._check_ffmpeg_available()
        
        for mode_id, label, tooltip in modes:
            btn = ttk.Radiobutton(
                btn_frame,
                text=label,
                variable=self.app.output_mode_var,
                value=mode_id,
                command=lambda: self.app.on_output_mode_change(),
                bootstyle="primary-toolbutton"
            )
            btn.pack(side='left', padx=(0, SPACING['element_gap']))
            
            # Disable RTSP if ffmpeg not found
            if mode_id == 'rtsp' and not ffmpeg_available:
                btn.config(state='disabled')
                ToolTip(btn, text="⚠️ RTSP requires ffmpeg\n\nInstall ffmpeg and add to PATH to enable.\nSee README.md for instructions.", bootstyle="warning-inverse")
            else:
                ToolTip(btn, text=tooltip, bootstyle="primary-inverse")
        
        # Status display (shows URLs when servers running) with copy button
        status_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        status_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        self.app.output_mode_status_var = tk.StringVar(value="Mode: File (default)")
        status_label = tk.Label(
            status_frame,
            textvariable=self.app.output_mode_status_var,
            font=FONTS['small'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_muted'],
            anchor='w'
        )
        status_label.pack(side='left', fill='x', expand=True)
        
        # Copy button (hidden in file mode)
        from .theme import create_secondary_button
        self.app.output_mode_copy_btn = create_secondary_button(
            status_frame,
            "📋 Copy URL",
            self.app.copy_output_url
        )
        self.app.output_mode_copy_btn.pack(side='right')
        self.app.output_mode_copy_btn.pack_forget()  # Hidden by default
        
        # File mode settings (shown by default)
        self.app.file_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        
        file_grid = tk.Frame(self.app.file_frame, bg=COLORS['bg_card'])
        file_grid.pack(fill='x')
        file_grid.columnconfigure(1, weight=1)
        
        row = 0
        
        # Output Directory
        tk.Label(file_grid, text="Output Directory:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'output_dir_var'):
            self.app.output_dir_var = tk.StringVar()
        output_entry = ttk.Entry(file_grid, textvariable=self.app.output_dir_var,
                                font=FONTS['body'], style='Dark.TEntry')
        output_entry.grid(row=row, column=1, sticky='ew', 
                         pady=(0, SPACING['row_gap']), padx=(0, SPACING['element_gap']))
        
        browse_btn = create_secondary_button(file_grid, "Browse...", self.app.browse_output_dir)
        browse_btn.grid(row=row, column=2, pady=(0, SPACING['row_gap']))
        
        row += 1
        
        # Filename Pattern
        tk.Label(file_grid, text="Filename Pattern:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['element_gap']))
        
        if not hasattr(self.app, 'filename_pattern_var'):
            self.app.filename_pattern_var = tk.StringVar(value="{session}_{filename}")
        pattern_entry = ttk.Entry(file_grid, textvariable=self.app.filename_pattern_var,
                                 font=FONTS['body'], style='Dark.TEntry')
        pattern_entry.grid(row=row, column=1, columnspan=2, sticky='ew',
                          pady=(0, SPACING['element_gap']))
        
        row += 1
        
        # Tokens helper text
        tk.Label(file_grid, text="", width=LAYOUT['label_width']).grid(row=row, column=0)
        tk.Label(file_grid, text="Tokens: {filename}, {session}, {timestamp}",
                font=FONTS['tiny'], bg=COLORS['bg_card'],
                fg=COLORS['text_muted']).grid(
            row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']), columnspan=2)
        
        row += 1
        
        # Output Format
        tk.Label(file_grid, text="Output Format:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'output_format_var'):
            self.app.output_format_var = tk.StringVar(value="png")
        format_frame = tk.Frame(file_grid, bg=COLORS['bg_card'])
        format_frame.grid(row=row, column=1, sticky='w', 
                         pady=(0, SPACING['row_gap']), columnspan=2)
        
        ttk.Radiobutton(format_frame, text="PNG (Lossless)",
                       variable=self.app.output_format_var, value="png",
                       bootstyle="primary-toolbutton").pack(side='left', padx=(0, 10))
        ttk.Radiobutton(format_frame, text="JPG",
                       variable=self.app.output_format_var, value="jpg",
                       bootstyle="primary-toolbutton").pack(side='left')
        
        row += 1
        
        # JPG Quality
        tk.Label(file_grid, text="JPG Quality:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w')
        
        if not hasattr(self.app, 'jpg_quality_var'):
            self.app.jpg_quality_var = tk.IntVar(value=95)
        quality_frame = tk.Frame(file_grid, bg=COLORS['bg_card'])
        quality_frame.grid(row=row, column=1, sticky='ew', columnspan=2)
        
        ttk.Scale(quality_frame, from_=1, to=100, variable=self.app.jpg_quality_var,
                 orient='horizontal', bootstyle="primary").pack(
            side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        tk.Label(quality_frame, textvariable=self.app.jpg_quality_var,
                font=FONTS['body_bold'], bg=COLORS['bg_card'],
                fg=COLORS['text_primary'], width=3).pack(side='left')
        
        # Webserver settings (hidden by default)
        self.app.webserver_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        
        grid = tk.Frame(self.app.webserver_frame, bg=COLORS['bg_card'])
        grid.pack(fill='x')
        grid.columnconfigure(1, weight=1)
        
        row = 0
        tk.Label(grid, text="Host:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'webserver_host_var'):
            self.app.webserver_host_var = tk.StringVar(value='127.0.0.1')
        host_entry = ttk.Entry(grid, textvariable=self.app.webserver_host_var,
                              font=FONTS['body'], style='Dark.TEntry', width=20)
        host_entry.grid(row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        row += 1
        tk.Label(grid, text="Port:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'webserver_port_var'):
            self.app.webserver_port_var = tk.IntVar(value=8080)
        port_spin = ttk.Spinbox(grid, from_=1024, to=65535,
                               textvariable=self.app.webserver_port_var,
                               font=FONTS['body'], style='Dark.TSpinbox', width=10)
        port_spin.grid(row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        row += 1
        tk.Label(grid, text="Image Path:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w')
        
        if not hasattr(self.app, 'webserver_path_var'):
            self.app.webserver_path_var = tk.StringVar(value='/latest')
        path_entry = ttk.Entry(grid, textvariable=self.app.webserver_path_var,
                              font=FONTS['body'], style='Dark.TEntry', width=20)
        path_entry.grid(row=row, column=1, sticky='w')
        
        # RTSP settings (hidden by default)
        self.app.rtsp_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        
        grid2 = tk.Frame(self.app.rtsp_frame, bg=COLORS['bg_card'])
        grid2.pack(fill='x')
        grid2.columnconfigure(1, weight=1)
        
        row = 0
        tk.Label(grid2, text="Host:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'rtsp_host_var'):
            self.app.rtsp_host_var = tk.StringVar(value='127.0.0.1')
        host_entry = ttk.Entry(grid2, textvariable=self.app.rtsp_host_var,
                              font=FONTS['body'], style='Dark.TEntry', width=20)
        host_entry.grid(row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        row += 1
        tk.Label(grid2, text="Port:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'rtsp_port_var'):
            self.app.rtsp_port_var = tk.IntVar(value=8554)
        port_spin = ttk.Spinbox(grid2, from_=1024, to=65535,
                               textvariable=self.app.rtsp_port_var,
                               font=FONTS['body'], style='Dark.TSpinbox', width=10)
        port_spin.grid(row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        row += 1
        tk.Label(grid2, text="Stream Name:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'rtsp_stream_name_var'):
            self.app.rtsp_stream_name_var = tk.StringVar(value='asiwatchdog')
        stream_entry = ttk.Entry(grid2, textvariable=self.app.rtsp_stream_name_var,
                                font=FONTS['body'], style='Dark.TEntry', width=20)
        stream_entry.grid(row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        row += 1
        tk.Label(grid2, text="FPS:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w')
        
        if not hasattr(self.app, 'rtsp_fps_var'):
            self.app.rtsp_fps_var = tk.DoubleVar(value=1.0)
        fps_spin = ttk.Spinbox(grid2, from_=0.1, to=30.0, increment=0.5,
                              textvariable=self.app.rtsp_fps_var,
                              font=FONTS['body'], style='Dark.TSpinbox', width=10)
        fps_spin.grid(row=row, column=1, sticky='w')
    
    
    def create_output_settings(self, parent):
        """Create output settings with grid layout"""
        # Grid container
        grid = tk.Frame(parent, bg=COLORS['bg_card'])
        grid.pack(fill='x')
        grid.columnconfigure(1, weight=1)  # Make input column expandable
        
        row = 0
        
        # Output Directory
        tk.Label(grid, text="Output Directory:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        self.app.output_dir_var = tk.StringVar()
        output_entry = ttk.Entry(grid, textvariable=self.app.output_dir_var,
                                font=FONTS['body'], style='Dark.TEntry')
        output_entry.grid(row=row, column=1, sticky='ew', 
                         pady=(0, SPACING['row_gap']), padx=(0, SPACING['element_gap']))
        
        browse_btn = create_secondary_button(grid, "Browse...", self.app.browse_output_dir)
        browse_btn.grid(row=row, column=2, pady=(0, SPACING['row_gap']))
        
        row += 1
        
        # Filename Pattern
        tk.Label(grid, text="Filename Pattern:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['element_gap']))
        
        self.app.filename_pattern_var = tk.StringVar(value="{session}_{filename}")
        pattern_entry = ttk.Entry(grid, textvariable=self.app.filename_pattern_var,
                                 font=FONTS['body'], style='Dark.TEntry')
        pattern_entry.grid(row=row, column=1, columnspan=2, sticky='ew',
                          pady=(0, SPACING['element_gap']))
        
        row += 1
        
        # Tokens helper text
        tk.Label(grid, text="", width=LAYOUT['label_width']).grid(row=row, column=0)
        tk.Label(grid, text="Tokens: {filename}, {session}, {timestamp}",
                font=FONTS['tiny'], bg=COLORS['bg_card'],
                fg=COLORS['text_muted']).grid(
            row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']), columnspan=2)
        
        row += 1
        
        # Output Format
        tk.Label(grid, text="Output Format:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        self.app.output_format_var = tk.StringVar(value="png")
        format_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        format_frame.grid(row=row, column=1, sticky='w', 
                         pady=(0, SPACING['row_gap']), columnspan=2)
        
        ttk.Radiobutton(format_frame, text="PNG (Lossless)",
                       variable=self.app.output_format_var, value="png",
                       bootstyle="primary-toolbutton").pack(side='left', padx=(0, 10))
        ttk.Radiobutton(format_frame, text="JPG",
                       variable=self.app.output_format_var, value="jpg",
                       bootstyle="primary-toolbutton").pack(side='left')
        
        row += 1
        
        # JPG Quality
        tk.Label(grid, text="JPG Quality:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w')
        
        self.app.jpg_quality_var = tk.IntVar(value=95)
        quality_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        quality_frame.grid(row=row, column=1, sticky='ew', columnspan=2)
        
        ttk.Scale(quality_frame, from_=1, to=100, variable=self.app.jpg_quality_var,
                 orient='horizontal', bootstyle="primary").pack(
            side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        tk.Label(quality_frame, textvariable=self.app.jpg_quality_var,
                font=FONTS['body_bold'], bg=COLORS['bg_card'],
                fg=COLORS['text_primary'], width=3).pack(side='left')
    
    
    def create_processing_settings(self, parent):
        """Create image processing settings with grid layout"""
        # Grid container
        grid = tk.Frame(parent, bg=COLORS['bg_card'])
        grid.pack(fill='x')
        grid.columnconfigure(1, weight=1)  # Make input column expandable
        
        row = 0
        
        # Resize
        tk.Label(grid, text="Resize:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        self.app.resize_percent_var = tk.IntVar(value=100)
        resize_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        resize_frame.grid(row=row, column=1, sticky='ew', 
                         pady=(0, SPACING['row_gap']), columnspan=2)
        
        ttk.Scale(resize_frame, from_=10, to=100, variable=self.app.resize_percent_var,
                 orient='horizontal', bootstyle="primary").pack(
            side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        tk.Label(resize_frame, textvariable=self.app.resize_percent_var,
                font=FONTS['body_bold'], bg=COLORS['bg_card'],
                fg=COLORS['text_primary'], width=3).pack(side='left', padx=(0, 2))
        
        tk.Label(resize_frame, text="%", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left')
        
        row += 1
        
        # Auto Brightness
        self.app.auto_brightness_var = tk.BooleanVar(value=False)
        auto_check = ttk.Checkbutton(grid, text="🔆 Auto Brightness Adjustment",
                                    variable=self.app.auto_brightness_var,
                                    command=self.app.on_auto_brightness_toggle,
                                    bootstyle="primary-round-toggle")
        auto_check.grid(row=row, column=0, columnspan=3, sticky='w',
                       pady=(0, SPACING['row_gap']))
        
        ToolTip(auto_check,
               text="Analyze each image's brightness and auto-enhance (dark images boosted more than bright ones)",
               bootstyle="primary-inverse")
        
        row += 1
        
        # Brightness Factor (manual multiplier)
        tk.Label(grid, text="Brightness Multiplier:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        self.app.brightness_var = tk.DoubleVar(value=1.0)
        
        factor_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        factor_frame.grid(row=row, column=1, sticky='ew', 
                         pady=(0, SPACING['row_gap']), columnspan=2)
        
        self.app.brightness_scale = ttk.Scale(
            factor_frame,
            from_=0.5, to=2.0,
            variable=self.app.brightness_var,
            orient='horizontal',
            bootstyle="warning",
            state='disabled'
        )
        self.app.brightness_scale.pack(side='left', fill='x', expand=True,
                                       padx=(0, SPACING['row_gap']))
        
        self.app.brightness_value_label = tk.Label(
            factor_frame,
            textvariable=self.app.brightness_var,
            font=FONTS['body_bold'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_disabled'],
            width=4
        )
        self.app.brightness_value_label.pack(side='left')
        
        ToolTip(self.app.brightness_scale,
               text="Multiplier applied on top of auto brightness (1.0 = neutral, >1.0 = brighter, <1.0 = darker)",
               bootstyle="warning-inverse")
        
        row += 1
        
        # Saturation Factor
        tk.Label(grid, text="Saturation:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        scale_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        scale_frame.grid(row=row, column=1, sticky='ew', pady=(0, SPACING['row_gap']))
        
        self.app.saturation_var = tk.DoubleVar(value=1.0)
        self.app.saturation_scale = ttk.Scale(
            scale_frame,
            from_=0.0, to=2.0,
            orient='horizontal',
            variable=self.app.saturation_var,
            bootstyle="success"
        )
        self.app.saturation_scale.pack(side='left', fill='x', expand=True,
                                       padx=(0, SPACING['element_gap']))
        
        self.app.saturation_value_label = tk.Label(
            scale_frame,
            textvariable=self.app.saturation_var,
            font=FONTS['body'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_primary'],
            width=4
        )
        self.app.saturation_value_label.pack(side='left')
        
        ToolTip(self.app.saturation_scale,
               text="Color saturation adjustment (0.0 = grayscale, 1.0 = neutral, 2.0 = very saturated)",
               bootstyle="success-inverse")
        
        row += 1
        
        # Timestamp
        self.app.timestamp_corner_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(grid, text="Add timestamp to corner",
                       variable=self.app.timestamp_corner_var,
                       bootstyle="primary-square-toggle").grid(
            row=row, column=0, columnspan=3, sticky='w')
    
    
    def create_cleanup_settings(self, parent):
        """Create cleanup settings with grid layout"""
        # Grid container
        grid = tk.Frame(parent, bg=COLORS['bg_card'])
        grid.pack(fill='x')
        grid.columnconfigure(1, weight=1)  # Make input column expandable
        
        row = 0
        
        # Enable cleanup checkbox
        self.app.cleanup_enabled_var = tk.BooleanVar(value=False)
        cleanup_check = ttk.Checkbutton(grid, text="🗑 Enable automatic cleanup",
                                       variable=self.app.cleanup_enabled_var,
                                       command=self._on_cleanup_toggle,
                                       bootstyle="warning-round-toggle")
        cleanup_check.grid(row=row, column=0, columnspan=3, sticky='w',
                          pady=(0, SPACING['row_gap']))
        
        row += 1
        
        # Max Size
        tk.Label(grid, text="Max Size (GB):", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        self.app.cleanup_max_size_var = tk.DoubleVar(value=10.0)
        self.app.cleanup_size_spinbox = ttk.Spinbox(
            grid,
            from_=1.0, to=1000.0, increment=1.0,
            textvariable=self.app.cleanup_max_size_var,
            width=12, font=FONTS['body'],
            style='Dark.TSpinbox',
            state='disabled'
        )
        self.app.cleanup_size_spinbox.grid(row=row, column=1, sticky='w',
                                          pady=(0, SPACING['row_gap']))
        
        row += 1
        
        # Strategy
        tk.Label(grid, text="Strategy:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w')
        
        self.app.cleanup_strategy_var = tk.StringVar(value="oldest")
        self.app.cleanup_strategy_combo = ttk.Combobox(
            grid,
            textvariable=self.app.cleanup_strategy_var,
            width=40, font=FONTS['body'],
            style='Dark.TCombobox',
            state='disabled',
            values=['oldest - Delete oldest files in watch directory']
        )
        self.app.cleanup_strategy_combo.grid(row=row, column=1, sticky='ew', columnspan=2)
        
        ToolTip(self.app.cleanup_strategy_combo,
               text="Only 'oldest' strategy supported - deletes files by modification time (never deletes folders)",
               bootstyle="warning-inverse")
    
    def _on_cleanup_toggle(self):
        """Handle cleanup enable/disable toggle"""
        enabled = self.app.cleanup_enabled_var.get()
        
        if enabled:
            self.app.cleanup_size_spinbox.config(state='normal')
            self.app.cleanup_strategy_combo.config(state='readonly')
        else:
            self.app.cleanup_size_spinbox.config(state='disabled')
            self.app.cleanup_strategy_combo.config(state='disabled')
    
    def _check_ffmpeg_available(self):
        """Check if ffmpeg is available in PATH"""
        import subprocess
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            return result.returncode == 0
        except:
            return False