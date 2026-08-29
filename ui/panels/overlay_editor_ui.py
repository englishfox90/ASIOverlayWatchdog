"""Editor UI builders for OverlaySettingsPanel."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QStackedWidget,
    QTextEdit,
)
from PySide6.QtCore import Qt

from qfluentwidgets import (
    SubtitleLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox,
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import FormRow, SwitchRow

from .overlay_preview import TOKENS, ANCHOR_POSITIONS, COLOR_OPTIONS


class OverlayEditorUIMixin:
    """Editor widget creation for OverlaySettingsPanel."""

    def _populate_token_combo(self):
        self.token_combo.clear()

        weather_enabled = False
        if self.main_window:
            weather_config = self.main_window.config.get('weather', {})
            api_key = weather_config.get('api_key', '')
            weather_enabled = weather_config.get('enabled', False) and bool(api_key)

        current_section = None
        for label, token in TOKENS:
            if token is None:
                if "Weather" in label and not weather_enabled:
                    current_section = "weather_skip"
                    continue
                current_section = "weather" if "Weather" in label else "other"
                self.token_combo.addItem(f"── {label} ──")
            else:
                if current_section == "weather_skip":
                    continue
                self.token_combo.addItem(label)

    def _create_editor_card(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.bg_app};
                border: none;
            }}
        """)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.md, Spacing.md, Spacing.md, Spacing.md)
        layout.setSpacing(Spacing.md)

        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("Overlay name")
        self.name_edit.textChanged.connect(self._on_name_changed)
        layout.addWidget(FormRow("Name", self.name_edit))

        self.type_combo = ComboBox()
        self.type_combo.addItems(["Text", "Image", "Compass"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        layout.addWidget(FormRow("Type", self.type_combo))

        layout.addWidget(self._create_divider())

        self.editor_stack = QStackedWidget()

        text_widget = self._create_text_editor()
        self.editor_stack.addWidget(text_widget)

        image_widget = self._create_image_editor()
        self.editor_stack.addWidget(image_widget)

        compass_widget = self._create_compass_editor()
        self.editor_stack.addWidget(compass_widget)

        layout.addWidget(self.editor_stack)

        layout.addWidget(self._create_divider())

        pos_header = self._create_section_header("Position")
        layout.addWidget(pos_header)

        self.anchor_combo = ComboBox()
        self.anchor_combo.addItems(ANCHOR_POSITIONS)
        self.anchor_combo.currentTextChanged.connect(self._on_position_changed)
        layout.addWidget(FormRow("Anchor", self.anchor_combo))

        self.offset_x_spin = SpinBox()
        self.offset_x_spin.setRange(-2000, 2000)
        self.offset_x_spin.setValue(15)
        self.offset_x_spin.setSuffix(" px")
        self.offset_x_spin.valueChanged.connect(self._on_position_changed)
        layout.addWidget(FormRow("Offset X", self.offset_x_spin))

        self.offset_y_spin = SpinBox()
        self.offset_y_spin.setRange(-2000, 2000)
        self.offset_y_spin.setValue(15)
        self.offset_y_spin.setSuffix(" px")
        self.offset_y_spin.valueChanged.connect(self._on_position_changed)
        layout.addWidget(FormRow("Offset Y", self.offset_y_spin))

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.sm)

        self.apply_btn = PrimaryPushButton("Apply Changes")
        self.apply_btn.setIcon(mdi('check'))
        self.apply_btn.clicked.connect(self._apply_changes)
        btn_row.addWidget(self.apply_btn)

        self.reset_btn = PushButton("Reset")
        self.reset_btn.setIcon(mdi('refresh'))
        self.reset_btn.clicked.connect(self._reset_editor)
        btn_row.addWidget(self.reset_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        return scroll

    def _create_section_header(self, title: str) -> QWidget:
        header = SubtitleLabel(title)
        header.setStyleSheet(f"color: {Colors.text_primary}; margin-top: 4px;")
        return header

    def _create_divider(self) -> QFrame:
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"background-color: {Colors.border_subtle}; max-height: 1px;")
        return divider

    def _create_text_editor(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)

        layout.addWidget(self._create_section_header("Text Content"))

        token_row = QHBoxLayout()
        token_row.setSpacing(Spacing.sm)

        self.token_combo = ComboBox()
        self.token_combo.setMinimumWidth(180)
        self._populate_token_combo()
        token_row.addWidget(self.token_combo, 1)

        insert_btn = PushButton("Insert")
        insert_btn.clicked.connect(self._insert_token)
        token_row.addWidget(insert_btn)

        token_widget = QWidget()
        token_widget.setLayout(token_row)
        layout.addWidget(FormRow("Tokens", token_widget))

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Enter overlay text with tokens...")
        self.text_edit.setMaximumHeight(80)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.bg_input};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
                color: {Colors.text_primary};
                font-family: {Typography.family_mono};
                padding: 6px;
            }}
        """)
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        layout.addWidget(self._create_divider())

        layout.addWidget(self._create_section_header("Appearance"))

        self.font_size_spin = SpinBox()
        self.font_size_spin.setRange(8, 200)
        self.font_size_spin.setValue(24)
        self.font_size_spin.setSuffix(" px")
        self.font_size_spin.valueChanged.connect(self._on_appearance_changed)
        layout.addWidget(FormRow("Font Size", self.font_size_spin))

        self.color_combo = ComboBox()
        self.color_combo.addItems(COLOR_OPTIONS)
        self.color_combo.currentTextChanged.connect(self._on_appearance_changed)
        layout.addWidget(FormRow("Color", self.color_combo))

        self.font_style_combo = ComboBox()
        self.font_style_combo.addItems(["normal", "bold", "italic"])
        self.font_style_combo.currentTextChanged.connect(self._on_appearance_changed)
        layout.addWidget(FormRow("Style", self.font_style_combo))

        self.text_align_combo = ComboBox()
        self.text_align_combo.addItems(["left", "center", "right"])
        self.text_align_combo.setToolTip("Horizontal text alignment for multi-line text")
        self.text_align_combo.currentTextChanged.connect(self._on_appearance_changed)
        layout.addWidget(FormRow("Alignment", self.text_align_combo))

        self.bg_switch = SwitchRow("Background", "Draw rectangle behind text")
        self.bg_switch.toggled.connect(self._on_bg_toggle)
        layout.addWidget(self.bg_switch)

        self.bg_color_widget = QWidget()
        bg_layout = QVBoxLayout(self.bg_color_widget)
        bg_layout.setContentsMargins(0, 0, 0, 0)

        self.bg_color_combo = ComboBox()
        self.bg_color_combo.addItems(["black", "white", "darkgray", "lightgray"])
        self.bg_color_combo.currentTextChanged.connect(self._on_appearance_changed)
        bg_layout.addWidget(FormRow("BG Color", self.bg_color_combo))

        self.bg_color_widget.hide()
        layout.addWidget(self.bg_color_widget)

        return widget

    def _create_image_editor(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)

        layout.addWidget(self._create_section_header("Image File"))

        path_row = QHBoxLayout()
        path_row.setSpacing(Spacing.sm)

        self.image_path_edit = LineEdit()
        self.image_path_edit.setReadOnly(True)
        self.image_path_edit.setPlaceholderText("Select an image...")
        path_row.addWidget(self.image_path_edit, 1)

        browse_btn = PushButton("Browse")
        browse_btn.setIcon(mdi('folder-outline'))
        browse_btn.clicked.connect(self._browse_image)
        path_row.addWidget(browse_btn)

        path_widget = QWidget()
        path_widget.setLayout(path_row)
        layout.addWidget(FormRow("File", path_widget))

        layout.addWidget(self._create_divider())

        layout.addWidget(self._create_section_header("Size"))

        self.image_width_spin = SpinBox()
        self.image_width_spin.setRange(10, 2000)
        self.image_width_spin.setValue(100)
        self.image_width_spin.setSuffix(" px")
        self.image_width_spin.valueChanged.connect(self._on_image_size_changed)
        layout.addWidget(FormRow("Width", self.image_width_spin))

        self.image_height_spin = SpinBox()
        self.image_height_spin.setRange(10, 2000)
        self.image_height_spin.setValue(100)
        self.image_height_spin.setSuffix(" px")
        self.image_height_spin.valueChanged.connect(self._on_image_size_changed)
        layout.addWidget(FormRow("Height", self.image_height_spin))

        self.aspect_switch = SwitchRow("Lock Aspect", "Maintain proportions")
        self.aspect_switch.set_checked(True)
        self.aspect_switch.toggled.connect(self._on_aspect_toggle)
        layout.addWidget(self.aspect_switch)

        self.opacity_spin = SpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setValue(100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.valueChanged.connect(self._on_image_changed)
        layout.addWidget(FormRow("Opacity", self.opacity_spin))

        return widget

    def _create_compass_editor(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)

        layout.addWidget(self._create_section_header("Compass Settings"))

        self.compass_rotation_spin = SpinBox()
        self.compass_rotation_spin.setRange(0, 359)
        self.compass_rotation_spin.setSuffix("°")
        self.compass_rotation_spin.valueChanged.connect(self._on_compass_field_changed)
        layout.addWidget(FormRow("Rotation", self.compass_rotation_spin,
                                 "North direction offset in degrees"))

        self.compass_size_spin = SpinBox()
        self.compass_size_spin.setRange(40, 200)
        self.compass_size_spin.setValue(80)
        self.compass_size_spin.setSuffix(" px")
        self.compass_size_spin.valueChanged.connect(self._on_compass_field_changed)
        layout.addWidget(FormRow("Size", self.compass_size_spin,
                                 "Compass diameter in pixels"))

        self.compass_mirror_switch = SwitchRow(
            "Mirror E/W", "Swap East and West for mirror-flipped views")
        self.compass_mirror_switch.toggled.connect(self._on_compass_field_changed)
        layout.addWidget(self.compass_mirror_switch)

        compass_info = CaptionLabel(
            "Draws a compass rose showing N/S/E/W cardinal directions.\n"
            "Use Rotation to align North with your image orientation.\n"
            "Enable Mirror E/W if East and West sit on the wrong sides — "
            "rotation alone cannot fix a mirrored view.\n"
            "Position is set via the shared Anchor and Offset fields below."
        )
        compass_info.setStyleSheet(f"color: {Colors.text_muted}; padding: 4px;")
        compass_info.setWordWrap(True)
        layout.addWidget(compass_info)

        return widget
