"""
Navigation Rail Component
Left-side navigation for section switching
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QLabel,
    QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QIcon, QPainter, QColor, QBrush
import qtawesome as qta

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.styles import get_nav_item_style


class NavButton(QPushButton):
    """Navigation rail button with icon, label, and optional badge"""
    
    def __init__(self, icon, text: str, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._selected = False
        self._original_text = text  # Store for collapse/expand
        self._badge_visible = False
        self._badge_text = ""
        self._badge_color = Colors.accent_default

        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        
        # Icon handling - QIcon instance
        if isinstance(icon, QIcon):
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
    
    def set_badge(self, visible: bool, text: str = "", color: str = None):
        """Show or hide a badge on this button."""
        self._badge_visible = visible
        self._badge_text = text
        self._badge_color = color or Colors.accent_default
        self.update()  # Trigger repaint
    
    def paintEvent(self, event):
        """Override to draw badge."""
        super().paintEvent(event)
        
        if self._badge_visible:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(self._badge_color)))

            if self._badge_text:
                # Pill shape sized to the text so multi-char labels (e.g. "BETA") fit.
                font = painter.font()
                font.setPixelSize(9)
                font.setBold(True)
                painter.setFont(font)
                pill_h = 16
                text_w = painter.fontMetrics().horizontalAdvance(self._badge_text)
                pill_w = text_w + 12
                x = self.width() - pill_w - 12
                y = (self.height() - pill_h) // 2
                painter.drawRoundedRect(x, y, pill_w, pill_h, pill_h // 2, pill_h // 2)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(x, y, pill_w, pill_h, Qt.AlignCenter, self._badge_text)
            else:
                # Simple dot
                badge_size = 10
                x = self.width() - badge_size - 12
                y = (self.height() - badge_size) // 2
                painter.drawEllipse(x, y, badge_size, badge_size)

            painter.end()
    
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
        _ico = lambda name: qta.icon(f'mdi6.{name}', color=Colors.text_secondary)
        nav_items = [
            (_ico('monitor-shimmer'), "Live Monitoring", 'monitoring'),
            (_ico('camera-plus-outline'), "Capture", 'capture'),
            (_ico('monitor-share'), "Output", 'output'),
            (_ico('image-edit-outline'), "Image Processing", 'processing'),
            (_ico('format-textbox'), "Overlays", 'overlays'),
            (_ico('sphere'), "All-Sky", 'allsky'),
            (_ico('filmstrip-box-multiple'), "Timelapse", 'timelapse'),
        ]
        nav_items.append((_ico('meteor'), "Meteor Tracker", 'meteor'))
        nav_items.append((_ico('image-multiple'), "Library", 'library'))
        nav_items.append((_ico('math-log'), "Logs", 'logs'))

        for icon, label, key in nav_items:
            btn = NavButton(icon, label, key, self)
            btn.clicked.connect(lambda checked, k=key: self._on_button_clicked(k))
            layout.addWidget(btn)
            self._buttons[key] = btn
        
        # Spacer
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        # Settings button (bottom)
        settings_btn = NavButton(_ico('cog'), "Settings", 'settings', self)
        settings_btn.clicked.connect(lambda checked: self._on_button_clicked('settings'))
        layout.addWidget(settings_btn)
        self._buttons['settings'] = settings_btn
        
        # Both All-Sky and Meteor Tracker are still in beta.
        for beta_key in ('allsky', 'meteor'):
            if beta_key in self._buttons:
                self._buttons[beta_key].set_badge(True, "BETA", Colors.warning_default)

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
    
    def set_active_section(self, key: str):
        """Set active section without emitting signal (for restoring state)"""
        if key not in self._buttons:
            return
        
        # Update visual selection
        for btn_key, btn in self._buttons.items():
            btn.set_selected(btn_key == key)
        
        self._current_section = key
    
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
    
    def refresh_styles(self):
        """Re-apply inline stylesheets on all buttons using current Colors values.
        Call after an accent theme change so the selected highlight updates."""
        for btn in self._buttons.values():
            btn._update_style()

    def set_badge(self, key: str, visible: bool, text: str = "", color: str = None):
        """Set badge visibility on a navigation button.

        Args:
            key: Button key ('settings', 'capture', etc.)
            visible: Whether to show the badge
            text: Optional text to show in badge (e.g., "1", "!")
            color: Optional badge fill color (defaults to accent)
        """
        if key in self._buttons:
            self._buttons[key].set_badge(visible, text, color)
    
    @property
    def is_collapsed(self) -> bool:
        return self._collapsed
