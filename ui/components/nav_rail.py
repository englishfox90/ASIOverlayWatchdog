"""
Navigation Rail Component
Left-side navigation for section switching
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QLabel,
    QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QIcon
from qfluentwidgets import FluentIcon, ToolButton

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.styles import get_nav_item_style


class NavButton(QPushButton):
    """Navigation rail button with icon and label"""
    
    def __init__(self, icon, text: str, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._selected = False
        self._original_text = text  # Store for collapse/expand
        
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        
        # Icon handling - FluentIcon or QIcon
        if hasattr(icon, 'icon'):
            self.setIcon(icon.icon())
        elif isinstance(icon, QIcon):
            self.setIcon(icon)
        
        self.setIconSize(QSize(20, 20))
        
        self._update_style()
    
    @property
    def key(self) -> str:
        return self._key
    
    def set_selected(self, selected: bool):
        self._selected = selected
        self.setChecked(selected)
        self._update_style()
    
    def _update_style(self):
        if self._selected:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.accent_subtle};
                    color: {Colors.accent_text};
                    border: none;
                    border-radius: {Layout.radius_md}px;
                    padding: 8px 12px;
                    text-align: left;
                    font-size: {Typography.size_body}px;
                    font-weight: {Typography.weight_semibold};
                }}
                QPushButton:hover {{
                    background-color: {Colors.iris_4};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {Colors.text_secondary};
                    border: none;
                    border-radius: {Layout.radius_md}px;
                    padding: 8px 12px;
                    text-align: left;
                    font-size: {Typography.size_body}px;
                }}
                QPushButton:hover {{
                    background-color: {Colors.bg_hover};
                    color: {Colors.text_primary};
                }}
            """)


class NavRail(QFrame):
    """
    Vertical navigation rail with section buttons
    Sections: Live Monitoring, Capture, Output, Image Processing, Overlays, Logs
    Collapsible with hamburger toggle
    """
    
    section_changed = Signal(str)  # Emits section key
    collapsed_changed = Signal(bool)  # Emits collapsed state
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_section = 'capture'
        self._buttons = {}
        self._collapsed = False
        self._expanded_width = 200
        self._collapsed_width = 56
        self._setup_ui()
    
    def _setup_ui(self):
        self.setFixedWidth(self._expanded_width)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.bg_surface};
                border-right: 1px solid {Colors.border_subtle};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.sm, Spacing.sm, Spacing.sm, Spacing.base)
        layout.setSpacing(Spacing.xs)
        
        # Hamburger toggle button
        self.toggle_btn = QPushButton()
        self.toggle_btn.setText("☰")
        self.toggle_btn.setFixedSize(40, 40)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {Colors.text_secondary};
                border: none;
                border-radius: {Layout.radius_md}px;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background-color: {Colors.bg_hover};
                color: {Colors.text_primary};
            }}
        """)
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        layout.addWidget(self.toggle_btn)
        
        # Section header (hidden when collapsed)
        self.header = QLabel("Navigation")
        self.header.setStyleSheet(f"""
            color: {Colors.text_muted};
            font-size: {Typography.size_small}px;
            font-weight: {Typography.weight_semibold};
            text-transform: uppercase;
            letter-spacing: 1px;
            padding: 4px 12px;
        """)
        layout.addWidget(self.header)
        
        # Navigation buttons
        nav_items = [
            (FluentIcon.VIEW, "Live Monitoring", 'monitoring'),
            (FluentIcon.CAMERA, "Capture", 'capture'),
            (FluentIcon.CLOUD, "Output", 'output'),
            (FluentIcon.PHOTO, "Image Processing", 'processing'),
            (FluentIcon.FONT, "Overlays", 'overlays'),
            (FluentIcon.GLOBE, "Services", 'services'),
            (FluentIcon.HISTORY, "Logs", 'logs'),
        ]
        
        for icon, label, key in nav_items:
            btn = NavButton(icon, label, key, self)
            btn.clicked.connect(lambda checked, k=key: self._on_button_clicked(k))
            layout.addWidget(btn)
            self._buttons[key] = btn
        
        # Spacer
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        # Set initial selection
        self._buttons['capture'].set_selected(True)
    
    def _on_button_clicked(self, key: str):
        """Handle button click"""
        if key == self._current_section:
            return
        
        # Update selection
        for btn_key, btn in self._buttons.items():
            btn.set_selected(btn_key == key)
        
        self._current_section = key
        self.section_changed.emit(key)
    
    def set_section(self, key: str):
        """Programmatically set current section"""
        if key in self._buttons:
            self._on_button_clicked(key)
    
    def toggle_collapsed(self):
        """Toggle between collapsed and expanded states"""
        self._collapsed = not self._collapsed
        target_width = self._collapsed_width if self._collapsed else self._expanded_width
        
        # Animate width change
        self._width_anim = QPropertyAnimation(self, b"minimumWidth")
        self._width_anim.setDuration(150)
        self._width_anim.setStartValue(self.width())
        self._width_anim.setEndValue(target_width)
        self._width_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self._width_anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._width_anim2.setDuration(150)
        self._width_anim2.setStartValue(self.width())
        self._width_anim2.setEndValue(target_width)
        self._width_anim2.setEasingCurve(QEasingCurve.OutCubic)
        
        self._width_anim.start()
        self._width_anim2.start()
        
        # Update button text visibility
        self.header.setVisible(not self._collapsed)
        for btn in self._buttons.values():
            btn.setText("" if self._collapsed else btn._original_text)
        
        # Update toggle icon
        self.toggle_btn.setText("☰" if self._collapsed else "☰")
        
        self.collapsed_changed.emit(self._collapsed)
    
    @property
    def is_collapsed(self) -> bool:
        return self._collapsed
