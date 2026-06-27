from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFileDialog, QStackedWidget
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, SubtitleLabel, CaptionLabel,
    PushButton, LineEdit,
    SegmentedWidget, InfoBar, InfoBarPosition
)

from ..theme.tokens import Colors, Spacing
from ..theme.icons import mdi
from ..components.cards import SettingsCard, SwitchRow
from ._camera_settings_widget import CameraSettingsWidget


class CaptureSettingsPanel(QScrollArea):
    settings_changed = Signal()
    detect_cameras_clicked = Signal()
    raw16_mode_changed = Signal(bool)
    revive_camera_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._loading_config = True
        self._setup_ui()
        self._loading_config = False

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

        mode_card = CardWidget()
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                       Spacing.card_padding, Spacing.card_padding)
        mode_layout.setSpacing(Spacing.md)

        mode_header = SubtitleLabel("Capture Mode")
        mode_header.setStyleSheet(f"color: {Colors.text_primary};")
        mode_layout.addWidget(mode_header)

        mode_desc = CaptionLabel(
            "Choose between monitoring a directory for new images or capturing directly from a ZWO camera."
        )
        mode_desc.setStyleSheet(f"color: {Colors.text_muted};")
        mode_desc.setWordWrap(True)
        mode_layout.addWidget(mode_desc)

        self.mode_selector = SegmentedWidget()
        self.mode_selector.addItem('watch', 'Directory Watch', onClick=lambda: self._on_mode_changed('watch'))
        self.mode_selector.addItem('camera', 'ZWO Camera', onClick=lambda: self._on_mode_changed('camera'))
        self.mode_selector.setCurrentItem('camera')
        mode_layout.addWidget(self.mode_selector)

        layout.addWidget(mode_card)

        self.settings_stack = QStackedWidget()

        self.watch_widget = self._create_watch_settings()
        self.settings_stack.addWidget(self.watch_widget)

        self.camera_widget = CameraSettingsWidget(self.main_window)
        self.camera_widget.settings_changed.connect(self.settings_changed)
        self.camera_widget.detect_cameras_clicked.connect(self.detect_cameras_clicked)
        self.camera_widget.raw16_mode_changed.connect(self.raw16_mode_changed)
        self.camera_widget.revive_camera_clicked.connect(self.revive_camera_clicked)
        self.settings_stack.addWidget(self.camera_widget)

        self.settings_stack.setCurrentIndex(1)

        layout.addWidget(self.settings_stack, 1)
        layout.addStretch()

    @property
    def _can_save(self):
        return not self._loading_config and self.main_window and hasattr(self.main_window, 'config')

    def _on_mode_changed(self, mode: str):
        self.settings_stack.setCurrentIndex(0 if mode == 'watch' else 1)
        if self._can_save:
            self.main_window.config.set('capture_mode', mode)
            self.settings_changed.emit()

    def _create_watch_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.card_gap)

        dir_card = SettingsCard(
            "Watch Directory",
            "Monitor this folder for new images to process"
        )

        dir_row = QHBoxLayout()
        dir_row.setSpacing(Spacing.sm)

        self.watch_dir_input = LineEdit()
        self.watch_dir_input.setPlaceholderText("Select directory to watch...")
        self.watch_dir_input.textChanged.connect(self._on_watch_dir_changed)
        dir_row.addWidget(self.watch_dir_input, 1)

        browse_btn = PushButton("Browse")
        browse_btn.setIcon(mdi('folder-outline'))
        browse_btn.clicked.connect(self._browse_watch_dir)
        dir_row.addWidget(browse_btn)

        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)
        dir_card.add_widget(dir_widget)

        self.recursive_switch = SwitchRow(
            "Include Subfolders",
            "Watch subdirectories recursively"
        )
        self.recursive_switch.toggled.connect(self._on_recursive_changed)
        dir_card.add_widget(self.recursive_switch)

        layout.addWidget(dir_card)
        layout.addStretch()

        return widget

    def _browse_watch_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Watch Directory")
        if dir_path:
            self.watch_dir_input.setText(dir_path)

    def _on_watch_dir_changed(self, text):
        if self._can_save:
            self.main_window.config.set('watch_directory', text)
            self.settings_changed.emit()

    def _on_recursive_changed(self, checked):
        if self._can_save:
            self.main_window.config.set('watch_recursive', checked)
            self.settings_changed.emit()

    def load_from_config(self, config):
        self._loading_config = True
        try:
            mode = config.get('capture_mode', 'camera')
            self.mode_selector.setCurrentItem(mode)
            self.settings_stack.setCurrentIndex(0 if mode == 'watch' else 1)

            self.watch_dir_input.setText(config.get('watch_directory', ''))
            self.recursive_switch.set_checked(config.get('watch_recursive', True))

            self.camera_widget.load_from_config(config)
        finally:
            self._loading_config = False

    def set_cameras(self, camera_list: list):
        self.camera_widget.set_cameras(camera_list)

    def set_detecting(self, is_detecting: bool):
        self.camera_widget.set_detecting(is_detecting)

    def set_detection_error(self, error: str):
        parent = getattr(self.main_window, 'content_area', self.main_window) if self.main_window else self
        bar = InfoBar.error(
            title="Camera Detection Failed",
            content=error,
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=5000
        )
        bar.raise_()

    def set_missing_camera_warning(self, saved_name: str, phantom_count: int = 0):
        self.camera_widget.set_missing_camera_warning(saved_name, phantom_count)

    def reset_revive_button(self):
        self.camera_widget.reset_revive_button()

    def clear_camera_selection(self):
        self.camera_widget.camera_combo.setCurrentIndex(-1)

    def set_capture_active(self, active: bool):
        """Lock the camera picker while capturing (switching cameras is Stop→Start)."""
        self.camera_widget.set_capture_active(active)

    def update_camera_capabilities(self, supports_raw16: bool, bit_depth: int):
        self.camera_widget.update_camera_capabilities(supports_raw16, bit_depth)

    def reset_camera_capabilities(self):
        self.camera_widget.reset_camera_capabilities()
