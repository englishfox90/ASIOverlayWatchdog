"""
PFRAstro Design Tokens
Based on PFRAstro Style Guide - Dark theme optimized for observatory use
Uses Iris (purple/violet) accent with Sand gray neutrals
"""

# =============================================================================
# COLOR PALETTE - PFRAstro / Radix Colors
# =============================================================================

class Colors:
    """PFRAstro color palette - Iris accent + Sand neutrals"""
    
    # === SAND GRAY SCALE (Neutrals) ===
    gray_1 = "#111110"   # Darkest - App background
    gray_2 = "#191918"   # Secondary background
    gray_3 = "#222221"   # Card/elevated surfaces
    gray_4 = "#2A2A28"   # Input fields, subtle borders
    gray_5 = "#313130"   # Hover states
    gray_6 = "#3B3B39"   # Subtle borders
    gray_7 = "#4A4A47"   # Strong borders
    gray_8 = "#63635E"   # Muted text, placeholders
    gray_9 = "#706F6A"   # Disabled text
    gray_10 = "#8B8B85"  # Secondary icons
    gray_11 = "#A1A09A"  # Secondary text
    gray_12 = "#EEEEEC"  # Primary text
    
    # === IRIS SCALE (Purple/Violet Accent) ===
    iris_1 = "#13131E"   # Subtle tinted background
    iris_2 = "#171625"   # Component background
    iris_3 = "#202248"   # Hovered component background
    iris_4 = "#262A65"   # Active/pressed component
    iris_5 = "#303374"   # Subtle accent borders
    iris_6 = "#3D3E94"   # Borders, focus rings
    iris_7 = "#4A4AB8"   # Solid accent backgrounds
    iris_8 = "#5B5BD6"   # Hovered solid accent
    iris_9 = "#5B5BD6"   # Primary solid (main buttons)
    iris_10 = "#6E6ADE"  # Hovered primary buttons
    iris_11 = "#B1A9FF"  # Low contrast accent text
    iris_12 = "#E0DFFE"  # High contrast accent text
    
    # === SEMANTIC ALIASES ===
    # Backgrounds
    bg_app = gray_1
    bg_surface = gray_2
    bg_card = gray_3
    bg_input = gray_4
    bg_hover = gray_5
    bg_elevated = gray_3
    
    # Text
    text_primary = gray_12
    text_secondary = gray_11
    text_muted = gray_8
    text_disabled = gray_9
    text_on_accent = "#FFFFFF"
    
    # Borders
    border_subtle = gray_6
    border_default = gray_7
    border_focus = iris_6
    
    # Accent (Primary actions)
    accent_subtle = iris_3
    accent_default = iris_9
    accent_hover = iris_10
    accent_active = iris_4
    accent_text = iris_11
    
    # === STATUS COLORS ===
    # Success (Green)
    success_bg = "#132D21"
    success_default = "#30A46C"
    success_text = "#3DD68C"
    
    # Warning (Amber)
    warning_bg = "#2D2305"
    warning_default = "#FFB224"
    warning_text = "#FFD166"
    
    # Error/Danger (Red)
    error_bg = "#2D1313"
    error_default = "#E5484D"
    error_hover = "#F2555A"
    error_text = "#FF6B6B"
    
    # Info (Blue)
    info_bg = "#0D1F2D"
    info_default = "#3B9EFF"
    info_text = "#70B8FF"
    
    # === APPLICATION STATUS ===
    status_live = success_default      # Green - actively capturing
    status_idle = gray_9               # Gray - stopped/not running
    status_connecting = warning_default # Amber - connecting/detecting
    status_error = error_default       # Red - error state
    status_success = success_default   # Green - success state
    status_offline = gray_8            # Dark gray - offline


# =============================================================================
# TYPOGRAPHY
# =============================================================================

class Typography:
    """Typography scale - Segoe UI (Windows) / SF Pro (macOS) fallback"""
    
    # Font families (Fluent uses system fonts)
    family_display = "Segoe UI Variable Display, Segoe UI, SF Pro Display, -apple-system, sans-serif"
    family_text = "Segoe UI Variable Text, Segoe UI, SF Pro Text, -apple-system, sans-serif"
    family_mono = "Cascadia Code, Consolas, SF Mono, monospace"
    
    # Font sizes (in pixels)
    size_display = 32    # Large titles
    size_title = 20      # Section titles
    size_subtitle = 16   # Card headers
    size_body = 14       # Body text (default)
    size_body_strong = 14
    size_caption = 12    # Secondary text
    size_small = 11      # Badges, chips
    
    # Font weights
    weight_regular = 400
    weight_semibold = 600
    weight_bold = 700
    
    # Line heights
    line_height_tight = 1.2
    line_height_normal = 1.4
    line_height_relaxed = 1.6


# =============================================================================
# SPACING
# =============================================================================

class Spacing:
    """Spacing scale based on 4px grid"""
    
    # Base scale
    xxs = 2    # 2px
    xs = 4     # 4px
    sm = 8     # 8px
    md = 12    # 12px
    base = 16  # 16px (default)
    lg = 24    # 24px
    xl = 32    # 32px
    xxl = 48   # 48px
    
    # Semantic spacing
    card_padding = 20       # Card content padding
    card_gap = 16           # Gap between cards
    section_gap = 24        # Gap between sections
    page_margin = 24        # Page margins
    element_gap = 8         # Small element spacing
    input_gap = 12          # Gap between form inputs


# =============================================================================
# LAYOUT
# =============================================================================

class Layout:
    """Layout constants"""
    
    # Border radius
    radius_sm = 4
    radius_md = 8
    radius_lg = 12
    radius_xl = 16
    radius_full = 9999
    
    # Minimum sizes
    min_button_width = 80
    min_button_height = 32
    min_input_height = 32
    min_touch_target = 44
    
    # Fixed widths
    nav_rail_width = 72
    nav_rail_expanded = 280
    inspector_width = 380
    
    # Header
    app_bar_height = 56
    status_chip_height = 24


# =============================================================================
# ICONS
# =============================================================================

class Icons:
    """Fluent icon references (Segoe Fluent Icons font codes)"""
    
    # Navigation
    home = "\uE80F"
    camera = "\uE722"
    settings = "\uE713"
    output = "\uE8A1"
    image = "\uEB9F"
    overlay = "\uE8F1"
    log = "\uE7C3"
    
    # Actions
    play = "\uE768"
    stop = "\uE71A"
    refresh = "\uE72C"
    save = "\uE74E"
    folder = "\uE8B7"
    
    # Status
    connected = "\uE703"
    disconnected = "\uE701"
    warning = "\uE7BA"
    error = "\uEA39"
    info = "\uE946"


# =============================================================================
# SHADOWS / ELEVATION (not directly supported in Qt, use as reference)
# =============================================================================

class Elevation:
    """Elevation levels for visual depth"""
    
    level_0 = "none"
    level_1 = "0 1px 2px rgba(0,0,0,0.3)"   # Cards
    level_2 = "0 2px 4px rgba(0,0,0,0.4)"   # Dropdowns
    level_3 = "0 4px 8px rgba(0,0,0,0.5)"   # Modals
    level_4 = "0 8px 16px rgba(0,0,0,0.6)"  # Tooltips


# =============================================================================
# ANIMATION
# =============================================================================

class Animation:
    """Animation timing"""
    
    duration_fast = 100      # ms - micro interactions
    duration_normal = 200    # ms - standard transitions
    duration_slow = 300      # ms - emphasis transitions
    
    easing_default = "ease-out"
    easing_bounce = "cubic-bezier(0.34, 1.56, 0.64, 1)"
