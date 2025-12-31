"""
Capture tab component - handles directory watch and ZWO camera capture modes
Production-polished UI with consistent dark theme styling
"""
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip
from .theme import COLORS, FONTS, SPACING, LAYOUT, configure_dark_input_styles, create_primary_button, create_secondary_button, create_destructive_button, create_card, create_gradient_scrollable_frame


class CaptureTab:
    """Capture tab with directory watch and camera capture modes"""
    
    def __init__(self, notebook, app):
        self.app = app
        self.tab = ttk.Frame(notebook)
        notebook.add(self.tab, text="  Capture  ")
        
        # Detection state
        self.detecting = False
        
        # Configure dark theme styles for inputs
        configure_dark_input_styles()
        
        self.create_ui()
    
    def create_ui(self):
        """Create the capture tab UI with production polish"""
        # Create scrollable frame for content
        scroll_container, scrollable_content = create_gradient_scrollable_frame(self.tab)
        scroll_container.pack(fill='both', expand=True)
        
        # Content frame with padding
        container = tk.Frame(scrollable_content, bg=COLORS['bg_primary'])
        container.pack(fill='both', expand=True, padx=SPACING['card_margin_x'], pady=SPACING['card_margin_y'])
        
        # Mode selection - horizontal segmented control
        self.create_mode_selector(container)
        
        # Directory Watch Settings (full-width card)
        self.create_watch_section(container)
        
        # ZWO Camera Settings (full-width card)
        self.create_camera_section(container)
    
    def create_mode_selector(self, parent):
        """Create horizontal segmented mode selector with equal-width buttons"""
        # Use theme create_card for consistent styling
        mode_content = create_card(parent, title="Capture Mode")
        
        # Horizontal button frame - centered
        button_frame = tk.Frame(mode_content, bg=COLORS['bg_card'])
        button_frame.pack(anchor='center', pady=(0, 0))
        
        self.app.capture_mode_var = tk.StringVar(value='watch')
        
        # Create mode buttons using theme - will be styled dynamically
        self.watch_mode_btn = create_secondary_button(
            button_frame, "📁 Directory Watch Mode",
            lambda: self.select_mode('watch')
        )
        self.watch_mode_btn.config(width=24)  # Wider to prevent cutoff
        self.watch_mode_btn.pack(side='left', padx=(0, 2))
        
        self.camera_mode_btn = create_secondary_button(
            button_frame, "📷 ZWO Camera Capture Mode",
            lambda: self.select_mode('camera')
        )
        self.camera_mode_btn.config(width=26)  # Wider for longer text
        self.camera_mode_btn.pack(side='left')
        
        # Pack the card container
        mode_content.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
    
    def update_mode_button_styling(self):
        """Update mode button styling based on current mode (call after config load)"""
        mode = self.app.capture_mode_var.get()
        if mode == 'watch':
            # Watch mode selected - filled
            self.watch_mode_btn.config(
                bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                activebackground=COLORS['accent_primary_hover'], 
                activeforeground=COLORS['text_primary']
            )
            # Camera mode unselected - outline
            self.camera_mode_btn.config(
                bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                activebackground='#3A3A3A', activeforeground='#C0C0C0'
            )
        else:  # camera mode
            # Camera mode selected - filled
            self.camera_mode_btn.config(
                bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                activebackground=COLORS['accent_primary_hover'], 
                activeforeground=COLORS['text_primary']
            )
            # Watch mode unselected - outline
            self.watch_mode_btn.config(
                bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                activebackground='#3A3A3A', activeforeground='#C0C0C0'
            )
    
    def select_mode(self, mode):
        """Handle mode selection with auto-detection for camera mode"""
        self.app.capture_mode_var.set(mode)
        
        if mode == 'watch':
            # Watch mode selected - filled
            self.watch_mode_btn.config(
                bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                activebackground=COLORS['accent_primary_hover'], 
                activeforeground=COLORS['text_primary']
            )
            # Camera mode unselected - outline
            self.camera_mode_btn.config(
                bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                activebackground='#3A3A3A', activeforeground='#C0C0C0'
            )
        else:
            # Camera mode selected - filled
            self.camera_mode_btn.config(
                bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                activebackground=COLORS['accent_primary_hover'], 
                activeforeground=COLORS['text_primary']
            )
            # Watch mode unselected - outline
            self.watch_mode_btn.config(
                bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                activebackground='#3A3A3A', activeforeground='#C0C0C0'
            )
        
        # Trigger mode change
        self.app.on_mode_change()
    
    def create_watch_section(self, parent):
        """Create directory watch settings section with dark theme inputs"""
        # Use create_card for consistent styling
        watch_content = create_card(parent, title="Directory Watch Settings")
        self.app.watch_frame = watch_content  # Store reference for show/hide logic
        
        # Watch directory row
        dir_frame = tk.Frame(watch_content, bg=COLORS['bg_card'])
        dir_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(dir_frame, text="Watch Directory:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=16, anchor='w').pack(side='left', padx=(0, SPACING['row_gap']))
        
        self.app.watch_dir_var = tk.StringVar()
        watch_entry = ttk.Entry(dir_frame, textvariable=self.app.watch_dir_var,
                               font=FONTS['body'], style='Dark.TEntry')
        watch_entry.pack(side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        browse_btn = create_secondary_button(dir_frame, "Browse...", self.app.browse_watch_dir)
        browse_btn.pack(side='left')
        
        # Recursive checkbox
        self.app.watch_recursive_var = tk.BooleanVar(value=True)
        check_frame = tk.Frame(watch_content, bg=COLORS['bg_card'])
        check_frame.pack(fill='x', pady=(0, SPACING['section_gap']))
        
        check = ttk.Checkbutton(check_frame, text="Watch subdirectories recursively",
                               variable=self.app.watch_recursive_var, 
                               bootstyle="success-round-toggle")
        check.pack(anchor='w')
        
        # Buttons - right aligned
        btn_frame = tk.Frame(watch_content, bg=COLORS['bg_card'])
        btn_frame.pack(fill='x', pady=(0, 0))
        
        btn_container = tk.Frame(btn_frame, bg=COLORS['bg_card'])
        btn_container.pack(side='right')
        
        self.app.start_watch_button = create_primary_button(
            btn_container, "▶ Start Watching", self.app.start_watching
        )
        self.app.start_watch_button.pack(side='left', padx=(0, SPACING['button_gap']))
        
        self.app.stop_watch_button = create_destructive_button(
            btn_container, "⏸ Stop Watching", self.app.stop_watching
        )
        self.app.stop_watch_button.config(state='disabled')
        self.app.stop_watch_button.pack(side='left')
        
        # Pack the card container
        watch_content.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
    
    def create_camera_section(self, parent):
        """Create ZWO camera settings section with 2-column grid layout"""
        # Use create_card for consistent styling
        camera_content = create_card(parent, title="ZWO Camera Settings")
        self.app.camera_frame = camera_content  # Store reference for show/hide logic
        
        # SDK and Camera Detection
        self.create_sdk_section(camera_content)
        
        # Camera parameters in 2-column grid
        self.create_camera_params_grid(camera_content)
        
        # Buttons - right aligned
        btn_container = tk.Frame(camera_content, bg=COLORS['bg_card'])
        btn_container.pack(fill='x', pady=(SPACING['section_gap'], 0))
        
        btn_frame = tk.Frame(btn_container, bg=COLORS['bg_card'])
        btn_frame.pack(side='right')
        
        self.app.start_capture_button = create_primary_button(
            btn_frame, "▶ Start Capture", self.app.start_camera_capture
        )
        self.app.start_capture_button.config(state='disabled')
        self.app.start_capture_button.pack(side='left', padx=(0, SPACING['button_gap']))
        
        self.app.stop_capture_button = create_destructive_button(
            btn_frame, "⏸ Stop Capture", self.app.stop_camera_capture
        )
        self.app.stop_capture_button.config(state='disabled')
        self.app.stop_capture_button.pack(side='left')
        
        # Pack the card container
        camera_content.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
    
    def create_sdk_section(self, parent):
        """Create SDK path and camera detection section with inline status"""
        sdk_container = tk.Frame(parent, bg=COLORS['bg_card'])
        sdk_container.pack(fill='x', pady=(0, SPACING['section_gap']))
        
        # SDK path row
        sdk_row = tk.Frame(sdk_container, bg=COLORS['bg_card'])
        sdk_row.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(sdk_row, text="SDK DLL Path:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=16, anchor='w').pack(side='left', padx=(0, SPACING['row_gap']))
        
        from utils_paths import resource_path
        self.app.sdk_path_var = tk.StringVar(value=resource_path("ASICamera2.dll"))
        sdk_entry = ttk.Entry(sdk_row, textvariable=self.app.sdk_path_var,
                             font=FONTS['body'], style='Dark.TEntry')
        sdk_entry.pack(side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        sdk_browse = create_secondary_button(sdk_row, "Browse...", self.app.browse_sdk_path)
        sdk_browse.pack(side='left')
        
        # Camera detection with spinner
        detect_row = tk.Frame(sdk_container, bg=COLORS['bg_card'])
        detect_row.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        self.app.detect_cameras_button = create_primary_button(
            detect_row, "🔍 Detect Cameras", self.app.detect_cameras
        )
        self.app.detect_cameras_button.pack(side='left', padx=(0, SPACING['row_gap']))
        
        # Spinner (hidden by default)
        self.spinner_label = tk.Label(detect_row, text="⌛", font=FONTS['title'],
                                     bg=COLORS['bg_card'], fg=COLORS['accent_primary'])
        
        # Detection error label (inline)
        self.app.detection_error_label = tk.Label(sdk_container, text="",
                                                 font=FONTS['small'],
                                                 bg=COLORS['bg_card'], fg=COLORS['accent_destructive'])
        self.app.detection_error_label.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        # Camera selection with inline status
        camera_row = tk.Frame(sdk_container, bg=COLORS['bg_card'])
        camera_row.pack(fill='x', pady=(0, 0))
        
        tk.Label(camera_row, text="Camera:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=16, anchor='w').pack(side='left', padx=(0, SPACING['row_gap']))
        
        # Camera dropdown
        self.app.camera_list_var = tk.StringVar()
        self.app.camera_combo = ttk.Combobox(camera_row, textvariable=self.app.camera_list_var,
                                            state='readonly', font=FONTS['body'], 
                                            style='Dark.TCombobox', width=30)
        self.app.camera_combo.pack(side='left', fill='x', expand=True, padx=(0, SPACING['section_gap']))
        self.app.camera_combo.bind('<<ComboboxSelected>>', self.app.on_camera_selected)
        
        # Status indicator inline
        status_frame = tk.Frame(camera_row, bg=COLORS['bg_card'])
        status_frame.pack(side='left')
        
        tk.Label(status_frame, text="Status:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary']).pack(side='left', padx=(0, 6))
        
        # Status dot canvas
        self.app.camera_status_dot = tk.Canvas(status_frame, width=10, height=10, 
                                              bg=COLORS['bg_card'], 
                                              highlightthickness=0)
        self.app.camera_status_dot.pack(side='left', padx=(0, 6))
        self.app.camera_status_dot.create_oval(2, 2, 8, 8, fill=COLORS['status_idle'], outline='')
        
        # Status text
        self.app.camera_status_var = tk.StringVar(value="Not Connected")
        tk.Label(status_frame, textvariable=self.app.camera_status_var, 
                font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary']).pack(side='left')
    
    def create_camera_params_grid(self, parent):
        """Create camera parameters in 2-column grid layout"""
        grid_container = tk.Frame(parent, bg=COLORS['bg_card'])
        grid_container.pack(fill='both', expand=True, pady=(SPACING['section_gap'], 0))
        
        # Configure grid to be responsive
        grid_container.grid_columnconfigure(0, weight=1, minsize=300)
        grid_container.grid_columnconfigure(1, weight=1, minsize=300)
        grid_container.grid_rowconfigure(0, weight=1)
        
        # Left column - Core Camera Controls
        left_col = tk.Frame(grid_container, bg=COLORS['bg_card'])
        left_col.grid(row=0, column=0, sticky='nsew', padx=(0, SPACING['element_gap']))
        
        # Exposure with unit selector
        exp_row = tk.Frame(left_col, bg=COLORS['bg_card'])
        exp_row.pack(fill='x', pady=(0, 12))
        
        tk.Label(exp_row, text="Exposure:", font=FONTS['body'],
                bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                width=12, anchor='w').pack(side='left', padx=(0, SPACING['row_gap']))
        
        self.app.exposure_var = tk.DoubleVar(value=1.0)
        self.app.exposure_entry = ttk.Entry(exp_row, textvariable=self.app.exposure_var,
                                           font=FONTS['body'], style='Dark.TEntry',
                                           width=14)
        self.app.exposure_entry.pack(side='left', padx=(0, 8))
        
        # Unit selector (segmented control)
        self.app.exposure_unit_var = tk.StringVar(value='s')
        unit_frame = tk.Frame(exp_row, bg=COLORS['border'], relief='flat', borderwidth=1)
        unit_frame.pack(side='left')
        
        self.ms_btn = tk.Button(unit_frame, text="ms", command=lambda: self.set_exposure_unit('ms'),
                               font=('Segoe UI', 8), bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                               activebackground='#3A3A3A', activeforeground='#C0C0C0',
                               relief='flat', padx=10, pady=4, cursor='hand2', borderwidth=0)
        self.ms_btn.pack(side='left')
        
        self.s_btn = tk.Button(unit_frame, text="s", command=lambda: self.set_exposure_unit('s'),
                              font=('Segoe UI', 8), bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                              activebackground=COLORS['accent_primary_hover'], activeforeground=COLORS['text_primary'],
                              relief='flat', padx=10, pady=4, cursor='hand2', borderwidth=0)
        self.s_btn.pack(side='left')
        
        # Exposure range hint
        self.app.exposure_range_label = tk.Label(left_col, text="(0.000032 – 3600 s)",
                                                font=('Segoe UI', 7), 
                                                bg=COLORS['bg_primary'], fg=COLORS['text_muted'])
        self.app.exposure_range_label.pack(anchor='w', padx=(96, 0), pady=(0, 12))
        
        # Gain
        gain_row = tk.Frame(left_col, bg=COLORS['bg_primary'])
        gain_row.pack(fill='x', pady=(0, 12))
        
        tk.Label(gain_row, text="Gain:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=10, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.gain_var = tk.IntVar(value=100)
        gain_entry = ttk.Entry(gain_row, textvariable=self.app.gain_var,
                              font=('Segoe UI', 9), style='Dark.TEntry',
                              width=14)
        gain_entry.pack(side='left', padx=(0, 8))
        
        tk.Label(gain_row, text="(0 – 600)", font=('Segoe UI', 7),
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # Interval
        interval_row = tk.Frame(left_col, bg=COLORS['bg_primary'])
        interval_row.pack(fill='x', pady=(0, 12))
        
        tk.Label(interval_row, text="Interval:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=10, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.interval_var = tk.DoubleVar(value=5.0)
        interval_entry = ttk.Entry(interval_row, textvariable=self.app.interval_var,
                                  font=('Segoe UI', 9), style='Dark.TEntry',
                                  width=14)
        interval_entry.pack(side='left', padx=(0, 8))
        
        tk.Label(interval_row, text="seconds", font=('Segoe UI', 7),
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # Scheduled Capture section
        schedule_section = tk.Frame(left_col, bg=COLORS['bg_primary'])
        schedule_section.pack(fill='x', pady=(0, 12))
        
        # Checkbox
        self.app.scheduled_capture_var = tk.BooleanVar(value=False)
        schedule_check = ttk.Checkbutton(schedule_section, text="⏰ Scheduled Capture",
                                        variable=self.app.scheduled_capture_var,
                                        command=self.app.on_scheduled_capture_toggle,
                                        bootstyle="info-round-toggle")
        schedule_check.pack(anchor='w', pady=(0, 8))
        
        # Time range row
        time_frame = tk.Frame(schedule_section, bg=COLORS['bg_primary'])
        time_frame.pack(fill='x')
        
        tk.Label(time_frame, text="Active:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=10, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.schedule_start_var = tk.StringVar(value="17:00")
        # Add trace to auto-save when time changes
        self.app.schedule_start_var.trace_add('write', self.app.on_schedule_time_change)
        start_entry = ttk.Entry(time_frame, textvariable=self.app.schedule_start_var,
                               font=('Segoe UI', 9), style='Dark.TEntry',
                               width=6)
        start_entry.pack(side='left', padx=(0, 6))
        
        tk.Label(time_frame, text="to", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left', padx=(0, 6))
        
        self.app.schedule_end_var = tk.StringVar(value="09:00")
        # Add trace to auto-save when time changes
        self.app.schedule_end_var.trace_add('write', self.app.on_schedule_time_change)
        end_entry = ttk.Entry(time_frame, textvariable=self.app.schedule_end_var,
                             font=('Segoe UI', 9), style='Dark.TEntry',
                             width=6)
        end_entry.pack(side='left', padx=(0, 8))
        
        tk.Label(time_frame, text="(HH:MM, 24hr)", font=('Segoe UI', 7),
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # Store entry widgets for enable/disable
        self.app.schedule_start_entry = start_entry
        self.app.schedule_end_entry = end_entry
        
        # Offset
        offset_row = tk.Frame(left_col, bg=COLORS['bg_primary'])
        offset_row.pack(fill='x', pady=(0, 12))
        
        tk.Label(offset_row, text="Offset:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=10, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.offset_var = tk.IntVar(value=20)
        offset_entry = ttk.Entry(offset_row, textvariable=self.app.offset_var,
                                font=('Segoe UI', 9), style='Dark.TEntry',
                                width=14)
        offset_entry.pack(side='left')
        
        # Bayer Pattern
        bayer_row = tk.Frame(left_col, bg=COLORS['bg_primary'])
        bayer_row.pack(fill='x', pady=(0, 12))
        
        tk.Label(bayer_row, text="Bayer Pattern:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=10, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.bayer_pattern_var = tk.StringVar(value='BGGR')
        bayer_combo = ttk.Combobox(bayer_row, textvariable=self.app.bayer_pattern_var,
                                   values=['RGGB', 'BGGR', 'GRBG', 'GBRG'],
                                   state='readonly', width=12, font=('Segoe UI', 9),
                                   style='Dark.TCombobox')
        bayer_combo.pack(side='left')
        
        # Flip
        flip_row = tk.Frame(left_col, bg=COLORS['bg_primary'])
        flip_row.pack(fill='x', pady=(0, 0))
        
        tk.Label(flip_row, text="Flip:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=10, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.flip_var = tk.StringVar(value="None")
        flip_combo = ttk.Combobox(flip_row, textvariable=self.app.flip_var,
                                 values=['None', 'Horizontal', 'Vertical', 'Both'],
                                 state='readonly', width=12, font=('Segoe UI', 9),
                                 style='Dark.TCombobox')
        flip_combo.pack(side='left')
        
        # Right column - Auto Exposure & White Balance
        right_col = tk.Frame(grid_container, bg=COLORS['bg_primary'])
        right_col.grid(row=0, column=1, sticky='nsew', padx=(SPACING['element_gap'], 0))
        
        # Auto Exposure section
        auto_frame = tk.Frame(right_col, bg=COLORS['bg_primary'])
        auto_frame.pack(fill='x', pady=(0, 16))
        
        self.app.auto_exposure_var = tk.BooleanVar(value=False)
        auto_check = ttk.Checkbutton(auto_frame, text="🔆 Auto Exposure",
                                    variable=self.app.auto_exposure_var,
                                    command=self.app.on_auto_exposure_toggle,
                                    bootstyle="success-round-toggle")
        auto_check.pack(anchor='w', pady=(0, 12))
        
        # Max exposure row
        max_exp_row = tk.Frame(auto_frame, bg=COLORS['bg_primary'])
        max_exp_row.pack(fill='x')
        
        tk.Label(max_exp_row, text="Max Exposure:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=13, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.max_exposure_var = tk.DoubleVar(value=30.0)
        self.app.max_exposure_entry = ttk.Entry(max_exp_row, textvariable=self.app.max_exposure_var,
                                               font=('Segoe UI', 9), style='Dark.TEntry',
                                               width=12)
        self.app.max_exposure_entry.pack(side='left', padx=(0, 6))
        
        tk.Label(max_exp_row, text="s", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # Target Brightness row
        target_br_row = tk.Frame(auto_frame, bg=COLORS['bg_primary'])
        target_br_row.pack(fill='x', pady=(8, 0))
        
        tk.Label(target_br_row, text="Target Bright:", font=('Segoe UI', 9),
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                width=13, anchor='w').pack(side='left', padx=(0, 12))
        
        self.app.target_brightness_var = tk.IntVar(value=100)
        self.app.target_brightness_scale = ttk.Scale(target_br_row, from_=20, to=200,
                                                     variable=self.app.target_brightness_var,
                                                     orient='horizontal', length=120, bootstyle="info")
        self.app.target_brightness_scale.pack(side='left', padx=(0, 6))
        
        self.app.target_brightness_label = tk.Label(target_br_row, text="100", width=3, anchor='e',
                                                     font=('Segoe UI', 9),
                                                     bg=COLORS['bg_primary'], fg=COLORS['text_primary'])
        self.app.target_brightness_label.pack(side='left', padx=(0, 6))
        
        # Update label when scale changes
        def update_brightness_label(*args):
            val = int(self.app.target_brightness_var.get())
            self.app.target_brightness_label.config(text=str(val))
        self.app.target_brightness_var.trace_add('write', update_brightness_label)
        
        # Hint label
        tk.Label(target_br_row, text="(20=dark, 200=bright)", font=('Segoe UI', 8),
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # White Balance frame
        wb_frame = tk.LabelFrame(right_col, text="  White Balance  ",
                                font=('Segoe UI', 9, 'bold'), 
                                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                                borderwidth=1, relief='solid', bd=1,
                                highlightbackground=COLORS['border'],
                                highlightcolor=COLORS['border'],
                                padx=12, pady=10)
        wb_frame.pack(fill='x', pady=(0, 0))
        wb_frame.config(borderwidth=1, relief='solid')
        
        # White Balance Mode selector
        mode_frame = tk.Frame(wb_frame, bg=COLORS['bg_primary'])
        mode_frame.pack(fill='x', pady=(0, 10))
        
        tk.Label(mode_frame, text="Mode:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], 
                width=5, anchor='w').pack(side='left', padx=(0, 8))
        
        self.app.wb_mode_var = tk.StringVar(value='asi_auto')
        wb_mode_combo = ttk.Combobox(mode_frame, textvariable=self.app.wb_mode_var,
                                     values=['asi_auto', 'manual', 'gray_world'],
                                     state='readonly', width=15, font=FONTS['body'])
        wb_mode_combo.pack(side='left', padx=(0, 8))
        wb_mode_combo.bind('<<ComboboxSelected>>', lambda e: self.app.on_wb_mode_change())
        
        # Hint label
        self.app.wb_mode_hint_label = tk.Label(mode_frame, text="(SDK Auto WB)",
                                               font=FONTS['small'], bg=COLORS['bg_primary'],
                                               fg=COLORS['text_muted'])
        self.app.wb_mode_hint_label.pack(side='left', padx=(8, 0))
        
        # Manual controls frame (SDK R/B values)
        self.app.wb_manual_frame = tk.Frame(wb_frame, bg=COLORS['bg_primary'])
        self.app.wb_manual_frame.pack(fill='x', pady=(0, 0))
        
        # Red slider (SDK WB)
        red_frame = tk.Frame(self.app.wb_manual_frame, bg=COLORS['bg_primary'])
        red_frame.pack(fill='x', pady=(0, 10))
        
        tk.Label(red_frame, text="Red:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], 
                width=5, anchor='w').pack(side='left', padx=(0, 8))
        
        self.app.wb_r_var = tk.IntVar(value=75)
        self.app.wb_r_scale = ttk.Scale(red_frame, from_=1, to=99, variable=self.app.wb_r_var,
                 orient='horizontal', length=200, bootstyle="danger")
        self.app.wb_r_scale.pack(side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        tk.Label(red_frame, textvariable=self.app.wb_r_var, font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary'], width=3).pack(side='left')
        
        # Blue slider (SDK WB)
        blue_frame = tk.Frame(self.app.wb_manual_frame, bg=COLORS['bg_primary'])
        blue_frame.pack(fill='x')
        
        tk.Label(blue_frame, text="Blue:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], 
                width=5, anchor='w').pack(side='left', padx=(0, 8))
        
        self.app.wb_b_var = tk.IntVar(value=99)
        self.app.wb_b_scale = ttk.Scale(blue_frame, from_=1, to=99, variable=self.app.wb_b_var,
                 orient='horizontal', length=200, bootstyle="info")
        self.app.wb_b_scale.pack(side='left', fill='x', expand=True, padx=(0, SPACING['row_gap']))
        
        tk.Label(blue_frame, textvariable=self.app.wb_b_var, font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary'], width=3).pack(side='left')
        
        # Gray World controls frame (software percentiles)
        self.app.wb_gray_world_frame = tk.Frame(wb_frame, bg=COLORS['bg_primary'])
        # Don't pack initially - will be shown/hidden based on mode
        
        # Low percentile
        low_pct_frame = tk.Frame(self.app.wb_gray_world_frame, bg=COLORS['bg_primary'])
        low_pct_frame.pack(fill='x', pady=(0, 10))
        
        tk.Label(low_pct_frame, text="Low %:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], 
                width=8, anchor='w').pack(side='left', padx=(0, 8))
        
        self.app.wb_gw_low_var = tk.IntVar(value=5)
        low_spinbox = ttk.Spinbox(low_pct_frame, from_=0, to=20, increment=1,
                                  textvariable=self.app.wb_gw_low_var, width=8,
                                  font=FONTS['body'], bootstyle="info")
        low_spinbox.pack(side='left', padx=(0, 8))
        
        tk.Label(low_pct_frame, text="(mask dark pixels)", font=FONTS['small'],
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # High percentile
        high_pct_frame = tk.Frame(self.app.wb_gray_world_frame, bg=COLORS['bg_primary'])
        high_pct_frame.pack(fill='x', pady=(0, 10))
        
        tk.Label(high_pct_frame, text="High %:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], 
                width=8, anchor='w').pack(side='left', padx=(0, 8))
        
        self.app.wb_gw_high_var = tk.IntVar(value=95)
        high_spinbox = ttk.Spinbox(high_pct_frame, from_=80, to=100, increment=1,
                                   textvariable=self.app.wb_gw_high_var, width=8,
                                   font=FONTS['body'], bootstyle="info")
        high_spinbox.pack(side='left', padx=(0, 8))
        
        tk.Label(high_pct_frame, text="(mask bright pixels)", font=FONTS['small'],
                bg=COLORS['bg_primary'], fg=COLORS['text_muted']).pack(side='left')
        
        # Info label
        info_label = tk.Label(self.app.wb_gray_world_frame, 
                             text="Gray World uses mid-tones to balance colors.\nBest for scenes with mixed colors.",
                             font=FONTS['small'], bg=COLORS['bg_primary'],
                             fg=COLORS['text_muted'], justify='left')
        info_label.pack(anchor='w', pady=(0, 0))
    
    # ===== BUTTON FACTORY METHODS =====
    # (Removed - using theme module functions directly)
    
    # ===== EXPOSURE UNIT HANDLING =====
    
    def set_exposure_unit(self, unit):
        """Set exposure unit and update UI with proper conversion"""
        old_unit = self.app.exposure_unit_var.get()
        value = self.app.exposure_var.get()
        
        # Convert value if switching units
        if old_unit != unit:
            if unit == 'ms' and old_unit == 's':
                self.app.exposure_var.set(value * 1000.0)
            elif unit == 's' and old_unit == 'ms':
                self.app.exposure_var.set(value / 1000.0)
        
        # Update variable
        self.app.exposure_unit_var.set(unit)
        
        # Update button styles
        if unit == 'ms':
            self.ms_btn.config(
                bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                activebackground=COLORS['accent_primary_hover'], 
                activeforeground=COLORS['text_primary']
            )
            self.s_btn.config(
                bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                activebackground='#3A3A3A', activeforeground='#C0C0C0'
            )
            self.app.exposure_range_label.config(text="(0.032 – 3600000 ms)")
        else:
            self.s_btn.config(
                bg=COLORS['accent_primary'], fg=COLORS['text_primary'],
                activebackground=COLORS['accent_primary_hover'], 
                activeforeground=COLORS['text_primary']
            )
            self.ms_btn.config(
                bg=COLORS['bg_input'], fg=COLORS['text_secondary'],
                activebackground='#3A3A3A', activeforeground='#C0C0C0'
            )
            self.app.exposure_range_label.config(text="(0.000032 – 3600 s)")
    
    # ===== CAMERA DETECTION UI =====
    
    def show_detection_spinner(self):
        """Show camera detection spinner animation"""
        if hasattr(self, 'spinner_label') and hasattr(self, 'app'):
            self.spinner_label.pack(side='left')
            self.app.detect_cameras_button.config(state='disabled', cursor='')
            self.detecting = True
            self._animate_spinner()
    
    def hide_detection_spinner(self):
        """Hide camera detection spinner"""
        if hasattr(self, 'spinner_label') and hasattr(self, 'app'):
            self.spinner_label.pack_forget()
            self.app.detect_cameras_button.config(state='normal', cursor='hand2')
            self.detecting = False
    
    def _animate_spinner(self):
        """Animate spinner with alternating icons"""
        if self.detecting:
            current = self.spinner_label.cget('text')
            chars = ['⌛', '⏳']
            next_char = chars[(chars.index(current) + 1) % len(chars)]
            self.spinner_label.config(text=next_char)
            self.spinner_label.after(500, self._animate_spinner)
    
    def show_detection_error(self, message):
        """Show inline detection error message"""
        if hasattr(self.app, 'detection_error_label'):
            self.app.detection_error_label.config(text=f"⚠ {message}")
    
    def clear_detection_error(self):
        """Clear detection error message"""
        if hasattr(self.app, 'detection_error_label'):
            self.app.detection_error_label.config(text="")
