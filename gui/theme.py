"""
Centralized theme configuration for PFR Sentinel
Design inspired by PFRAstro Style Guide - Liquid Glass aesthetic
Uses Iris accent color and Sand gray scale with glass effects
"""
import tkinter as tk
import ttkbootstrap as ttk

# ===== COLOR PALETTE (PFRAstro Style Guide) =====
# Based on Radix Colors: Iris accent, Sand gray scale
COLORS = {
    # Backgrounds (Sand gray scale)
    'bg_primary': '#111110',        # --gray-1: Darkest background
    'bg_secondary': '#191918',      # --gray-2: Secondary background
    'bg_card': '#222221',           # --gray-3: Card/elevated surfaces
    'bg_input': '#2A2A28',          # --gray-4: Input fields
    'bg_input_disabled': '#1E1E1D', # --gray-2: Disabled inputs
    'bg_hover': '#313130',          # --gray-5: Hover states
    
    # Glass Effect Colors
    'glass_bg': 'rgba(34, 34, 33, 0.6)',           # 60% panel color
    'glass_border': 'rgba(91, 91, 214, 0.3)',     # 30% accent (iris)
    'glass_border_subtle': 'rgba(255, 255, 255, 0.1)',  # Subtle neutral
    
    # Borders & Separators (Sand scale)
    'border': '#3B3B39',            # --gray-6: Subtle borders
    'border_strong': '#4A4A47',     # --gray-7: Strong borders
    'separator': '#2A2A28',         # --gray-4: Divider lines
    
    # Text Colors (Sand scale)
    'text_primary': '#EEEEEC',      # --gray-12: Primary text
    'text_secondary': '#A1A09A',    # --gray-11: Secondary text
    'text_disabled': '#706F6A',     # --gray-9: Disabled text
    'text_muted': '#63635E',        # --gray-8: Muted/hint text
    'accent_secondary_fg': '#FFFFFF', # White text on colored buttons
    
    # Accent Colors (Iris scale - purple/violet)
    'accent_1': '#13131E',          # --iris-1: Subtle background
    'accent_2': '#171625',          # --iris-2: Component background
    'accent_3': '#202248',          # --iris-3: Hovered component bg
    'accent_4': '#262A65',          # --iris-4: Active component bg
    'accent_5': '#303374',          # --iris-5: Subtle borders
    'accent_6': '#3D3E94',          # --iris-6: Borders, focus rings
    'accent_7': '#4A4AB8',          # --iris-7: Solid backgrounds
    'accent_8': '#5B5BD6',          # --iris-8: Hovered solid
    'accent_9': '#5B5BD6',          # --iris-9: Primary solid (buttons)
    'accent_10': '#6E6ADE',         # --iris-10: Hovered primary
    'accent_11': '#B1A9FF',         # --iris-11: Low contrast text
    'accent_12': '#E0DFFE',         # --iris-12: High contrast text
    
    # Primary action (lighter iris tone)
    'accent_primary': '#202248',         # --iris-3: Primary buttons
    'accent_primary_hover': '#262A65',   # --iris-4: Hover state
    
    # Secondary action (darker iris tone)
    'accent_secondary': '#171625',       # --iris-2: Secondary buttons
    'accent_secondary_hover': '#202248', # --iris-3: Hover state
    
    # Destructive action (Red scale)
    'accent_destructive': '#E5484D',     # --red-9
    'accent_destructive_hover': '#F2555A', # --red-10
    
    # Semantic/Status Colors (matching PFRAstro)
    'status_live': '#30A46C',            # --green-9: Live/Capturing
    'status_standby': '#3B9EFF',         # --blue-9: Standby/Idle
    'status_warning': '#FFB224',         # --amber-9: Warning
    'status_error': '#E5484D',           # --red-9: Error
    'status_offline': '#706F6A',         # --gray-9: Offline
    
    # Legacy aliases for compatibility
    'status_idle': '#706F6A',            # Gray - idle/no camera
    'status_capturing': '#30A46C',       # Green - actively capturing
    'status_connecting': '#FFB224',      # Amber - connecting/detecting
}

# ===== TYPOGRAPHY (PFRAstro - Space Grotesk inspired) =====
# Note: tkinter uses system fonts, we use Segoe UI as closest match on Windows
# For true Space Grotesk, would need custom font loading
FONTS = {
    'title': ('Segoe UI Semibold', 12),      # size="6" ~24px
    'heading': ('Segoe UI Semibold', 10),    # size="5" ~20px
    'body': ('Segoe UI', 9),                  # size="3" default body
    'body_bold': ('Segoe UI Semibold', 9),   # Emphasized values
    'small': ('Segoe UI', 8),                 # size="2" secondary
    'tiny': ('Segoe UI', 7),                  # size="1" captions
    'status': ('Segoe UI Semibold', 8),      # Status badges (uppercase)
}

# ===== SPACING (PFRAstro Scale) =====
# Based on 4px base unit: 4, 8, 12, 16, 24, 32, 40, 48, 64
SPACING = {
    'xs': 4,                 # --space-1
    'sm': 8,                 # --space-2
    'md': 12,                # --space-3
    'base': 16,              # --space-4 (default padding)
    'lg': 24,                # --space-5
    'xl': 32,                # --space-6
    'xxl': 40,               # --space-7
    
    # Semantic spacing
    'card_padding': 20,          # p="5" - Card content padding
    'card_margin_x': 12,         # Horizontal margin
    'card_margin_y': 8,          # Vertical margin
    'section_gap': 24,           # py between sections (--space-5)
    'row_gap': 12,               # gap="3" between rows
    'element_gap': 8,            # gap="2" between elements
    'button_gap': 12,            # gap="3" between buttons
}

# ===== LAYOUT =====
LAYOUT = {
    'label_width': 18,           # Fixed width for left-column labels
    'button_padding_x': 12,      # Horizontal padding for buttons (compact)
    'button_padding_y': 4,       # Vertical padding for buttons (compact)
    'button_padding_x_sm': 8,    # Small button horizontal padding
    'button_padding_y_sm': 2,    # Small button vertical padding
    'border_radius': 8,          # For widgets that support it
}

# ===== GLASS EFFECT HELPERS =====
def get_glass_style():
    """Get glass effect style properties for manual application"""
    return {
        'bg': COLORS['bg_card'],
        'border_color': COLORS['border'],
        'highlight_thickness': 1,
    }


def create_gradient_background(canvas, width, height):
    """
    Create a gradient background on a canvas (PFRAstro radial gradient style)
    Gradient: Dark center fading to iris-tinted edges
    
    Args:
        canvas: tk.Canvas widget
        width: Width of gradient
        height: Height of gradient
    """
    # Create vertical gradient from dark to slightly purple-tinted
    steps = 100
    for i in range(steps):
        # Blend from bg_primary to a subtle iris tint
        ratio = i / steps
        # Start color: #111110 (17, 17, 16)
        # End color: subtle iris tint #1a1a24 (26, 26, 36)
        r = int(17 + (26 - 17) * ratio)
        g = int(17 + (26 - 17) * ratio)
        b = int(16 + (36 - 16) * ratio)
        color = f'#{r:02x}{g:02x}{b:02x}'
        
        y0 = int(height * i / steps)
        y1 = int(height * (i + 1) / steps)
        canvas.create_rectangle(0, y0, width, y1, fill=color, outline=color)


class GradientFrame(tk.Canvas):
    """
    A Frame-like widget with gradient background (PFRAstro style)
    Use as a replacement for tk.Frame when gradient background is desired
    """
    def __init__(self, parent, **kwargs):
        super().__init__(parent, highlightthickness=0, **kwargs)
        self.bind('<Configure>', self._draw_gradient)
        
    def _draw_gradient(self, event=None):
        """Draw the gradient background"""
        self.delete('gradient')
        width = self.winfo_width()
        height = self.winfo_height()
        
        if width <= 1 or height <= 1:
            return
            
        steps = 50  # Fewer steps for performance
        for i in range(steps):
            ratio = i / steps
            # Vertical gradient: dark top to subtle iris-tinted bottom
            r = int(17 + (22 - 17) * ratio)  # 11 -> 16
            g = int(17 + (22 - 17) * ratio)  # 11 -> 16
            b = int(16 + (32 - 16) * ratio)  # 10 -> 20 (more blue/purple)
            color = f'#{r:02x}{g:02x}{b:02x}'
            
            y0 = int(height * i / steps)
            y1 = int(height * (i + 1) / steps) + 1
            self.create_rectangle(0, y0, width, y1, fill=color, outline=color, tags='gradient')
        
        # Lower gradient below all other items
        self.tag_lower('gradient')


def configure_dark_input_styles():
    """
    Configure ttk styles for dark theme inputs
    Uses PFRAstro color palette with Sand gray scale
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
             fieldbackground=[('disabled', COLORS['bg_input_disabled']),
                             ('focus', COLORS['bg_hover'])],
             foreground=[('disabled', COLORS['text_disabled'])],
             bordercolor=[('focus', COLORS['accent_6'])])
    
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
             fieldbackground=[('readonly', COLORS['bg_input']), 
                             ('disabled', COLORS['bg_input_disabled']),
                             ('focus', COLORS['bg_hover'])],
             foreground=[('disabled', COLORS['text_disabled'])],
             selectbackground=[('readonly', COLORS['accent_primary'])],
             selectforeground=[('readonly', COLORS['text_primary'])],
             bordercolor=[('focus', COLORS['accent_6'])])
    
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
             fieldbackground=[('disabled', COLORS['bg_input_disabled']),
                             ('focus', COLORS['bg_hover'])],
             foreground=[('disabled', COLORS['text_disabled'])],
             bordercolor=[('focus', COLORS['accent_6'])])
    
    # Status Badge styles
    style.configure('Status.TLabel',
                   font=FONTS['status'],
                   padding=(8, 4))
    
    # Custom Toolbutton style (PFRAstro Iris colors)
    style.configure('Iris.Toolbutton',
                   font=FONTS['body'],
                   padding=(8, 4),
                   background=COLORS['bg_input'],
                   foreground=COLORS['text_secondary'],
                   borderwidth=1,
                   relief='flat')
    
    style.map('Iris.Toolbutton',
             background=[('selected', COLORS['accent_primary']),
                        ('active', COLORS['bg_hover']),
                        ('!selected', COLORS['bg_input'])],
             foreground=[('selected', COLORS['text_primary']),
                        ('!selected', COLORS['text_secondary'])])
    
    # Custom Toggle style (PFRAstro)
    style.configure('Iris.Toggle',
                   font=FONTS['body'],
                   padding=(6, 3),
                   background=COLORS['bg_input'],
                   foreground=COLORS['text_secondary'])
    
    style.map('Iris.Toggle',
             background=[('selected', COLORS['accent_primary']),
                        ('active', COLORS['bg_hover'])],
             foreground=[('selected', COLORS['text_primary'])])


def create_primary_button(parent, text, command, compact=False):
    """Create primary action button - solid Iris purple (PFRAstro style)
    
    Args:
        parent: Parent widget
        text: Button text
        command: Click callback
        compact: If True, use smaller padding
    """
    px = LAYOUT['button_padding_x_sm'] if compact else LAYOUT['button_padding_x']
    py = LAYOUT['button_padding_y_sm'] if compact else LAYOUT['button_padding_y']
    
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body_bold'],
        relief='flat',
        padx=px,
        pady=py,
        cursor='hand2',
        borderwidth=0,
    )
    btn.config(
        bg=COLORS['accent_primary'],
        fg=COLORS['text_primary'],
        activebackground=COLORS['accent_primary_hover'],
        activeforeground=COLORS['text_primary']
    )
    
    # Add hover effects
    def on_enter(e):
        btn.config(bg=COLORS['accent_primary_hover'])
    def on_leave(e):
        btn.config(bg=COLORS['accent_primary'])
    btn.bind('<Enter>', on_enter)
    btn.bind('<Leave>', on_leave)
    
    return btn


def create_destructive_button(parent, text, command, compact=False):
    """Create destructive action button - Red (PFRAstro error color)"""
    px = LAYOUT['button_padding_x_sm'] if compact else LAYOUT['button_padding_x']
    py = LAYOUT['button_padding_y_sm'] if compact else LAYOUT['button_padding_y']
    
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body_bold'],
        relief='flat',
        padx=px,
        pady=py,
        cursor='hand2',
        borderwidth=0,
    )
    btn.config(
        bg=COLORS['accent_destructive'],
        fg=COLORS['text_primary'],
        activebackground=COLORS['accent_destructive_hover'],
        activeforeground=COLORS['text_primary']
    )
    
    # Add hover effects
    def on_enter(e):
        btn.config(bg=COLORS['accent_destructive_hover'])
    def on_leave(e):
        btn.config(bg=COLORS['accent_destructive'])
    btn.bind('<Enter>', on_enter)
    btn.bind('<Leave>', on_leave)
    
    return btn


def create_secondary_button(parent, text, command, compact=False):
    """Create secondary button - softer Iris purple (PFRAstro soft variant)"""
    px = LAYOUT['button_padding_x_sm'] if compact else LAYOUT['button_padding_x']
    py = LAYOUT['button_padding_y_sm'] if compact else LAYOUT['button_padding_y']
    
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body'],
        relief='flat',
        padx=px,
        pady=py,
        cursor='hand2',
        borderwidth=0,
    )
    btn.config(
        bg=COLORS['accent_secondary'],
        fg=COLORS['accent_secondary_fg'],
        activebackground=COLORS['accent_secondary_hover'],
        activeforeground=COLORS['accent_secondary_fg']
    )
    
    # Add hover effects
    def on_enter(e):
        btn.config(bg=COLORS['accent_secondary_hover'])
    def on_leave(e):
        btn.config(bg=COLORS['accent_secondary'])
    btn.bind('<Enter>', on_enter)
    btn.bind('<Leave>', on_leave)
    
    return btn


def create_outline_button(parent, text, command, compact=False):
    """Create outline/ghost button (PFRAstro outline variant)"""
    px = LAYOUT['button_padding_x_sm'] if compact else LAYOUT['button_padding_x']
    py = LAYOUT['button_padding_y_sm'] if compact else LAYOUT['button_padding_y']
    
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONTS['body'],
        relief='flat',
        padx=px,
        pady=py,
        cursor='hand2',
        borderwidth=1,
        highlightthickness=1,
    )
    btn.config(
        bg=COLORS['bg_card'],
        fg=COLORS['accent_11'],  # Light iris text
        activebackground=COLORS['accent_3'],
        activeforeground=COLORS['accent_12'],
        highlightbackground=COLORS['accent_6'],
        highlightcolor=COLORS['accent_8'],
    )
    
    # Add hover effects
    def on_enter(e):
        btn.config(bg=COLORS['accent_2'], fg=COLORS['accent_12'])
    def on_leave(e):
        btn.config(bg=COLORS['bg_card'], fg=COLORS['accent_11'])
    btn.bind('<Enter>', on_enter)
    btn.bind('<Leave>', on_leave)
    
    return btn


def create_card(parent, title=None, interactive=False):
    """
    Create a styled card container with glass effect (PFRAstro style)
    
    Args:
        parent: Parent widget
        title: Optional title for the card
        interactive: If True, add hover effects (PFRAstro card pattern)
    
    Returns:
        content_frame: The frame where card content should be added
    """
    # Card container with subtle border (glass effect approximation)
    card = tk.Frame(parent, bg=COLORS['bg_card'],
                   highlightbackground=COLORS['border'],
                   highlightthickness=1)
    
    # Add hover effects for interactive cards (PFRAstro style)
    if interactive:
        def on_enter(e):
            card.config(highlightbackground=COLORS['accent_6'])
        def on_leave(e):
            card.config(highlightbackground=COLORS['border'])
        card.bind('<Enter>', on_enter)
        card.bind('<Leave>', on_leave)
    
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
        
        # Separator line with accent tint
        tk.Frame(title_frame, bg=COLORS['border'], 
                height=1).pack(fill='x', pady=(SPACING['sm'], 0))
    
    return content


def create_glass_card(parent, title=None):
    """
    Create an elevated card with glass aesthetic (PFRAstro liquid glass style)
    Uses slightly different background for visual hierarchy
    """
    # Elevated card with stronger border
    card = tk.Frame(parent, bg=COLORS['bg_secondary'],
                   highlightbackground=COLORS['border_strong'],
                   highlightthickness=1)
    
    # Content frame with padding
    content = tk.Frame(card, bg=COLORS['bg_secondary'])
    content.pack(fill='both', expand=True, 
                padx=SPACING['card_padding'], 
                pady=SPACING['card_padding'])
    
    if title:
        title_frame = tk.Frame(content, bg=COLORS['bg_secondary'])
        title_frame.pack(fill='x', pady=(0, SPACING['row_gap']))
        
        # Title with accent color
        tk.Label(title_frame, text=title,
                font=FONTS['title'],
                bg=COLORS['bg_secondary'], 
                fg=COLORS['accent_11']).pack(anchor='w')
        
        # Accent-tinted separator
        tk.Frame(title_frame, bg=COLORS['accent_5'], 
                height=1).pack(fill='x', pady=(SPACING['sm'], 0))
    
    return content


def create_status_badge(parent, text, status='standby'):
    """
    Create a status badge (PFRAstro style - uppercase with letter spacing)
    
    Args:
        parent: Parent widget
        text: Badge text
        status: One of 'live', 'standby', 'warning', 'error', 'offline'
    
    Returns:
        Label widget
    """
    status_colors = {
        'live': COLORS['status_live'],
        'capturing': COLORS['status_live'],
        'standby': COLORS['status_standby'],
        'idle': COLORS['status_standby'],
        'warning': COLORS['status_warning'],
        'connecting': COLORS['status_warning'],
        'error': COLORS['status_error'],
        'offline': COLORS['status_offline'],
    }
    
    bg_color = status_colors.get(status, COLORS['status_standby'])
    
    badge = tk.Label(
        parent,
        text=text.upper(),  # Uppercase for status badges
        font=FONTS['status'],
        bg=bg_color,
        fg=COLORS['text_primary'],
        padx=8,
        pady=2,
    )
    
    return badge


def create_gradient_stripe(parent, height=4):
    """
    Create a horizontal gradient accent stripe (PFRAstro style).
    Bell curve gradient: dark -> iris purple -> dark
    
    Args:
        parent: Parent widget
        height: Height of the stripe in pixels (default 4)
    
    Returns:
        Canvas widget containing the gradient
    """
    gradient_canvas = tk.Canvas(parent, height=height, highlightthickness=0, bg=COLORS['bg_primary'])
    gradient_canvas.pack(fill='x')
    
    def draw_gradient(event=None):
        """Draw horizontal gradient stripe"""
        gradient_canvas.delete('all')
        width = gradient_canvas.winfo_width()
        if width <= 1:
            return
        
        steps = 50
        for i in range(steps):
            ratio = i / steps
            # Bell curve: strongest purple in middle
            bell = 1 - abs(2 * ratio - 1)  # 0 -> 1 -> 0
            r = int(17 + (91 - 17) * bell)   # 11 -> 5b -> 11
            g = int(17 + (91 - 17) * bell)   # 11 -> 5b -> 11
            b = int(16 + (214 - 16) * bell)  # 10 -> d6 -> 10
            color = f'#{r:02x}{g:02x}{b:02x}'
            
            x0 = int(width * i / steps)
            x1 = int(width * (i + 1) / steps) + 1
            gradient_canvas.create_rectangle(x0, 0, x1, height, fill=color, outline=color)
    
    gradient_canvas.bind('<Configure>', draw_gradient)
    return gradient_canvas


def create_scrollable_frame(parent):
    """
    Create a scrollable frame with vertical scrollbar for tab content.
    
    Args:
        parent: Parent widget (typically the tab frame)
    
    Returns:
        tuple: (container_frame, scrollable_content_frame)
            - container_frame: The outer frame to pack into parent
            - scrollable_content_frame: The inner frame where content should be added
    """
    # Container frame
    container = ttk.Frame(parent)
    
    # Create canvas and scrollbar
    canvas = tk.Canvas(container, bg=COLORS['bg_primary'], highlightthickness=0)
    scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview, bootstyle="round")
    
    # Create scrollable frame inside canvas
    scrollable_frame = ttk.Frame(canvas)
    
    # Configure scrolling
    def on_frame_configure(event=None):
        canvas.configure(scrollregion=canvas.bbox('all'))
    
    def on_canvas_configure(event):
        # When canvas is resized, make the inner frame match its width
        canvas_width = event.width
        canvas.itemconfig(canvas_window, width=canvas_width)
    
    scrollable_frame.bind('<Configure>', on_frame_configure)
    canvas.bind('<Configure>', on_canvas_configure)
    
    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # Pack canvas and scrollbar
    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')
    
    # Enable mousewheel scrolling
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
    
    def bind_mousewheel(event):
        canvas.bind_all('<MouseWheel>', on_mousewheel)
    
    def unbind_mousewheel(event):
        canvas.unbind_all('<MouseWheel>')
    
    # Bind mousewheel only when mouse is over this canvas
    canvas.bind('<Enter>', bind_mousewheel)
    canvas.bind('<Leave>', unbind_mousewheel)
    
    return container, scrollable_frame


def create_gradient_scrollable_frame(parent):
    """
    Create a scrollable frame with gradient accent stripe at top (PFRAstro style).
    Since tkinter frames can't be transparent, we add a visible gradient banner.
    
    Args:
        parent: Parent widget (typically the tab frame)
    
    Returns:
        tuple: (container_frame, scrollable_content_frame)
    """
    # Container frame
    container = ttk.Frame(parent)
    
    # Gradient accent stripe at top (visible gradient banner)
    gradient_height = 4
    gradient_canvas = tk.Canvas(container, height=gradient_height, highlightthickness=0, bg=COLORS['bg_primary'])
    gradient_canvas.pack(fill='x')
    
    def draw_gradient_stripe(event=None):
        """Draw horizontal gradient stripe"""
        gradient_canvas.delete('all')
        width = gradient_canvas.winfo_width()
        if width <= 1:
            return
        
        steps = 50
        for i in range(steps):
            ratio = i / steps
            # Horizontal gradient: dark -> iris purple -> dark
            # Bell curve effect: strongest in middle
            bell = 1 - abs(2 * ratio - 1)  # 0 -> 1 -> 0
            r = int(17 + (91 - 17) * bell)   # 11 -> 5b -> 11
            g = int(17 + (91 - 17) * bell)   # 11 -> 5b -> 11
            b = int(16 + (214 - 16) * bell)  # 10 -> d6 -> 10
            color = f'#{r:02x}{g:02x}{b:02x}'
            
            x0 = int(width * i / steps)
            x1 = int(width * (i + 1) / steps) + 1
            gradient_canvas.create_rectangle(x0, 0, x1, gradient_height, fill=color, outline=color)
    
    gradient_canvas.bind('<Configure>', draw_gradient_stripe)
    
    # Create canvas and scrollbar for content
    canvas = tk.Canvas(container, highlightthickness=0, bg=COLORS['bg_primary'])
    scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview, bootstyle="round")
    
    # Create scrollable frame inside canvas
    scrollable_frame = tk.Frame(canvas, bg=COLORS['bg_primary'])
    
    def on_frame_configure(event=None):
        canvas.configure(scrollregion=canvas.bbox('all'))
    
    def on_canvas_configure(event):
        canvas_width = event.width
        canvas.itemconfig(canvas_window, width=canvas_width)
    
    scrollable_frame.bind('<Configure>', on_frame_configure)
    canvas.bind('<Configure>', on_canvas_configure)
    
    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # Pack canvas and scrollbar
    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')
    
    # Enable mousewheel scrolling
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
    
    def bind_mousewheel(event):
        canvas.bind_all('<MouseWheel>', on_mousewheel)
    
    def unbind_mousewheel(event):
        canvas.unbind_all('<MouseWheel>')
    
    canvas.bind('<Enter>', bind_mousewheel)
    canvas.bind('<Leave>', unbind_mousewheel)
    
    return container, scrollable_frame
    
    canvas.bind('<Enter>', bind_mousewheel)
    canvas.bind('<Leave>', unbind_mousewheel)
    
    # Initial gradient draw after widget is mapped
    canvas.after(100, draw_gradient)
    
    return container, scrollable_frame


class ToggleButtonGroup(tk.Frame):
    """
    A group of toggle buttons (PFRAstro styled radio button alternative)
    Used for Output Mode selector, Units toggle, etc.
    """
    def __init__(self, parent, options, variable, command=None, bg=None):
        """
        Create a toggle button group.
        
        Args:
            parent: Parent widget
            options: List of (value, label) tuples
            variable: tk.StringVar to bind to
            command: Optional callback when selection changes
            bg: Background color (defaults to card background)
        """
        bg_color = bg or COLORS['bg_card']
        super().__init__(parent, bg=bg_color)
        
        self.variable = variable
        self.command = command
        self.buttons = {}
        
        for value, label in options:
            btn = tk.Button(
                self,
                text=label,
                font=FONTS['body'],
                relief='flat',
                padx=LAYOUT['button_padding_x_sm'],
                pady=LAYOUT['button_padding_y_sm'],
                cursor='hand2',
                borderwidth=0,
                command=lambda v=value: self._select(v)
            )
            btn.pack(side='left', padx=(0, 2))
            self.buttons[value] = btn
            
            # Bind hover effects
            btn.bind('<Enter>', lambda e, b=btn, v=value: self._on_enter(b, v))
            btn.bind('<Leave>', lambda e, b=btn, v=value: self._on_leave(b, v))
        
        # Set initial state
        self._update_styles()
        
        # Track variable changes
        self.variable.trace_add('write', lambda *args: self._update_styles())
    
    def _select(self, value):
        """Handle button selection"""
        self.variable.set(value)
        if self.command:
            self.command()
    
    def _update_styles(self):
        """Update button styles based on current selection"""
        current = self.variable.get()
        for value, btn in self.buttons.items():
            if value == current:
                btn.config(
                    bg=COLORS['accent_primary'],
                    fg=COLORS['text_primary'],
                    activebackground=COLORS['accent_primary_hover'],
                    activeforeground=COLORS['text_primary']
                )
            else:
                btn.config(
                    bg=COLORS['bg_input'],
                    fg=COLORS['text_secondary'],
                    activebackground=COLORS['bg_hover'],
                    activeforeground=COLORS['text_primary']
                )
    
    def _on_enter(self, btn, value):
        """Handle mouse enter"""
        if value != self.variable.get():
            btn.config(bg=COLORS['bg_hover'])
    
    def _on_leave(self, btn, value):
        """Handle mouse leave"""
        if value != self.variable.get():
            btn.config(bg=COLORS['bg_input'])


class ToggleSwitch(tk.Frame):
    """
    A custom toggle switch widget (PFRAstro styled checkbutton alternative)
    Provides a visual on/off toggle with Iris accent color
    """
    def __init__(self, parent, text, variable, command=None, bg=None):
        """
        Create a toggle switch.
        
        Args:
            parent: Parent widget
            text: Label text for the toggle
            variable: tk.BooleanVar to bind to
            command: Optional callback when toggled
            bg: Background color (defaults to card background)
        """
        bg_color = bg or COLORS['bg_card']
        super().__init__(parent, bg=bg_color)
        
        self.variable = variable
        self.command = command
        self.bg_color = bg_color
        
        # Toggle track (the background pill)
        self.track = tk.Canvas(
            self,
            width=36,
            height=20,
            bg=bg_color,
            highlightthickness=0,
            cursor='hand2'
        )
        self.track.pack(side='left', padx=(0, 8))
        
        # Draw initial state
        self._draw_toggle()
        
        # Label
        self.label = tk.Label(
            self,
            text=text,
            font=FONTS['body'],
            bg=bg_color,
            fg=COLORS['text_secondary'],
            cursor='hand2'
        )
        self.label.pack(side='left')
        
        # Bind click events
        self.track.bind('<Button-1>', self._toggle)
        self.label.bind('<Button-1>', self._toggle)
        
        # Track variable changes
        self.variable.trace_add('write', lambda *args: self._draw_toggle())
    
    def _toggle(self, event=None):
        """Toggle the switch"""
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
    
    def _draw_toggle(self):
        """Draw the toggle switch based on current state"""
        self.track.delete('all')
        
        is_on = self.variable.get()
        
        # Track color
        track_color = COLORS['accent_primary'] if is_on else COLORS['bg_input']
        
        # Draw rounded track
        self.track.create_oval(0, 0, 20, 20, fill=track_color, outline=track_color)
        self.track.create_oval(16, 0, 36, 20, fill=track_color, outline=track_color)
        self.track.create_rectangle(10, 0, 26, 20, fill=track_color, outline=track_color)
        
        # Draw thumb (circle)
        thumb_x = 22 if is_on else 4
        self.track.create_oval(
            thumb_x, 2, thumb_x + 16, 18,
            fill=COLORS['text_primary'],
            outline=COLORS['text_primary']
        )
