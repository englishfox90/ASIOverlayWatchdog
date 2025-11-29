"""
Overlay preview component
"""
import tkinter as tk
from ..theme import COLORS


class OverlayPreview:
    """Overlay preview panel with canvas"""
    
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.create_ui()
    
    def create_ui(self):
        """Create preview UI"""
        # Canvas for preview
        preview_frame = tk.Frame(self.parent, bg=COLORS['bg_card'])
        preview_frame.pack(fill='both', expand=True)
        
        self.app.overlay_preview_canvas = tk.Canvas(
            preview_frame,
            bg=COLORS['bg_primary'],
            highlightthickness=0,
            height=200
        )
        self.app.overlay_preview_canvas.pack(fill='both', expand=True)
        
        # Initialize preview variables
        self.app.overlay_preview_image = None
        self.app.overlay_preview_photo = None
