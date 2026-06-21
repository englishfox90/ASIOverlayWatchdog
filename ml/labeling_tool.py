#!/usr/bin/env python3
"""
ML Labeling Tool for PFR Sentinel

Three-column GUI: lum FITS image | data (context, ML + AI predictions) | manual
label form. Edits labels in the calibration JSON. Shows ML and AI pre-label
predictions alongside for comparison/validation.

Usage:
    python ml/labeling_tool.py "D:\\Pier Camera ML Data"
    python ml/labeling_tool.py  # Uses default path
"""
import sys
import json
import argparse
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QGroupBox, QPushButton, QMessageBox, QTabWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from ml.labeling_io import find_sample_sets, load_fits_as_qpixmap, create_placeholder_pixmap
from ml.labels_widget import LabelsWidget
from ml.context_widget import ContextPanel
from ml.ai_worker import AiLabelWorker
from ml.review_tab import ReviewTab, to_bool
from services.logger import app_logger

try:
    from ml.roof_classifier import RoofClassifier
    ROOF_ML_AVAILABLE = True
except ImportError:
    ROOF_ML_AVAILABLE = False

try:
    from ml.sky_classifier import SkyClassifier
    SKY_ML_AVAILABLE = True
except ImportError:
    SKY_ML_AVAILABLE = False


class LabelingTool(QMainWindow):
    """Main labeling tool window."""

    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.samples = find_sample_sets(data_dir)
        self.current_index = 0
        self.current_cal = {}

        self.roof_classifier = None
        self.sky_classifier = None

        if ROOF_ML_AVAILABLE:
            model_path = Path(__file__).parent / 'models' / 'roof_classifier_v1.pth'
            if model_path.exists():
                try:
                    self.roof_classifier = RoofClassifier.load(str(model_path), image_size=128)
                    app_logger.info(f"Loaded roof classifier from {model_path}")
                except Exception as e:
                    app_logger.warning(f"Failed to load roof model: {e}")

        if SKY_ML_AVAILABLE:
            model_path = Path(__file__).parent / 'models' / 'sky_classifier_v1.pth'
            if model_path.exists():
                try:
                    self.sky_classifier = SkyClassifier.load(str(model_path), image_size=256)
                    app_logger.info(f"Loaded sky classifier from {model_path}")
                except Exception as e:
                    app_logger.warning(f"Failed to load sky model: {e}")

        self.classifier = self.roof_classifier  # legacy alias

        self.setWindowTitle(f"ML Labeling Tool - {data_dir}")
        self.setMinimumSize(1400, 900)

        self.setup_ui()
        self.setup_shortcuts()

        if self.samples:
            self.labels_widget.update_unlabeled_count(self.samples)
            self.load_sample(0)
        else:
            QMessageBox.warning(self, "No Data", f"No calibration files found in:\n{data_dir}")

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background: #2a2a2a; padding: 10px 20px;
                border: 1px solid #444; border-bottom: none;
                margin-right: 2px;
            }
            QTabBar::tab:selected { background: #333; border-bottom: 1px solid #333; }
            QTabBar::tab:hover { background: #3a3a3a; }
        """)
        main_layout.addWidget(self.tabs)

        labeling_widget = QWidget()
        labeling_layout = QHBoxLayout(labeling_widget)
        self.setup_labeling_ui(labeling_layout)
        self.tabs.addTab(labeling_widget, "📝 Labeling")

        self.review_tab = ReviewTab(self.samples)
        self.review_tab.navigate_to_sample.connect(self.go_to_sample_from_review)
        self.tabs.addTab(self.review_tab, "🔍 Review Predictions")

        self.tabs.currentChanged.connect(self.on_tab_changed)

    def setup_labeling_ui(self, main_layout):
        # Left side: image viewer
        images_widget = QWidget()
        images_layout = QVBoxLayout(images_widget)

        lum_group = QGroupBox("Luminance (Stretched)")
        lum_layout = QVBoxLayout(lum_group)
        self.lum_label = QLabel()
        self.lum_label.setAlignment(Qt.AlignCenter)
        self.lum_label.setMinimumSize(400, 400)
        self.lum_label.setStyleSheet("background: #1a1a1a; border: 1px solid #333;")
        lum_layout.addWidget(self.lum_label)
        images_layout.addWidget(lum_group)

        main_layout.addWidget(images_widget, 1)

        self.context_panel = ContextPanel()
        self.context_panel.ai_requested.connect(self.request_ai_suggestion)
        main_layout.addWidget(self.context_panel, 1)

        self.labels_widget = LabelsWidget()
        main_layout.addWidget(self.labels_widget, 1)

        self.labels_widget.prev_requested.connect(self.prev_sample)
        self.labels_widget.next_requested.connect(self.next_sample)
        self.labels_widget.save_requested.connect(self._do_save)
        self.labels_widget.save_next_requested.connect(self._do_save_next)
        self.labels_widget.skip_changed.connect(self._on_skip_changed)

    def on_tab_changed(self, index: int):
        if index == 1:
            self.review_tab.refresh_data()

    def go_to_sample_from_review(self, index: int):
        self.tabs.setCurrentIndex(0)
        self.load_sample(index)

    def request_ai_suggestion(self):
        """Run the AI labeler on the currently displayed frame (background thread)."""
        sample = self.samples[self.current_index]
        if 'calibration' not in sample or 'lum' not in sample:
            QMessageBox.information(self, "AI Suggest", "This sample has no lum frame to send.")
            return

        self.context_panel.set_ai_busy(True)
        jobs = [{
            'cal_path': str(sample['calibration']),
            'lum_path': str(sample['lum']),
            'timestamp': sample['timestamp'],
        }]
        self._ai_worker = AiLabelWorker(jobs)
        self._ai_worker.completed.connect(self._on_ai_suggestion_done)
        self._ai_worker.start()

    def _on_ai_suggestion_done(self, labelled: int, failed: int):
        self.context_panel.set_ai_busy(False)
        sample = self.samples[self.current_index]
        if labelled and 'calibration' in sample:
            with open(sample['calibration'], 'r') as f:
                self.current_cal = json.load(f)
            self.context_panel.populate(self.current_cal)
            # Only push the AI result into the form if the user has no in-progress edits.
            if not self.labels_widget.unsaved_changes:
                roof_pred, sky_pred = self.run_model_prediction(sample, self.current_cal)
                self.labels_widget.populate_fields(self.current_cal, roof_pred, sky_pred)
                self.labels_widget.mark_saved()
        if failed:
            QMessageBox.warning(self, "AI Suggest",
                                "AI request failed. Check OPENROUTER_API_KEY and your connection.")

    def setup_shortcuts(self):
        QShortcut(QKeySequence("A"), self, self.prev_sample)
        QShortcut(QKeySequence("D"), self, self.next_sample)
        QShortcut(QKeySequence("S"), self, self._do_save)
        QShortcut(QKeySequence("Space"), self, self._do_save_next)
        QShortcut(QKeySequence("Left"), self, self.prev_sample)
        QShortcut(QKeySequence("Right"), self, self.next_sample)

    def find_next_unlabeled(self, start: int, direction: int = 1) -> int:
        index = start + direction
        while 0 <= index < len(self.samples):
            if not self.labels_widget.is_sample_labeled(self.samples[index]):
                return index
            index += direction
        return -1

    def load_sample(self, index: int):
        if not self.samples:
            return

        if self.labels_widget.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes before moving to next sample?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self._do_save()
            elif reply == QMessageBox.Cancel:
                return

        index = max(0, min(index, len(self.samples) - 1))
        self.current_index = index
        sample = self.samples[index]

        folder_name = sample.get('folder', Path()).name
        skip_mode = self.labels_widget.skip_labeled_checked
        if skip_mode:
            prev_enabled = self.find_next_unlabeled(index, -1) >= 0
            next_enabled = self.find_next_unlabeled(index, 1) >= 0
        else:
            prev_enabled = index > 0
            next_enabled = index < len(self.samples) - 1
        self.labels_widget.set_navigation(index, len(self.samples), prev_enabled, next_enabled,
                                          folder_name, sample['timestamp'])

        if 'lum' in sample:
            self.lum_label.setPixmap(load_fits_as_qpixmap(sample['lum'], 380))
        else:
            self.lum_label.setPixmap(create_placeholder_pixmap("No lum FITS", 380))

        if 'calibration' in sample:
            with open(sample['calibration'], 'r') as f:
                self.current_cal = json.load(f)
            self.context_panel.populate(self.current_cal)
            roof_pred, sky_pred = self.run_model_prediction(sample, self.current_cal)
            self.labels_widget.populate_fields(self.current_cal, roof_pred, sky_pred)
        else:
            self.current_cal = {}
            self.context_panel.populate({})
            self.context_panel.set_model_text("⚠️ No calibration file found")
            self.labels_widget.populate_fields({}, None, None)

        self.labels_widget.mark_saved()

    def run_model_prediction(self, sample: dict, cal: dict):
        """Run ML models on the current image. Returns (roof_pred, sky_pred)."""
        lines = []
        roof_pred = None
        sky_pred = None

        if not self.roof_classifier and not self.sky_classifier:
            self.context_panel.set_model_text(
                "⚠️ No ML models loaded\n\nTo train models:\n"
                "  python ml/train_roof_classifier.py\n"
                "  python ml/train_sky_classifier.py"
            )
            return roof_pred, sky_pred

        if 'lum' not in sample:
            self.context_panel.set_model_text("⚠️ No FITS image available for prediction")
            return roof_pred, sky_pred

        metadata = None
        if cal:
            tc = cal.get('time_context', {})
            ca = cal.get('corner_analysis', {})
            mc = cal.get('moon_context', {})
            st = cal.get('stretch', {})
            metadata = {
                'corner_to_center_ratio': ca.get('corner_to_center_ratio', 1.0),
                'median_lum': st.get('median_lum', 0.0),
                'is_astronomical_night': tc.get('is_astronomical_night', False),
                'hour': tc.get('hour', 12),
                'moon_illumination': mc.get('illumination_pct', 0.0),
                'moon_is_up': mc.get('moon_is_up', False),
            }

        if self.roof_classifier:
            try:
                result = self.roof_classifier.predict_from_fits(sample['lum'])
                roof_pred = result
                roof_status = "🟢 OPEN" if result.roof_open else "🔴 CLOSED"
                conf_bar = "█" * int(result.confidence * 10) + "░" * (10 - int(result.confidence * 10))

                lines.append("━━━ ROOF CLASSIFIER ━━━")
                lines.append(f"State:      {roof_status}")
                lines.append(f"Confidence: [{conf_bar}] {result.confidence:.1%}")

                rs = cal.get('roof_state', {}) if cal else {}
                if rs.get('available'):
                    ctx_roof = to_bool(rs.get('roof_open', False))
                    lines.append(f"vs API:     {'✓' if ctx_roof == result.roof_open else '✗'}")

                labels = cal.get('labels', {}) if cal else {}
                if labels.get('labeled_at'):
                    lbl_roof = to_bool(labels.get('roof_open', False))
                    lines.append(f"vs Label:   {'✓' if lbl_roof == result.roof_open else '✗'}")

            except Exception as e:
                lines.append("━━━ ROOF CLASSIFIER ━━━")
                lines.append(f"⚠️ Error: {e}")

        if self.sky_classifier:
            lines.append("")
            lines.append("━━━ SKY CLASSIFIER ━━━")

            if not (roof_pred and roof_pred.roof_open):
                lines.append("⛔ N/A - Roof is CLOSED")
                lines.append("   (Pier camera cannot see sky)")
                lines.append("")
                lines.append("   Note: Manual labels still work")
                lines.append("   (use all-sky camera reference)")
            else:
                try:
                    result = self.sky_classifier.predict_from_fits(sample['lum'], metadata)
                    sky_pred = result

                    lines.append(f"Sky:     {result.sky_condition} ({result.sky_confidence:.0%})")

                    sorted_probs = sorted(result.sky_probabilities.items(), key=lambda x: -x[1])
                    for cond, prob in sorted_probs[:3]:
                        bar = "█" * int(prob * 10) + "░" * (10 - int(prob * 10))
                        marker = "◄" if cond == result.sky_condition else " "
                        lines.append(f"  [{bar}] {prob:5.1%} {cond[:12]:<12}{marker}")

                    stars_icon = "⭐" if result.stars_visible else "  "
                    lines.append(f"Stars:   {stars_icon} {'Yes' if result.stars_visible else 'No'} ({result.stars_confidence:.0%})")
                    if result.stars_visible:
                        density_bar = "★" * int(result.star_density * 5) + "☆" * (5 - int(result.star_density * 5))
                        lines.append(f"         Density: [{density_bar}] {result.star_density:.2f}")

                    moon_icon = "🌙" if result.moon_visible else "  "
                    lines.append(f"Moon:    {moon_icon} {'Yes' if result.moon_visible else 'No'} ({result.moon_confidence:.0%})")

                    labels = cal.get('labels', {}) if cal else {}
                    if labels.get('labeled_at'):
                        lines.append("")
                        lines.append("vs Manual Labels:")
                        lbl_sky = labels.get('sky_condition', '')
                        if lbl_sky:
                            lines.append(f"  Sky:   {'✓' if lbl_sky == result.sky_condition else '✗'} (label: {lbl_sky})")
                        lbl_stars = to_bool(labels.get('stars_visible', False))
                        lines.append(f"  Stars: {'✓' if lbl_stars == result.stars_visible else '✗'}")
                        lbl_moon = to_bool(labels.get('moon_visible', False))
                        lines.append(f"  Moon:  {'✓' if lbl_moon == result.moon_visible else '✗'}")

                except Exception as e:
                    lines.append(f"⚠️ Error: {e}")

        self.context_panel.set_model_text("\n".join(lines))
        return roof_pred, sky_pred

    def _do_save(self):
        sample = self.samples[self.current_index]
        if 'calibration' not in sample:
            return
        if self.labels_widget.save_labels(self.current_cal, sample['calibration']):
            self.labels_widget.update_unlabeled_count(self.samples)

    def _do_save_next(self):
        self._do_save()
        self.next_sample()

    def _on_skip_changed(self):
        self.labels_widget.update_unlabeled_count(self.samples)
        if self.labels_widget.skip_labeled_checked:
            if self.labels_widget.is_sample_labeled(self.samples[self.current_index]):
                self.next_sample()

    def prev_sample(self):
        if self.labels_widget.skip_labeled_checked:
            next_idx = self.find_next_unlabeled(self.current_index, -1)
            if next_idx >= 0:
                self.load_sample(next_idx)
        elif self.current_index > 0:
            self.load_sample(self.current_index - 1)

    def next_sample(self):
        if self.labels_widget.skip_labeled_checked:
            next_idx = self.find_next_unlabeled(self.current_index, 1)
            if next_idx >= 0:
                self.load_sample(next_idx)
            else:
                QMessageBox.information(self, "Done", "All samples have been labeled!")
        elif self.current_index < len(self.samples) - 1:
            self.load_sample(self.current_index + 1)

    def closeEvent(self, event):
        if self.labels_widget.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self._do_save()
                event.accept()
            elif reply == QMessageBox.No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="ML Labeling Tool for calibration data")
    parser.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data",
                        help="Directory containing calibration files")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        app_logger.error(f"Directory not found: {data_dir}")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    app.setStyleSheet("""
        QMainWindow, QWidget { background: #1e1e1e; color: #e0e0e0; }
        QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 10px; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QPushButton { background: #333; border: 1px solid #555; padding: 8px 16px; border-radius: 4px; }
        QPushButton:hover { background: #444; }
        QPushButton:pressed { background: #555; }
        QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit {
            background: #2a2a2a; border: 1px solid #444; padding: 5px; border-radius: 3px;
        }
        QCheckBox { spacing: 8px; }
        QScrollArea { border: none; }
    """)

    window = LabelingTool(data_dir)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
