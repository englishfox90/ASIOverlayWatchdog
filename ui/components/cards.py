"""
Reusable Card Components
Fluent-styled cards for settings panels
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QGridLayout, QSizePolicy, QSlider
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, ExpandSettingCard, SettingCard,
    SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ToggleButton,
    ComboBox, LineEdit, SpinBox, DoubleSpinBox,
    Slider, SwitchButton, FluentIcon
)

from ..theme.tokens import Colors, Typography, Spacing, Layout


class ClickSlider(QSlider):
    """Slider that only responds to click, not hover/wheel without click"""
    
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._pressed = False
        self.setStyleSheet(f"""
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
        """)
    
    def mousePressEvent(self, event):
        self._pressed = True
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        self._pressed = False
        super().mouseReleaseEvent(event)
    
    def mouseMoveEvent(self, event):
        if self._pressed:
            super().mouseMoveEvent(event)
    
    def wheelEvent(self, event):
        # Ignore wheel events - only allow click-drag
        event.ignore()

class MonitoringCard(CardWidget):
    """Card for monitoring/display sections"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._setup_ui()
    
    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(
            Spacing.card_padding, Spacing.card_padding,
            Spacing.card_padding, Spacing.card_padding
        )
        self.layout.setSpacing(Spacing.element_gap)
        
        # Title
        self.title_label = SubtitleLabel(self._title)
        self.title_label.setStyleSheet(f"color: {Colors.text_primary};")
        self.layout.addWidget(self.title_label)
    
    def add_widget(self, widget, stretch=0):
        """Add widget to card content"""
        self.layout.addWidget(widget, stretch)
    
    def add_layout(self, layout):
        """Add layout to card content"""
        self.layout.addLayout(layout)


class SettingsCard(CardWidget):
    """Card for settings groups with consistent styling"""
    
    def __init__(self, title: str, description: str = None, parent=None):
        super().__init__(parent)
        self._title = title
        self._description = description
        self._setup_ui()
    
    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(
            Spacing.card_padding, Spacing.card_padding,
            Spacing.card_padding, Spacing.card_padding
        )
        self.main_layout.setSpacing(Spacing.md)
        
        # Header section
        header = QVBoxLayout()
        header.setSpacing(Spacing.xs)
        
        self.title_label = SubtitleLabel(self._title)
        self.title_label.setStyleSheet(f"color: {Colors.text_primary};")
        header.addWidget(self.title_label)
        
        if self._description:
            self.desc_label = CaptionLabel(self._description)
            self.desc_label.setStyleSheet(f"color: {Colors.text_muted};")
            self.desc_label.setWordWrap(True)
            header.addWidget(self.desc_label)
        
        self.main_layout.addLayout(header)
        
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.border_subtle};
                border: none;
                height: 1px;
                margin: {Spacing.sm}px 0px;
            }}
        """)
        self.main_layout.addWidget(separator)
        
        # Content area
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(Spacing.input_gap)
        self.main_layout.addLayout(self.content_layout)
    
    def add_widget(self, widget):
        """Add widget to card content"""
        self.content_layout.addWidget(widget)
    
    def add_row(self, label: str, widget: QWidget, hint: str = None):
        """Add a labeled form row"""
        row = FormRow(label, widget, hint)
        self.content_layout.addWidget(row)
        return row


class FormRow(QWidget):
    """Consistent form row with label and input"""
    
    def __init__(self, label: str, widget: QWidget, hint: str = None, parent=None):
        super().__init__(parent)
        self._setup_ui(label, widget, hint)
    
    def _setup_ui(self, label: str, widget: QWidget, hint: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)
        
        # Label column (fixed width for alignment)
        label_widget = BodyLabel(label)
        label_widget.setFixedWidth(140)
        label_widget.setStyleSheet(f"color: {Colors.text_secondary};")
        layout.addWidget(label_widget)
        
        # Input column
        input_layout = QVBoxLayout()
        input_layout.setSpacing(Spacing.xs)
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_layout.addWidget(widget)
        
        if hint:
            hint_label = CaptionLabel(hint)
            hint_label.setStyleSheet(f"color: {Colors.text_muted};")
            hint_label.setWordWrap(True)
            input_layout.addWidget(hint_label)
        
        layout.addLayout(input_layout, 1)


class SwitchRow(QWidget):
    """Form row with toggle switch"""
    
    toggled = Signal(bool)
    
    def __init__(self, label: str, description: str = None, parent=None):
        super().__init__(parent)
        self._setup_ui(label, description)
    
    def _setup_ui(self, label: str, description: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)
        
        # Text column
        text_layout = QVBoxLayout()
        text_layout.setSpacing(Spacing.xs)
        
        label_widget = BodyLabel(label)
        label_widget.setStyleSheet(f"color: {Colors.text_primary};")
        text_layout.addWidget(label_widget)
        
        if description:
            desc = CaptionLabel(description)
            desc.setStyleSheet(f"color: {Colors.text_muted};")
            desc.setWordWrap(True)
            text_layout.addWidget(desc)
        
        layout.addLayout(text_layout, 1)
        
        # Switch
        self.switch = SwitchButton()
        self.switch.checkedChanged.connect(self.toggled.emit)
        layout.addWidget(self.switch)
    
    def is_checked(self) -> bool:
        return self.switch.isChecked()
    
    def set_checked(self, checked: bool):
        self.switch.setChecked(checked)


class CollapsibleCard(CardWidget):
    """Expandable/collapsible settings card"""
    
    def __init__(self, title: str, icon=None, parent=None):
        super().__init__(parent)
        self._title = title
        self._icon = icon
        self._expanded = False  # Default to collapsed
        self._setup_ui()
    
    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Header (clickable) - compact height
        self.header = QFrame()
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
            }}
            QFrame:hover {{
                background-color: {Colors.bg_hover};
            }}
        """)
        
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(
            Spacing.base, Spacing.sm,
            Spacing.base, Spacing.sm
        )
        
        # Icon (optional)
        if self._icon:
            icon_label = QLabel()
            if hasattr(self._icon, 'icon'):
                icon_label.setPixmap(self._icon.icon().pixmap(20, 20))
            header_layout.addWidget(icon_label)
        
        # Title
        title_label = SubtitleLabel(self._title)
        title_label.setStyleSheet(f"color: {Colors.text_primary};")
        header_layout.addWidget(title_label, 1)
        
        # Expand indicator (collapsed by default)
        self.expand_icon = QLabel("▶")
        self.expand_icon.setStyleSheet(f"color: {Colors.text_muted};")
        header_layout.addWidget(self.expand_icon)
        
        self.main_layout.addWidget(self.header)
        
        # Content area (hidden by default)
        self.content = QWidget()
        self.content.setVisible(False)  # Start collapsed
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(
            Spacing.card_padding, Spacing.sm,
            Spacing.card_padding, Spacing.md
        )
        self.content_layout.setSpacing(Spacing.input_gap)
        self.main_layout.addWidget(self.content)
        
        # Connect header click
        self.header.mousePressEvent = self._toggle_expanded
    
    def _toggle_expanded(self, event):
        self._expanded = not self._expanded
        self.content.setVisible(self._expanded)
        self.expand_icon.setText("▼" if self._expanded else "▶")
    
    def add_widget(self, widget):
        """Add widget to card content"""
        self.content_layout.addWidget(widget)
    
    def add_row(self, label: str, widget: QWidget, hint: str = None):
        """Add a labeled form row"""
        row = FormRow(label, widget, hint)
        self.content_layout.addWidget(row)
        return row
