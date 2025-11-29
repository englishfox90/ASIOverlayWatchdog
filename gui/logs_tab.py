"""
Logs tab component - log display with controls and log directory info
"""
import tkinter as tk
import ttkbootstrap as ttk
import os
import subprocess
from . import theme
from .theme import COLORS, FONTS, SPACING
from services.logger import app_logger


class LogsTab:
    """Logs tab for viewing application logs"""
    
    def __init__(self, notebook, app):
        self.app = app
        self.tab = ttk.Frame(notebook)
        notebook.add(self.tab, text="  Logs  ")
        
        self.create_ui()
    
    def create_ui(self):
        """Create the logs tab UI with theme"""
        # Main container
        logs_container = tk.Frame(self.tab, bg=COLORS['bg_primary'])
        logs_container.pack(fill='both', expand=True)
        logs_container.grid_columnconfigure(0, weight=1)
        logs_container.grid_rowconfigure(1, weight=1)
        
        # ===== Controls row (top) =====
        controls = tk.Frame(logs_container, bg=COLORS['bg_primary'])
        controls.grid(row=0, column=0, sticky="ew",
                     padx=SPACING['card_margin_x'],
                     pady=(SPACING['card_margin_y'], SPACING['row_gap']))
        controls.grid_columnconfigure(3, weight=1)  # Spacer column
        
        # Clear Logs button (destructive style)
        clear_button = theme.create_destructive_button(
            controls, "🗑 Clear Logs", self.app.clear_logs
        )
        clear_button.grid(row=0, column=0, padx=(0, SPACING['element_gap']))
        
        # Save Logs button (secondary style)
        save_button = theme.create_secondary_button(
            controls, "💾 Save Logs...", self.app.save_logs
        )
        save_button.grid(row=0, column=1, padx=(0, SPACING['element_gap']))
        
        # Open Log Folder button (secondary style)
        open_logs_button = theme.create_secondary_button(
            controls, "📁 Open Log Folder", self.open_log_folder
        )
        open_logs_button.grid(row=0, column=2, padx=(0, SPACING['element_gap']))
        
        # Auto-scroll checkbox (right-aligned)
        auto_check = tk.Checkbutton(
            controls,
            text="Auto-scroll",
            variable=self.app.auto_scroll_var,
            font=FONTS['body'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_primary'],
            activebackground=COLORS['bg_primary'],
            activeforeground=COLORS['text_secondary'],
            selectcolor=COLORS['bg_card'],
            highlightthickness=0
        )
        auto_check.grid(row=0, column=4, padx=(SPACING['element_gap'], 0))
        
        # ===== Log output area as themed card =====
        logs_content = theme.create_card(logs_container, title=None)
        logs_card = logs_content.master
        
        logs_card.grid(
            row=1, column=0, sticky="nsew",
            padx=SPACING['card_margin_x'],
            pady=(0, SPACING['card_margin_y'])
        )
        logs_content.grid_columnconfigure(0, weight=1)
        logs_content.grid_rowconfigure(0, weight=1)
        
        # Log text widget
        self.app.log_text = tk.Text(
            logs_content,
            bg=COLORS['bg_primary'],
            fg=COLORS['text_primary'],
            insertbackground=COLORS['text_primary'],
            font=FONTS['body'],
            borderwidth=0,
            highlightthickness=0,
            wrap='word'
        )
        self.app.log_text.grid(row=0, column=0, sticky="nsew")
        self.app.log_text.config(state='disabled')
        
        # Vertical scrollbar
        scrollbar = tk.Scrollbar(
            logs_content,
            command=self.app.log_text.yview,
            bg=COLORS['bg_card'],
            troughcolor=COLORS['bg_card'],
            highlightthickness=0,
            bd=0
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.app.log_text.config(yscrollcommand=scrollbar.set)
        
        # Configure tags for different log levels
        self.app.log_text.tag_config('ERROR', foreground='#f44747')
        self.app.log_text.tag_config('WARNING', foreground='#ff8c00')
        self.app.log_text.tag_config('INFO', foreground='#4ec9b0')
        self.app.log_text.tag_config('DEBUG', foreground='#858585')
        
        # ===== Footer with log directory info =====
        footer = tk.Frame(logs_container, bg=COLORS['bg_primary'])
        footer.grid(row=2, column=0, sticky="ew",
                   padx=SPACING['card_margin_x'],
                   pady=(SPACING['row_gap'], SPACING['card_margin_y']))
        
        footer_label = tk.Label(
            footer,
            text=f"📂 Log files are saved to: {app_logger.get_log_dir()} (kept for 7 days)",
            font=FONTS['small'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_primary'],
            anchor='w'
        )
        footer_label.pack(fill='x')
    
    def open_log_folder(self):
        """Open the log directory in Windows Explorer"""
        log_dir = app_logger.get_log_dir()
        if os.path.exists(log_dir):
            try:
                subprocess.run(['explorer', log_dir], check=False)
            except Exception as e:
                app_logger.error(f"Failed to open log folder: {e}")
        else:
            app_logger.warning(f"Log directory does not exist: {log_dir}")
