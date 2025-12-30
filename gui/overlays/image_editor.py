"""
Image overlay editor component
"""
import os
import shutil
import tkinter as tk
import ttkbootstrap as ttk
from tkinter import filedialog
from PIL import Image
from ..theme import COLORS, FONTS, SPACING
from .. import theme
from .constants import POSITION_PRESETS


class ImageOverlayEditor:
    """Image overlay editor panel"""
    
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.overlay_images_dir = None
        # Create container frame for show/hide capability
        self.frame = tk.Frame(parent, bg=COLORS['bg_card'])
        self.create_ui()
    
    def create_ui(self):
        """Create image editor UI"""
        # Name field
        name_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        name_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(name_frame, text="Name:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        # Use shared overlay_name_var (created by text editor or main_window)
        if not hasattr(self.app, 'overlay_name_var'):
            self.app.overlay_name_var = tk.StringVar()
        name_entry = ttk.Entry(name_frame, 
                              textvariable=self.app.overlay_name_var,
                              style='Dark.TEntry', width=30)
        name_entry.pack(side='left', fill='x', expand=True)
        self.app.overlay_name_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        # Image selection
        image_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        image_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(image_frame, text="Image:",
                font=FONTS['body_bold'],
                fg=COLORS['text_primary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        self.app.overlay_image_path_var = tk.StringVar()
        path_entry = ttk.Entry(image_frame, 
                              textvariable=self.app.overlay_image_path_var,
                              style='Dark.TEntry',
                              state='readonly')
        path_entry.pack(side='left', fill='x', expand=True,
                       padx=(0, SPACING['element_gap']))
        self.app.overlay_image_path_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        browse_btn = theme.create_primary_button(image_frame, "Browse...",
                                                 self.browse_image)
        browse_btn.pack(side='left')
        
        # Size controls
        size_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        size_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(size_frame, text="Width (px):",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        self.app.overlay_image_width_var = tk.IntVar(value=100)
        self.width_spinbox = ttk.Spinbox(size_frame, from_=10, to=2000,
                                textvariable=self.app.overlay_image_width_var,
                                width=10, style='Dark.TSpinbox',
                                command=self.app.on_overlay_edit)
        self.width_spinbox.pack(side='left', padx=(0, SPACING['element_gap'] * 2))
        self.app.overlay_image_width_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        tk.Label(size_frame, text="Height (px):",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        self.app.overlay_image_height_var = tk.IntVar(value=100)
        height_spin = ttk.Spinbox(size_frame, from_=10, to=2000,
                                 textvariable=self.app.overlay_image_height_var,
                                 width=10, style='Dark.TSpinbox',
                                 command=self.app.on_overlay_edit)
        height_spin.pack(side='left', padx=(0, SPACING['element_gap']))
        self.app.overlay_image_height_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        # Maintain aspect ratio checkbox
        self.app.overlay_image_maintain_aspect_var = tk.BooleanVar(value=True)
        aspect_check = tk.Checkbutton(
            size_frame,
            text="Maintain aspect ratio",
            variable=self.app.overlay_image_maintain_aspect_var,
            command=self.on_aspect_toggle,
            font=FONTS['small'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_card'],
            activebackground=COLORS['bg_card'],
            selectcolor=COLORS['accent_primary']
        )
        aspect_check.pack(side='left', padx=(SPACING['element_gap'] * 2, 0))
        
        # Disable width by default since aspect ratio is on
        self.width_spinbox.config(state='disabled')
        
        # Opacity slider
        opacity_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        opacity_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(opacity_frame, text="Opacity:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        self.app.overlay_image_opacity_var = tk.IntVar(value=100)
        opacity_scale = ttk.Scale(opacity_frame, from_=0, to=100,
                                 variable=self.app.overlay_image_opacity_var,
                                 orient='horizontal',
                                 command=lambda *args: self.app.on_overlay_edit(),
                                 bootstyle='primary')
        opacity_scale.pack(side='left', fill='x', expand=True,
                          padx=(0, SPACING['element_gap']))
        
        opacity_label = tk.Label(opacity_frame, 
                                textvariable=self.app.overlay_image_opacity_var,
                                font=FONTS['body'],
                                fg=COLORS['text_primary'],
                                bg=COLORS['bg_card'],
                                width=4)
        opacity_label.pack(side='left')
        
        # Position settings
        self.create_position_section()
    
    def create_position_section(self):
        """Create position controls"""
        pos_label = tk.Label(self.frame, text="Position:",
                            font=FONTS['body_bold'],
                            fg=COLORS['text_primary'],
                            bg=COLORS['bg_card'])
        pos_label.pack(anchor='w', 
                      pady=(SPACING['row_gap'], SPACING['element_gap']))
        
        # Anchor
        anchor_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        anchor_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(anchor_frame, text="Anchor:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        # Use shared anchor_var (created by text editor or main_window)
        if not hasattr(self.app, 'anchor_var'):
            self.app.anchor_var = tk.StringVar(value='Bottom-Right')
        anchor_combo = ttk.Combobox(anchor_frame,
                                    textvariable=self.app.anchor_var,
                                    values=POSITION_PRESETS,
                                    state='readonly',
                                    style='Dark.TCombobox',
                                    width=15)
        anchor_combo.pack(side='left')
        anchor_combo.bind('<<ComboboxSelected>>', 
                         lambda e: self.app.on_overlay_edit())
        
        # X/Y Offsets
        offset_frame = tk.Frame(self.frame, bg=COLORS['bg_card'])
        offset_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(offset_frame, text="X Offset:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        # Use shared offset_x_var (created by text editor or main_window)
        if not hasattr(self.app, 'offset_x_var'):
            self.app.offset_x_var = tk.IntVar(value=10)
        x_spin = ttk.Spinbox(offset_frame, from_=-500, to=500,
                            textvariable=self.app.offset_x_var,
                            width=8, style='Dark.TSpinbox',
                            command=self.app.on_overlay_edit)
        x_spin.pack(side='left', padx=(0, SPACING['element_gap'] * 2))
        self.app.offset_x_var.trace('w', lambda *args: self.app.on_overlay_edit())
        
        tk.Label(offset_frame, text="Y Offset:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_card']).pack(side='left', 
                                          padx=(0, SPACING['element_gap']))
        
        # Use shared offset_y_var (created by text editor or main_window)
        if not hasattr(self.app, 'offset_y_var'):
            self.app.offset_y_var = tk.IntVar(value=10)
        y_spin = ttk.Spinbox(offset_frame, from_=-500, to=500,
                            textvariable=self.app.offset_y_var,
                            width=8, style='Dark.TSpinbox',
                            command=self.app.on_overlay_edit)
        y_spin.pack(side='left')
        self.app.offset_y_var.trace('w', lambda *args: self.app.on_overlay_edit())
    
    def browse_image(self):
        """Open file dialog to select image"""
        filename = filedialog.askopenfilename(
            title="Select Overlay Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("PNG files", "*.png"),
                ("JPEG files", "*.jpg *.jpeg"),
                ("All files", "*.*")
            ]
        )
        
        if filename:
            # Copy image to overlay_images directory
            stored_path = self.store_image(filename)
            if stored_path:
                self.app.overlay_image_path_var.set(stored_path)
                
                # Default to 100px height, calculate width based on aspect ratio
                try:
                    with Image.open(stored_path) as img:
                        aspect_ratio = img.width / img.height
                        default_height = 100
                        default_width = int(default_height * aspect_ratio)
                        self.app.overlay_image_height_var.set(default_height)
                        self.app.overlay_image_width_var.set(default_width)
                except Exception as e:
                    print(f"Error reading image dimensions: {e}")
                    # Fallback to square if image can't be read
                    self.app.overlay_image_height_var.set(100)
                    self.app.overlay_image_width_var.set(100)
                
                self.app.on_overlay_edit()
    
    def store_image(self, source_path):
        """
        Copy image to application's overlay_images directory
        
        Args:
            source_path: Path to source image
            
        Returns:
            Path to stored image, or None if failed
        """
        try:
            # Create overlay_images directory if it doesn't exist
            if not self.overlay_images_dir:
                # Get app data directory (consistent with config.py pattern)
                from app_config import APP_DATA_FOLDER
                data_dir = os.path.join(os.getenv('LOCALAPPDATA'), APP_DATA_FOLDER)
                
                self.overlay_images_dir = os.path.join(data_dir, "overlay_images")
            
            os.makedirs(self.overlay_images_dir, exist_ok=True)
            
            # Generate unique filename
            filename = os.path.basename(source_path)
            name, ext = os.path.splitext(filename)
            dest_path = os.path.join(self.overlay_images_dir, filename)
            
            # Handle duplicate filenames
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(self.overlay_images_dir, 
                                        f"{name}_{counter}{ext}")
                counter += 1
            
            # Copy file
            shutil.copy2(source_path, dest_path)
            return dest_path
            
        except Exception as e:
            print(f"Error storing image: {e}")
            return None
    
    def on_aspect_toggle(self):
        """Toggle width spinbox enabled/disabled based on aspect ratio checkbox"""
        if self.app.overlay_image_maintain_aspect_var.get():
            # Aspect ratio is on - disable width
            self.width_spinbox.config(state='disabled')
        else:
            # Aspect ratio is off - enable width
            self.width_spinbox.config(state='normal')
        
        # Trigger preview update
        self.app.on_overlay_edit()
