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

from ml.labeling_io import (
    find_sample_sets, load_fits_as_qpixmap, create_placeholder_pixmap,
    remove_sample_files,
)
from ml.labels_widget import LabelsWidget
from ml.context_widget import ContextPanel
from ml.ai_worker import AiLabelWorker
from ml.review_tab import ReviewTab, to_bool
from ml.filter_bar import FilterBar
from ml.label_filters import extract_filter_meta, frame_matches
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
        self.meta_cache = self._build_meta_cache()
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
            self.labels_widget.set_jump_dates(self._available_dates())
            self._update_filter_count()
            self.load_sample(0)
        else:
            QMessageBox.warning(self, "No Data", f"No calibration files found in:\n{data_dir}")

    def _build_meta_cache(self) -> dict:
        """ts -> compact filter metadata, read once so navigation never re-reads JSON."""
        cache = {}
        for sample in self.samples:
            cal_path = sample.get('calibration')
            if not cal_path:
                continue
            try:
                with open(cal_path, 'r') as f:
                    cache[sample['timestamp']] = extract_filter_meta(json.load(f))
            except Exception:
                continue
        return cache

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
        labeling_outer = QVBoxLayout(labeling_widget)

        self.filter_bar = FilterBar()
        self.filter_bar.changed.connect(self._on_view_changed)
        labeling_outer.addWidget(self.filter_bar)

        columns = QHBoxLayout()
        self.setup_labeling_ui(columns)
        labeling_outer.addLayout(columns)
        self.tabs.addTab(labeling_widget, "📝 Labeling")

        self.review_tab = ReviewTab(self.samples)
        self.review_tab.navigate_to_sample.connect(self.go_to_sample_from_review)
        self.tabs.addTab(self.review_tab, "🔍 Review Predictions")

        self.tabs.currentChanged.connect(self.on_tab_changed)

    def setup_labeling_ui(self, main_layout):
        # Left side: image viewer
        images_widget = QWidget()
        images_layout = QVBoxLayout(images_widget)

        self.mismatch_banner = QLabel("")
        self.mismatch_banner.setAlignment(Qt.AlignCenter)
        self.mismatch_banner.setWordWrap(True)
        self.mismatch_banner.setVisible(False)
        self.mismatch_banner.setStyleSheet(
            "background: #7f1d1d; color: white; font-weight: bold; "
            "font-size: 14px; padding: 8px; border-radius: 5px;")
        images_layout.addWidget(self.mismatch_banner)

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
        self.labels_widget.first_requested.connect(self.go_first)
        self.labels_widget.last_requested.connect(self.go_last)
        self.labels_widget.jump_date_requested.connect(self.jump_to_date)
        self.labels_widget.save_requested.connect(self._do_save)
        self.labels_widget.save_next_requested.connect(self._do_save_next)
        self.labels_widget.remove_requested.connect(self._do_remove)
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

    def _on_ai_suggestion_done(self, labelled: int, failed: int, error: str):
        self.context_panel.set_ai_busy(False)
        sample = self.samples[self.current_index]
        if labelled and 'calibration' in sample:
            with open(sample['calibration'], 'r') as f:
                self.current_cal = json.load(f)
            self.context_panel.populate(self.current_cal)
            self._update_mismatch_banner(self.current_cal)
            # Only push the AI result into the form if the user has no in-progress edits.
            if not self.labels_widget.unsaved_changes:
                roof_pred, sky_pred = self.run_model_prediction(sample, self.current_cal)
                self.labels_widget.populate_fields(self.current_cal, roof_pred, sky_pred)
                self.labels_widget.mark_saved()
        if failed:
            detail = error or "Unknown error"
            hint = ""
            if "OPENROUTER_API_KEY" in detail:
                hint = ("\n\nThe key is not set in this app's environment. Launch the tool "
                        "from a shell that has it, e.g.\n"
                        "  $env:OPENROUTER_API_KEY=\"sk-or-...\"; python ml/labeling_tool.py\n"
                        "or set it persistently with setx and restart.")
            QMessageBox.warning(self, "AI Suggest", f"AI request failed:\n\n{detail}{hint}")

    def setup_shortcuts(self):
        QShortcut(QKeySequence("A"), self, self.prev_sample)
        QShortcut(QKeySequence("D"), self, self.next_sample)
        QShortcut(QKeySequence("S"), self, self._do_save)
        QShortcut(QKeySequence("Space"), self, self._do_save_next)
        QShortcut(QKeySequence("Left"), self, self.prev_sample)
        QShortcut(QKeySequence("Right"), self, self.next_sample)
        QShortcut(QKeySequence("Home"), self, self.go_first)
        QShortcut(QKeySequence("End"), self, self.go_last)
        QShortcut(QKeySequence("Delete"), self, self._do_remove)

    # ── Filtering / stepping ──────────────────────────────────────────────────

    def _filter_active(self) -> bool:
        return self.filter_bar.criteria().is_active()

    def _stepping_active(self) -> bool:
        """True when navigation should skip non-matching frames."""
        return self._filter_active() or self.labels_widget.skip_labeled_checked

    def _matches(self, sample: dict) -> bool:
        """Frame passes the filter bar AND the skip-labeled toggle."""
        meta = self.meta_cache.get(sample.get('timestamp'))
        if meta is None:
            return False
        if not frame_matches(meta, self.filter_bar.criteria()):
            return False
        if self.labels_widget.skip_labeled_checked and meta['has_label']:
            return False
        return True

    def find_next_matching(self, start: int, direction: int = 1) -> int:
        index = start + direction
        while 0 <= index < len(self.samples):
            if self._matches(self.samples[index]):
                return index
            index += direction
        return -1

    def find_first_match(self) -> int:
        for i, sample in enumerate(self.samples):
            if self._matches(sample):
                return i
        return -1

    def find_last_match(self) -> int:
        for i in range(len(self.samples) - 1, -1, -1):
            if self._matches(self.samples[i]):
                return i
        return -1

    def go_first(self):
        if not self.samples:
            return
        target = self.find_first_match() if self._stepping_active() else 0
        if target >= 0:
            self.load_sample(target)

    def go_last(self):
        if not self.samples:
            return
        target = self.find_last_match() if self._stepping_active() else len(self.samples) - 1
        if target >= 0:
            self.load_sample(target)

    def _available_dates(self) -> list:
        """Unique capture dates (YYYYMMDD) as (display, raw) pairs, in order."""
        seen = set()
        dates = []
        for sample in self.samples:
            raw = sample.get('timestamp', '')[:8]
            if len(raw) == 8 and raw.isdigit() and raw not in seen:
                seen.add(raw)
                dates.append((f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}", raw))
        return dates

    def jump_to_date(self, date_str: str):
        """Jump to the first frame captured on/after the chosen night (absolute)."""
        for i, sample in enumerate(self.samples):
            if sample.get('timestamp', '')[:8] >= date_str:
                self.load_sample(i)
                return
        if self.samples:
            self.load_sample(len(self.samples) - 1)

    def _matching_count(self) -> int:
        return sum(1 for s in self.samples if self._matches(s))

    def _update_filter_count(self):
        self.filter_bar.set_count(self._matching_count(), len(self.samples))

    def _on_view_changed(self):
        """Filter or skip-labeled toggled: recount and jump to a match if needed."""
        self.labels_widget.update_unlabeled_count(self.samples)
        self._update_filter_count()
        if not self.samples:
            return
        if self._stepping_active() and not self._matches(self.samples[self.current_index]):
            nxt = self.find_next_matching(self.current_index, 1)
            target = nxt if nxt >= 0 else self.find_first_match()
            if target >= 0:
                self.load_sample(target)
                return
        self._refresh_nav_buttons()

    def _refresh_nav_buttons(self):
        idx = self.current_index
        if self._stepping_active():
            prev_enabled = self.find_next_matching(idx, -1) >= 0
            next_enabled = self.find_next_matching(idx, 1) >= 0
        else:
            prev_enabled = idx > 0
            next_enabled = idx < len(self.samples) - 1
        self.labels_widget.set_nav_enabled(prev_enabled, next_enabled)

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
        if self._stepping_active():
            prev_enabled = self.find_next_matching(index, -1) >= 0
            next_enabled = self.find_next_matching(index, 1) >= 0
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

        self._update_mismatch_banner(self.current_cal)
        self.labels_widget.mark_saved()

    def _update_mismatch_banner(self, cal: dict):
        """Flag frames where the AI roof call disagrees with the NINA roof state."""
        ai = cal.get('ai_suggestion')
        rs = cal.get('roof_state', {})
        if not ai or not rs.get('available') or rs.get('roof_open') is None:
            self.mismatch_banner.setVisible(False)
            return

        ai_open = bool(ai.get('roof_open'))
        nina_open = to_bool(rs.get('roof_open'))
        if ai_open == nina_open:
            self.mismatch_banner.setVisible(False)
            return

        self.mismatch_banner.setText(
            f"⚠️ MISMATCH — AI: roof {'OPEN' if ai_open else 'CLOSED'}  vs  "
            f"NINA: roof {'OPEN' if nina_open else 'CLOSED'}  ·  worth reviewing")
        self.mismatch_banner.setVisible(True)

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
            self.meta_cache[sample['timestamp']] = extract_filter_meta(self.current_cal)
            self.labels_widget.update_unlabeled_count(self.samples)
            self._update_filter_count()

    def _do_save_next(self):
        self._do_save()
        self.next_sample()

    def _do_remove(self):
        """Move the current sample's files to the _removed folder and advance."""
        if not self.samples:
            return
        sample = self.samples[self.current_index]
        ts = sample.get('timestamp', '?')
        trash_dir = self.data_dir / "_removed"
        reply = QMessageBox.question(
            self, "Remove image",
            f"Move sample {ts} out of the dataset?\n\n"
            f"Its calibration JSON and lum FITS are moved to:\n{trash_dir}\n"
            f"(recoverable — move them back to undo).",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            moved = remove_sample_files(sample, trash_dir)
        except Exception as e:
            QMessageBox.warning(self, "Remove failed", f"Could not move files:\n{e}")
            return

        app_logger.info(f"Removed sample {ts}: moved {len(moved)} file(s) to {trash_dir}")
        self.meta_cache.pop(ts, None)
        del self.samples[self.current_index]      # in-place so ReviewTab's list stays in sync
        self.labels_widget.mark_saved()           # nothing pending for the removed frame

        if not self.samples:
            self.current_cal = {}
            QMessageBox.information(self, "Removed", "No samples remain in the dataset.")
            return

        self.labels_widget.update_unlabeled_count(self.samples)
        self.labels_widget.set_jump_dates(self._available_dates())
        self._update_filter_count()

        new_index = min(self.current_index, len(self.samples) - 1)
        if self._stepping_active() and not self._matches(self.samples[new_index]):
            nxt = self.find_next_matching(new_index, 1)
            if nxt < 0:
                nxt = self.find_first_match()
            if nxt >= 0:
                new_index = nxt
        self.current_index = new_index
        self.load_sample(new_index)

    def _on_skip_changed(self):
        self._on_view_changed()

    def prev_sample(self):
        if self._stepping_active():
            prev_idx = self.find_next_matching(self.current_index, -1)
            if prev_idx >= 0:
                self.load_sample(prev_idx)
        elif self.current_index > 0:
            self.load_sample(self.current_index - 1)

    def next_sample(self):
        if self._stepping_active():
            next_idx = self.find_next_matching(self.current_index, 1)
            if next_idx >= 0:
                self.load_sample(next_idx)
            elif self.labels_widget.skip_labeled_checked and not self._filter_active():
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
