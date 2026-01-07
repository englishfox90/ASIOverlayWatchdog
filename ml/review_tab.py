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
    QComboBox, QProgressBar
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
        
        stats_layout.addStretch()
        
        # Filter
        stats_layout.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All with ML predictions",
            "ML matches NINA",
            "ML disagrees with NINA",
            "Labeled samples only",
            "Unlabeled only"
        ])
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        stats_layout.addWidget(self.filter_combo)
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        stats_layout.addWidget(self.refresh_btn)
        
        layout.addWidget(stats_group)
        
        # Results table
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Timestamp", "ML Prediction", "Confidence", "NINA State",
            "ML vs NINA", "Manual Label", "ML vs Label", "Folder", "Go"
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
        header.setSectionResizeMode(7, QHeaderView.Stretch)          # Folder
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)  # Go
        
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
            
            self.all_data.append({
                'index': idx,
                'timestamp': sample['timestamp'],
                'folder': str(sample['folder'].name),
                'ml_prediction': ml,
                'nina_state': roof,
                'labels': labels,
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
    
    def update_table(self):
        """Update table with filtered data."""
        self.table.setRowCount(len(self.filtered_data))
        
        for row, item in enumerate(self.filtered_data):
            ml = item['ml_prediction']
            nina = item['nina_state']
            labels = item['labels']
            
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
            
            # Folder
            folder_item = QTableWidgetItem(item['folder'])
            self.table.setItem(row, 7, folder_item)
            
            # Go button
            go_btn = QPushButton("→")
            go_btn.setMaximumWidth(40)
            go_btn.setToolTip("Go to this sample in Labeling tab")
            go_btn.clicked.connect(lambda checked, idx=item['index']: self.go_to_sample(idx))
            self.table.setCellWidget(row, 8, go_btn)
    
    def go_to_sample(self, index: int):
        """Emit signal to navigate to sample."""
        self.navigate_to_sample.emit(index)
