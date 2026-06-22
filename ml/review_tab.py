#!/usr/bin/env python3
"""
ML Prediction Review Tab

Shows all samples with ML predictions for validation review.
Compares ML predictions vs NINA roof state vs manual labels.
"""
import json
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QGroupBox, QHeaderView, QAbstractItemView,
    QComboBox, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush

def to_bool(value) -> bool:
    """Convert various representations to boolean (handles string 'True'/'False')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    return bool(value)

class ReviewTab(QWidget):
    """Tab for reviewing ML predictions vs ground truth."""
    
    # Signal to navigate to a specific sample in the labeling tab
    navigate_to_sample = Signal(int)
    
    def __init__(self, samples: list, parent=None):
        super().__init__(parent)
        self.samples = samples
        self.filtered_data = []
        
        self.setup_ui()
        self.refresh_data()
    
    def setup_ui(self):
        """Setup the review UI."""
        layout = QVBoxLayout(self)
        
        # Stats summary
        stats_group = QGroupBox("Prediction Statistics")
        stats_layout = QHBoxLayout(stats_group)
        
        self.total_label = QLabel("Total: 0")
        self.total_label.setStyleSheet("font-size: 14px;")
        stats_layout.addWidget(self.total_label)
        
        self.with_ml_label = QLabel("With ML: 0")
        self.with_ml_label.setStyleSheet("font-size: 14px; color: #8b5cf6;")
        stats_layout.addWidget(self.with_ml_label)
        
        self.accuracy_label = QLabel("Accuracy vs NINA: --")
        self.accuracy_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #10b981;")
        stats_layout.addWidget(self.accuracy_label)
        
        self.accuracy_bar = QProgressBar()
        self.accuracy_bar.setRange(0, 100)
        self.accuracy_bar.setMaximumWidth(150)
        self.accuracy_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #444; border-radius: 5px; text-align: center; }
            QProgressBar::chunk { background: #10b981; border-radius: 4px; }
        """)
        stats_layout.addWidget(self.accuracy_bar)

        self.ai_accuracy_label = QLabel("AI vs NINA: --")
        self.ai_accuracy_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0EA5E9;")
        stats_layout.addWidget(self.ai_accuracy_label)

        stats_layout.addStretch()
        
        # Filter
        stats_layout.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All with ML predictions",
            "ML matches NINA",
            "ML disagrees with NINA",
            "Labeled samples only",
            "Unlabeled only",
            "Has AI suggestion",
            "Missing AI suggestion",
            "AI disagrees with NINA",
            "AI disagrees with manual label",
        ])
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        stats_layout.addWidget(self.filter_combo)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        stats_layout.addWidget(self.refresh_btn)

        self.ai_run_btn = QPushButton("🌐 Run AI on filtered")
        self.ai_run_btn.setStyleSheet("background: #0EA5E9; color: white; font-weight: bold;")
        self.ai_run_btn.setToolTip("Send every filtered frame that has a lum image to the AI labeler")
        self.ai_run_btn.clicked.connect(self.run_ai_on_filtered)
        stats_layout.addWidget(self.ai_run_btn)

        self.ai_progress = QProgressBar()
        self.ai_progress.setRange(0, 100)
        self.ai_progress.setMaximumWidth(160)
        self.ai_progress.setVisible(False)
        stats_layout.addWidget(self.ai_progress)

        layout.addWidget(stats_group)
        
        # Results table
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Timestamp", "ML Prediction", "Confidence", "NINA State",
            "ML vs NINA", "Manual Label", "ML vs Label",
            "AI Pred", "AI vs NINA", "AI vs Label", "Folder", "Go"
        ])
        
        # Table styling
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget { 
                gridline-color: #333; 
                alternate-background-color: #252525;
            }
            QTableWidget::item { padding: 5px; }
            QHeaderView::section { 
                background: #333; 
                padding: 8px;
                border: 1px solid #444;
                font-weight: bold;
            }
        """)
        
        # Column sizing
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # ML Prediction
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Confidence
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # NINA
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # ML vs NINA
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Manual
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # ML vs Label
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)  # AI Pred
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)  # AI vs NINA
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)  # AI vs Label
        header.setSectionResizeMode(10, QHeaderView.Stretch)          # Folder
        header.setSectionResizeMode(11, QHeaderView.ResizeToContents)  # Go
        
        layout.addWidget(self.table)
        
        # Legend
        legend = QLabel(
            "🟢 OPEN  🔴 CLOSED  ✅ Match  ❌ Mismatch  "
            "⚠️ No NINA data  📝 Labeled  ⬜ Unlabeled"
        )
        legend.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(legend)
    
    def refresh_data(self):
        """Reload all sample data and refresh table."""
        self.all_data = []
        
        for idx, sample in enumerate(self.samples):
            if 'calibration' not in sample:
                continue
            
            try:
                with open(sample['calibration'], 'r') as f:
                    cal = json.load(f)
            except:
                continue
            
            ml = cal.get('ml_prediction')
            roof = cal.get('roof_state', {})
            labels = cal.get('labels', {})
            ai = cal.get('ai_suggestion')

            self.all_data.append({
                'index': idx,
                'timestamp': sample['timestamp'],
                'folder': str(sample['folder'].name),
                'ml_prediction': ml,
                'nina_state': roof,
                'labels': labels,
                'ai': ai,
                'lum': sample.get('lum'),
                'cal_path': sample['calibration'],
                'cal': cal
            })
        
        self.apply_filter()
    
    def apply_filter(self):
        """Apply selected filter and update table."""
        filter_idx = self.filter_combo.currentIndex()
        
        self.filtered_data = []
        
        for item in self.all_data:
            ml = item['ml_prediction']
            nina = item['nina_state']
            labels = item['labels']
            ai = item['ai']
            has_label = bool(labels.get('labeled_at'))

            if filter_idx == 0:  # All with ML
                if ml:
                    self.filtered_data.append(item)
            elif filter_idx == 1:  # ML matches NINA
                if ml and nina.get('available'):
                    if to_bool(ml.get('roof_open')) == to_bool(nina.get('roof_open')):
                        self.filtered_data.append(item)
            elif filter_idx == 2:  # ML disagrees with NINA
                if ml and nina.get('available'):
                    if to_bool(ml.get('roof_open')) != to_bool(nina.get('roof_open')):
                        self.filtered_data.append(item)
            elif filter_idx == 3:  # Labeled only
                if has_label and ml:
                    self.filtered_data.append(item)
            elif filter_idx == 4:  # Unlabeled only
                if not has_label and ml:
                    self.filtered_data.append(item)
            elif filter_idx == 5:  # Has AI suggestion
                if ai:
                    self.filtered_data.append(item)
            elif filter_idx == 6:  # Missing AI suggestion
                if not ai:
                    self.filtered_data.append(item)
            elif filter_idx == 7:  # AI disagrees with NINA
                if ai and nina.get('available'):
                    if bool(ai.get('roof_open')) != to_bool(nina.get('roof_open')):
                        self.filtered_data.append(item)
            elif filter_idx == 8:  # AI disagrees with manual label
                if ai and has_label:
                    if bool(ai.get('roof_open')) != to_bool(labels.get('roof_open')):
                        self.filtered_data.append(item)

        self.update_table()
        self.update_stats()
    
    def update_stats(self):
        """Update statistics labels."""
        total = len(self.all_data)
        with_ml = sum(1 for d in self.all_data if d['ml_prediction'])
        
        self.total_label.setText(f"Total: {total}")
        self.with_ml_label.setText(f"With ML: {with_ml}")
        
        # Calculate accuracy vs NINA
        correct = 0
        compared = 0
        for item in self.all_data:
            ml = item['ml_prediction']
            nina = item['nina_state']
            if ml and nina.get('available'):
                compared += 1
                if to_bool(ml.get('roof_open')) == to_bool(nina.get('roof_open')):
                    correct += 1
        
        if compared > 0:
            accuracy = (correct / compared) * 100
            self.accuracy_label.setText(f"Accuracy vs NINA: {accuracy:.1f}% ({correct}/{compared})")
            self.accuracy_bar.setValue(int(accuracy))
        else:
            self.accuracy_label.setText("Accuracy vs NINA: -- (no comparisons)")
            self.accuracy_bar.setValue(0)

        ai_correct = ai_compared = 0
        for item in self.all_data:
            ai = item['ai']
            nina = item['nina_state']
            if ai and nina.get('available'):
                ai_compared += 1
                if bool(ai.get('roof_open')) == to_bool(nina.get('roof_open')):
                    ai_correct += 1
        if ai_compared:
            self.ai_accuracy_label.setText(
                f"AI vs NINA: {ai_correct / ai_compared * 100:.1f}% ({ai_correct}/{ai_compared})")
        else:
            self.ai_accuracy_label.setText("AI vs NINA: --")
    
    def update_table(self):
        """Update table with filtered data."""
        self.table.setRowCount(len(self.filtered_data))
        
        for row, item in enumerate(self.filtered_data):
            ml = item['ml_prediction']
            nina = item['nina_state']
            labels = item['labels']
            ai = item['ai']

            # Timestamp
            ts_item = QTableWidgetItem(item['timestamp'])
            self.table.setItem(row, 0, ts_item)
            
            # ML Prediction
            if ml:
                ml_open = to_bool(ml.get('roof_open'))
                ml_text = "🟢 OPEN" if ml_open else "🔴 CLOSED"
                ml_item = QTableWidgetItem(ml_text)
                ml_item.setForeground(QBrush(QColor("#10b981" if ml_open else "#ef4444")))
            else:
                ml_item = QTableWidgetItem("--")
            self.table.setItem(row, 1, ml_item)
            
            # Confidence
            if ml:
                conf = ml.get('confidence', 0) * 100
                conf_item = QTableWidgetItem(f"{conf:.1f}%")
                # Color by confidence level
                if conf >= 95:
                    conf_item.setForeground(QBrush(QColor("#10b981")))
                elif conf >= 80:
                    conf_item.setForeground(QBrush(QColor("#f59e0b")))
                else:
                    conf_item.setForeground(QBrush(QColor("#ef4444")))
            else:
                conf_item = QTableWidgetItem("--")
            self.table.setItem(row, 2, conf_item)
            
            # NINA State
            if nina.get('available'):
                nina_open = to_bool(nina.get('roof_open'))
                nina_text = "🟢 OPEN" if nina_open else "🔴 CLOSED"
                nina_item = QTableWidgetItem(nina_text)
            else:
                nina_item = QTableWidgetItem("⚠️ N/A")
                nina_item.setForeground(QBrush(QColor("#888")))
            self.table.setItem(row, 3, nina_item)
            
            # ML vs NINA
            if ml and nina.get('available'):
                match = to_bool(ml.get('roof_open')) == to_bool(nina.get('roof_open'))
                match_item = QTableWidgetItem("✅" if match else "❌")
                match_item.setForeground(QBrush(QColor("#10b981" if match else "#ef4444")))
            else:
                match_item = QTableWidgetItem("--")
            self.table.setItem(row, 4, match_item)
            
            # Manual Label
            if labels.get('labeled_at'):
                label_open = to_bool(labels.get('roof_open'))
                label_text = "🟢 OPEN" if label_open else "🔴 CLOSED"
                label_item = QTableWidgetItem(f"📝 {label_text}")
            else:
                label_item = QTableWidgetItem("⬜ --")
                label_item.setForeground(QBrush(QColor("#888")))
            self.table.setItem(row, 5, label_item)
            
            # ML vs Label
            if ml and labels.get('labeled_at'):
                match = to_bool(ml.get('roof_open')) == to_bool(labels.get('roof_open'))
                mlabel_item = QTableWidgetItem("✅" if match else "❌")
                mlabel_item.setForeground(QBrush(QColor("#10b981" if match else "#ef4444")))
            else:
                mlabel_item = QTableWidgetItem("--")
            self.table.setItem(row, 6, mlabel_item)

            # AI Prediction
            if ai:
                ai_open = bool(ai.get('roof_open'))
                ai_item = QTableWidgetItem("🟢 OPEN" if ai_open else "🔴 CLOSED")
                ai_item.setForeground(QBrush(QColor("#10b981" if ai_open else "#ef4444")))
            else:
                ai_item = QTableWidgetItem("--")
                ai_item.setForeground(QBrush(QColor("#888")))
            self.table.setItem(row, 7, ai_item)

            # AI vs NINA
            self.table.setItem(row, 8, self._match_cell(
                ai and nina.get('available'),
                ai and bool(ai.get('roof_open')) == to_bool(nina.get('roof_open'))))

            # AI vs Label
            self.table.setItem(row, 9, self._match_cell(
                ai and labels.get('labeled_at'),
                ai and bool(ai.get('roof_open')) == to_bool(labels.get('roof_open'))))

            # Folder
            folder_item = QTableWidgetItem(item['folder'])
            self.table.setItem(row, 10, folder_item)

            # Go button
            go_btn = QPushButton("→")
            go_btn.setMaximumWidth(40)
            go_btn.setToolTip("Go to this sample in Labeling tab")
            go_btn.clicked.connect(lambda checked, idx=item['index']: self.go_to_sample(idx))
            self.table.setCellWidget(row, 11, go_btn)
    
    def _match_cell(self, applicable, is_match) -> QTableWidgetItem:
        """Build a ✅/❌ cell, or '--' when the comparison doesn't apply."""
        if not applicable:
            return QTableWidgetItem("--")
        item = QTableWidgetItem("✅" if is_match else "❌")
        item.setForeground(QBrush(QColor("#10b981" if is_match else "#ef4444")))
        return item

    def go_to_sample(self, index: int):
        """Emit signal to navigate to sample."""
        self.navigate_to_sample.emit(index)

    # ── AI batch run ──────────────────────────────────────────────────────────

    def run_ai_on_filtered(self):
        """Send every currently-filtered frame that has a lum image to the AI labeler."""
        jobs = [
            {'cal_path': str(item['cal_path']), 'lum_path': str(item['lum']),
             'timestamp': item['timestamp']}
            for item in self.filtered_data if item.get('lum')
        ]
        if not jobs:
            QMessageBox.information(self, "Run AI", "No filtered rows have a lum frame to send.")
            return

        est = len(jobs) * 0.0008
        reply = QMessageBox.question(
            self, "Run AI on filtered",
            f"Send {len(jobs)} frame(s) to OpenRouter (~${est:.2f})?\n\n"
            f"This overwrites any existing AI suggestion on these frames and runs "
            f"image-only (no hints).",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        from ml.ai_worker import AiLabelWorker
        self.ai_run_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.filter_combo.setEnabled(False)
        self.ai_progress.setVisible(True)
        self.ai_progress.setValue(0)

        self._batch_worker = AiLabelWorker(jobs)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.completed.connect(self._on_batch_done)
        self._batch_worker.start()

    def _on_batch_progress(self, done: int, total: int, msg: str):
        self.ai_progress.setValue(int(done / total * 100) if total else 0)
        self.ai_accuracy_label.setText(f"AI: {done}/{total} — {msg[:40]}")

    def _on_batch_done(self, labelled: int, failed: int, error: str):
        self.ai_run_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.filter_combo.setEnabled(True)
        self.ai_progress.setVisible(False)
        msg = f"AI labelled {labelled} frame(s); {failed} failed."
        if failed and error:
            msg += f"\n\nLast error: {error}"
            if "OPENROUTER_API_KEY" in error:
                msg += "\n\nThe key is not set in this app's environment — launch the tool from a shell that has it."
        QMessageBox.information(self, "Run AI complete", msg)
        self.refresh_data()
