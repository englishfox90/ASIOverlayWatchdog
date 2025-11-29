"""
Overlay management module
Handles all overlay-related operations
"""
import tkinter as tk
import ttkbootstrap as ttk
from tkinter import messagebox
from services.logger import app_logger
from .theme import SPACING


class OverlayManager:
    """Manages overlay configuration and editing"""
    
    def __init__(self, app):
        self.app = app
    
    def get_overlays_config(self):
        """Get current overlays configuration"""
        return self.app.config.get('overlays', [])
    
    def rebuild_overlay_list(self):
        """Rebuild the overlay list UI (Treeview)"""
        # Clear existing tree items
        for item in self.app.overlay_tree.get_children():
            self.app.overlay_tree.delete(item)
        
        # Get overlays
        overlays = self.get_overlays_config()
        
        # Populate tree
        for i, overlay in enumerate(overlays):
            name = overlay.get('name', overlay.get('text', 'Overlay')[:20])
            overlay_type = 'Text'  # Phase 1: text only
            summary = overlay.get('anchor', 'Bottom-Left')
            
            self.app.overlay_tree.insert('', 'end', iid=str(i),
                                         text=name,
                                         values=(overlay_type, summary))
        
        # Select first if available
        if overlays:
            self.app.overlay_tree.selection_set('0')
            self.app.selected_overlay_index = 0
            self.load_overlay_into_editor(overlays[0])
    
    def on_overlay_tree_select(self, event=None):
        """Handle Treeview selection"""
        selection = self.app.overlay_tree.selection()
        if not selection:
            return
        
        # Get selected index
        item_id = selection[0]
        self.app.selected_overlay_index = int(item_id)
        
        # Load overlay
        overlays = self.get_overlays_config()
        if 0 <= self.app.selected_overlay_index < len(overlays):
            self.load_overlay_into_editor(overlays[self.app.selected_overlay_index])
    
    def load_overlay_into_editor(self, overlay):
        """Load overlay data into editor"""
        # Load all fields from overlay config
        self.app.overlay_name_var.set(overlay.get('name', overlay.get('text', '')[:30]))
        
        # Text content
        self.app.overlay_text.delete('1.0', 'end')
        self.app.overlay_text.insert('1.0', overlay.get('text', ''))
        
        # Datetime format (default to 'full')
        self.app.datetime_mode_var.set(overlay.get('datetime_mode', 'full'))
        self.app.datetime_custom_var.set(overlay.get('datetime_format', '%Y-%m-%d %H:%M:%S'))
        if hasattr(self.app, 'datetime_locale_var'):
            self.app.datetime_locale_var.set(overlay.get('datetime_locale', 'ISO (YYYY-MM-DD)'))
        
        # Font appearance
        self.app.font_size_var.set(overlay.get('font_size', 24))
        self.app.color_var.set(overlay.get('color', 'white'))
        self.app.font_style_var.set(overlay.get('font_style', 'normal'))
        
        # Background
        self.app.background_enabled_var.set(overlay.get('background_enabled', False))
        self.app.bg_color_var.set(overlay.get('background_color', 'black'))
        self.on_background_toggle()  # Update UI state
        
        # Position
        self.app.anchor_var.set(overlay.get('anchor', 'Bottom-Left'))
        self.app.offset_x_var.set(overlay.get('offset_x', 10))
        self.app.offset_y_var.set(overlay.get('offset_y', 10))
        
        # Check if datetime section should be visible
        text_content = overlay.get('text', '')
        self.update_datetime_visibility('{DATETIME}' in text_content.upper())
    
    def add_new_overlay(self):
        """Add new overlay"""
        overlays = self.get_overlays_config()
        overlays.append({
            'name': f'Overlay {len(overlays) + 1}',
            'text': 'New Overlay {CAMERA}',
            'anchor': 'Bottom-Left',
            'color': 'white',
            'font_size': 24,
            'font_style': 'normal',
            'offset_x': 10,
            'offset_y': 10
        })
        self.app.config.set('overlays', overlays)
        self.rebuild_overlay_list()
        
        # Select the new overlay
        new_index = len(overlays) - 1
        self.app.overlay_tree.selection_set(str(new_index))
        self.app.selected_overlay_index = new_index
    
    def duplicate_overlay(self):
        """Duplicate selected overlay"""
        if self.app.selected_overlay_index is not None:
            overlays = self.get_overlays_config()
            if 0 <= self.app.selected_overlay_index < len(overlays):
                overlay_copy = overlays[self.app.selected_overlay_index].copy()
                overlays.append(overlay_copy)
                self.app.config.set('overlays', overlays)
                self.rebuild_overlay_list()
    
    def delete_overlay(self):
        """Delete selected overlay"""
        if self.app.selected_overlay_index is None:
            return
        
        if messagebox.askyesno("Confirm", "Delete this overlay?"):
            overlays = self.get_overlays_config()
            if 0 <= self.app.selected_overlay_index < len(overlays):
                overlays.pop(self.app.selected_overlay_index)
                self.app.config.set('overlays', overlays)
                self.app.selected_overlay_index = None
                self.rebuild_overlay_list()
    
    def clear_all_overlays(self):
        """Clear all overlays"""
        if messagebox.askyesno("Confirm", "Delete ALL overlays?"):
            self.app.config.set('overlays', [])
            self.app.selected_overlay_index = None
            self.rebuild_overlay_list()
            if hasattr(self.app, 'overlay_preview_canvas'):
                self.app.overlay_preview_canvas.delete('all')
    
    def apply_overlay_changes(self):
        """Apply changes from editor to selected overlay"""
        if self.app.selected_overlay_index is None:
            return
        
        overlays = self.get_overlays_config()
        if 0 <= self.app.selected_overlay_index < len(overlays):
            # Get datetime format based on mode and locale
            mode = self.app.datetime_mode_var.get()
            if mode == 'custom':
                datetime_format = self.app.datetime_custom_var.get()
            elif hasattr(self.app, 'datetime_locale_var'):
                # Use locale-specific formats
                from .overlays.constants import LOCALE_FORMATS
                locale = self.app.datetime_locale_var.get()
                locale_data = LOCALE_FORMATS.get(locale, {'date': '%Y-%m-%d', 'time': '%H:%M:%S', 'datetime': '%Y-%m-%d %H:%M:%S'})
                if mode == 'date':
                    datetime_format = locale_data['date']
                elif mode == 'time':
                    datetime_format = locale_data['time']
                else:  # full
                    datetime_format = locale_data['datetime']
            else:
                from .overlays.constants import DATETIME_FORMATS
                datetime_format = DATETIME_FORMATS.get(mode, '%Y-%m-%d %H:%M:%S')
            
            # Save all fields
            overlays[self.app.selected_overlay_index] = {
                'name': self.app.overlay_name_var.get(),
                'text': self.app.overlay_text.get('1.0', 'end-1c'),
                'anchor': self.app.anchor_var.get(),
                'color': self.app.color_var.get(),
                'font_size': self.app.font_size_var.get(),
                'font_style': self.app.font_style_var.get(),
                'offset_x': self.app.offset_x_var.get(),
                'offset_y': self.app.offset_y_var.get(),
                'datetime_mode': mode,
                'datetime_format': datetime_format,
                'datetime_locale': self.app.datetime_locale_var.get() if hasattr(self.app, 'datetime_locale_var') else 'ISO (YYYY-MM-DD)',
                'background_enabled': self.app.background_enabled_var.get(),
                'background_color': self.app.bg_color_var.get()
            }
            self.app.config.set('overlays', overlays)
            self.rebuild_overlay_list()
            app_logger.info("Overlay changes applied")
    
    def reset_overlay_editor(self):
        """Reset editor to selected overlay's saved state"""
        if self.app.selected_overlay_index is not None:
            overlays = self.get_overlays_config()
            if 0 <= self.app.selected_overlay_index < len(overlays):
                self.load_overlay_into_editor(overlays[self.app.selected_overlay_index])
    
    def on_overlay_edit(self):
        """Handle overlay editor changes"""
        # Update preview with current editor values
        self.app.image_processor.update_overlay_preview()
        
        # Check if datetime section should be visible
        if hasattr(self.app, 'overlay_text'):
            text_content = self.app.overlay_text.get('1.0', 'end-1c')
            self.update_datetime_visibility('{DATETIME}' in text_content.upper())
    
    def on_datetime_mode_change(self):
        """Handle datetime format mode change"""
        mode = self.app.datetime_mode_var.get()
        
        # Show/hide custom format input based on mode
        if hasattr(self.app, 'datetime_custom_frame'):
            if mode == 'custom':
                # Show custom format input
                self.app.datetime_custom_frame.pack(fill='x', pady=(0, SPACING['element_gap']),
                                                   after=self.app.datetime_section_frame.winfo_children()[2])
                self.app.datetime_custom_entry.config(state='normal')
            else:
                # Hide custom format input
                self.app.datetime_custom_frame.pack_forget()
        
        # Update preview with new format
        self.update_datetime_preview()
        
        # Refresh overlay preview
        self.on_overlay_edit()
    
    def on_background_toggle(self):
        """Handle background rectangle toggle"""
        is_enabled = self.app.background_enabled_var.get()
        self.on_overlay_edit()
    
    def update_datetime_visibility(self, show):
        """Show/hide datetime format controls based on token presence"""
        from .theme import SPACING
        
        if not hasattr(self.app, 'datetime_section_frame'):
            return
        
        if show:
            try:
                self.app.datetime_section_frame.pack_info()
            except:
                self.app.datetime_section_frame.pack(fill='x', 
                                                     pady=(SPACING['section_gap'], 0),
                                                     before=self.app.appearance_section_frame)
        else:
            try:
                self.app.datetime_section_frame.pack_forget()
            except:
                pass
    
    def update_datetime_preview(self):
        """Update the datetime format preview (triggers overlay preview update)"""
        # Just trigger the overlay preview update - no need for a separate text preview
        # The image preview will show the actual formatted datetime
        self.on_overlay_edit()
    
    def insert_token(self):
        """Insert selected token into overlay text"""
        try:
            from .overlays.constants import TOKENS
            
            # Get selected token from combobox display text
            if not hasattr(self.app, 'token_display_var'):
                app_logger.warning("Token display variable not found")
                return
            
            selected_label = self.app.token_display_var.get()
            if not selected_label:
                messagebox.showwarning("No Token Selected", "Please select a token from the dropdown first.")
                return
            
            # Find matching token value
            token_value = None
            for label, value in TOKENS:
                if label == selected_label:
                    token_value = value
                    break
            
            if token_value and hasattr(self.app, 'overlay_text'):
                # Insert at cursor position in text widget
                self.app.overlay_text.insert('insert', token_value)
                self.app.overlay_text.focus_set()
                
                # Trigger overlay update (which also handles datetime section visibility)
                self.app.on_overlay_edit()
                app_logger.debug(f"Inserted token: {token_value}")
            else:
                messagebox.showerror("Error", "Could not insert token. Please try again.")
                
        except Exception as e:
            app_logger.error(f"Error inserting token: {e}")
            messagebox.showerror("Error", f"Failed to insert token: {str(e)}")
    
    def choose_custom_color(self):
        """Color picker for text color - REMOVED, using presets only"""
        pass
    
    def choose_custom_bg_color(self):
        """Color picker for background - REMOVED, using presets only"""
        pass
