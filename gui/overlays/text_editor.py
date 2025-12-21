"""
Text overlay editor component
"""
import tkinter as tk
import ttkbootstrap as ttk
from tkinter import colorchooser
from datetime import datetime
from ..theme import COLORS, FONTS, SPACING
from .. import theme
from .constants import TOKENS, POSITION_PRESETS, DATETIME_FORMATS


class TextOverlayEditor:
    """Text overlay editor panel"""
    
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        # Create container frame for show/hide capability
        self.frame = tk.Frame(parent, bg=COLORS['bg_card'])
        self.create_ui()
    
    def create_ui(self):
        """Create text editor UI"""
        # Name field
        name_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        name_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(name_frame, text="Name:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        self.app.overlay_name_var = tk.StringVar()
        name_entry = ttk.Entry(name_frame, 
                              textvariable=self.app.overlay_name_var,
                              style='Dark.TEntry', width=30)
        name_entry.pack(side='left', fill='x', expand=True)
        self.app.overlay_name_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        # Text area with token insertion
        text_label = tk.Label(self.frame, text="Text:",
                             font=FONTS['body_bold'],
                             fg=COLORS['text_primary'],
                             bg=COLORS['bg_card'])
        text_label.pack(anchor='w', 
                       pady=(SPACING['row_gap'], SPACING['element_gap']))
        
        # Token toolbar
        self.create_token_toolbar()
        
        # Text widget
        self.app.overlay_text = tk.Text(
            self.frame,
            height=4,
            wrap='word',
            font=FONTS['body'],
            bg=COLORS['bg_input'],
            fg=COLORS['text_primary'],
            insertbackground=COLORS['text_primary'],
            borderwidth=1,
            relief='solid',
            highlightthickness=0
        )
        self.app.overlay_text.pack(fill='x', pady=(0, SPACING['row_gap']))
        self.app.overlay_text.bind('<KeyRelease>', 
                                   lambda e: self.app.on_overlay_edit())
        
        # DateTime format section
        self.create_datetime_section()
        
        # Text appearance
        self.create_appearance_section()
        
        # Background options
        self.create_background_section()
        
        # Position settings
        self.create_position_section()
    
    def create_token_toolbar(self):
        """Create token insertion toolbar"""
        token_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        token_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        tk.Label(token_frame, text="Tokens:",
                font=FONTS['tiny'],
                fg=COLORS['text_muted'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        self.app.token_display_var = tk.StringVar()
        # Extract only the labels (including headers which will be grayed out)
        token_labels = [label for label, _ in TOKENS]
        token_combo = ttk.Combobox(token_frame,
                                   textvariable=self.app.token_display_var,
                                   values=token_labels,
                                   state='readonly',
                                   style='Dark.TCombobox',
                                   width=25)  # Slightly wider for header text
        token_combo.pack(side='left', padx=(0, SPACING['element_gap']))
        
        # Bind selection event to prevent selecting headers
        token_combo.bind('<<ComboboxSelected>>', self.on_token_selected)
        
        insert_btn = theme.create_secondary_button(token_frame, "Insert",
                                                   self.app.insert_token)
        insert_btn.pack(side='left')
        
        # Store reference for header validation
        self.token_combo = token_combo
    
    def on_token_selected(self, event=None):
        """Handle token selection - prevent selecting headers"""
        selected_label = self.app.token_display_var.get()
        
        # Find the selected item in TOKENS
        for label, token in TOKENS:
            if label == selected_label:
                if token is None:  # Header selected
                    # Clear selection and show message
                    self.app.token_display_var.set('')
                    return
                break
    
    def create_datetime_section(self):
        """Create DateTime format configuration"""
        dt_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        # Store reference for show/hide
        self.app.datetime_section_frame = dt_frame
        # Don't pack initially - will be shown when {DATETIME} token is present
        
        tk.Label(dt_frame, text="Date/Time Format:",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(anchor='w', 
                                          pady=(0, SPACING['element_gap']))
        
        self.app.datetime_mode_var = tk.StringVar(value="full")
        self.app.datetime_custom_var = tk.StringVar(value="%Y-%m-%d %H:%M:%S")
        
        # Radio buttons
        radio_frame = tk.Frame(dt_frame, bg=COLORS['bg_card'])
        radio_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        modes = [
            ("Full date & time", "full"),
            ("Date only", "date"),
            ("Time only", "time"),
            ("Custom", "custom")
        ]
        
        for label, value in modes:
            rb = tk.Radiobutton(
                radio_frame, text=label, value=value,
                variable=self.app.datetime_mode_var,
                command=self.app.on_datetime_mode_change,
                font=FONTS['small'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card'],
                activebackground=COLORS['bg_card'],
                selectcolor=COLORS['accent_primary']
            )
            rb.pack(anchor='w')
        
        # Locale selector for date format
        locale_frame = tk.Frame(dt_frame, bg=COLORS['bg_card'])
        locale_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
        
        tk.Label(locale_frame, text="Date locale:",
                font=FONTS['small'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(20, SPACING['element_gap']))
        
        from .constants import LOCALE_FORMATS
        self.app.datetime_locale_var = tk.StringVar(value="ISO (YYYY-MM-DD)")
        locale_combo = ttk.Combobox(
            locale_frame,
            textvariable=self.app.datetime_locale_var,
            values=list(LOCALE_FORMATS.keys()),
            state='readonly',
            style='Dark.TCombobox',
            width=18
        )
        locale_combo.pack(side='left')
        locale_combo.bind('<<ComboboxSelected>>', 
                         lambda e: self.app.update_datetime_preview())
        
        # Custom format entry
        custom_frame = tk.Frame(dt_frame, bg=COLORS['bg_card'])
        self.app.datetime_custom_frame = custom_frame
        # Don't pack initially - will be shown when custom mode selected
        
        tk.Label(custom_frame, text="Custom format:",
                font=FONTS['small'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(20, SPACING['element_gap']))
        
        self.app.datetime_custom_entry = ttk.Entry(
            custom_frame,
            textvariable=self.app.datetime_custom_var,
            style='Dark.TEntry',
            width=25
        )
        self.app.datetime_custom_entry.pack(side='left')
        self.app.datetime_custom_entry.bind('<KeyRelease>', 
                                           lambda e: self.app.update_datetime_preview())
    
    def create_appearance_section(self):
        """Create text appearance settings"""
        appearance_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        appearance_frame.pack(fill='x', pady=(SPACING['section_gap'], 0))
        self.app.appearance_section_frame = appearance_frame
        
        tk.Label(appearance_frame, text="Text Appearance:",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).grid(row=0, column=0, columnspan=4,
                                          sticky='w', 
                                          pady=(0, SPACING['element_gap']))
        
        row = 1
        # Font Size
        tk.Label(appearance_frame, text="Font Size:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).grid(row=row, column=0, sticky='w',
                                          pady=(SPACING['element_gap'], SPACING['element_gap']))
        
        self.app.font_size_var = tk.IntVar(value=24)
        ttk.Spinbox(appearance_frame, from_=8, to=200,
                   textvariable=self.app.font_size_var,
                   width=10, style='Dark.TSpinbox',
                   command=self.app.on_overlay_edit).grid(
            row=row, column=1, sticky='w', 
            padx=(SPACING['element_gap'], 0))
        
        # Text Color
        tk.Label(appearance_frame, text="Color:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).grid(row=row, column=2, sticky='w',
                                          padx=(SPACING['section_gap'], 0),
                                          pady=(SPACING['element_gap'], SPACING['element_gap']))
        
        color_frame = tk.Frame(appearance_frame, bg=COLORS['bg_card'])
        color_frame.grid(row=row, column=3, sticky='w',
                        padx=(SPACING['element_gap'], 0))
        
        self.app.color_var = tk.StringVar(value="white")
        color_combo = ttk.Combobox(color_frame,
                                   textvariable=self.app.color_var,
                                   values=['white', 'black', 'lightgray', 'darkgray',
                                          'red', 'green', 'blue', 'cyan', 'magenta', 
                                          'yellow', 'orange', 'purple', 'pink', 'lime'],
                                   state='readonly',
                                   style='Dark.TCombobox',
                                   width=12)
        color_combo.pack(side='left')
        self.app.color_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        row += 1
        # Font Style
        tk.Label(appearance_frame, text="Font Style:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).grid(row=row, column=0, sticky='w',
                                          pady=(SPACING['element_gap'], SPACING['element_gap']))
        
        self.app.font_style_var = tk.StringVar(value="normal")
        ttk.Combobox(appearance_frame,
                    textvariable=self.app.font_style_var,
                    values=['normal', 'bold', 'italic'],
                    state='readonly',
                    style='Dark.TCombobox',
                    width=10).grid(row=row, column=1, sticky='w',
                                  padx=(SPACING['element_gap'], 0))
        self.app.font_style_var.trace('w', lambda *args: self.app.on_overlay_edit())
    
    def create_background_section(self):
        """Create background rectangle options"""
        bg_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        bg_frame.pack(fill='x', pady=(SPACING['section_gap'], 0))
        
        tk.Label(bg_frame, text="Background:",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(anchor='w', 
                                          pady=(0, SPACING['element_gap']))
        
        # Enable checkbox
        self.app.background_enabled_var = tk.BooleanVar(value=False)
        bg_check = tk.Checkbutton(
            bg_frame, text="Draw background rectangle behind text",
            variable=self.app.background_enabled_var,
            command=self.app.on_background_toggle,
            font=FONTS['body'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        bg_check.pack(anchor='w')
        
        # Background color options
        bg_color_frame = tk.Frame(bg_frame, bg=COLORS['bg_card'])
        bg_color_frame.pack(fill='x', padx=(20, 0), 
                           pady=(SPACING['element_gap'], 0))
        
        tk.Label(bg_color_frame, text="BG Color:",
                font=FONTS['small'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']),
                                          pady=SPACING['element_gap'])
        
        self.app.bg_color_var = tk.StringVar(value="black")
        bg_color_combo = ttk.Combobox(bg_color_frame,
                                      textvariable=self.app.bg_color_var,
                                      values=['transparent', 'black', 'white', 
                                             'darkgray', 'lightgray', 'red', 'green', 
                                             'blue', 'cyan', 'magenta', 'yellow'],
                                      state='readonly',
                                      style='Dark.TCombobox',
                                      width=12)
        bg_color_combo.pack(side='left')
        self.app.bg_color_var.trace('w', lambda *args: self.app.on_overlay_edit())
    
    def create_position_section(self):
        """Create position settings"""
        pos_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        pos_frame.pack(fill='x', pady=(SPACING['section_gap'], 0))
        
        tk.Label(pos_frame, text="Position:",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).grid(row=0, column=0, columnspan=4,
                                          sticky='w', 
                                          pady=(0, SPACING['element_gap']))
        
        row = 1
        # Position preset
        tk.Label(pos_frame, text="Anchor:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).grid(row=row, column=0, sticky='w',
                                          pady=(SPACING['element_gap'], SPACING['element_gap']))
        
        self.app.anchor_var = tk.StringVar(value="Bottom-Left")
        anchor_combo = ttk.Combobox(pos_frame,
                                    textvariable=self.app.anchor_var,
                                    values=POSITION_PRESETS,
                                    state='readonly',
                                    style='Dark.TCombobox',
                                    width=15)
        anchor_combo.grid(row=row, column=1, sticky='w',
                         padx=(SPACING['element_gap'], 0))
        self.app.anchor_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        row += 1
        # Offset X
        tk.Label(pos_frame, text="Offset X:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).grid(row=row, column=0, sticky='w',
                                          pady=(SPACING['element_gap'], SPACING['element_gap']))
        
        self.app.offset_x_var = tk.IntVar(value=10)
        ttk.Spinbox(pos_frame, from_=-2000, to=2000,
                   textvariable=self.app.offset_x_var,
                   width=10, style='Dark.TSpinbox',
                   command=self.app.on_overlay_edit).grid(
            row=row, column=1, sticky='w',
            padx=(SPACING['element_gap'], 0))
        
        # Offset Y
        tk.Label(pos_frame, text="Offset Y:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).grid(row=row, column=2, sticky='w',
                                          padx=(SPACING['section_gap'], 0),
                                          pady=(SPACING['element_gap'], SPACING['element_gap']))
        
        self.app.offset_y_var = tk.IntVar(value=10)
        ttk.Spinbox(pos_frame, from_=-2000, to=2000,
                   textvariable=self.app.offset_y_var,
                   width=10, style='Dark.TSpinbox',
                   command=self.app.on_overlay_edit).grid(
            row=row, column=3, sticky='w',
            padx=(SPACING['element_gap'], 0))
