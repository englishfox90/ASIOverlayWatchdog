"""
PFRAstro Stylesheet Generator
Generates Qt stylesheets from design tokens for QFluentWidgets
"""
from qfluentwidgets import setTheme, Theme, setThemeColor, isDarkTheme
from qfluentwidgets import FluentStyleSheet
from PySide6.QtGui import QColor, QCursor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox
from .tokens import Colors, Typography, Spacing, Layout


def apply_theme():
    """Apply PFRAstro dark theme to QFluentWidgets"""
    # Set dark theme
    setTheme(Theme.DARK)
    
    # Set accent color to Iris purple
    setThemeColor(QColor(Colors.iris_9))


def configure_widget_cursors(widget: QWidget):
    """
    Recursively configure appropriate cursor shapes for widgets
    
    Args:
        widget: Root widget to configure (usually main window or panel)
    """
    # Configure this widget
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
        widget.setCursor(Qt.CursorShape.IBeamCursor)
    elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        # SpinBox has text area, but also buttons - keep default for now
        pass
    elif isinstance(widget, QPushButton):
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
    elif isinstance(widget, QComboBox):
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
    
    # Recursively configure children
    for child in widget.findChildren(QWidget):
        if isinstance(child, (QLineEdit, QTextEdit, QPlainTextEdit)):
            child.setCursor(Qt.CursorShape.IBeamCursor)
        elif isinstance(child, QPushButton):
            child.setCursor(Qt.CursorShape.PointingHandCursor)
        elif isinstance(child, QComboBox):
            child.setCursor(Qt.CursorShape.PointingHandCursor)



def get_stylesheet() -> str:
    """Generate comprehensive Qt stylesheet from tokens"""
    
    return f"""
    /* =================================================================
       PFRAstro Global Stylesheet
       ================================================================= */
    
    /* === BASE WIDGET STYLING === */
    QWidget {{
        background-color: {Colors.bg_app};
        color: {Colors.text_primary};
        font-family: {Typography.family_text};
        font-size: {Typography.size_body}px;
    }}
    
    QMainWindow {{
        background-color: {Colors.bg_app};
    }}
    
    /* === SCROLL AREAS === */
    QScrollArea {{
        background-color: transparent;
        border: none;
    }}
    
    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}
    
    QScrollBar:vertical {{
        background-color: {Colors.bg_surface};
        width: 8px;
        border-radius: 4px;
        margin: 0;
    }}
    
    QScrollBar::handle:vertical {{
        background-color: {Colors.gray_6};
        border-radius: 4px;
        min-height: 32px;
    }}
    
    QScrollBar::handle:vertical:hover {{
        background-color: {Colors.gray_7};
    }}
    
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    
    QScrollBar:horizontal {{
        background-color: {Colors.bg_surface};
        height: 8px;
        border-radius: 4px;
    }}
    
    QScrollBar::handle:horizontal {{
        background-color: {Colors.gray_6};
        border-radius: 4px;
        min-width: 32px;
    }}
    
    /* === LABELS === */
    QLabel {{
        background-color: transparent;
        color: {Colors.text_primary};
    }}
    
    QLabel[class="title"] {{
        font-size: {Typography.size_title}px;
        font-weight: {Typography.weight_semibold};
        color: {Colors.text_primary};
    }}
    
    QLabel[class="subtitle"] {{
        font-size: {Typography.size_subtitle}px;
        font-weight: {Typography.weight_semibold};
        color: {Colors.text_primary};
    }}
    
    QLabel[class="caption"] {{
        font-size: {Typography.size_caption}px;
        color: {Colors.text_secondary};
    }}
    
    QLabel[class="muted"] {{
        color: {Colors.text_muted};
    }}
    
    /* === INPUTS === */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {Colors.bg_input};
        border: 1px solid {Colors.border_subtle};
        border-radius: {Layout.radius_md}px;
        padding: 6px 12px;
        min-height: {Layout.min_input_height}px;
        color: {Colors.text_primary};
        selection-background-color: {Colors.iris_6};
    }}
    
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
        border-color: {Colors.border_default};
    }}
    
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {Colors.border_focus};
        outline: none;
    }}
    
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        background-color: {Colors.bg_surface};
        color: {Colors.text_disabled};
    }}
    
    /* === TEXT AREAS === */
    QTextEdit, QPlainTextEdit {{
        background-color: {Colors.bg_input};
        border: 1px solid {Colors.border_subtle};
        border-radius: {Layout.radius_md}px;
        padding: 8px;
        color: {Colors.text_primary};
        selection-background-color: {Colors.iris_6};
    }}
    
    /* === COMBO BOX === */
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {Colors.text_secondary};
    }}
    
    QComboBox QAbstractItemView {{
        background-color: {Colors.bg_card};
        border: 1px solid {Colors.border_default};
        border-radius: {Layout.radius_md}px;
        selection-background-color: {Colors.accent_subtle};
        padding: 4px;
    }}
    
    /* === CHECKBOXES & RADIO BUTTONS === */
    QCheckBox, QRadioButton {{
        spacing: 8px;
        color: {Colors.text_primary};
    }}
    
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px;
        height: 18px;
    }}
    
    QCheckBox::indicator {{
        border: 2px solid {Colors.border_default};
        border-radius: 4px;
        background-color: transparent;
    }}
    
    QCheckBox::indicator:checked {{
        background-color: {Colors.accent_default};
        border-color: {Colors.accent_default};
    }}
    
    QRadioButton::indicator {{
        border: 2px solid {Colors.border_default};
        border-radius: 9px;
        background-color: transparent;
    }}
    
    QRadioButton::indicator:checked {{
        background-color: {Colors.accent_default};
        border-color: {Colors.accent_default};
    }}
    
    /* === SLIDERS === */
    QSlider::groove:horizontal {{
        height: 4px;
        background-color: {Colors.gray_6};
        border-radius: 2px;
    }}
    
    QSlider::handle:horizontal {{
        background-color: {Colors.accent_default};
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 8px;
    }}
    
    QSlider::handle:horizontal:hover {{
        background-color: {Colors.accent_hover};
    }}
    
    QSlider::sub-page:horizontal {{
        background-color: {Colors.accent_default};
        border-radius: 2px;
    }}
    
    /* === PROGRESS BAR === */
    QProgressBar {{
        background-color: {Colors.bg_input};
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
    }}
    
    QProgressBar::chunk {{
        background-color: {Colors.accent_default};
        border-radius: 3px;
    }}
    
    /* === GROUP BOX (avoid heavy borders) === */
    QGroupBox {{
        background-color: {Colors.bg_card};
        border: 1px solid {Colors.border_subtle};
        border-radius: {Layout.radius_lg}px;
        margin-top: 16px;
        padding: {Spacing.card_padding}px;
        padding-top: 28px;
        font-weight: {Typography.weight_semibold};
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 4px 12px;
        color: {Colors.text_primary};
    }}
    
    /* === TAB WIDGET (not used but override for safety) === */
    QTabWidget::pane {{
        border: none;
        background-color: transparent;
    }}
    
    QTabBar::tab {{
        background-color: transparent;
        color: {Colors.text_secondary};
        padding: 8px 16px;
        border: none;
    }}
    
    QTabBar::tab:selected {{
        color: {Colors.accent_text};
        border-bottom: 2px solid {Colors.accent_default};
    }}
    
    /* === TOOL TIP === */
    QToolTip {{
        background-color: {Colors.bg_card};
        color: {Colors.text_primary};
        border: 1px solid {Colors.border_default};
        border-radius: {Layout.radius_md}px;
        padding: 6px 10px;
        font-size: {Typography.size_caption}px;
    }}
    
    /* === MENU === */
    QMenu {{
        background-color: {Colors.bg_card};
        border: 1px solid {Colors.border_default};
        border-radius: {Layout.radius_md}px;
        padding: 4px;
    }}
    
    QMenu::item {{
        padding: 8px 24px;
        border-radius: {Layout.radius_sm}px;
    }}
    
    QMenu::item:selected {{
        background-color: {Colors.accent_subtle};
    }}
    
    QMenu::separator {{
        height: 1px;
        background-color: {Colors.border_subtle};
        margin: 4px 8px;
    }}
    
    /* === SPLITTER === */
    QSplitter::handle {{
        background-color: {Colors.border_subtle};
    }}
    
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    
    QSplitter::handle:vertical {{
        height: 1px;
    }}
    
    /* === STATUS BAR === */
    QStatusBar {{
        background-color: {Colors.bg_surface};
        color: {Colors.text_secondary};
        border-top: 1px solid {Colors.border_subtle};
    }}
    
    /* === FRAME (Cards) === */
    QFrame[class="card"] {{
        background-color: {Colors.bg_card};
        border: 1px solid {Colors.border_subtle};
        border-radius: {Layout.radius_lg}px;
    }}
    
    QFrame[class="card-flat"] {{
        background-color: {Colors.bg_surface};
        border: none;
        border-radius: {Layout.radius_lg}px;
    }}
    """


def get_status_chip_style(status: str) -> str:
    """Get inline style for status chips"""
    
    status_colors = {
        'live': (Colors.success_bg, Colors.success_text),
        'capturing': (Colors.success_bg, Colors.success_text),
        'connected': (Colors.success_bg, Colors.success_text),
        'idle': (Colors.gray_4, Colors.gray_11),
        'stopped': (Colors.gray_4, Colors.gray_11),
        'connecting': (Colors.warning_bg, Colors.warning_text),
        'detecting': (Colors.warning_bg, Colors.warning_text),
        'error': (Colors.error_bg, Colors.error_text),
        'disconnected': (Colors.error_bg, Colors.error_text),
        'enabled': (Colors.info_bg, Colors.info_text),
        'disabled': (Colors.gray_4, Colors.gray_9),
    }
    
    bg, text = status_colors.get(status.lower(), (Colors.gray_4, Colors.gray_11))
    
    return f"""
        background-color: {bg};
        color: {text};
        border: none;
        border-radius: {Layout.status_chip_height // 2}px;
        padding: 4px 12px;
        font-size: {Typography.size_small}px;
        font-weight: {Typography.weight_semibold};
    """


def get_nav_item_style(selected: bool = False) -> str:
    """Get style for navigation items"""
    
    if selected:
        return f"""
            background-color: {Colors.accent_subtle};
            color: {Colors.accent_text};
            border-radius: {Layout.radius_md}px;
            padding: 12px 16px;
        """
    else:
        return f"""
            background-color: transparent;
            color: {Colors.text_secondary};
            border-radius: {Layout.radius_md}px;
            padding: 12px 16px;
        """
