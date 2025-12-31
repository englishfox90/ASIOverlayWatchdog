"""
Overlay tab component - Theme integration with modular structure
"""
import tkinter as tk
import ttkbootstrap as ttk
from .theme import COLORS, FONTS, SPACING, create_gradient_stripe
from . import theme
from .overlays.overlay_list import OverlayListPanel
from .overlays.text_editor import TextOverlayEditor
from .overlays.image_editor import ImageOverlayEditor
from .overlays.preview import OverlayPreview


class OverlayTab:
    """Themed Overlay tab - modular design"""
    
    def __init__(self, notebook, app):
        self.app = app
        self.tab = ttk.Frame(notebook)
        notebook.add(self.tab, text="  Overlays  ")
        
        self.create_ui()
    
    def create_ui(self):
        """Create the themed overlay tab UI - 2 column layout"""
        # Gradient accent stripe at top
        create_gradient_stripe(self.tab)
        
        # Main container with pack
        overlays_container = tk.Frame(self.tab, bg=COLORS['bg_primary'])
        overlays_container.pack(fill='both', expand=True)
        
        # LEFT COLUMN: List + Preview (stacked vertically)
        left_column = tk.Frame(overlays_container, bg=COLORS['bg_primary'])
        left_column.pack(side='left', fill='both', expand=False,
                        padx=(SPACING['card_margin_x'], SPACING['element_gap']),
                        pady=SPACING['card_margin_y'], ipadx=100)
        
        # Overlay List Card (top of left column)
        list_content = theme.create_card(left_column, title="Overlay List")
        list_card = list_content.master
        list_card.pack(fill='both', expand=True,
                      pady=(0, SPACING['row_gap']))
        
        # Create list panel
        self.list_panel = OverlayListPanel(list_content, self.app)
        
        # Preview Card (bottom of left column)
        preview_content = theme.create_card(left_column, title="Preview")
        preview_card = preview_content.master
        preview_card.pack(fill='both', expand=False, ipady=150)
        
        # Create preview panel
        self.preview_panel = OverlayPreview(preview_content, self.app)
        
        # RIGHT COLUMN: Editor (full height)
        right_column = tk.Frame(overlays_container, bg=COLORS['bg_primary'])
        right_column.pack(side='left', fill='both', expand=True,
                         padx=(0, SPACING['card_margin_x']),
                         pady=SPACING['card_margin_y'])
        
        # Overlay Editor Card (full height)
        editor_content = theme.create_card(right_column, title="Overlay Editor")
        editor_card = editor_content.master
        editor_card.pack(fill='both', expand=True)
        
        self.create_editor_panel(editor_content)
    
    def create_editor_panel(self, parent):
        """Create editor panel with switchable text/image editors"""
        # Scrollable editor content
        editor_scroll_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        editor_scroll_frame.pack(fill='both', expand=True, pady=(0, SPACING['row_gap']))
        
        # Canvas for scrolling
        editor_canvas = tk.Canvas(editor_scroll_frame, bg=COLORS['bg_card'],
                                 highlightthickness=0)
        editor_scrollbar = ttk.Scrollbar(editor_scroll_frame, orient='vertical',
                                        command=editor_canvas.yview,
                                        bootstyle="round")
        
        self.app.editor_content_frame = tk.Frame(editor_canvas, bg=COLORS['bg_card'])
        self.app.editor_content_frame.bind(
            '<Configure>',
            lambda e: editor_canvas.configure(scrollregion=editor_canvas.bbox('all'))
        )
        
        window_id = editor_canvas.create_window((0, 0), 
                                                window=self.app.editor_content_frame,
                                                anchor='nw')
        editor_canvas.configure(yscrollcommand=editor_scrollbar.set)
        
        editor_canvas.pack(side='left', fill='both', expand=True)
        editor_scrollbar.pack(side='right', fill='y')
        
        # Bind canvas width updates
        def configure_canvas_width(event):
            canvas_width = event.width
            editor_canvas.itemconfig(window_id, width=canvas_width)
        
        editor_canvas.bind('<Configure>', configure_canvas_width)
        
        # Create both text and image editors (hide/show based on type)
        self.text_editor = TextOverlayEditor(self.app.editor_content_frame, self.app)
        self.image_editor = ImageOverlayEditor(self.app.editor_content_frame, self.app)
        
        # Start with text editor visible
        self.text_editor.frame.pack(fill='both', expand=True)
        self.image_editor.frame.pack_forget()
        
        # Buttons at bottom
        btn_frame = tk.Frame(parent, bg=COLORS['bg_card'])
        btn_frame.pack(fill='x')
        
        apply_btn = theme.create_primary_button(btn_frame, "✓ Apply Changes",
                                                self.app.apply_overlay_changes)
        apply_btn.pack(side='left', padx=(0, SPACING['button_gap']))
        
        reset_btn = theme.create_secondary_button(btn_frame, "↺ Reset",
                                                  self.app.reset_overlay_editor)
        reset_btn.pack(side='left')
    
    def switch_editor(self, overlay_type):
        """Switch between text and image editors based on overlay type"""
        if overlay_type == 'image':
            self.text_editor.frame.pack_forget()
            self.image_editor.frame.pack(fill='both', expand=True)
        else:  # 'text' or default
            self.image_editor.frame.pack_forget()
            self.text_editor.frame.pack(fill='both', expand=True)

