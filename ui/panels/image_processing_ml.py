"""
ML Models + Community Data Contribution sections of the Image Processing panel.
Extracted from image_processing.py to keep the main panel under the size cap.
"""
import os
import webbrowser

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox
)
from PySide6.QtCore import Signal, QTimer
from qfluentwidgets import (
    CaptionLabel, PushButton, LineEdit, PrimaryPushButton
)

from ..theme.tokens import Colors, Spacing
from ..theme.icons import mdi
from ..components.cards import SwitchRow, CollapsibleCard
from services.logger import app_logger
from services.ml_service import get_ml_service
from services.ml_data_collector import get_ml_collector, UPLOAD_FORM_URL


class ImageProcessingMLSection(QWidget):
    """
    ML Models (Beta) + Community Data Contribution cards.

    Owns:
    - ML enable toggle + status label
    - ASCOM safety file output (enable, path, browse)
    - ML data contribution toggle + status + export/upload/clear buttons
    """

    settings_changed = Signal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._loading_config = True
        self._setup_ui()
        self._loading_config = False

        self._ml_status_timer = QTimer(self)
        self._ml_status_timer.timeout.connect(self._update_ml_contrib_status)
        self._ml_status_timer.start(5000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.card_gap)

        # === ML MODELS (Beta) ===
        ml_card = CollapsibleCard("ML Models (Beta)", mdi('brain'))

        self.ml_enabled_switch = SwitchRow(
            "Enable ML Analysis",
            "Use machine learning to analyze observatory conditions"
        )
        self.ml_enabled_switch.toggled.connect(self._on_ml_enabled_changed)
        ml_card.add_widget(self.ml_enabled_switch)

        ml_info = CaptionLabel(
            "🔭 Roof Classifier: Detects if observatory roof is open or closed\n"
            "🌤️ Sky Classifier: Identifies sky conditions (Clear, Cloudy, etc.) when roof is open\n\n"
            "New overlay tokens available:\n"
            "• {ROOF_STATUS} - \"Open (95%)\" or \"Closed (98%)\"\n"
            "• {SKY_CONDITION} - \"Clear (87%)\" or \"Partly Cloudy (72%)\"\n"
            "• {STARS_VISIBLE} - \"Yes\" or \"No\"\n"
            "• {STAR_DENSITY} - \"High (0.85)\" or \"Low (0.12)\""
        )
        ml_info.setStyleSheet(f"color: {Colors.text_secondary}; padding: 8px;")
        ml_info.setWordWrap(True)
        ml_card.add_widget(ml_info)

        self.ml_status_label = CaptionLabel("Status: Not initialized")
        self.ml_status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")
        ml_card.add_widget(self.ml_status_label)

        self.roof_gates_sky_switch = SwitchRow(
            "Skip Sky Features When Roof Closed",
            "Turn off if you have no roof (e.g. an open-air all-sky camera) — "
            "keeps star detection and the all-sky overlay/calibration running "
            "even when the roof classifier misreads \"Closed\""
        )
        self.roof_gates_sky_switch.toggled.connect(self._on_roof_gates_sky_changed)
        ml_card.add_widget(self.roof_gates_sky_switch)

        self.ascom_safety_switch = SwitchRow(
            "ASCOM Safety File",
            "Write roof status to file for NINA GenericFile safety monitor"
        )
        self.ascom_safety_switch.toggled.connect(self._on_ascom_safety_changed)
        ml_card.add_widget(self.ascom_safety_switch)

        ascom_path_row = QHBoxLayout()
        ascom_path_row.setSpacing(Spacing.sm)

        self.ascom_file_path = LineEdit()
        self.ascom_file_path.setPlaceholderText("%LOCALAPPDATA%\\PFRSentinel\\RoofStatusFile.txt")
        self.ascom_file_path.editingFinished.connect(self._on_ascom_path_changed)
        ascom_path_row.addWidget(self.ascom_file_path, 1)

        self.ascom_browse_btn = PushButton("Browse")
        self.ascom_browse_btn.setFixedWidth(70)
        self.ascom_browse_btn.clicked.connect(self._browse_ascom_path)
        ascom_path_row.addWidget(self.ascom_browse_btn)

        ascom_path_widget = QWidget()
        ascom_path_widget.setLayout(ascom_path_row)
        ml_card.add_row("File Path", ascom_path_widget, "Path where NINA monitors for status")

        ascom_info = CaptionLabel(
            "Configure NINA GenericFile with:\n"
            "• Preamble: \"Roof Status:\"\n"
            "• Safe trigger: \"OPEN\"\n"
            "• Unsafe trigger: \"CLOSED\""
        )
        ascom_info.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")
        ascom_info.setWordWrap(True)
        ml_card.add_widget(ascom_info)

        layout.addWidget(ml_card)

        # === ML DATA CONTRIBUTION ===
        contrib_card = CollapsibleCard("Community Data Contribution", mdi('account-group'))

        contrib_info = CaptionLabel(
            "🧠 Help improve scene detection for everyone!\n\n"
            "When enabled, PFR Sentinel collects anonymous training samples that help "
            "improve the ML models for all users. Data is stored locally until you "
            "choose to upload it."
        )
        contrib_info.setStyleSheet(f"color: {Colors.text_secondary}; padding: 8px;")
        contrib_info.setWordWrap(True)
        contrib_card.add_widget(contrib_info)

        self.ml_contrib_switch = SwitchRow(
            "Enable Data Contribution",
            "Collect anonymous training samples every 30 minutes"
        )
        self.ml_contrib_switch.toggled.connect(self._on_ml_contrib_changed)
        contrib_card.add_widget(self.ml_contrib_switch)

        collected_info = CaptionLabel(
            "📦 What's collected:\n"
            "• Downscaled image (256×256) - ~80 KB\n"
            "• Camera settings & image statistics\n"
            "• Time/moon context (no GPS data)\n"
            "• Roof/weather status if available"
        )
        collected_info.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")
        collected_info.setWordWrap(True)
        contrib_card.add_widget(collected_info)

        self.ml_contrib_status_label = CaptionLabel("Samples: 0 / 500 (0 MB)")
        self.ml_contrib_status_label.setStyleSheet(f"""
            color: {Colors.text_muted};
            padding: 12px;
            background: {Colors.bg_card};
            border-radius: 6px;
            font-weight: 500;
        """)
        contrib_card.add_widget(self.ml_contrib_status_label)

        contrib_btn_row = QHBoxLayout()
        contrib_btn_row.setSpacing(Spacing.sm)

        self.ml_export_btn = PrimaryPushButton("Export for Upload")
        self.ml_export_btn.setIcon(mdi('folder-zip-outline'))
        self.ml_export_btn.clicked.connect(self._export_ml_data)
        contrib_btn_row.addWidget(self.ml_export_btn)

        self.ml_upload_btn = PushButton("Open Upload Form")
        self.ml_upload_btn.setIcon(mdi('cloud-upload-outline'))
        self.ml_upload_btn.clicked.connect(self._open_ml_upload_form)
        contrib_btn_row.addWidget(self.ml_upload_btn)

        self.ml_clear_btn = PushButton("Clear")
        self.ml_clear_btn.setIcon(mdi('delete-outline'))
        self.ml_clear_btn.clicked.connect(self._clear_ml_samples)
        contrib_btn_row.addWidget(self.ml_clear_btn)

        contrib_btn_row.addStretch()

        contrib_btn_widget = QWidget()
        contrib_btn_widget.setLayout(contrib_btn_row)
        contrib_card.add_widget(contrib_btn_widget)

        steps_info = CaptionLabel(
            "📤 How to contribute:\n"
            "1. Enable data contribution above\n"
            "2. Let it collect while you capture normally\n"
            "3. Click 'Export for Upload' when ready\n"
            "4. Upload the ZIP via the Google Form\n"
            "5. Click 'Clear' after successful upload"
        )
        steps_info.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")
        steps_info.setWordWrap(True)
        contrib_card.add_widget(steps_info)

        layout.addWidget(contrib_card)

    # === ML MODELS HANDLERS ===

    def _on_ml_enabled_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            ml_config = self.main_window.config.get('ml_models', {})
            ml_config['enabled'] = checked
            self.main_window.config.set('ml_models', ml_config)
            self.main_window.config.save()
            self.settings_changed.emit()

            if checked:
                app_logger.info("ML Models enabled - initializing classifiers...")
                self._initialize_ml_service()
            else:
                app_logger.info("ML Models disabled")
                self.ml_status_label.setText("Status: Disabled")

    def _initialize_ml_service(self):
        try:
            ml = get_ml_service()
            ml.initialize()

            status = ml.get_status()
            roof_ok = status['roof_classifier']['available']
            sky_ok = status['sky_classifier']['available']

            if roof_ok and sky_ok:
                self.ml_status_label.setText("Status: ✓ Both models loaded")
                self.ml_status_label.setStyleSheet(f"color: #4ade80; padding: 8px;")
            elif roof_ok:
                self.ml_status_label.setText("Status: ✓ Roof model only")
                self.ml_status_label.setStyleSheet(f"color: #facc15; padding: 8px;")
            elif sky_ok:
                self.ml_status_label.setText("Status: ✓ Sky model only")
                self.ml_status_label.setStyleSheet(f"color: #facc15; padding: 8px;")
            else:
                roof_err = status['roof_classifier'].get('error', 'Unknown')
                self.ml_status_label.setText(f"Status: ✗ No models available ({roof_err})")
                self.ml_status_label.setStyleSheet(f"color: #f87171; padding: 8px;")

        except Exception as e:
            self.ml_status_label.setText(f"Status: ✗ Error: {str(e)[:50]}")
            self.ml_status_label.setStyleSheet(f"color: #f87171; padding: 8px;")

    def _on_roof_gates_sky_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            ml_config = self.main_window.config.get('ml_models', {})
            ml_config['roof_gates_sky_features'] = checked
            self.main_window.config.set('ml_models', ml_config)
            self.main_window.config.save()
            self.settings_changed.emit()

            if checked:
                app_logger.info("Roof-closed gating of sky features enabled")
            else:
                app_logger.info("Roof-closed gating of sky features disabled (no-roof/all-sky rig)")

    def _on_ascom_safety_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            ml_config = self.main_window.config.get('ml_models', {})
            ascom_config = ml_config.get('ascom_safety_file', {})
            ascom_config['enabled'] = checked
            ml_config['ascom_safety_file'] = ascom_config
            self.main_window.config.set('ml_models', ml_config)
            self.main_window.config.save()
            self.settings_changed.emit()

            if checked:
                path = ascom_config.get('file_path', '')
                app_logger.info(f"ASCOM Safety file output enabled: {path or '(no path set)'}")
            else:
                app_logger.info("ASCOM Safety file output disabled")

    def _on_ascom_path_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            ml_config = self.main_window.config.get('ml_models', {})
            ascom_config = ml_config.get('ascom_safety_file', {})
            ascom_config['file_path'] = self.ascom_file_path.text().strip()
            ml_config['ascom_safety_file'] = ascom_config
            self.main_window.config.set('ml_models', ml_config)
            self.main_window.config.save()
            self.settings_changed.emit()

    def _browse_ascom_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select ASCOM Safety File Location",
            self.ascom_file_path.text() or "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if path:
            self.ascom_file_path.setText(path)
            self._on_ascom_path_changed()

    # === ML DATA CONTRIBUTION HANDLERS ===

    def _on_ml_contrib_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            ml_contrib = self.main_window.config.get('ml_contribution', {})
            ml_contrib['enabled'] = checked
            self.main_window.config.set('ml_contribution', ml_contrib)
            self.main_window.config.save()
            self.settings_changed.emit()
            self._update_ml_contrib_status()

            if checked:
                app_logger.info("ML Data Contribution enabled - collecting samples every 30 min")
            else:
                app_logger.info("ML Data Contribution disabled")

    def _update_ml_contrib_status(self):
        try:
            collector = get_ml_collector()
            if collector:
                stats = collector.get_stats()
                samples = stats.get('total_samples', 0)
                max_samples = stats.get('max_samples', 500)
                mb = stats.get('disk_usage_mb', 0)

                if stats.get('enabled'):
                    status = f"✓ Collecting: {samples} / {max_samples} samples ({mb:.1f} MB)"
                    self.ml_contrib_status_label.setStyleSheet(f"color: #4ade80; padding: 8px;")
                else:
                    status = f"Samples: {samples} / {max_samples} ({mb:.1f} MB)"
                    self.ml_contrib_status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")

                self.ml_contrib_status_label.setText(status)

                has_samples = samples > 0
                self.ml_export_btn.setEnabled(has_samples)
                self.ml_clear_btn.setEnabled(has_samples)
        except Exception:
            self.ml_contrib_status_label.setText("Status unavailable")
            self.ml_contrib_status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")

    def _export_ml_data(self):
        try:
            collector = get_ml_collector()
            if collector:
                zip_path = collector.export_for_upload()
                if zip_path and zip_path.exists():
                    msg = QMessageBox(self)
                    msg.setWindowTitle("Export Complete")
                    msg.setIcon(QMessageBox.Information)
                    msg.setText("Data exported successfully!")
                    msg.setInformativeText(
                        f"ZIP file created:\n{zip_path}\n\n"
                        "Next steps:\n"
                        "1. Click 'Open Upload Form' to open the Google Form\n"
                        "2. Upload the ZIP file\n"
                        "3. Click 'Clear' after successful upload"
                    )
                    msg.setStandardButtons(QMessageBox.Ok)

                    os.startfile(zip_path.parent)

                    msg.exec()
                else:
                    QMessageBox.warning(self, "Export Failed", "No samples to export or export failed.")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")

    def _open_ml_upload_form(self):
        webbrowser.open(UPLOAD_FORM_URL)

    def _clear_ml_samples(self):
        result = QMessageBox.question(
            self,
            "Clear Samples",
            "Are you sure you want to clear all collected samples?\n\n"
            "Only do this after you've successfully uploaded the data.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if result == QMessageBox.Yes:
            try:
                collector = get_ml_collector()
                if collector and collector.clear_samples():
                    self._update_ml_contrib_status()
                    QMessageBox.information(self, "Cleared", "All samples have been cleared.")
            except Exception as e:
                QMessageBox.critical(self, "Clear Error", f"Failed to clear samples: {e}")

    # === CONFIG LOADING ===

    def load_from_config(self, config):
        self._loading_config = True
        try:
            ml_config = config.get('ml_models', {})
            self.ml_enabled_switch.set_checked(ml_config.get('enabled', False))
            self.roof_gates_sky_switch.set_checked(ml_config.get('roof_gates_sky_features', True))

            ascom_config = ml_config.get('ascom_safety_file', {})
            self.ascom_safety_switch.set_checked(ascom_config.get('enabled', False))
            self.ascom_file_path.setText(ascom_config.get('file_path', ''))

            if ml_config.get('enabled', False):
                self._initialize_ml_service()
            else:
                self.ml_status_label.setText("Status: Disabled")
                self.ml_status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")

            ml_contrib = config.get('ml_contribution', {})
            self.ml_contrib_switch.set_checked(ml_contrib.get('enabled', False))
        finally:
            self._loading_config = False

        self._update_ml_contrib_status()
