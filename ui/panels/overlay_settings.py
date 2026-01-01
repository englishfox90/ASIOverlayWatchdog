"""
Overlay Settings Panel
Text/Image overlay configuration with list, preview, and editor
Matches the old Tkinter UI layout and features
"""
import os
import random
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QStackedWidget,
    QSizePolicy, QTextEdit, QSplitter, QHeaderView, QFileDialog,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QLabel
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QFont, QPen, QBrush

from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox, CheckBox, FluentIcon, TableWidget, Slider,
    SwitchButton
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..components.cards import FormRow, SwitchRow


# Token definitions organized with headers
TOKENS = [
    ("━━━ Camera ━━━", None),
    ("Camera", "{CAMERA}"),
    ("Exposure", "{EXPOSURE}"),
    ("Gain", "{GAIN}"),
    ("Temperature", "{TEMP}"),
    ("Resolution", "{RES}"),
    ("Session", "{SESSION}"),
    ("Date & Time", "{DATETIME}"),
    ("Filename", "{FILENAME}"),
    ("━━━ Image Stats ━━━", None),
    ("Brightness", "{BRIGHTNESS}"),
    ("Median", "{MEDIAN}"),
    ("Min Pixel", "{MIN}"),
    ("Max Pixel", "{MAX}"),
    ("━━━ Weather ━━━", None),
    ("Weather Temp", "{WEATHER_TEMP}"),
    ("Condition", "{WEATHER_CONDITION}"),
    ("Humidity", "{WEATHER_HUMIDITY}"),
    ("Wind Speed", "{WEATHER_WIND_SPEED}"),
]

ANCHOR_POSITIONS = [
    "Top-Left", "Top-Center", "Top-Right",
    "Bottom-Left", "Bottom-Center", "Bottom-Right",
]

COLOR_OPTIONS = [
    "white", "black", "lightgray", "darkgray",
    "red", "green", "blue", "cyan", "magenta", 
    "yellow", "orange", "purple", "pink", "lime"
]


class OverlaySettingsPanel(QWidget):
    """
    Overlay settings panel with 2-column layout:
    - Left: Overlay list + Preview
    - Right: Editor (text or image based on type)
    """
    
    settings_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._overlays = []
        self._selected_index = -1
        self._image_cache = {}  # Cache loaded overlay images
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {Colors.bg_app};")
        
        # Main horizontal layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        main_layout.setSpacing(Spacing.card_gap)
        
        # === LEFT COLUMN: List + Preview ===
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(Spacing.card_gap)
        
        # Overlay List Card
        list_card = self._create_list_card()
        left_layout.addWidget(list_card, stretch=1)
        
        # Preview Card
        preview_card = self._create_preview_card()
        left_layout.addWidget(preview_card, stretch=1)
        
        main_layout.addWidget(left_column, stretch=2)
        
        # === RIGHT COLUMN: Editor ===
        editor_card = self._create_editor_card()
        main_layout.addWidget(editor_card, stretch=3)
    
    def _create_list_card(self) -> CardWidget:
        """Create overlay list card with table-style appearance"""
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                  Spacing.card_padding, Spacing.card_padding)
        layout.setSpacing(Spacing.md)
        
        # Header
        header = SubtitleLabel("Overlay List")
        header.setStyleSheet(f"color: {Colors.text_primary};")
        layout.addWidget(header)
        
        # Action buttons - use fixed width to prevent overlap
        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.md)
        
        self.add_btn = PrimaryPushButton("Add")
        self.add_btn.setIcon(FluentIcon.ADD)
        self.add_btn.setFixedWidth(90)
        self.add_btn.clicked.connect(self._show_add_menu)
        btn_row.addWidget(self.add_btn)
        
        self.dup_btn = PushButton("Duplicate")
        self.dup_btn.setIcon(FluentIcon.COPY)
        self.dup_btn.setFixedWidth(115)
        self.dup_btn.clicked.connect(self._duplicate_overlay)
        btn_row.addWidget(self.dup_btn)
        
        self.del_btn = PushButton("Delete")
        self.del_btn.setIcon(FluentIcon.DELETE)
        self.del_btn.setFixedWidth(90)
        self.del_btn.clicked.connect(self._delete_overlay)
        btn_row.addWidget(self.del_btn)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)
        
        # Table widget for overlay list - clearer table styling
        self.overlay_table = TableWidget()
        self.overlay_table.setColumnCount(3)
        self.overlay_table.setHorizontalHeaderLabels(["Name", "Type", "Summary"])
        self.overlay_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.overlay_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.overlay_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.overlay_table.verticalHeader().setVisible(False)
        self.overlay_table.itemSelectionChanged.connect(self._on_overlay_selected)
        
        # Column widths
        header = self.overlay_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 120)
        header.resizeSection(1, 60)
        
        # Style the table
        self.overlay_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {Colors.bg_input};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
                gridline-color: {Colors.border_subtle};
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {Colors.border_subtle};
            }}
            QTableWidget::item:selected {{
                background-color: {Colors.accent_default};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {Colors.gray_8};
                color: {Colors.text_secondary};
                padding: 8px;
                border: none;
                border-bottom: 2px solid {Colors.border_subtle};
                font-weight: bold;
            }}
        """)
        
        layout.addWidget(self.overlay_table)
        
        return card
    
    def _create_preview_card(self) -> CardWidget:
        """Create preview card with rendered overlay"""
        card = CardWidget()
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                  Spacing.card_padding, Spacing.card_padding)
        layout.setSpacing(Spacing.md)
        
        header = SubtitleLabel("Preview")
        header.setStyleSheet(f"color: {Colors.text_primary};")
        layout.addWidget(header)
        
        # Preview container - fixed aspect ratio
        self.preview_container = QWidget()
        self.preview_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Preview label - will be manually painted
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(200, 150)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(f"""
            background-color: {Colors.gray_9};
            border: 1px solid {Colors.border_subtle};
            border-radius: {Layout.radius_md}px;
        """)
        container_layout.addWidget(self.preview_label)
        
        layout.addWidget(self.preview_container, stretch=1)
        
        # Generate initial preview
        self._generate_preview_background()
        
        return card
    
    def _generate_preview_background(self):
        """Generate a starry sky background for preview"""
        self._update_preview()
    
    def _update_preview(self):
        """Render all overlays on the preview"""
        # Get actual label size
        label_w = max(self.preview_label.width(), 200)
        label_h = max(self.preview_label.height(), 150)
        
        # Create pixmap at label size
        preview = QPixmap(label_w, label_h)
        preview.fill(QColor('#0a0e27'))
        
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw stars - seed for consistency
        random.seed(42)
        for _ in range(80):
            x = random.randint(5, label_w - 5)
            y = random.randint(5, label_h - 5)
            brightness = random.randint(150, 255)
            size = random.randint(1, 3)
            painter.setPen(QPen(QColor(brightness, brightness, brightness)))
            painter.setBrush(QColor(brightness, brightness, brightness))
            painter.drawEllipse(x, y, size, size)
        
        # Render only the selected overlay
        if self._selected_index >= 0 and self._selected_index < len(self._overlays):
            self._render_overlay(painter, self._overlays[self._selected_index], label_w, label_h)
        
        painter.end()
        self.preview_label.setPixmap(preview)
    
    def _render_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        """Render a single overlay onto the painter"""
        overlay_type = overlay.get('type', 'text')
        
        if overlay_type == 'image':
            self._render_image_overlay(painter, overlay, width, height)
        else:
            self._render_text_overlay(painter, overlay, width, height)
    
    def _render_text_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        """Render text overlay"""
        text = overlay.get('text', '')
        anchor = overlay.get('anchor', 'Bottom-Left')
        offset_x = overlay.get('offset_x', 15)
        offset_y = overlay.get('offset_y', 15)
        font_size = overlay.get('font_size', 24)
        font_style = overlay.get('font_style', 'normal')
        color = overlay.get('color', 'white')
        bg_enabled = overlay.get('bg_enabled', False)
        bg_color = overlay.get('bg_color', 'transparent')
        
        # Replace tokens with sample values
        sample_text = self._substitute_tokens(text)
        if not sample_text.strip():
            return
        
        # Scale font size proportionally (preview is smaller than actual image)
        # Assume actual image is ~1920px wide, scale down
        scale = max(0.1, width / 800.0)  # Use 800 as reference, minimum scale 0.1
        scaled_font_size = max(8, int(font_size * scale))
        
        # Setup font - ensure valid point size
        font = QFont()
        font.setPointSize(max(1, scaled_font_size))
        if font_style == 'bold':
            font.setBold(True)
        elif font_style == 'italic':
            font.setItalic(True)
        painter.setFont(font)
        
        # Calculate text bounds
        metrics = painter.fontMetrics()
        lines = sample_text.split('\n')
        text_width = max(metrics.horizontalAdvance(line) for line in lines) if lines else 0
        line_height = metrics.height()
        text_height = line_height * len(lines)
        
        # Scale offsets too
        scaled_offset_x = int(offset_x * scale)
        scaled_offset_y = int(offset_y * scale)
        margin = int(10 * scale)
        
        # Calculate position based on anchor
        if 'Left' in anchor:
            x = margin + scaled_offset_x
        elif 'Right' in anchor:
            x = width - text_width - margin - scaled_offset_x
        else:  # Center
            x = (width - text_width) // 2 + scaled_offset_x
        
        if 'Top' in anchor:
            y = margin + line_height + scaled_offset_y
        elif 'Bottom' in anchor:
            y = height - text_height - margin + line_height - scaled_offset_y
        else:  # Center
            y = (height - text_height) // 2 + line_height + scaled_offset_y
        
        # Draw background rectangle if enabled
        if bg_enabled and bg_color != 'transparent':
            bg_qcolor = QColor(bg_color)
            bg_qcolor.setAlpha(180)
            padding = int(5 * scale)
            painter.fillRect(
                int(x - padding), int(y - line_height - padding//2),
                int(text_width + padding*2), int(text_height + padding),
                bg_qcolor
            )
        
        # Draw text
        painter.setPen(QColor(color))
        for i, line in enumerate(lines):
            painter.drawText(int(x), int(y + i * line_height), line)
    
    def _render_image_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        """Render image overlay"""
        image_path = overlay.get('image_path', '')
        if not image_path or not os.path.exists(image_path):
            return
        
        anchor = overlay.get('anchor', 'Bottom-Right')
        offset_x = overlay.get('offset_x', 15)
        offset_y = overlay.get('offset_y', 15)
        img_width = overlay.get('width', 100)
        img_height = overlay.get('height', 100)
        opacity = overlay.get('opacity', 100) / 100.0
        
        # Load image (with caching)
        if image_path not in self._image_cache:
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                return
            self._image_cache[image_path] = pixmap
        else:
            pixmap = self._image_cache[image_path]
        
        # Scale for preview (assume 800 reference width)
        scale = width / 800.0
        scaled_w = max(10, int(img_width * scale))
        scaled_h = max(10, int(img_height * scale))
        scaled_offset_x = int(offset_x * scale)
        scaled_offset_y = int(offset_y * scale)
        margin = int(10 * scale)
        
        # Scale pixmap
        scaled_pixmap = pixmap.scaled(scaled_w, scaled_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        actual_w = scaled_pixmap.width()
        actual_h = scaled_pixmap.height()
        
        # Calculate position based on anchor
        if 'Left' in anchor:
            x = margin + scaled_offset_x
        elif 'Right' in anchor:
            x = width - actual_w - margin - scaled_offset_x
        else:  # Center
            x = (width - actual_w) // 2 + scaled_offset_x
        
        if 'Top' in anchor:
            y = margin + scaled_offset_y
        elif 'Bottom' in anchor:
            y = height - actual_h - margin - scaled_offset_y
        else:  # Center
            y = (height - actual_h) // 2 + scaled_offset_y
        
        # Draw with opacity
        old_opacity = painter.opacity()
        painter.setOpacity(opacity)
        painter.drawPixmap(int(x), int(y), scaled_pixmap)
        painter.setOpacity(old_opacity)
    
    def _substitute_tokens(self, text: str) -> str:
        """Replace tokens with sample values"""
        result = text
        result = result.replace('{CAMERA}', 'ASI676MC')
        result = result.replace('{EXPOSURE}', '100ms')
        result = result.replace('{GAIN}', '150')
        result = result.replace('{TEMP}', '25°C')
        result = result.replace('{RES}', '1920x1080')
        result = result.replace('{SESSION}', '2026-01-01')
        result = result.replace('{DATETIME}', '2026-01-01 20:30:00')
        result = result.replace('{FILENAME}', 'capture_001.png')
        result = result.replace('{BRIGHTNESS}', '128')
        result = result.replace('{WEATHER_TEMP}', '15°C')
        result = result.replace('{WEATHER_CONDITION}', 'Clear')
        result = result.replace('{WEATHER_HUMIDITY}', '45%')
        result = result.replace('{WEATHER_WIND_SPEED}', '5 km/h')
        return result
    
    def _create_editor_card(self) -> QScrollArea:
        """Create overlay editor as flat scrollable area (Windows 11 Settings style)"""
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
        
        # === BASIC INFO ===
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("Overlay name")
        self.name_edit.textChanged.connect(self._on_name_changed)
        layout.addWidget(FormRow("Name", self.name_edit))
        
        self.type_combo = ComboBox()
        self.type_combo.addItems(["Text", "Image"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        layout.addWidget(FormRow("Type", self.type_combo))
        
        # Divider
        layout.addWidget(self._create_divider())
        
        # === STACKED WIDGET FOR TEXT/IMAGE EDITORS ===
        self.editor_stack = QStackedWidget()
        
        # Text editor widget
        text_widget = self._create_text_editor()
        self.editor_stack.addWidget(text_widget)
        
        # Image editor widget
        image_widget = self._create_image_editor()
        self.editor_stack.addWidget(image_widget)
        
        layout.addWidget(self.editor_stack)
        
        # Divider
        layout.addWidget(self._create_divider())
        
        # === POSITION (shared) ===
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
        
        # === ACTION BUTTONS ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.sm)
        
        self.apply_btn = PrimaryPushButton("Apply Changes")
        self.apply_btn.setIcon(FluentIcon.ACCEPT)
        self.apply_btn.clicked.connect(self._apply_changes)
        btn_row.addWidget(self.apply_btn)
        
        self.reset_btn = PushButton("Reset")
        self.reset_btn.setIcon(FluentIcon.SYNC)
        self.reset_btn.clicked.connect(self._reset_editor)
        btn_row.addWidget(self.reset_btn)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)
        
        return scroll
    
    def _create_section_header(self, title: str) -> QWidget:
        """Create a simple section header (Windows 11 style)"""
        header = SubtitleLabel(title)
        header.setStyleSheet(f"color: {Colors.text_primary}; margin-top: 4px;")
        return header
    
    def _create_divider(self) -> QFrame:
        """Create a subtle horizontal divider"""
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"background-color: {Colors.border_subtle}; max-height: 1px;")
        return divider
    
    def _create_text_editor(self) -> QWidget:
        """Create text-specific editor widget (flat layout)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)
        
        # Section header
        layout.addWidget(self._create_section_header("Text Content"))
        
        # Token dropdown with insert button
        token_row = QHBoxLayout()
        token_row.setSpacing(Spacing.sm)
        
        self.token_combo = ComboBox()
        self.token_combo.setMinimumWidth(180)
        token_items = [label for label, token in TOKENS if token is not None]
        self.token_combo.addItems(token_items)
        token_row.addWidget(self.token_combo, 1)
        
        insert_btn = PushButton("Insert")
        insert_btn.clicked.connect(self._insert_token)
        token_row.addWidget(insert_btn)
        
        token_widget = QWidget()
        token_widget.setLayout(token_row)
        layout.addWidget(FormRow("Tokens", token_widget))
        
        # Text edit
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
        
        # Divider
        layout.addWidget(self._create_divider())
        
        # Appearance section
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
        
        # Background toggle
        self.bg_switch = SwitchRow("Background", "Draw rectangle behind text")
        self.bg_switch.toggled.connect(self._on_bg_toggle)
        layout.addWidget(self.bg_switch)
        
        # Background color (conditional)
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
        """Create image-specific editor widget (flat layout)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)
        
        # Section header
        layout.addWidget(self._create_section_header("Image File"))
        
        # File path with browse button
        path_row = QHBoxLayout()
        path_row.setSpacing(Spacing.sm)
        
        self.image_path_edit = LineEdit()
        self.image_path_edit.setReadOnly(True)
        self.image_path_edit.setPlaceholderText("Select an image...")
        path_row.addWidget(self.image_path_edit, 1)
        
        browse_btn = PushButton("Browse")
        browse_btn.setIcon(FluentIcon.FOLDER)
        browse_btn.clicked.connect(self._browse_image)
        path_row.addWidget(browse_btn)
        
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        layout.addWidget(FormRow("File", path_widget))
        
        # Divider
        layout.addWidget(self._create_divider())
        
        # Size section
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
        
        # Opacity
        self.opacity_spin = SpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setValue(100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.valueChanged.connect(self._on_image_changed)
        layout.addWidget(FormRow("Opacity", self.opacity_spin))
        
        return widget
    
    # === LIST OPERATIONS ===
    
    def _refresh_list(self):
        """Refresh overlay table display"""
        self.overlay_table.setRowCount(0)
        for i, overlay in enumerate(self._overlays):
            self.overlay_table.insertRow(i)
            
            name = overlay.get('name', 'Unnamed')
            otype = overlay.get('type', 'text').capitalize()
            
            # Build summary based on type
            if otype == 'Image':
                path = overlay.get('image_path', '')
                summary = os.path.basename(path) if path else overlay.get('anchor', 'Bottom-Right')
            else:
                text = overlay.get('text', '')
                summary = text[:35].replace('\n', ' ')
                if len(text) > 35:
                    summary += '...'
                if not summary:
                    summary = overlay.get('anchor', 'Bottom-Left')
            
            from PySide6.QtWidgets import QTableWidgetItem
            self.overlay_table.setItem(i, 0, QTableWidgetItem(name))
            self.overlay_table.setItem(i, 1, QTableWidgetItem(otype))
            self.overlay_table.setItem(i, 2, QTableWidgetItem(summary))
    
    def _show_add_menu(self):
        """Show menu to add text or image overlay"""
        from qfluentwidgets import RoundMenu, Action
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.FONT, "Add Text Overlay", triggered=self._add_text_overlay))
        menu.addAction(Action(FluentIcon.PHOTO, "Add Image Overlay", triggered=self._add_image_overlay))
        
        # Show below the button
        pos = self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft())
        menu.exec(pos)
    
    def _add_text_overlay(self):
        """Add new text overlay"""
        new_overlay = {
            'name': f'Text {len(self._overlays) + 1}',
            'type': 'text',
            'text': '{CAMERA}\n{EXPOSURE}',
            'anchor': 'Bottom-Left',
            'offset_x': 15,
            'offset_y': 15,
            'font_size': 24,
            'font_style': 'normal',
            'color': 'white',
            'bg_enabled': False,
            'bg_color': 'transparent'
        }
        self._overlays.append(new_overlay)
        self._refresh_list()
        self.overlay_table.selectRow(len(self._overlays) - 1)
        self._save_overlays()
    
    def _add_image_overlay(self):
        """Add new image overlay"""
        new_overlay = {
            'name': f'Image {len(self._overlays) + 1}',
            'type': 'image',
            'image_path': '',
            'anchor': 'Bottom-Right',
            'offset_x': 15,
            'offset_y': 15,
            'width': 100,
            'height': 100,
            'opacity': 100,
            'maintain_aspect': True
        }
        self._overlays.append(new_overlay)
        self._refresh_list()
        self.overlay_table.selectRow(len(self._overlays) - 1)
        self._save_overlays()
    
    def _duplicate_overlay(self):
        """Duplicate selected overlay"""
        if self._selected_index >= 0 and self._selected_index < len(self._overlays):
            original = self._overlays[self._selected_index]
            duplicate = original.copy()
            duplicate['name'] = f"{original.get('name', 'Overlay')} Copy"
            self._overlays.append(duplicate)
            self._refresh_list()
            self.overlay_table.selectRow(len(self._overlays) - 1)
            self._save_overlays()
    
    def _delete_overlay(self):
        """Delete selected overlay"""
        if self._selected_index >= 0 and self._selected_index < len(self._overlays):
            del self._overlays[self._selected_index]
            self._refresh_list()
            self._selected_index = -1
            self._clear_editor()
            self._save_overlays()
            self._update_preview()
    
    def _on_overlay_selected(self):
        """Handle overlay selection"""
        rows = self.overlay_table.selectedIndexes()
        if rows:
            self._selected_index = rows[0].row()
            if self._selected_index >= 0 and self._selected_index < len(self._overlays):
                self._load_overlay_to_editor(self._overlays[self._selected_index])
                self._update_preview()
        else:
            self._selected_index = -1
            self._clear_editor()
            self._update_preview()
    
    # === EDITOR OPERATIONS ===
    
    def _load_overlay_to_editor(self, overlay: dict):
        """Load overlay data into editor fields"""
        # Block signals while loading
        self._block_all_signals(True)
        
        self.name_edit.setText(overlay.get('name', ''))
        
        overlay_type = overlay.get('type', 'text')
        type_idx = 0 if overlay_type == 'text' else 1
        self.type_combo.setCurrentIndex(type_idx)
        self.editor_stack.setCurrentIndex(type_idx)
        
        if overlay_type == 'text':
            self.text_edit.setPlainText(overlay.get('text', ''))
            self.font_size_spin.setValue(overlay.get('font_size', 24))
            
            color = overlay.get('color', 'white')
            idx = self.color_combo.findText(color)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
            
            style = overlay.get('font_style', 'normal')
            idx = self.font_style_combo.findText(style)
            if idx >= 0:
                self.font_style_combo.setCurrentIndex(idx)
            
            bg_enabled = overlay.get('bg_enabled', False)
            self.bg_switch.set_checked(bg_enabled)
            self.bg_color_widget.setVisible(bg_enabled)
            
            bg_color = overlay.get('bg_color', 'black')
            idx = self.bg_color_combo.findText(bg_color)
            if idx >= 0:
                self.bg_color_combo.setCurrentIndex(idx)
        else:  # image
            self.image_path_edit.setText(overlay.get('image_path', ''))
            self.image_width_spin.setValue(overlay.get('width', 100))
            self.image_height_spin.setValue(overlay.get('height', 100))
            self.opacity_spin.setValue(overlay.get('opacity', 100))
            self.aspect_switch.set_checked(overlay.get('maintain_aspect', True))
        
        # Position (shared)
        anchor = overlay.get('anchor', 'Bottom-Left')
        idx = self.anchor_combo.findText(anchor)
        if idx >= 0:
            self.anchor_combo.setCurrentIndex(idx)
        
        self.offset_x_spin.setValue(overlay.get('offset_x', 15))
        self.offset_y_spin.setValue(overlay.get('offset_y', 15))
        
        self._block_all_signals(False)
    
    def _block_all_signals(self, block: bool):
        """Block/unblock signals on all editor widgets"""
        widgets = [
            self.name_edit, self.type_combo, self.text_edit,
            self.font_size_spin, self.color_combo, self.font_style_combo,
            self.bg_color_combo,
            self.image_path_edit, self.image_width_spin, self.image_height_spin,
            self.opacity_spin,
            self.anchor_combo, self.offset_x_spin, self.offset_y_spin
        ]
        for w in widgets:
            w.blockSignals(block)
        # Block SwitchRow signals via their internal switch
        self.bg_switch.switch.blockSignals(block)
        self.aspect_switch.switch.blockSignals(block)
    
    def _clear_editor(self):
        """Clear editor fields"""
        self._block_all_signals(True)
        self.name_edit.clear()
        self.type_combo.setCurrentIndex(0)
        self.editor_stack.setCurrentIndex(0)
        self.text_edit.clear()
        self.font_size_spin.setValue(24)
        self.color_combo.setCurrentIndex(0)
        self.font_style_combo.setCurrentIndex(0)
        self.bg_switch.set_checked(False)
        self.bg_color_widget.hide()
        self.image_path_edit.clear()
        self.image_width_spin.setValue(100)
        self.image_height_spin.setValue(100)
        self.opacity_spin.setValue(100)
        self.aspect_switch.set_checked(True)
        self.anchor_combo.setCurrentIndex(0)
        self.offset_x_spin.setValue(15)
        self.offset_y_spin.setValue(15)
        self._block_all_signals(False)
    
    def _update_current_overlay(self):
        """Update current overlay from editor values"""
        if self._selected_index >= 0 and self._selected_index < len(self._overlays):
            overlay = self._overlays[self._selected_index]
            overlay['name'] = self.name_edit.text()
            overlay['type'] = 'text' if self.type_combo.currentIndex() == 0 else 'image'
            
            if overlay['type'] == 'text':
                overlay['text'] = self.text_edit.toPlainText()
                overlay['font_size'] = self.font_size_spin.value()
                overlay['color'] = self.color_combo.currentText()
                overlay['font_style'] = self.font_style_combo.currentText()
                overlay['bg_enabled'] = self.bg_switch.is_checked()
                overlay['bg_color'] = self.bg_color_combo.currentText()
            else:
                overlay['image_path'] = self.image_path_edit.text()
                overlay['width'] = self.image_width_spin.value()
                overlay['height'] = self.image_height_spin.value()
                overlay['opacity'] = self.opacity_spin.value()
                overlay['maintain_aspect'] = self.aspect_switch.is_checked()
            
            # Position (shared)
            overlay['anchor'] = self.anchor_combo.currentText()
            overlay['offset_x'] = self.offset_x_spin.value()
            overlay['offset_y'] = self.offset_y_spin.value()
    
    def _insert_token(self):
        """Insert selected token into text editor"""
        selected_label = self.token_combo.currentText()
        for label, token in TOKENS:
            if label == selected_label and token is not None:
                self.text_edit.insertPlainText(token)
                break
    
    def _browse_image(self):
        """Browse for image file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Overlay Image",
            "",
            "Images (*.png *.jpg *.jpeg *.gif *.bmp);;All Files (*)"
        )
        if file_path:
            self.image_path_edit.setText(file_path)
            # Clear cache for this image
            if file_path in self._image_cache:
                del self._image_cache[file_path]
            self._on_image_changed()
    
    # === EVENT HANDLERS ===
    
    def _on_type_changed(self, text):
        """Handle type change"""
        self.editor_stack.setCurrentIndex(0 if text == "Text" else 1)
        self._update_current_overlay()
        self._refresh_list()
        self._update_preview()
    
    def _on_name_changed(self, text):
        self._update_current_overlay()
        self._refresh_list()
    
    def _on_text_changed(self):
        self._update_current_overlay()
        self._refresh_list()
        self._update_preview()
    
    def _on_appearance_changed(self):
        self._update_current_overlay()
        self._update_preview()
    
    def _on_position_changed(self):
        self._update_current_overlay()
        self._update_preview()
    
    def _on_bg_toggle(self, state):
        self.bg_color_widget.setVisible(bool(state))
        self._update_current_overlay()
        self._update_preview()
    
    def _on_image_changed(self):
        self._update_current_overlay()
        self._refresh_list()
        self._update_preview()
    
    def _on_image_size_changed(self):
        """Handle image size change with aspect ratio"""
        if self.aspect_switch.is_checked():
            # Update height based on width if we have an image
            image_path = self.image_path_edit.text()
            if image_path and os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    aspect = pixmap.height() / pixmap.width() if pixmap.width() > 0 else 1
                    sender = self.sender()
                    if sender == self.image_width_spin:
                        self.image_height_spin.blockSignals(True)
                        self.image_height_spin.setValue(int(self.image_width_spin.value() * aspect))
                        self.image_height_spin.blockSignals(False)
                    elif sender == self.image_height_spin:
                        self.image_width_spin.blockSignals(True)
                        self.image_width_spin.setValue(int(self.image_height_spin.value() / aspect))
                        self.image_width_spin.blockSignals(False)
        
        self._update_current_overlay()
        self._update_preview()
    
    def _on_aspect_toggle(self, state):
        """Handle aspect ratio toggle"""
        self._on_image_size_changed()
    
    def _apply_changes(self):
        """Save changes to config"""
        self._update_current_overlay()
        self._save_overlays()
    
    def _reset_editor(self):
        """Reset editor to saved values"""
        if self._selected_index >= 0 and self._selected_index < len(self._overlays):
            self._load_overlay_to_editor(self._overlays[self._selected_index])
    
    def _save_overlays(self):
        """Save overlays to config"""
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('overlays', self._overlays)
            self.settings_changed.emit()
    
    # === CONFIG LOADING ===
    
    def load_from_config(self, config):
        """Load overlays from config"""
        self._overlays = config.get('overlays', [])
        self._refresh_list()
        self._selected_index = -1
        self._clear_editor()
        self._update_preview()
    
    def resizeEvent(self, event):
        """Update preview on resize"""
        super().resizeEvent(event)
        # Delayed update to avoid excessive redraws
        QTimer.singleShot(100, self._update_preview)
