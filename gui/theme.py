"""
Centralized theme configuration for ASIOverlayWatchDog
All UI components should import from this module for consistent styling
"""
import ttkbootstrap as ttk

# ===== COLOR PALETTE =====
COLORS = {
    # Backgrounds
    'bg_primary': '#1E1E1E',        # Main background
    'bg_card': '#2A2D2E',           # Card/section background
    'bg_input': '#2A2D2E',          # Input field background
    'bg_input_disabled': '#252728', # Disabled input background
    
    # Borders & Separators
    'border': '#3A3D3F',            # Subtle border color
    'separator': '#2A2A2A',         # Divider lines
    
    # Text Colors
    'text_primary': '#FFFFFF',      # Main text (bright white)
    'text_secondary': '#A0A0A0',    # Labels (muted grey)
    'text_disabled': '#888888',     # Disabled text
    'text_muted': '#666666',        # Hints/helper text
    'accent_secondary_fg': '#FFFFFF', # Secondary accent text (white)
    
    # Accent Colors
    'accent_primary': '#0D92B8',         # Primary action (teal)
    'accent_primary_hover': '#12A4CC',   # Primary hover
    'accent_secondary': '#5B3EAF',         # Secondary action (Nebula Purple)
    'accent_secondary_hover': '#6A4BC4',   # Secondary hover
    'accent_destructive': '#B91C1C',     # Destructive action (red)
    'accent_destructive_hover': '#DC2626', # Destructive hover
    
    # Status Indicator Colors
    'status_idle': '#666666',            # Grey - idle/no camera
    'status_capturing': '#22C55E',       # Green - actively capturing
    'status_connecting': '#FFD93D',      # Yellow - connecting/detecting
    'status_error': '#FF4C4C',           # Red - error state
}

# ===== TYPOGRAPHY =====
FONTS = {
    'title': ('Segoe UI', 11, 'bold'),        # Section titles
    'heading': ('Segoe UI', 10, 'bold'),      # Subsection headings
    'body': ('Segoe UI', 9),                  # Normal text, labels
    'body_bold': ('Segoe UI', 9, 'bold'),     # Emphasized values
    'small': ('Segoe UI', 8),                 # Small text
    'tiny': ('Segoe UI', 7),                  # Hints, tokens
}

# ===== SPACING =====
SPACING = {
    'card_padding': 16,          # Padding inside cards
    'card_margin_x': 16,         # Left/right margin for cards
    'card_margin_y': 12,         # Top/bottom margin for main container
    'section_gap': 20,           # Gap between major sections/cards
    'row_gap': 12,               # Gap between rows within a section
    'element_gap': 8,            # Gap between small elements
    'button_gap': 10,            # Gap between buttons
}

# ===== LAYOUT =====
LAYOUT = {
    'label_width': 18,           # Fixed width for left-column labels
    'button_padding_x': 20,      # Horizontal padding for primary buttons
    'button_padding_y': 8,       # Vertical padding for primary buttons
}


def configure_dark_input_styles():
    """
    Configure ttk styles for dark theme inputs
    Call this once during application initialization
    """
    style = ttk.Style()
    
    # Dark Entry style
    style.configure('Dark.TEntry',
                   fieldbackground=COLORS['bg_input'],
                   foreground=COLORS['text_primary'],
                   bordercolor=COLORS['border'],
                   darkcolor=COLORS['bg_input'],
                   lightcolor=COLORS['bg_input'],
                   insertcolor=COLORS['text_primary'],
                   borderwidth=1,
                   relief='flat')
    
    style.map('Dark.TEntry',
             fieldbackground=[('disabled', COLORS['bg_input_disabled'])],
             foreground=[('disabled', COLORS['text_disabled'])])
    
    # Dark Combobox style
    style.configure('Dark.TCombobox',
                   fieldbackground=COLORS['bg_input'],
                   background=COLORS['bg_input'],
                   foreground=COLORS['text_primary'],
                   bordercolor=COLORS['border'],
                   arrowcolor=COLORS['text_secondary'],
                   darkcolor=COLORS['bg_input'],
                   lightcolor=COLORS['bg_input'],
                   borderwidth=1,
                   arrowsize=14,
                   padding=6,
                   relief='flat')
    
    style.map('Dark.TCombobox',
             fieldbackground=[('readonly', COLORS['bg_input']), ('disabled', COLORS['bg_input_disabled'])],
             foreground=[('disabled', COLORS['text_disabled'])],
             selectbackground=[('readonly', COLORS['accent_primary'])],
             selectforeground=[('readonly', COLORS['text_primary'])])
    
    # Dark Spinbox style
    style.configure('Dark.TSpinbox',
                   fieldbackground=COLORS['bg_input'],
                   foreground=COLORS['text_primary'],
                   bordercolor=COLORS['border'],
                   arrowcolor=COLORS['text_secondary'],
                   darkcolor=COLORS['bg_input'],
                   lightcolor=COLORS['bg_input'],
                   borderwidth=1,
                   arrowsize=14,
                   padding=6,
                   relief='flat')
    
    style.map('Dark.TSpinbox',
             fieldbackground=[('disabled', COLORS['bg_input_disabled'])],
             foreground=[('disabled', COLORS['text_disabled'])])


def create_primary_button(parent, text, command):
    """Create primary action button with consistent styling"""
    import tkinter as tk
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body'],
        relief='flat',
        padx=LAYOUT['button_padding_x'],
        pady=LAYOUT['button_padding_y'],
        cursor='hand2',
        borderwidth=0,
        height=1,
    )
    # Configure colors after creation to override theme
    btn.config(
        bg=COLORS['accent_primary'],
        fg=COLORS['text_primary'],
        activebackground=COLORS['accent_primary_hover'],
        activeforeground=COLORS['text_primary']
    )
    return btn


def create_destructive_button(parent, text, command):
    """Create destructive action button with consistent styling"""
    import tkinter as tk
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body_bold'],
        relief='flat',
        padx=LAYOUT['button_padding_x'],
        pady=LAYOUT['button_padding_y'],
        cursor='hand2',
        borderwidth=0,
        height=1,
    )
    # Configure colors after creation to override theme
    btn.config(
        bg=COLORS['accent_destructive'],
        fg=COLORS['text_primary'],
        activebackground=COLORS['accent_destructive_hover'],
        activeforeground=COLORS['text_primary']
    )
    return btn


def create_secondary_button(parent, text, command):
    """Create secondary filled button with consistent styling"""
    import tkinter as tk
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body'],  # same size/weight as primary
        relief='flat',
        padx=LAYOUT['button_padding_x'],
        pady=LAYOUT['button_padding_y'],
        cursor='hand2',
        borderwidth=0,
        height=1,
    )
    # Configure colors after creation to override theme
    btn.config(
        bg=COLORS['accent_secondary'],
        fg=COLORS['accent_secondary_fg'],
        activebackground=COLORS['accent_secondary_hover'],
        activeforeground=COLORS['accent_secondary_fg']
    )
    return btn


def create_card(parent, title=None):
    """
    Create a styled card container
    
    Args:
        parent: Parent widget
        title: Optional title for the card
    
    Returns:
        content_frame: The frame where card content should be added
    """
    import tkinter as tk
    
    # Card container with border
    card = tk.Frame(parent, bg=COLORS['bg_card'],
                   highlightbackground=COLORS['border'],
                   highlightthickness=1)
    
    # Content frame with padding
    content = tk.Frame(card, bg=COLORS['bg_card'])
    content.pack(fill='both', expand=True, 
                padx=SPACING['card_padding'], 
                pady=SPACING['card_padding'])
    
    # Optional title with separator
    if title:
        title_frame = tk.Frame(content, bg=COLORS['bg_card'])
        title_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        tk.Label(title_frame, text=title,
                font=FONTS['title'],
                bg=COLORS['bg_card'], 
                fg=COLORS['text_primary']).pack(anchor='w')
        
        # Separator line
        tk.Frame(title_frame, bg=COLORS['separator'], 
                height=1).pack(fill='x', pady=(8, 0))
    
    return content
