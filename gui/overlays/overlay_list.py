"""
Overlay list component with Treeview
"""
import tkinter as tk
import ttkbootstrap as ttk
from ..theme import COLORS, FONTS, SPACING
from .. import theme


class OverlayListPanel:
    """Overlay list panel with themed Treeview"""
    
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.create_ui()
    
    def create_ui(self):
        """Create the list panel UI"""
        # Buttons row
        btn_frame = tk.Frame(self.parent, bg=COLORS['bg_card'])
        btn_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        add_btn = theme.create_primary_button(btn_frame, "➕ Add", 
                                              self.app.add_new_overlay)
        add_btn.pack(side='left', padx=(0, SPACING['button_gap']))
        
        dup_btn = theme.create_secondary_button(btn_frame, "📋 Duplicate", 
                                                self.app.duplicate_overlay)
        dup_btn.pack(side='left', padx=(0, SPACING['button_gap']))
        
        del_btn = theme.create_destructive_button(btn_frame, "🗑 Delete", 
                                                  self.app.delete_overlay)
        del_btn.pack(side='left')
        
        # Treeview for overlay list
        tree_frame = tk.Frame(self.parent, bg=COLORS['bg_card'])
        tree_frame.pack(fill='both', expand=True)
        
        # Create Treeview
        columns = ('type', 'summary')
        self.app.overlay_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show='tree headings',
            selectmode='browse',
            height=10
        )
        
        # Configure columns with left-aligned headers
        self.app.overlay_tree.heading('#0', text='Name', anchor='w')
        self.app.overlay_tree.heading('type', text='Type', anchor='w')
        self.app.overlay_tree.heading('summary', text='Summary', anchor='w')
        
        self.app.overlay_tree.column('#0', width=120, minwidth=80, anchor='w')
        self.app.overlay_tree.column('type', width=60, minwidth=50, anchor='w')
        self.app.overlay_tree.column('summary', width=150, minwidth=100, anchor='w')
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical',
                                 command=self.app.overlay_tree.yview,
                                 bootstyle="round")
        self.app.overlay_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack layout
        self.app.overlay_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Bind selection
        self.app.overlay_tree.bind('<<TreeviewSelect>>', 
                                   self.app.on_overlay_tree_select)
        self.app.overlay_tree.bind('<Double-Button-1>', 
                                   self.app.on_overlay_tree_select)
