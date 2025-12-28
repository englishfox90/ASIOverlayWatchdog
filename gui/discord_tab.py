"""
Discord alerts tab - webhook configuration and alert settings
"""
import tkinter as tk
import ttkbootstrap as ttk
from .theme import COLORS, FONTS, SPACING, create_scrollable_frame
from . import theme


class DiscordTab:
    """Discord alerts configuration tab"""
    
    def __init__(self, notebook, app):
        self.app = app
        
        # Create tab (match pattern from other tabs)
        self.tab = ttk.Frame(notebook)
        notebook.add(self.tab, text="  Discord  ")
        
        # Create UI
        self.create_ui()
    
    def create_ui(self):
        """Create Discord tab UI"""
        # Create scrollable frame for content
        scroll_container, scrollable_content = create_scrollable_frame(self.tab)
        scroll_container.pack(fill='both', expand=True)
        
        # Content frame with padding
        container = tk.Frame(scrollable_content, bg=COLORS['bg_primary'])
        container.pack(fill='both', expand=True,
                      padx=SPACING['card_margin_x'],
                      pady=SPACING['card_margin_y'])
        
        # Card 1: Connection Settings
        connection_card = theme.create_card(container, "Connection Settings")
        connection_card.master.pack(fill='both', expand=True, pady=(0, SPACING['section_gap']))
        
        # Webhook URL
        url_frame = tk.Frame(connection_card, bg=COLORS['bg_card'])
        url_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(url_frame, text="Webhook URL:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(anchor='w', 
                                          pady=(0, SPACING['element_gap']))
        
        # Use existing var or create new one
        if not hasattr(self.app, 'discord_webhook_var'):
            self.app.discord_webhook_var = tk.StringVar()
        
        webhook_entry = ttk.Entry(url_frame,
                                 textvariable=self.app.discord_webhook_var,
                                 style='Dark.TEntry')
        webhook_entry.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        tk.Label(url_frame, 
                text="Get your webhook URL from Discord Server Settings → Integrations → Webhooks",
                font=FONTS['tiny'],
                fg=COLORS['text_muted'],
                bg=COLORS['bg_card']).pack(anchor='w')
        
        # Buttons
        btn_frame = tk.Frame(connection_card, bg=COLORS['bg_card'])
        btn_frame.pack(fill='x', pady=(SPACING['row_gap'], 0))
        
        save_btn = theme.create_primary_button(btn_frame, "Save Discord Settings",
                                              self.app.save_discord_settings)
        save_btn.pack(side='left', padx=(0, SPACING['element_gap']))
        
        test_btn = theme.create_secondary_button(btn_frame, "Test Webhook",
                                                self.app.test_discord_webhook)
        test_btn.pack(side='left')
        
        # Test status label
        if not hasattr(self.app, 'discord_test_status_var'):
            self.app.discord_test_status_var = tk.StringVar(value="")
        
        test_status = tk.Label(btn_frame,
                              textvariable=self.app.discord_test_status_var,
                              font=FONTS['small'],
                              fg=COLORS['text_muted'],
                              bg=COLORS['bg_card'])
        test_status.pack(side='left', padx=(SPACING['row_gap'], 0))
        
        # Card 2: Alert Options
        alerts_card = theme.create_card(container, "Alert Options")
        alerts_card.master.pack(fill='x', pady=(0, SPACING['section_gap']))
        
        # Master enable toggle
        if not hasattr(self.app, 'discord_enabled_var'):
            self.app.discord_enabled_var = tk.BooleanVar(value=False)
        
        enable_check = tk.Checkbutton(
            alerts_card,
            text="Enable Discord Alerts",
            variable=self.app.discord_enabled_var,
            command=self.app.on_discord_enabled_change,
            font=FONTS['body_bold'],
            fg=COLORS['text_primary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        enable_check.pack(anchor='w', pady=(0, SPACING['row_gap']))
        
        # Create frame for all alert options (will be disabled when discord is off)
        self.app.discord_options_frame = tk.Frame(alerts_card, bg=COLORS['bg_card'])
        self.app.discord_options_frame.pack(fill='x')
        
        # Error Alerts
        error_section = tk.Frame(self.app.discord_options_frame, bg=COLORS['bg_card'])
        error_section.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(error_section, text="Error Alerts",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(anchor='w',
                                          pady=(0, SPACING['element_gap']))
        
        if not hasattr(self.app, 'discord_post_errors_var'):
            self.app.discord_post_errors_var = tk.BooleanVar(value=False)
        
        error_check = tk.Checkbutton(
            error_section,
            text="Post Errors to Discord",
            variable=self.app.discord_post_errors_var,
            font=FONTS['body'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        error_check.pack(anchor='w', padx=(20, 0))
        
        tk.Label(error_section,
                text="Send a Discord message whenever an error is logged.",
                font=FONTS['small'],
                fg=COLORS['text_muted'],
                bg=COLORS['bg_card']).pack(anchor='w', padx=(40, 0))
        
        # Startup/Shutdown Alerts
        lifecycle_section = tk.Frame(self.app.discord_options_frame, bg=COLORS['bg_card'])
        lifecycle_section.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(lifecycle_section, text="Startup / Shutdown Alerts",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(anchor='w',
                                          pady=(0, SPACING['element_gap']))
        
        if not hasattr(self.app, 'discord_post_lifecycle_var'):
            self.app.discord_post_lifecycle_var = tk.BooleanVar(value=False)
        
        lifecycle_check = tk.Checkbutton(
            lifecycle_section,
            text="Post Startup and Shutdown",
            variable=self.app.discord_post_lifecycle_var,
            font=FONTS['body'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        lifecycle_check.pack(anchor='w', padx=(20, 0))
        
        tk.Label(lifecycle_section,
                text="Notify when application starts or stops.",
                font=FONTS['small'],
                fg=COLORS['text_muted'],
                bg=COLORS['bg_card']).pack(anchor='w', padx=(40, 0))
        
        # Periodic Image Posts
        periodic_section = tk.Frame(self.app.discord_options_frame, bg=COLORS['bg_card'])
        periodic_section.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(periodic_section, text="Periodic Image Posts",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(anchor='w',
                                          pady=(0, SPACING['element_gap']))
        
        if not hasattr(self.app, 'discord_periodic_enabled_var'):
            self.app.discord_periodic_enabled_var = tk.BooleanVar(value=False)
        
        periodic_check = tk.Checkbutton(
            periodic_section,
            text="Enable Periodic Image Posts",
            variable=self.app.discord_periodic_enabled_var,
            command=self.app.on_discord_periodic_change,
            font=FONTS['body'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        periodic_check.pack(anchor='w', padx=(20, 0))
        
        # Periodic options frame
        self.app.discord_periodic_options_frame = tk.Frame(periodic_section, 
                                                          bg=COLORS['bg_card'])
        self.app.discord_periodic_options_frame.pack(fill='x', padx=(40, 0),
                                                    pady=(SPACING['element_gap'], 0))
        
        # Interval
        interval_frame = tk.Frame(self.app.discord_periodic_options_frame,
                                bg=COLORS['bg_card'])
        interval_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        tk.Label(interval_frame, text="Interval (minutes):",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left',
                                          padx=(0, SPACING['element_gap']))
        
        if not hasattr(self.app, 'discord_interval_var'):
            self.app.discord_interval_var = tk.IntVar(value=60)
        
        interval_spin = ttk.Spinbox(interval_frame,
                                   from_=1, to=1440,
                                   textvariable=self.app.discord_interval_var,
                                   width=10,
                                   style='Dark.TSpinbox')
        interval_spin.pack(side='left')
        
        # Include image checkbox
        if not hasattr(self.app, 'discord_include_image_var'):
            self.app.discord_include_image_var = tk.BooleanVar(value=True)
        
        image_check = tk.Checkbutton(
            self.app.discord_periodic_options_frame,
            text="Attach Latest Image",
            variable=self.app.discord_include_image_var,
            font=FONTS['body'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        image_check.pack(anchor='w')
        
        # Embed Color
        color_section = tk.Frame(self.app.discord_options_frame, bg=COLORS['bg_card'])
        color_section.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(color_section, text="Embed Color",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(anchor='w',
                                          pady=(0, SPACING['element_gap']))
        
        color_input_frame = tk.Frame(color_section, bg=COLORS['bg_card'])
        color_input_frame.pack(fill='x', padx=(20, 0))
        
        tk.Label(color_input_frame, text="Hex Color:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left',
                                          padx=(0, SPACING['element_gap']))
        
        if not hasattr(self.app, 'discord_color_var'):
            self.app.discord_color_var = tk.StringVar(value="#0EA5E9")
        
        color_entry = ttk.Entry(color_input_frame,
                              textvariable=self.app.discord_color_var,
                              width=10,
                              style='Dark.TEntry')
        color_entry.pack(side='left', padx=(0, SPACING['element_gap']))
        
        # Color preview
        self.app.discord_color_preview = tk.Frame(color_input_frame,
                                                 bg="#0EA5E9",
                                                 width=30, height=30,
                                                 relief='solid',
                                                 borderwidth=1)
        self.app.discord_color_preview.pack(side='left')
        self.app.discord_color_preview.pack_propagate(False)
        
        # Bind color change
        self.app.discord_color_var.trace_add('write', self.app.on_discord_color_change)
