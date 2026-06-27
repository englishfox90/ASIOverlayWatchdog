#!/usr/bin/env python3
"""Filter bar for the labeling tab — narrows navigation to matching frames."""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QCheckBox, QPushButton,
)
from PySide6.QtCore import Signal

from .label_filters import FilterCriteria, SKY_LABELS


class FilterBar(QWidget):
    """Compact row of sky/weather/moon filters. Emits `changed` on any edit."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        layout.addWidget(QLabel("Filter:"))

        layout.addWidget(QLabel("Sky label"))
        self.sky_combo = QComboBox()
        self.sky_combo.addItems(["Any"] + SKY_LABELS + ["Unlabeled"])
        self.sky_combo.currentIndexChanged.connect(self._emit_changed)
        layout.addWidget(self.sky_combo)

        layout.addWidget(QLabel("Weather"))
        self.weather_combo = QComboBox()
        self.weather_combo.addItems(["Any", "Clear sky", "Cloudy sky"])
        self.weather_combo.currentIndexChanged.connect(self._emit_changed)
        layout.addWidget(self.weather_combo)

        self.moon_check = QCheckBox("Bright moon up")
        self.moon_check.stateChanged.connect(self._emit_changed)
        layout.addWidget(self.moon_check)

        self.suspect_check = QCheckBox("⚠ Suspect only")
        self.suspect_check.setToolTip(
            "Frames labeled Partly Cloudy / Overcast on a night the weather "
            "service reported a CLEAR sky — likely moon-glow mislabels.")
        self.suspect_check.setStyleSheet("font-weight: bold; color: #f59e0b;")
        self.suspect_check.stateChanged.connect(self._emit_changed)
        layout.addWidget(self.suspect_check)

        self.ai_disagree_check = QCheckBox("⚠ AI disagrees")
        self.ai_disagree_check.setToolTip(
            "Frames where the validation model's sky verdict differs from your "
            "label. Run ml/validate_labels.py first to populate ai_suggestion.")
        self.ai_disagree_check.setStyleSheet("font-weight: bold; color: #0EA5E9;")
        self.ai_disagree_check.stateChanged.connect(self._emit_changed)
        layout.addWidget(self.ai_disagree_check)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Reset all filters")
        self.clear_btn.clicked.connect(self.reset)
        layout.addWidget(self.clear_btn)

        layout.addStretch()

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #0EA5E9; font-weight: bold;")
        layout.addWidget(self.count_label)

    def _emit_changed(self):
        self.changed.emit()

    def criteria(self) -> FilterCriteria:
        return FilterCriteria(
            sky_label=self.sky_combo.currentText(),
            weather=self.weather_combo.currentText(),
            bright_moon_up=self.moon_check.isChecked(),
            suspect_only=self.suspect_check.isChecked(),
            ai_disagrees=self.ai_disagree_check.isChecked(),
        )

    def reset(self):
        widgets = (self.sky_combo, self.weather_combo, self.moon_check,
                   self.suspect_check, self.ai_disagree_check)
        for w in widgets:
            w.blockSignals(True)
        self.sky_combo.setCurrentIndex(0)
        self.weather_combo.setCurrentIndex(0)
        self.moon_check.setChecked(False)
        self.suspect_check.setChecked(False)
        self.ai_disagree_check.setChecked(False)
        for w in widgets:
            w.blockSignals(False)
        self.changed.emit()

    def set_count(self, matching: int, total: int):
        if self.criteria().is_active():
            self.count_label.setText(f"{matching} matching / {total}")
        else:
            self.count_label.setText(f"{total} samples")
