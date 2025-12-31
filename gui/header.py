"""
Header components for status and live monitoring
"""
import tkinter as tk
import ttkbootstrap as ttk
from tkinter import scrolledtext
from datetime import datetime
import os
from .theme import COLORS, FONTS, SPACING


class StatusHeader:
    """Modern unified status header with two-column layout"""
    
    def __init__(self, parent):
        # Main container with dark background
        self.container = tk.Frame(parent, bg=COLORS['bg_primary'], 
                                 padx=SPACING['card_padding'], pady=SPACING['row_gap'])
        self.container.pack(fill='x', padx=SPACING['button_gap'], pady=(SPACING['button_gap'], 0))
        
        # Two-column layout
        self.frame = tk.Frame(self.container, bg=COLORS['bg_primary'])
        self.frame.pack(fill='x')
        
        # Left column - Mode and camera info
        left_frame = tk.Frame(self.frame, bg=COLORS['bg_primary'])
        left_frame.pack(side='left', fill='both', expand=True)
        self.left_frame = left_frame  # Store reference for progress bar placement
        
        # Status indicator + Mode (first row)
        mode_row = tk.Frame(left_frame, bg=COLORS['bg_primary'])
        mode_row.pack(anchor='w', pady=(0, SPACING['element_gap']))
        
        # Status dot canvas - vertically centered
        self.status_canvas = tk.Canvas(mode_row, width=10, height=10, bg=COLORS['bg_primary'], 
                                       highlightthickness=0)
        self.status_canvas.pack(side='left', padx=(0, 6))
        self.status_dot = self.status_canvas.create_oval(1, 1, 9, 9, fill=COLORS['status_idle'], outline='')
        
        # Mode label and value
        tk.Label(mode_row, text="Mode:", font=FONTS['heading'], 
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary']).pack(side='left', padx=(0, 8))
        
        self.mode_status_var = tk.StringVar(value="Not Running")
        tk.Label(mode_row, textvariable=self.mode_status_var, font=FONTS['title'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary']).pack(side='left')
        
        # Camera/capture info (second row) - muted grey
        self.capture_info_var = tk.StringVar(value="No active session")
        self.capture_info_label = tk.Label(left_frame, textvariable=self.capture_info_var, font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'])
        self.capture_info_label.pack(anchor='w')
        
        # Exposure progress bar (third row) - only visible during exposure
        self.progress_frame = tk.Frame(left_frame, bg=COLORS['bg_primary'], height=6)
        # Don't pack yet - will be shown when exposure starts
        
        # Progress bar canvas with fixed width
        self.progress_canvas = tk.Canvas(self.progress_frame, height=6, bg=COLORS['bg_input'],
                                        highlightthickness=0, bd=0, width=400)
        self.progress_canvas.pack(fill='x', expand=True)
        
        # Progress bar fill (will be resized based on remaining time)
        self.progress_bar = self.progress_canvas.create_rectangle(
            0, 0, 400, 6, fill=COLORS['accent_primary'], outline=''
        )
        
        # Right column - Session stats (right-aligned with fixed-width grid)
        right_frame = tk.Frame(self.frame, bg=COLORS['bg_primary'])
        right_frame.pack(side='right', padx=(0, 2))
        
        # Create grid for aligned columns
        stats_grid = tk.Frame(right_frame, bg=COLORS['bg_primary'])
        stats_grid.pack()
        
        # Session row
        tk.Label(stats_grid, text="Session:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], anchor='e', width=8).grid(row=0, column=0, sticky='e', pady=SPACING['element_gap']//4)
        self.session_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        tk.Label(stats_grid, textvariable=self.session_var, font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary'], anchor='w').grid(row=0, column=1, sticky='w', padx=(SPACING['element_gap']//1.3, 0))
        
        # Images row
        tk.Label(stats_grid, text="Images:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], anchor='e', width=8).grid(row=1, column=0, sticky='e', pady=SPACING['element_gap']//4)
        self.image_count_var = tk.StringVar(value="0")
        tk.Label(stats_grid, textvariable=self.image_count_var, font=FONTS['body_bold'],
                bg=COLORS['bg_primary'], fg=COLORS['status_capturing'], anchor='w').grid(row=1, column=1, sticky='w', padx=(SPACING['element_gap']//1.3, 0))
        
        # Output row with tooltip support
        tk.Label(stats_grid, text="Output:", font=FONTS['body'],
                bg=COLORS['bg_primary'], fg=COLORS['text_secondary'], anchor='e', width=8).grid(row=2, column=0, sticky='e', pady=SPACING['element_gap']//4)
        self.output_info_var = tk.StringVar(value="Not configured")
        self.output_display_var = tk.StringVar(value="Not configured")
        self.output_label = tk.Label(stats_grid, textvariable=self.output_display_var, font=FONTS['body'],
                                     bg=COLORS['bg_primary'], fg=COLORS['text_primary'], anchor='w', cursor='hand2')
        self.output_label.grid(row=2, column=1, sticky='w', padx=(SPACING['element_gap']//1.3, 0))
        
        # Tooltip for full path
        self._create_tooltip(self.output_label)
        
        # Bottom separator line
        separator = tk.Frame(self.container, bg=COLORS['separator'], height=1)
        separator.pack(fill='x', pady=(10, 0))
    
    def _create_tooltip(self, widget):
        """Create tooltip for output path"""
        self.tooltip = None
        
        def on_enter(event):
            if self.output_info_var.get() and self.output_info_var.get() != "Not configured":
                x, y, _, _ = widget.bbox("insert")
                x += widget.winfo_rootx() + 25
                y += widget.winfo_rooty() + 25
                
                self.tooltip = tk.Toplevel(widget)
                self.tooltip.wm_overrideredirect(True)
                self.tooltip.wm_geometry(f"+{x}+{y}")
                
                label = tk.Label(self.tooltip, text=self.output_info_var.get(),
                               font=FONTS['body'], bg=COLORS['bg_card'], fg=COLORS['text_primary'],
                               relief='solid', borderwidth=1, 
                               padx=SPACING['element_gap'], pady=SPACING['element_gap']//2)
                label.pack()
        
        def on_leave(event):
            if self.tooltip:
                self.tooltip.destroy()
                self.tooltip = None
        
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
    
    def _truncate_path(self, path, max_length=40):
        """Truncate path to show first 25% and last 40% with ellipsis
        
        Args:
            path: Full path string
            max_length: Maximum display length
            
        Returns:
            Truncated path string
        """
        if len(path) <= max_length:
            return path
        
        # Calculate split points
        first_part_len = int(max_length * 0.25)
        last_part_len = int(max_length * 0.40)
        
        # Keep drive letter and first folder, then end portion
        first_part = path[:first_part_len]
        last_part = path[-last_part_len:]
        
        return f"{first_part}...{last_part}"
    
    def update_output_path(self, path):
        """Update output path with truncation
        
        Args:
            path: Full output path
        """
        self.output_info_var.set(path)
        self.output_display_var.set(self._truncate_path(path))
    
    def set_status_color(self, color):
        """Update status indicator dot color
        
        Args:
            color: 'idle' (grey), 'capturing' (green), 'connecting' (yellow), 'error' (red)
        """
        color_map = {
            'idle': COLORS['status_idle'],
            'capturing': COLORS['status_capturing'],
            'connecting': COLORS['status_connecting'],
            'error': COLORS['status_error']
        }
        self.status_canvas.itemconfig(self.status_dot, fill=color_map.get(color, COLORS['status_idle']))
    
    def update_exposure_progress(self, exposure_total, exposure_remaining):
        """Update exposure progress bar
        
        Args:
            exposure_total: Total exposure time in seconds
            exposure_remaining: Remaining exposure time in seconds
        """
        if exposure_remaining > 0 and exposure_total > 0:
            # Show progress bar immediately (pack after the capture info label)
            if not self.progress_frame.winfo_ismapped():
                self.progress_frame.pack(anchor='w', fill='x', pady=(4, 0), in_=self.left_frame, after=self.capture_info_label)
            
            # Calculate progress (inverted - bar shrinks as time passes)
            progress = exposure_remaining / exposure_total
            # Use fixed canvas width of 400 for consistent, smooth animation
            bar_width = int(400 * progress)
            self.progress_canvas.coords(self.progress_bar, 0, 0, bar_width, 6)
        else:
            # Hide progress bar when not exposing
            if self.progress_frame.winfo_ismapped():
                self.progress_frame.pack_forget()


class LiveMonitoringHeader:
    """Live monitoring section with preview, histogram, and logs"""
    
    def __init__(self, parent):
        # Custom LabelFrame with Iris accent color for visibility
        self.frame = tk.LabelFrame(
            parent, 
            text="  Live Monitoring  ",
            font=FONTS['body_bold'],
            fg=COLORS['accent_11'],  # Light iris purple text
            bg=COLORS['bg_primary'],
            bd=1,
            relief='groove',
            highlightbackground=COLORS['accent_6'],  # Iris border
            highlightcolor=COLORS['accent_8'],
            highlightthickness=1,
            padx=10,
            pady=10
        )
        self.frame.pack(fill='both', padx=SPACING['button_gap'], pady=SPACING['element_gap'])
        
        # Layout: Preview on left, Histogram + Logs stacked on right
        left_frame = tk.Frame(self.frame, bg=COLORS['bg_primary'])
        left_frame.pack(side='left', padx=SPACING['button_gap'])
        
        tk.Label(left_frame, text="Last Capture", font=FONTS['body_bold'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary']).pack()
        self.mini_preview_label = tk.Label(left_frame, text="No image yet", 
                                           relief='sunken', width=25,
                                           bg=COLORS['bg_input'], fg=COLORS['text_secondary'])
        self.mini_preview_label.pack()
        self.mini_preview_image = None
        
        # Right side: Histogram and logs stacked
        right_frame = tk.Frame(self.frame, bg=COLORS['bg_primary'])
        right_frame.pack(side='left', fill='both', expand=True, padx=SPACING['button_gap'])
        
        # Histogram on top
        tk.Label(right_frame, text="Histogram", font=FONTS['body_bold'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary']).pack()
        self.histogram_canvas = tk.Canvas(right_frame, width=600, height=100, 
                                          bg=COLORS['bg_primary'], 
                                          highlightthickness=1,
                                          highlightbackground=COLORS['border'])
        self.histogram_canvas.pack(fill='x')
        
        # Logs below
        tk.Label(right_frame, text="Recent Activity", font=FONTS['body_bold'],
                bg=COLORS['bg_primary'], fg=COLORS['text_primary']).pack(pady=(SPACING['element_gap'], 0))
        self.mini_log_text = scrolledtext.ScrolledText(right_frame, height=2, wrap=tk.WORD, font=FONTS['tiny'])
        self.mini_log_text.pack(fill='both', expand=True)
        self.mini_log_text.config(state='disabled')
