"""
Preview tab component - image preview with zoom controls
"""
import tkinter as tk
import ttkbootstrap as ttk
from . import theme
from .theme import COLORS, FONTS, SPACING


class PreviewTab:
    """Preview tab for viewing processed images"""
    
    def __init__(self, notebook, app):
        self.app = app
        self.tab = ttk.Frame(notebook)
        notebook.add(self.tab, text="  Preview  ")
        
        self.create_ui()
    
    def create_ui(self):
        """Create the preview tab UI with theme"""
        # Main container
        preview_container = tk.Frame(self.tab, bg=COLORS['bg_primary'])
        preview_container.pack(fill='both', expand=True)
        preview_container.grid_columnconfigure(0, weight=1)
        preview_container.grid_rowconfigure(1, weight=1)
        
        # ===== Controls row (top) =====
        controls = tk.Frame(preview_container, bg=COLORS['bg_primary'])
        controls.grid(row=0, column=0, sticky="ew",
                     padx=SPACING['card_margin_x'],
                     pady=(SPACING['card_margin_y'], SPACING['row_gap']))
        controls.grid_columnconfigure(2, weight=1)
        
        # Refresh button
        refresh_button = theme.create_primary_button(controls, "🔄 Refresh", self.on_refresh_preview)
        refresh_button.grid(row=0, column=0, padx=(0, SPACING['element_gap']))
        
        # Zoom label
        tk.Label(controls, text="Zoom:",
                font=FONTS['body'],
                fg=COLORS['text_secondary'],
                bg=COLORS['bg_primary']).grid(row=0, column=1, sticky="w")
        
        # Zoom slider (use pre-initialized variable from app)
        zoom_slider = ttk.Scale(
            controls, from_=10, to=200,
            variable=self.app.preview_zoom_var,
            orient="horizontal",
            command=self.on_zoom_change,
            bootstyle="info"
        )
        zoom_slider.grid(row=0, column=2, sticky="ew", padx=SPACING['element_gap'])
        
        # Zoom percentage label
        self.zoom_label = tk.Label(controls, text="100 %",
                                   font=FONTS['small'],
                                   fg=COLORS['text_secondary'],
                                   bg=COLORS['bg_primary'])
        self.zoom_label.grid(row=0, column=3, padx=(SPACING['element_gap'], 0))
        
        # Auto-refresh checkbox (use pre-initialized variable from app)
        auto_check = tk.Checkbutton(
            controls, text="Auto-refresh",
            variable=self.app.auto_refresh_var,
            font=FONTS['small'],
            fg=COLORS['text_secondary'],
            bg=COLORS['bg_primary'],
            activebackground=COLORS['bg_primary'],
            selectcolor=COLORS['bg_card']
        )
        auto_check.grid(row=0, column=4, padx=(SPACING['element_gap'], 0))
        
        # ===== Image preview area =====
        preview_content = theme.create_card(preview_container, title=None)
        preview_card = preview_content.master
        
        preview_card.grid(row=1, column=0, sticky="nsew",
                         padx=SPACING['card_margin_x'],
                         pady=(0, SPACING['card_margin_y']))
        
        preview_content.grid_columnconfigure(0, weight=1)
        preview_content.grid_rowconfigure(0, weight=1)
        
        # Canvas with scrollbars
        canvas_frame = tk.Frame(preview_content, bg=COLORS['bg_primary'])
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)
        
        # Scrollbars
        v_scroll = ttk.Scrollbar(canvas_frame, orient='vertical', bootstyle="round")
        h_scroll = ttk.Scrollbar(canvas_frame, orient='horizontal', bootstyle="round")
        
        # Canvas
        self.app.preview_canvas = tk.Canvas(
            canvas_frame,
            bg=COLORS['bg_primary'],
            highlightthickness=0,
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set
        )
        
        v_scroll.config(command=self.app.preview_canvas.yview)
        h_scroll.config(command=self.app.preview_canvas.xview)
        
        # Grid layout for scrollbars
        self.app.preview_canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        
        # Initialize preview variables
        self.app.preview_image = None
        self.app.preview_photo = None
    
    def on_refresh_preview(self):
        """Handle manual refresh button click"""
        self.app.refresh_preview(auto_fit=True)
    
    def on_zoom_change(self, value):
        """Handle zoom slider change"""
        zoom_percent = int(float(value))
        self.zoom_label.config(text=f"{zoom_percent} %")
        self.app.refresh_preview(auto_fit=False)
