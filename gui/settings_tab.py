"""
Settings tab component - output, processing, and cleanup settings
Modern dark theme with consistent styling matching Capture tab
"""
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip
from .theme import (COLORS, FONTS, SPACING, LAYOUT, configure_dark_input_styles, 
                   create_card, create_secondary_button, create_primary_button,
                   create_gradient_scrollable_frame, ToggleButtonGroup, ToggleSwitch)


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
        # Create scrollable frame with gradient background for content
        scroll_container, scrollable_content = create_gradient_scrollable_frame(self.tab)
        scroll_container.pack(fill='both', expand=True)
        
        # Content frame with padding - transparent to show gradient
        # Note: Cards will have their own solid backgrounds for readability
        container = tk.Frame(scrollable_content)
        container.pack(fill='both', expand=True,
                      padx=SPACING['card_margin_x'],
                      pady=SPACING['card_margin_y'])
        
        # Output Mode Card - NEW: Select File/Webserver/RTSP streaming
        output_mode_card_frame = create_card(container, title="Output Mode")
        output_mode_card_frame.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
        self.create_output_mode_selector(output_mode_card_frame)
        
        # Weather Settings Card - NEW: OpenWeatherMap API integration
        weather_card = create_card(container, title="Weather Settings (Optional)")
        weather_card.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
        self.create_weather_settings(weather_card)
        
        # Image Processing Card - full width
        processing_card = create_card(container, title="Image Processing")
        processing_card.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
        self.create_processing_settings(processing_card)
        
        # Cleanup Settings Card - full width
        cleanup_card = create_card(container, title="Cleanup Settings")
        cleanup_card.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
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
        
        # Check if ffmpeg is available for RTSP
        ffmpeg_available = self._check_ffmpeg_available()
        
        # Build options list (exclude RTSP if ffmpeg not available)
        options = [
            ('file', '💾 Save to File'),
            ('webserver', '🌐 Web Server'),
        ]
        if ffmpeg_available:
            options.append(('rtsp', '📡 RTSP Stream'))
        
        # Create styled toggle button group
        toggle_group = ToggleButtonGroup(
            btn_frame,
            options=options,
            variable=self.app.output_mode_var,
            command=lambda: self.app.on_output_mode_change(),
            bg=COLORS['bg_card']
        )
        toggle_group.pack(side='left')
        
        # RTSP warning if not available
        if not ffmpeg_available:
            rtsp_hint = tk.Label(
                btn_frame,
                text="(RTSP requires ffmpeg)",
                font=FONTS['tiny'],
                bg=COLORS['bg_card'],
                fg=COLORS['text_muted']
            )
            rtsp_hint.pack(side='left', padx=(SPACING['element_gap'], 0))
        
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
        
        # Use custom styled toggle button group
        format_toggle = ToggleButtonGroup(
            format_frame,
            options=[('png', 'PNG (Lossless)'), ('jpg', 'JPG')],
            variable=self.app.output_format_var,
            bg=COLORS['bg_card']
        )
        format_toggle.pack(side='left')
        
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
        
        # Image Path (always visible)
        tk.Label(grid, text="Image Path:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'webserver_path_var'):
            self.app.webserver_path_var = tk.StringVar(value='/latest')
        path_entry = ttk.Entry(grid, textvariable=self.app.webserver_path_var,
                              font=FONTS['body'], style='Dark.TEntry', width=20)
        path_entry.grid(row=row, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        row += 1
        
        # Advanced Settings toggle - using custom styled toggle
        if not hasattr(self.app, 'webserver_advanced_var'):
            self.app.webserver_advanced_var = tk.BooleanVar(value=False)
        
        advanced_toggle = ToggleSwitch(
            grid,
            text="⚙️ Show Advanced Settings (IP & Port)",
            variable=self.app.webserver_advanced_var,
            command=self._toggle_webserver_advanced,
            bg=COLORS['bg_card']
        )
        advanced_toggle.grid(row=row, column=0, columnspan=2, sticky='w', pady=(SPACING['element_gap'], SPACING['row_gap']))
        
        row += 1
        
        # Advanced settings frame (hidden by default)
        self.webserver_advanced_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        self.webserver_advanced_frame.grid(row=row, column=0, columnspan=2, sticky='ew')
        self.webserver_advanced_frame.grid_remove()  # Hidden by default
        
        # Create advanced settings content
        adv_grid = tk.Frame(self.webserver_advanced_frame, bg=COLORS['bg_card'])
        adv_grid.pack(fill='x')
        adv_grid.columnconfigure(1, weight=1)
        
        # Warning label
        warning_frame = tk.Frame(adv_grid, bg=COLORS['bg_card'])
        warning_frame.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, SPACING['row_gap']))
        
        tk.Label(warning_frame, text="⚠️",
                font=FONTS['body'], bg=COLORS['bg_card'], fg=COLORS['status_connecting']).pack(side='left')
        tk.Label(warning_frame, 
                text=" Changing IP/Port may cause conflicts. Use 0.0.0.0 for all interfaces.",
                font=FONTS['small'], bg=COLORS['bg_card'], fg=COLORS['status_connecting']).pack(side='left')
        
        # Host setting
        tk.Label(adv_grid, text="Bind IP:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=1, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        if not hasattr(self.app, 'webserver_host_var'):
            self.app.webserver_host_var = tk.StringVar(value='127.0.0.1')
        
        host_frame = tk.Frame(adv_grid, bg=COLORS['bg_card'])
        host_frame.grid(row=1, column=1, sticky='w', pady=(0, SPACING['row_gap']))
        
        host_entry = ttk.Entry(host_frame, textvariable=self.app.webserver_host_var,
                              font=FONTS['body'], style='Dark.TEntry', width=15)
        host_entry.pack(side='left')
        host_entry.bind('<FocusOut>', self._on_webserver_advanced_change)
        
        tk.Label(host_frame, text="(127.0.0.1 = local only)",
                font=FONTS['tiny'], bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left', padx=(5, 0))
        
        # Port setting
        tk.Label(adv_grid, text="Port:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=2, column=0, sticky='w')
        
        if not hasattr(self.app, 'webserver_port_var'):
            self.app.webserver_port_var = tk.IntVar(value=8080)
        
        port_frame = tk.Frame(adv_grid, bg=COLORS['bg_card'])
        port_frame.grid(row=2, column=1, sticky='w')
        
        port_spin = ttk.Spinbox(port_frame, from_=1024, to=65535,
                               textvariable=self.app.webserver_port_var,
                               font=FONTS['body'], style='Dark.TSpinbox', width=8)
        port_spin.pack(side='left')
        port_spin.bind('<FocusOut>', self._on_webserver_advanced_change)
        
        tk.Label(port_frame, text="(1024-65535)",
                font=FONTS['tiny'], bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left', padx=(5, 0))
        
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
        
        # Use custom styled toggle button group
        format_toggle = ToggleButtonGroup(
            format_frame,
            options=[('png', 'PNG (Lossless)'), ('jpg', 'JPG')],
            variable=self.app.output_format_var,
            bg=COLORS['bg_card']
        )
        format_toggle.pack(side='left')
        
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
    
    
    def create_weather_settings(self, parent):
        """Create weather API settings (OpenWeatherMap) - Optimized compact layout"""
        # Main container with better spacing
        container = tk.Frame(parent, bg=COLORS['bg_card'])
        container.pack(fill='x', padx=5, pady=5)
        
        # === Row 1: Info and Link ===
        info_row = tk.Frame(container, bg=COLORS['bg_card'])
        info_row.pack(fill='x', pady=(0, 8))
        
        tk.Label(info_row, 
                text="🌤️ Add live weather data to overlays • ",
                font=FONTS['small'],
                bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left')
        
        link_label = tk.Label(info_row,
                text="Get free API key (1000 calls/day)",
                font=FONTS['small'],
                bg=COLORS['bg_card'], fg=COLORS['accent_primary'],
                cursor='hand2')
        link_label.pack(side='left')
        link_label.bind('<Button-1>', lambda e: self._open_weather_url())
        
        # === Row 2: API Key (full width) ===
        api_row = tk.Frame(container, bg=COLORS['bg_card'])
        api_row.pack(fill='x', pady=(0, 6))
        
        tk.Label(api_row, text="API Key:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=12, anchor='w').pack(side='left')
        
        # OpenWeatherMap label
        tk.Label(api_row, text="(OpenWeatherMap)", font=FONTS['tiny'],
                bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='right', padx=(5, 0))
        
        if not hasattr(self.app, 'weather_api_key_var'):
            self.app.weather_api_key_var = tk.StringVar()
        api_entry = ttk.Entry(api_row, textvariable=self.app.weather_api_key_var,
                             font=FONTS['body'], style='Dark.TEntry', show='*')
        api_entry.pack(side='left', fill='x', expand=True, padx=(0, 5))
        
        # Show/Hide toggle
        self.weather_api_show_var = tk.BooleanVar(value=False)
        show_btn = ttk.Checkbutton(api_row, text="Show",
                                   variable=self.weather_api_show_var,
                                   command=lambda: api_entry.config(
                                       show='' if self.weather_api_show_var.get() else '*'),
                                   bootstyle="primary-round-toggle")
        show_btn.pack(side='left')
        
        # === Row 3: Location OR Coordinates (all on one row) ===
        loc_row = tk.Frame(container, bg=COLORS['bg_card'])
        loc_row.pack(fill='x', pady=(0, 2))
        
        tk.Label(loc_row, text="Location:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=12, anchor='w').pack(side='left')
        
        if not hasattr(self.app, 'weather_location_var'):
            self.app.weather_location_var = tk.StringVar()
        location_entry = ttk.Entry(loc_row, textvariable=self.app.weather_location_var,
                                   font=FONTS['body'], style='Dark.TEntry', width=18)
        location_entry.pack(side='left', padx=(0, 10))
        
        # Separator
        tk.Label(loc_row, text="or", font=FONTS['small'],
                bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left', padx=(0, 10))
        
        # Latitude
        tk.Label(loc_row, text="Lat:", font=FONTS['small'],
                bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left')
        
        if not hasattr(self.app, 'weather_lat_var'):
            self.app.weather_lat_var = tk.StringVar()
        lat_entry = ttk.Entry(loc_row, textvariable=self.app.weather_lat_var,
                              font=FONTS['body'], style='Dark.TEntry', width=10)
        lat_entry.pack(side='left', padx=(2, 8))
        
        # Longitude
        tk.Label(loc_row, text="Lon:", font=FONTS['small'],
                bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack(side='left')
        
        if not hasattr(self.app, 'weather_lon_var'):
            self.app.weather_lon_var = tk.StringVar()
        lon_entry = ttk.Entry(loc_row, textvariable=self.app.weather_lon_var,
                              font=FONTS['body'], style='Dark.TEntry', width=10)
        lon_entry.pack(side='left', padx=(2, 0))
        
        # Hint row
        hint_row = tk.Frame(container, bg=COLORS['bg_card'])
        hint_row.pack(fill='x', pady=(0, 8))
        tk.Label(hint_row, text="", width=12).pack(side='left')  # Spacer
        tk.Label(hint_row, 
                text="City name (e.g., London,GB) or coordinates • Lat/Lon preferred if both provided",
                font=FONTS['tiny'], bg=COLORS['bg_card'],
                fg=COLORS['text_muted']).pack(side='left')
        
        # === Row 4: Units + Test + Status (compact inline) ===
        control_row = tk.Frame(container, bg=COLORS['bg_card'])
        control_row.pack(fill='x', pady=(0, 8))
        
        tk.Label(control_row, text="Units:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=12, anchor='w').pack(side='left')
        
        if not hasattr(self.app, 'weather_units_var'):
            self.app.weather_units_var = tk.StringVar(value='metric')
        
        # Units toggle using custom styled toggle button group
        units_toggle = ToggleButtonGroup(
            control_row,
            options=[('metric', '°C'), ('imperial', '°F')],
            variable=self.app.weather_units_var,
            bg=COLORS['bg_card']
        )
        units_toggle.pack(side='left', padx=(0, 12))
        
        # Test button
        test_btn = create_secondary_button(control_row, "🌐 Test",
                                          self.app.test_weather_connection)
        test_btn.pack(side='left', padx=(0, 10))
        
        # Status (flexible width)
        if not hasattr(self.app, 'weather_status_var'):
            self.app.weather_status_var = tk.StringVar(value="Not configured")
        tk.Label(control_row, textvariable=self.app.weather_status_var,
                font=FONTS['small'], bg=COLORS['bg_card'],
                fg=COLORS['text_muted'], anchor='w').pack(side='left', fill='x', expand=True)
        
        # === Row 5: Weather Icon Helper ===
        icon_row = tk.Frame(container, bg=COLORS['bg_card'])
        icon_row.pack(fill='x', pady=(4, 0))
        
        tk.Label(icon_row, text="", width=12).pack(side='left')  # Spacer
        
        icon_btn = create_primary_button(icon_row, "🌤️ Add Weather Icon",
                                          self.app.add_weather_icon_overlay)
        icon_btn.pack(side='left', padx=(0, 8))
        
        tk.Label(icon_row, 
                text="Dynamic icon that updates with conditions",
                font=FONTS['tiny'], bg=COLORS['bg_card'],
                fg=COLORS['text_muted']).pack(side='left')
    
    def _open_weather_url(self):
        """Open OpenWeatherMap API page in browser"""
        import webbrowser
        webbrowser.open('https://openweathermap.org/api')
    
    
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
            text=f"{self.app.brightness_var.get():.2f}",
            font=FONTS['body_bold'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_disabled'],
            width=6
        )
        self.app.brightness_value_label.pack(side='left')
        
        # Update label and preview when slider moves
        def update_brightness_label(*args):
            self.app.brightness_value_label.config(text=f"{self.app.brightness_var.get():.2f}")
            # Refresh preview if there's an image loaded
            if self.app.last_processed_pil_image:
                self.app.root.after(10, lambda: self.app.refresh_preview(auto_fit=False))
        
        # Remove any existing traces to prevent duplicates
        try:
            for trace_id in self.app.brightness_var.trace_info():
                self.app.brightness_var.trace_remove(*trace_id)
        except:
            pass
        
        self.app.brightness_var.trace_add('write', update_brightness_label)
        
        ToolTip(self.app.brightness_scale,
               text="Post-processing brightness adjustment for saved images (1.0 = no change). Does not affect camera exposure.",
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
            text=f"{self.app.saturation_var.get():.2f}",
            font=FONTS['body'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_primary'],
            width=6
        )
        self.app.saturation_value_label.pack(side='left')
        
        # Update label and preview when slider moves
        def update_saturation_label(*args):
            self.app.saturation_value_label.config(text=f"{self.app.saturation_var.get():.2f}")
            # Refresh preview if there's an image loaded
            if self.app.last_processed_pil_image:
                self.app.root.after(10, lambda: self.app.refresh_preview(auto_fit=False))
        
        # Remove any existing traces to prevent duplicates
        try:
            for trace_id in self.app.saturation_var.trace_info():
                self.app.saturation_var.trace_remove(*trace_id)
        except:
            pass
        
        self.app.saturation_var.trace_add('write', update_saturation_label)
        
        ToolTip(self.app.saturation_scale,
               text="Color saturation adjustment (0.0 = grayscale, 1.0 = neutral, 2.0 = very saturated)",
               bootstyle="success-inverse")
        
        row += 1
        
        # === Auto Stretch Section ===
        # Separator
        ttk.Separator(grid, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=SPACING['section_gap'])
        row += 1
        
        # Auto Stretch Toggle
        self.app.auto_stretch_var = tk.BooleanVar(value=False)
        stretch_check = ttk.Checkbutton(grid, text="✨ Auto Stretch (MTF)",
                                       variable=self.app.auto_stretch_var,
                                       command=self._on_auto_stretch_toggle,
                                       bootstyle="info-round-toggle")
        stretch_check.grid(row=row, column=0, columnspan=3, sticky='w',
                          pady=(0, SPACING['row_gap']))
        
        ToolTip(stretch_check,
               text="Apply Midtone Transfer Function stretch to enhance image contrast. "
                    "Best for fixed-exposure captures - brings out detail without changing camera settings.",
               bootstyle="info-inverse")
        
        row += 1
        
        # Target Median (how bright the midtones should be)
        tk.Label(grid, text="Target Brightness:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        stretch_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        stretch_frame.grid(row=row, column=1, sticky='ew', 
                          pady=(0, SPACING['row_gap']), columnspan=2)
        
        self.app.stretch_median_var = tk.DoubleVar(value=0.25)
        self.app.stretch_median_scale = ttk.Scale(
            stretch_frame,
            from_=0.1, to=0.5,
            variable=self.app.stretch_median_var,
            orient='horizontal',
            bootstyle="info",
            state='disabled'
        )
        self.app.stretch_median_scale.pack(side='left', fill='x', expand=True,
                                           padx=(0, SPACING['row_gap']))
        
        self.app.stretch_median_label = tk.Label(
            stretch_frame,
            text=f"{int(self.app.stretch_median_var.get()*100)}%",
            font=FONTS['body_bold'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_disabled'],
            width=6
        )
        self.app.stretch_median_label.pack(side='left')
        
        def update_stretch_median(*args):
            self.app.stretch_median_label.config(
                text=f"{int(self.app.stretch_median_var.get()*100)}%"
            )
            if self.app.last_processed_pil_image:
                self.app.root.after(10, lambda: self.app.refresh_preview(auto_fit=False))
        
        try:
            for trace_id in self.app.stretch_median_var.trace_info():
                self.app.stretch_median_var.trace_remove(*trace_id)
        except:
            pass
        
        self.app.stretch_median_var.trace_add('write', update_stretch_median)
        
        ToolTip(self.app.stretch_median_scale,
               text="Target brightness for midtones (10-50%). Lower = darker sky, higher = brighter details",
               bootstyle="info-inverse")
        
        row += 1
        
        # Linked stretch checkbox
        self.app.stretch_linked_var = tk.BooleanVar(value=True)
        linked_check = ttk.Checkbutton(grid, text="Linked RGB channels",
                                      variable=self.app.stretch_linked_var,
                                      bootstyle="info-square-toggle",
                                      state='disabled')
        linked_check.grid(row=row, column=0, columnspan=3, sticky='w',
                         pady=(0, SPACING['row_gap']))
        self.app.stretch_linked_check = linked_check
        
        ToolTip(linked_check,
               text="When enabled, applies same stretch to all color channels (preserves color). "
                    "When disabled, stretches each channel independently (may shift colors).",
               bootstyle="info-inverse")
        
        row += 1
        
        # Preserve Blacks checkbox
        self.app.stretch_preserve_blacks_var = tk.BooleanVar(value=True)
        preserve_blacks_check = ttk.Checkbutton(grid, text="Preserve black point",
                                               variable=self.app.stretch_preserve_blacks_var,
                                               bootstyle="info-square-toggle",
                                               state='disabled')
        preserve_blacks_check.grid(row=row, column=0, columnspan=3, sticky='w',
                                  pady=(0, SPACING['row_gap']))
        self.app.stretch_preserve_blacks_check = preserve_blacks_check
        
        ToolTip(preserve_blacks_check,
               text="Keep true blacks dark instead of lifting them to grey. "
                    "Prevents the washed-out look while still stretching midtones.",
               bootstyle="info-inverse")
        
        row += 1
        
        # Shadow Aggressiveness slider
        tk.Label(grid, text="Shadow Clip:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        shadow_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        shadow_frame.grid(row=row, column=1, sticky='ew', 
                         pady=(0, SPACING['row_gap']), columnspan=2)
        
        self.app.stretch_shadow_var = tk.DoubleVar(value=2.8)
        self.app.stretch_shadow_scale = ttk.Scale(
            shadow_frame,
            from_=1.5, to=4.5,  # 1.5=aggressive (more grey), 4.5=gentle (darker blacks)
            variable=self.app.stretch_shadow_var,
            orient='horizontal',
            bootstyle="info",
            state='disabled'
        )
        self.app.stretch_shadow_scale.pack(side='left', fill='x', expand=True,
                                           padx=(0, SPACING['row_gap']))
        
        self.app.stretch_shadow_label = tk.Label(
            shadow_frame,
            text="Std",
            font=FONTS['body_bold'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_disabled'],
            width=8
        )
        self.app.stretch_shadow_label.pack(side='left')
        
        def update_shadow_label(*args):
            val = self.app.stretch_shadow_var.get()
            if val <= 2.0:
                label = "Aggressive"
            elif val <= 3.0:
                label = "Standard"
            else:
                label = "Gentle"
            self.app.stretch_shadow_label.config(text=label)
            if self.app.last_processed_pil_image:
                self.app.root.after(10, lambda: self.app.refresh_preview(auto_fit=False))
        
        try:
            for trace_id in self.app.stretch_shadow_var.trace_info():
                self.app.stretch_shadow_var.trace_remove(*trace_id)
        except:
            pass
        
        self.app.stretch_shadow_var.trace_add('write', update_shadow_label)
        
        ToolTip(self.app.stretch_shadow_scale,
               text="How aggressively to clip shadows. Gentle = darker blacks preserved, Aggressive = more lifted.",
               bootstyle="info-inverse")
        
        row += 1
        
        # Saturation Boost slider
        tk.Label(grid, text="Saturation Boost:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=LAYOUT['label_width'], anchor='w').grid(
            row=row, column=0, sticky='w', pady=(0, SPACING['row_gap']))
        
        sat_boost_frame = tk.Frame(grid, bg=COLORS['bg_card'])
        sat_boost_frame.grid(row=row, column=1, sticky='ew', 
                            pady=(0, SPACING['row_gap']), columnspan=2)
        
        self.app.stretch_saturation_var = tk.DoubleVar(value=1.5)
        self.app.stretch_saturation_scale = ttk.Scale(
            sat_boost_frame,
            from_=1.0, to=2.0,  # 1.0=none, 2.0=strong
            variable=self.app.stretch_saturation_var,
            orient='horizontal',
            bootstyle="info",
            state='disabled'
        )
        self.app.stretch_saturation_scale.pack(side='left', fill='x', expand=True,
                                               padx=(0, SPACING['row_gap']))
        
        self.app.stretch_saturation_label = tk.Label(
            sat_boost_frame,
            text="1.5x",
            font=FONTS['body_bold'],
            bg=COLORS['bg_card'],
            fg=COLORS['text_disabled'],
            width=6
        )
        self.app.stretch_saturation_label.pack(side='left')
        
        def update_saturation_label(*args):
            val = self.app.stretch_saturation_var.get()
            self.app.stretch_saturation_label.config(text=f"{val:.1f}x")
            if self.app.last_processed_pil_image:
                self.app.root.after(10, lambda: self.app.refresh_preview(auto_fit=False))
        
        try:
            for trace_id in self.app.stretch_saturation_var.trace_info():
                self.app.stretch_saturation_var.trace_remove(*trace_id)
        except:
            pass
        
        self.app.stretch_saturation_var.trace_add('write', update_saturation_label)
        
        ToolTip(self.app.stretch_saturation_scale,
               text="Boost color saturation after stretch (1.0 = no boost, 2.0 = double). "
                    "Helps restore color vibrancy that stretching can reduce.",
               bootstyle="info-inverse")
        
        row += 1
        
        # === End Auto Stretch Section ===
        
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
    
    def _on_auto_stretch_toggle(self):
        """Handle auto-stretch enable/disable toggle"""
        enabled = self.app.auto_stretch_var.get()
        
        if enabled:
            # Enable stretch controls
            self.app.stretch_median_scale.config(state='normal')
            self.app.stretch_median_label.config(fg=COLORS['text_primary'])
            self.app.stretch_linked_check.config(state='normal')
            self.app.stretch_preserve_blacks_check.config(state='normal')
            self.app.stretch_shadow_scale.config(state='normal')
            self.app.stretch_shadow_label.config(fg=COLORS['text_primary'])
            self.app.stretch_saturation_scale.config(state='normal')
            self.app.stretch_saturation_label.config(fg=COLORS['text_primary'])
        else:
            # Disable stretch controls
            self.app.stretch_median_scale.config(state='disabled')
            self.app.stretch_median_label.config(fg=COLORS['text_disabled'])
            self.app.stretch_linked_check.config(state='disabled')
            self.app.stretch_preserve_blacks_check.config(state='disabled')
            self.app.stretch_shadow_scale.config(state='disabled')
            self.app.stretch_shadow_label.config(fg=COLORS['text_disabled'])
            self.app.stretch_saturation_scale.config(state='disabled')
            self.app.stretch_saturation_label.config(fg=COLORS['text_disabled'])
        
        # Refresh preview if there's an image loaded
        if self.app.last_processed_pil_image:
            self.app.root.after(10, lambda: self.app.refresh_preview(auto_fit=False))
    
    def _toggle_webserver_advanced(self):
        """Toggle visibility of advanced webserver settings (IP/Port)"""
        if self.app.webserver_advanced_var.get():
            # Show warning when enabling advanced settings
            from tkinter import messagebox
            messagebox.showwarning(
                "Advanced Settings Warning",
                "⚠️ Changing the web server IP or port may cause issues:\n\n"
                "• Port conflicts with other applications\n"
                "• Firewall blocking connections\n"
                "• Services unable to connect\n\n"
                "IP Options:\n"
                "• 127.0.0.1 - Local machine only (default, safest)\n"
                "• 0.0.0.0 - All network interfaces (allows remote access)\n"
                "• Specific IP - Bind to a specific interface\n\n"
                "After making changes, click 'Apply All Settings'.\n"
                "The web server will restart with the new settings."
            )
            self.webserver_advanced_frame.grid()
        else:
            self.webserver_advanced_frame.grid_remove()
    
    def _on_webserver_advanced_change(self, event=None):
        """Placeholder for future validation if needed"""
        pass
    
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