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
        self._compact = False  # collapsed rail: badges shrink to a corner dot

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

    def set_compact(self, compact: bool):
        """Collapsed rail: there's no room for a text pill, so badges with text
        (e.g. BETA) shrink to a corner dot over the icon."""
        if compact == self._compact:
            return
        self._compact = compact
        self.update()

    def paintEvent(self, event):
        """Override to draw badge."""
        super().paintEvent(event)

        if not self._badge_visible:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(self._badge_color)))

        if self._badge_text and not self._compact:
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
        elif self._compact:
            # Collapsed: a small dot tucked at the icon's top-right corner.
            badge_size = 8
            x = self.width() - badge_size - 8
            y = 7
            painter.drawEllipse(x, y, badge_size, badge_size)
        else:
            # Expanded, text-less badge (e.g. timelapse activity dot).
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
        # Scope to the NavRail class — a bare `QFrame` selector also matches child
        # QLabels (QLabel subclasses QFrame), giving the group headers a stray
        # right border that reads as a double line.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            NavRail {{
                background-color: {Colors.bg_surface};
                border-right: 1px solid {Colors.border_subtle};
            }}
        """)

        self._group_labels = []
        self._dividers = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.sm, Spacing.sm, Spacing.sm, Spacing.base)
        layout.setSpacing(Spacing.xs)

        # Hamburger toggle button
        self.toggle_btn = QPushButton()
        self.toggle_btn.setIcon(qta.icon('mdi6.menu', color=Colors.text_secondary))
        self.toggle_btn.setIconSize(QSize(20, 20))
        self.toggle_btn.setFixedSize(40, 40)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {Layout.radius_md}px;
            }}
            QPushButton:hover {{
                background-color: {Colors.bg_hover};
            }}
        """)
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        layout.addWidget(self.toggle_btn)

        _ico = lambda name: qta.icon(f'mdi6.{name}', color=Colors.text_secondary)

        # Grouped sections: each (group title, [(icon, label, key), ...]).
        groups = [
            ("Monitor", [
                (_ico('monitor-shimmer'), "Live Monitoring", 'monitoring'),
                (_ico('meteor'), "Meteor Tracker", 'meteor'),
            ]),
            ("Image", [
                (_ico('camera-plus-outline'), "Capture", 'capture'),
                (_ico('image-edit-outline'), "Image Processing", 'processing'),
                (_ico('format-textbox'), "Overlays", 'overlays'),
                (_ico('sphere'), "All-Sky", 'allsky'),
            ]),
            ("Publish", [
                (_ico('monitor-share'), "Output", 'output'),
                (_ico('filmstrip-box-multiple'), "Timelapse", 'timelapse'),
                (_ico('image-multiple'), "Library", 'library'),
            ]),
        ]

        for gi, (title, items) in enumerate(groups):
            if gi > 0:
                layout.addWidget(self._make_divider())
            layout.addWidget(self._make_group_label(title))
            for icon, label, key in items:
                btn = NavButton(icon, label, key, self)
                btn.clicked.connect(lambda checked, k=key: self._on_button_clicked(k))
                layout.addWidget(btn)
                self._buttons[key] = btn

        # Push Logs + Settings to the bottom.
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        layout.addWidget(self._make_divider())
        for icon, label, key in (
            (_ico('math-log'), "Logs", 'logs'),
            (_ico('cog'), "Settings", 'settings'),
        ):
            btn = NavButton(icon, label, key, self)
            btn.clicked.connect(lambda checked, k=key: self._on_button_clicked(k))
            layout.addWidget(btn)
            self._buttons[key] = btn

        # Meteor Tracker is still in beta.
        for beta_key in ('meteor',):
            if beta_key in self._buttons:
                self._buttons[beta_key].set_badge(True, "BETA", Colors.warning_default)

        # Set initial selection
        self._buttons['capture'].set_selected(True)

    def _make_group_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(f"""
            color: {Colors.text_muted};
            font-size: {Typography.size_small}px;
            font-weight: {Typography.weight_bold};
            letter-spacing: 1px;
            padding: 6px 12px 2px;
        """)
        self._group_labels.append(lbl)
        return lbl

    def _make_divider(self) -> QFrame:
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {Colors.border_subtle}; border: none;")
        self._dividers.append(div)
        return div
    
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
        
        # Hide group labels + dividers and button text when collapsed.
        for lbl in self._group_labels:
            lbl.setVisible(not self._collapsed)
        for div in self._dividers:
            div.setVisible(not self._collapsed)
        for btn in self._buttons.values():
            btn.setText("" if self._collapsed else btn._original_text)
            btn.set_compact(self._collapsed)

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
