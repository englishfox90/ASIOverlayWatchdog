"""
All-Sky Overlay Settings Panel.

Provides:
  - Calibration status + "Calibrate Now" button
  - Layer toggles: Grid, Constellations, Messier, NGC, Planets
  - Per-layer color, opacity, line width controls
  - Enabled/disabled master toggle
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QGridLayout, QSizePolicy, QProgressBar, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from qfluentwidgets import (
    PushButton, SwitchButton, SpinBox,
    CardWidget, CaptionLabel, BodyLabel, SubtitleLabel,
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import CollapsibleCard


def _section_card(title: str) -> tuple:
    """Create a labelled card widget. Returns (card, inner_layout)."""
    card = CardWidget()
    card.setStyleSheet(f"CardWidget {{ border-radius: {Layout.radius_md}px; }}")
    vl = QVBoxLayout(card)
    vl.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.lg)
    vl.setSpacing(Spacing.sm)

    lbl = SubtitleLabel(title)
    vl.addWidget(lbl)
    return card, vl


class LayerToggleRow(QWidget):
    """A row with a label + SwitchButton for a single layer toggle."""

    toggled = Signal(bool)

    def __init__(self, label: str, default: bool = True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = BodyLabel(label)
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._switch = SwitchButton()
        self._switch.setChecked(default)
        self._switch.checkedChanged.connect(self.toggled)
        layout.addWidget(lbl)
        layout.addWidget(self._switch)

    def is_checked(self) -> bool:
        return self._switch.isChecked()

    def set_checked(self, v: bool) -> None:
        self._switch.setChecked(v)


# 10 preset overlay colors — bright enough to read against a dark sky
OVERLAY_PALETTE = [
    ('#4488FF', 'Blue'),
    ('#FF8844', 'Orange'),
    ('#88FF44', 'Green'),
    ('#FF4444', 'Red'),
    ('#44DDFF', 'Cyan'),
    ('#FFDD44', 'Yellow'),
    ('#AA66FF', 'Purple'),
    ('#FF66AA', 'Pink'),
    ('#FFFFFF', 'White'),
    ('#44FFAA', 'Teal'),
]


class _ColorPopup(QFrame):
    """Popup grid of color swatches shown when the color button is clicked."""

    color_picked = Signal(str)

    def __init__(self, selected: str, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(
            "QFrame { background: #2b2b2b; border: 1px solid #555; border-radius: 6px; }"
        )
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(4)

        cols = 5
        for i, (hex_color, name) in enumerate(OVERLAY_PALETTE):
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setToolTip(name)
            btn.setCursor(Qt.PointingHandCursor)
            if hex_color == selected:
                border = '2px solid #FFFFFF'
            else:
                border = '2px solid transparent'
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_color}; border: {border}; "
                f"border-radius: 4px; min-width: 28px; min-height: 28px; }}"
                f"QPushButton:hover {{ border: 2px solid #AAAAAA; }}"
            )
            btn.clicked.connect(lambda _=False, c=hex_color: self._pick(c))
            grid.addWidget(btn, i // cols, i % cols)

    def _pick(self, color: str) -> None:
        self.color_picked.emit(color)
        self.close()


class ColorPaletteRow(QWidget):
    """Label + single color swatch (right-aligned) that opens a popup picker."""

    color_changed = Signal(str)

    def __init__(self, default_color: str = '#4488FF', parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        lbl = BodyLabel("Color")
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(lbl)

        self._selected = default_color
        self._swatch = QPushButton()
        self._swatch.setFixedSize(32, 22)
        self._swatch.setCursor(Qt.PointingHandCursor)
        self._swatch.clicked.connect(self._show_popup)
        layout.addWidget(self._swatch)

        self._update_swatch()

    def _show_popup(self) -> None:
        popup = _ColorPopup(self._selected, self)
        popup.color_picked.connect(self._select)
        # Position below the swatch button
        pos = self._swatch.mapToGlobal(self._swatch.rect().bottomLeft())
        popup.move(pos.x(), pos.y() + 2)
        popup.show()

    def _select(self, color: str) -> None:
        self._selected = color
        self._update_swatch()
        self.color_changed.emit(color)

    def _update_swatch(self) -> None:
        self._swatch.setStyleSheet(
            f"QPushButton {{ background: {self._selected}; border: 2px solid #888; "
            f"border-radius: 4px; min-width: 32px; min-height: 22px; }}"
            f"QPushButton:hover {{ border: 2px solid #FFFFFF; }}"
        )
        # Find the color name for the tooltip
        name = self._selected
        for hex_color, color_name in OVERLAY_PALETTE:
            if hex_color == self._selected:
                name = color_name
                break
        self._swatch.setToolTip(name)

    def selected_color(self) -> str:
        return self._selected

    def set_color(self, color: str) -> None:
        self._selected = color
        self._update_swatch()


class QualityBadge(QFrame):
    """Colored pill badge showing the current calibration quality level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(4)

        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        layout.addWidget(self._dot)

        self._label = CaptionLabel("Not calibrated")
        layout.addWidget(self._label)

        self.setFixedHeight(26)
        self.set_quality('none')

    def set_quality(self, level: str) -> None:
        from services.allsky.calibration_service import CalibrationQuality
        bg, text = CalibrationQuality.badge_colors(level)
        desc = CalibrationQuality.description(level)
        label = level.capitalize() if level != 'none' else 'None'

        self._label.setText(label)
        self.setToolTip(desc)
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border-radius: 13px; }}"
        )
        self._label.setStyleSheet(
            f"color: {text}; font-size: 11px; font-weight: 600;"
        )
        self._dot.setStyleSheet(
            f"background: {text}; border-radius: 4px;"
        )


class AllSkySettingsPanel(QScrollArea):
    """
    Scrollable settings panel for the All-Sky overlay feature.
    Panels are UI-only — business logic is in AllSkyController.
    """

    # Emitted whenever a setting changes so controller can save config
    settings_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        self.setWidget(inner)
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        self._layout.setSpacing(Spacing.sm)

        self._build_header()
        self._build_calibration_card()
        self._build_master_toggle()
        self._build_constellations_card()
        self._build_bright_stars_card()
        self._build_messier_card()
        self._build_ngc_card()
        self._build_planets_card()

        self._layout.addStretch()

    # ------------------------------------------------------------------
    # Build sections
    # ------------------------------------------------------------------

    def _build_header(self):
        title = SubtitleLabel("All-Sky Overlay")
        self._layout.addWidget(title)
        desc = CaptionLabel(
            "Overlay constellation lines, DSO labels, and planet positions on each frame.\n"
            "Requires fisheye lens calibration before first use."
        )
        desc.setWordWrap(True)
        self._layout.addWidget(desc)

    def _build_calibration_card(self):
        card, vl = _section_card("Lens Calibration")

        # Quality badge + status label row
        badge_row = QHBoxLayout()
        self._quality_badge = QualityBadge()
        badge_row.addWidget(self._quality_badge)
        badge_row.addStretch()
        vl.addLayout(badge_row)

        self._status_label = BodyLabel("Not calibrated")
        self._status_label.setWordWrap(True)
        vl.addWidget(self._status_label)

        self._calibrate_btn = PushButton("Calibrate Now", icon=mdi('refresh'))
        self._calibrate_btn.clicked.connect(self._on_calibrate_clicked)
        vl.addWidget(self._calibrate_btn)

        # Guided fallback for hard installs (obstructed / near-vertical / hazy)
        # where automatic calibration can't determine orientation.
        self._guided_btn = PushButton("Guided Calibration…", icon=mdi('target'))
        self._guided_btn.clicked.connect(self._on_guided_clicked)
        vl.addWidget(self._guided_btn)

        self._layout.addWidget(card)

    def _build_master_toggle(self):
        card, vl = _section_card("Enable Overlay")
        self._master_toggle = LayerToggleRow("All-Sky overlay enabled", default=False)
        self._master_toggle.toggled.connect(self._on_setting_changed)
        vl.addWidget(self._master_toggle)
        self._top_n = self._spin_row(vl, "Max objects visible", 5, 50, 15, 5)
        self._layout.addWidget(card)

    def _build_constellations_card(self):
        card = CollapsibleCard("Constellations", mdi('vector-polyline'))
        self._con_enabled = LayerToggleRow("Show constellations", default=True)
        self._con_lines = LayerToggleRow("Lines", default=True)
        self._con_labels = LayerToggleRow("Labels", default=True)
        for row in (self._con_enabled, self._con_lines, self._con_labels):
            row.toggled.connect(self._on_setting_changed)
            card.add_widget(row)
        self._con_color = ColorPaletteRow('#4488FF')
        self._con_color.color_changed.connect(self._on_setting_changed)
        card.add_widget(self._con_color)
        self._layout.addWidget(card)

    def _build_bright_stars_card(self):
        card = CollapsibleCard("Bright Stars", mdi('star-four-points'))
        self._stars_enabled = LayerToggleRow("Show named bright stars", default=False)
        self._stars_enabled.toggled.connect(self._on_setting_changed)
        card.add_widget(self._stars_enabled)
        self._stars_max_mag = self._spin_row_in(card, "Max magnitude", 1, 5, 3, 1)
        self._stars_bayer = LayerToggleRow("Use Bayer designation when unnamed", default=False)
        self._stars_bayer.toggled.connect(self._on_setting_changed)
        card.add_widget(self._stars_bayer)
        self._stars_color = ColorPaletteRow('#FFDD44')
        self._stars_color.color_changed.connect(self._on_setting_changed)
        card.add_widget(self._stars_color)
        self._layout.addWidget(card)

    def _build_messier_card(self):
        card = CollapsibleCard("Messier Objects", mdi('blur'))
        self._messier_enabled = LayerToggleRow("Show Messier objects", default=True)
        self._messier_enabled.toggled.connect(self._on_setting_changed)
        card.add_widget(self._messier_enabled)
        self._messier_color = ColorPaletteRow('#FF8844')
        self._messier_color.color_changed.connect(self._on_setting_changed)
        card.add_widget(self._messier_color)
        self._layout.addWidget(card)

    def _build_ngc_card(self):
        card = CollapsibleCard("NGC/IC Objects", mdi('telescope'))
        self._ngc_enabled = LayerToggleRow("Show NGC objects (mag filtered)", default=False)
        self._ngc_enabled.toggled.connect(self._on_setting_changed)
        card.add_widget(self._ngc_enabled)
        self._ngc_max_mag = self._spin_row_in(card, "Max magnitude", 5, 12, 8, 1)
        self._ngc_color = ColorPaletteRow('#88FF44')
        self._ngc_color.color_changed.connect(self._on_setting_changed)
        card.add_widget(self._ngc_color)
        self._layout.addWidget(card)

    def _build_planets_card(self):
        card = CollapsibleCard("Planets & Moon", mdi('orbit'))
        self._planets_enabled = LayerToggleRow("Show planets & Moon", default=True)
        self._planets_enabled.toggled.connect(self._on_setting_changed)
        card.add_widget(self._planets_enabled)
        self._planets_color = ColorPaletteRow('#FFFFCC')
        self._planets_color.color_changed.connect(self._on_setting_changed)
        card.add_widget(self._planets_color)
        self._layout.addWidget(card)

    def _spin_row(self, layout, label: str, min_v: int, max_v: int,
                  default: int, step: int) -> SpinBox:
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label))
        spin = SpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(default)
        spin.setSingleStep(step)
        spin.valueChanged.connect(self._on_setting_changed)
        row.addWidget(spin)
        layout.addLayout(row)
        return spin

    def _spin_row_in(self, card: CollapsibleCard, label: str, min_v: int, max_v: int,
                     default: int, step: int) -> SpinBox:
        spin = SpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(default)
        spin.setSingleStep(step)
        spin.valueChanged.connect(self._on_setting_changed)
        card.add_row(label, spin)
        return spin

    # ------------------------------------------------------------------
    # Public API (called by controller)
    # ------------------------------------------------------------------

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def set_quality(self, level: str) -> None:
        """Update the calibration quality badge."""
        self._quality_badge.set_quality(level)

    def set_calibrating(self, active: bool) -> None:
        self._calibrate_btn.setEnabled(not active)
        self._calibrate_btn.setText("Calibrating…" if active else "Calibrate Now")

    def load_from_config(self, config: dict) -> None:
        """Populate all controls from the given allsky_overlay config dict."""
        c = config
        self._master_toggle.set_checked(c.get('enabled', False))
        self._top_n.setValue(int(c.get('top_n', 15)))

        con = c.get('constellations', {})
        self._con_enabled.set_checked(con.get('enabled', True))
        self._con_lines.set_checked(con.get('lines', True))
        self._con_labels.set_checked(con.get('labels', True))
        self._con_color.set_color(con.get('color', '#4488FF'))

        stars = c.get('bright_stars', {})
        self._stars_enabled.set_checked(stars.get('enabled', False))
        self._stars_max_mag.setValue(int(round(float(stars.get('max_magnitude', 3)))))
        self._stars_bayer.set_checked(stars.get('bayer_fallback', False))
        self._stars_color.set_color(stars.get('color', '#FFDD44'))

        messier = c.get('messier', {})
        self._messier_enabled.set_checked(messier.get('enabled', True))
        self._messier_color.set_color(messier.get('color', '#FF8844'))

        ngc = c.get('ngc', {})
        self._ngc_enabled.set_checked(ngc.get('enabled', False))
        self._ngc_max_mag.setValue(int(ngc.get('min_magnitude', 8)))
        self._ngc_color.set_color(ngc.get('color', '#88FF44'))

        planets = c.get('planets', {})
        self._planets_enabled.set_checked(planets.get('enabled', True))
        self._planets_color.set_color(planets.get('color', '#FFFFCC'))

    def get_config(self) -> dict:
        """Collect current UI state into allsky_overlay config dict."""
        return {
            'enabled': self._master_toggle.is_checked(),
            'calibration_file': '',  # Preserved by controller from actual config
            'top_n': self._top_n.value(),
            'grid': {
                'enabled': False, 'horizon': False,
                'altitude_rings': False, 'cardinal_labels': False,
                'altitude_step': 30, 'azimuth_lines': False,
                'color': '#336633', 'line_width': 1,
                'label_size': 14, 'opacity': 120,
            },
            'constellations': {
                'enabled': self._con_enabled.is_checked(),
                'lines': self._con_lines.is_checked(),
                'labels': self._con_labels.is_checked(),
                'color': self._con_color.selected_color(),
                'line_width': 2, 'label_size': 12, 'opacity': 180,
            },
            'bright_stars': {
                'enabled': self._stars_enabled.is_checked(),
                'max_magnitude': float(self._stars_max_mag.value()),
                'bayer_fallback': self._stars_bayer.is_checked(),
                'color': self._stars_color.selected_color(),
                'label_size': 11, 'opacity': 220,
            },
            'messier': {
                'enabled': self._messier_enabled.is_checked(),
                'color': self._messier_color.selected_color(),
                'marker_size': 8, 'label_size': 10, 'opacity': 200,
            },
            'ngc': {
                'enabled': self._ngc_enabled.is_checked(),
                'min_magnitude': float(self._ngc_max_mag.value()),
                'color': self._ngc_color.selected_color(),
                'marker_size': 6, 'label_size': 9, 'opacity': 150,
            },
            'planets': {
                'enabled': self._planets_enabled.is_checked(),
                'color': self._planets_color.selected_color(),
                'label_size': 14, 'marker_size': 10, 'opacity': 255,
            },
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_calibrate_clicked(self):
        """Signal controller to start calibration (controller is wired in main_window)."""
        # Controller is connected externally; emit settings_changed as a trigger
        self.settings_changed.emit({'_action': 'calibrate'})

    def _on_guided_clicked(self):
        """Signal main_window to open the guided-calibration dialog."""
        self.settings_changed.emit({'_action': 'guided_calibrate'})

    def _on_setting_changed(self, *_):
        self.settings_changed.emit(self.get_config())
