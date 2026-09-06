"""
Logs Panel
Full log viewer with filtering
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, ComboBox, LineEdit, SwitchButton
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import SettingsCard, SwitchRow


class LogsPanel(QScrollArea):
    """
    Full log viewer panel with:
    - Log text area
    - Filter by level
    - Search
    - Auto-scroll toggle
    - Clear button
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._max_lines = 1000
        self._auto_scroll = True
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.bg_app};
                border: none;
            }}
        """)
        
        content = QWidget()
        self.setWidget(content)
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.card_gap)
        
        # === CONTROLS ===
        controls_card = CardWidget()
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(Spacing.card_padding, Spacing.md,
                                          Spacing.card_padding, Spacing.md)
        controls_layout.setSpacing(Spacing.md)
        
        # Filter by level
        filter_label = BodyLabel("Level:")
        filter_label.setStyleSheet(f"color: {Colors.text_secondary};")
        controls_layout.addWidget(filter_label)
        
        self.level_filter = ComboBox()
        self.level_filter.addItems(["Info+", "All", "INFO", "WARN", "ERROR", "DEBUG"])
        self.level_filter.setCurrentText("Info+")
        self.level_filter.currentTextChanged.connect(self._on_filter_changed)
        self.level_filter.setFixedWidth(100)
        controls_layout.addWidget(self.level_filter)
        
        # Search
        self.search_input = LineEdit()
        self.search_input.setPlaceholderText("Search logs...")
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setMinimumWidth(100)
        self.search_input.setMaximumWidth(250)
        controls_layout.addWidget(self.search_input)
        
        controls_layout.addStretch()
        
        # Auto-scroll
        self.auto_scroll_switch = SwitchButton()
        self.auto_scroll_switch.setChecked(True)
        self.auto_scroll_switch.checkedChanged.connect(self._on_auto_scroll_changed)
        controls_layout.addWidget(BodyLabel("Auto-scroll"))
        controls_layout.addWidget(self.auto_scroll_switch)
        
        # Clear button
        self.clear_btn = PushButton("Clear")
        self.clear_btn.setIcon(mdi('delete-outline'))
        self.clear_btn.clicked.connect(self._clear_logs)
        controls_layout.addWidget(self.clear_btn)
        
        # Open log folder
        self.open_folder_btn = PushButton("Open Folder")
        self.open_folder_btn.setIcon(mdi('folder-outline'))
        self.open_folder_btn.clicked.connect(self._open_log_folder)
        controls_layout.addWidget(self.open_folder_btn)
        
        layout.addWidget(controls_card)
        
        # === LOG TEXT AREA ===
        log_card = CardWidget()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                      Spacing.card_padding, Spacing.card_padding)
        log_layout.setSpacing(0)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)  # Allow horizontal scroll
        # A manual cursor trim frees nothing while undo is on: QTextDocument
        # keeps every insert *and* every removal on the undo stack, so an
        # all-night run grows without bound. maximumBlockCount discards the
        # oldest block in-place instead.
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.document().setMaximumBlockCount(self._max_lines)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.bg_input};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
                color: {Colors.text_secondary};
                font-family: {Typography.family_mono};
                font-size: {Typography.size_small}px;
                padding: 8px;
            }}
        """)
        log_layout.addWidget(self.log_text)
        
        # Log location info
        from services.logger import app_logger
        log_path = app_logger.get_log_location()
        log_info = CaptionLabel(f"Log file: {log_path}")
        log_info.setStyleSheet(f"color: {Colors.text_muted}; padding-top: 8px;")
        log_layout.addWidget(log_info)
        
        layout.addWidget(log_card, 1)
    
    def load_from_config(self, config):
        saved = config.get('ui_log_level', 'Info+')
        index = self.level_filter.findText(saved)
        if index >= 0:
            self.level_filter.setCurrentIndex(index)

    def _on_filter_changed(self, level):
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('ui_log_level', level)
            if hasattr(self.main_window, 'save_config'):
                self.main_window.save_config()
            else:
                self.main_window.config.save()
    
    def _on_search_changed(self, text):
        """Handle search text change"""
        # Will be implemented with actual searching
        pass
    
    def _on_auto_scroll_changed(self, checked):
        """Handle auto-scroll toggle"""
        self._auto_scroll = checked
        if checked:
            self._scroll_to_bottom()
    
    def _clear_logs(self):
        """Clear log display"""
        self.log_text.clear()
    
    def _open_log_folder(self):
        """Open log folder in file explorer"""
        import subprocess
        import platform
        from services.logger import app_logger
        
        log_dir = app_logger.get_log_dir()
        
        if platform.system() == 'Windows':
            subprocess.run(['explorer', log_dir])
        elif platform.system() == 'Darwin':
            subprocess.run(['open', log_dir])
        else:
            subprocess.run(['xdg-open', log_dir])
    
    def _scroll_to_bottom(self):
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _append_one(self, message: str):
        """Render one message into the document. No scrolling — see append_logs."""
        # Color coding based on level
        if "ERROR" in message:
            color = Colors.error_text
        elif "WARN" in message:
            color = Colors.warning_text
        elif "DEBUG" in message:
            color = Colors.text_muted
        else:
            color = Colors.text_secondary
        
        # Apply filter
        current_filter = self.level_filter.currentText()
        if current_filter == "Info+":
            if "DEBUG" in message:
                return
        elif current_filter != "All":
            if current_filter not in message:
                return
        
        # Apply search
        search_text = self.search_input.text()
        if search_text and search_text.lower() not in message.lower():
            return
        
        # Append with color
        self.log_text.append(f'<span style="color: {color};">{message}</span>')

    def append_log(self, message: str):
        """Append a single log message"""
        self.append_logs([message])

    def append_logs(self, messages: list):
        """Append a batch of log messages with one repaint and one scroll."""
        if not messages:
            return
        # The switch is the only gate: a resize leaves the scrollbar short of
        # its new maximum, so an "already at bottom" check would silently stop
        # following after any window/splitter change.
        follow = self._auto_scroll
        self.log_text.setUpdatesEnabled(False)
        try:
            for msg in messages:
                self._append_one(msg)
        finally:
            self.log_text.setUpdatesEnabled(True)
        if follow:
            self._scroll_to_bottom()
