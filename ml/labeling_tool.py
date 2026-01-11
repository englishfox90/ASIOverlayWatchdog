#!/usr/bin/env python3
"""
ML Labeling Tool for PFR Sentinel

Simple GUI to view lum FITS + all-sky images and add/edit labels
in calibration JSON files. Shows model predictions alongside for comparison.

Usage:
    python ml/labeling_tool.py "E:\\Pier Camera ML Data"
    python ml/labeling_tool.py  # Uses default path
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QScrollArea, QSplitter, QMessageBox, QComboBox,
    QLineEdit, QTextEdit, QFrame, QSizePolicy, QTabWidget
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QImage, QKeySequence, QShortcut

import numpy as np

# Optional: astropy for FITS
try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False

# Optional: PIL for JPG
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Optional: ML models for predictions
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

ML_AVAILABLE = ROOF_ML_AVAILABLE or SKY_ML_AVAILABLE

# Import review tab
from ml.review_tab import ReviewTab, to_bool


def find_sample_sets(data_dir: Path) -> list:
    """
    Find all sample sets by timestamp (searches recursively).
    
    Returns list of dicts with paths to each file type.
    """
    samples = {}
    
    # Find all calibration files recursively and extract timestamps
    for cal_file in data_dir.rglob("calibration_*.json"):
        # Extract timestamp: calibration_20260105_220825.json -> 20260105_220825
        name = cal_file.stem
        if name.startswith("calibration_"):
            timestamp = name[len("calibration_"):]
            
            if timestamp not in samples:
                samples[timestamp] = {
                    'timestamp': timestamp,
                    'folder': cal_file.parent
                }
            
            samples[timestamp]['calibration'] = cal_file
    
    # Match lum and allsky files (in same folder as calibration)
    for timestamp, sample in samples.items():
        folder = sample['folder']
        lum_path = folder / f"lum_{timestamp}.fits"
        allsky_path = folder / f"allsky_{timestamp}.jpg"
        
        if lum_path.exists():
            sample['lum'] = lum_path
        if allsky_path.exists():
            sample['allsky'] = allsky_path
    
    # Sort by timestamp and return as list
    return [samples[ts] for ts in sorted(samples.keys())]


def load_fits_as_qpixmap(fits_path: Path, target_size: int = 400) -> QPixmap:
    """Load FITS file and return as QPixmap with basic stretch."""
    if not ASTROPY_AVAILABLE:
        return create_placeholder_pixmap("FITS not available\n(install astropy)", target_size)
    
    try:
        with fits.open(fits_path) as hdul:
            data = hdul[0].data
        
        if data is None:
            return create_placeholder_pixmap("No image data", target_size)
        
        # Simple arcsinh stretch
        data = data.astype(np.float32)
        
        # Normalize to 0-1
        vmin, vmax = np.percentile(data, [1, 99])
        if vmax > vmin:
            data = (data - vmin) / (vmax - vmin)
        data = np.clip(data, 0, 1)
        
        # Arcsinh stretch for dark scenes
        stretch = 5.0
        data = np.arcsinh(data * stretch) / np.arcsinh(stretch)
        
        # Convert to 8-bit
        img_8bit = (data * 255).astype(np.uint8)
        
        # Create QImage
        h, w = img_8bit.shape
        qimg = QImage(img_8bit.data, w, h, w, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg.copy())
        
        # Scale to target size
        return pixmap.scaled(target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
    except Exception as e:
        return create_placeholder_pixmap(f"Error: {e}", target_size)


def load_jpg_as_qpixmap(jpg_path: Path, target_size: int = 400) -> QPixmap:
    """Load JPG file and return as QPixmap."""
    try:
        pixmap = QPixmap(str(jpg_path))
        if pixmap.isNull():
            return create_placeholder_pixmap("Failed to load image", target_size)
        return pixmap.scaled(target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception as e:
        return create_placeholder_pixmap(f"Error: {e}", target_size)


def create_placeholder_pixmap(text: str, size: int) -> QPixmap:
    """Create a placeholder pixmap with text."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.darkGray)
    return pixmap


class LabelingTool(QMainWindow):
    """Main labeling tool window."""
    
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.samples = find_sample_sets(data_dir)
        self.current_index = 0
        self.current_cal = {}
        self.unsaved_changes = False
        
        # Load ML models if available
        self.roof_classifier = None
        self.sky_classifier = None
        
        if ROOF_ML_AVAILABLE:
            model_path = Path(__file__).parent / 'models' / 'roof_classifier_v1.pth'
            if model_path.exists():
                try:
                    self.roof_classifier = RoofClassifier.load(str(model_path), image_size=128)
                    print(f"✓ Loaded roof classifier from {model_path}")
                except Exception as e:
                    print(f"Warning: Failed to load roof model: {e}")
        
        if SKY_ML_AVAILABLE:
            model_path = Path(__file__).parent / 'models' / 'sky_classifier_v1.pth'
            if model_path.exists():
                try:
                    self.sky_classifier = SkyClassifier.load(str(model_path), image_size=256)
                    print(f"✓ Loaded sky classifier from {model_path}")
                except Exception as e:
                    print(f"Warning: Failed to load sky model: {e}")
        
        # Legacy alias for compatibility
        self.classifier = self.roof_classifier
        
        self.setWindowTitle(f"ML Labeling Tool - {data_dir}")
        self.setMinimumSize(1400, 900)
        
        self.setup_ui()
        self.setup_shortcuts()
        
        if self.samples:
            self.update_unlabeled_count()
            self.load_sample(0)
        else:
            QMessageBox.warning(self, "No Data", f"No calibration files found in:\n{data_dir}")
    
    def setup_ui(self):
        """Setup the main UI layout with tabs."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # Tab widget
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
        
        # Labeling tab
        labeling_widget = QWidget()
        labeling_layout = QHBoxLayout(labeling_widget)
        self.setup_labeling_ui(labeling_layout)
        self.tabs.addTab(labeling_widget, "📝 Labeling")
        
        # Review tab
        self.review_tab = ReviewTab(self.samples)
        self.review_tab.navigate_to_sample.connect(self.go_to_sample_from_review)
        self.tabs.addTab(self.review_tab, "🔍 Review Predictions")
        
        # Refresh review tab when switching to it
        self.tabs.currentChanged.connect(self.on_tab_changed)
    
    def on_tab_changed(self, index: int):
        """Handle tab change - refresh review data."""
        if index == 1:  # Review tab
            self.review_tab.refresh_data()
    
    def go_to_sample_from_review(self, index: int):
        """Navigate to a sample from the review tab."""
        self.tabs.setCurrentIndex(0)  # Switch to labeling tab
        self.load_sample(index)
    
    def setup_labeling_ui(self, main_layout):
        """Setup the labeling tab UI."""
        
        # Left side: Images
        images_widget = QWidget()
        images_layout = QVBoxLayout(images_widget)
        
        # All-sky image
        allsky_group = QGroupBox("All-Sky Camera")
        allsky_layout = QVBoxLayout(allsky_group)
        self.allsky_label = QLabel()
        self.allsky_label.setAlignment(Qt.AlignCenter)
        self.allsky_label.setMinimumSize(400, 400)
        self.allsky_label.setStyleSheet("background: #1a1a1a; border: 1px solid #333;")
        allsky_layout.addWidget(self.allsky_label)
        images_layout.addWidget(allsky_group)
        
        # Luminance image
        lum_group = QGroupBox("Luminance (Stretched)")
        lum_layout = QVBoxLayout(lum_group)
        self.lum_label = QLabel()
        self.lum_label.setAlignment(Qt.AlignCenter)
        self.lum_label.setMinimumSize(400, 400)
        self.lum_label.setStyleSheet("background: #1a1a1a; border: 1px solid #333;")
        lum_layout.addWidget(self.lum_label)
        images_layout.addWidget(lum_group)
        
        main_layout.addWidget(images_widget, 1)
        
        # Right side: Labels and context
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Navigation
        nav_group = QGroupBox("Navigation")
        nav_layout = QHBoxLayout(nav_group)
        
        self.prev_btn = QPushButton("← Previous (A)")
        self.prev_btn.clicked.connect(self.prev_sample)
        nav_layout.addWidget(self.prev_btn)
        
        self.sample_label = QLabel("0 / 0")
        self.sample_label.setAlignment(Qt.AlignCenter)
        nav_layout.addWidget(self.sample_label)
        
        self.next_btn = QPushButton("Next (D) →")
        self.next_btn.clicked.connect(self.next_sample)
        nav_layout.addWidget(self.next_btn)
        
        nav_layout.addSpacing(20)
        
        self.skip_labeled = QCheckBox("Skip labeled")
        self.skip_labeled.setToolTip("Only show unlabeled samples")
        self.skip_labeled.stateChanged.connect(self.on_skip_labeled_changed)
        nav_layout.addWidget(self.skip_labeled)
        
        self.unlabeled_count = QLabel("")
        self.unlabeled_count.setStyleSheet("color: #888;")
        nav_layout.addWidget(self.unlabeled_count)
        
        right_layout.addWidget(nav_group)
        
        # Timestamp
        self.timestamp_label = QLabel("")
        self.timestamp_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0EA5E9;")
        right_layout.addWidget(self.timestamp_label)
        
        # Scroll area for all the fields
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # Auto-populated context (read-only)
        context_group = QGroupBox("Auto-Populated Context (from APIs/sensors)")
        context_layout = QVBoxLayout(context_group)
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        self.context_text.setMaximumHeight(150)
        self.context_text.setStyleSheet("background: #2a2a2a; font-family: monospace;")
        context_layout.addWidget(self.context_text)
        scroll_layout.addWidget(context_group)
        
        # Model prediction panel (read-only) - expanded for sky classifier
        model_group = QGroupBox("🤖 ML Model Predictions")
        model_group.setStyleSheet("QGroupBox { font-weight: bold; color: #8b5cf6; }")
        model_layout = QVBoxLayout(model_group)
        self.model_text = QTextEdit()
        self.model_text.setReadOnly(True)
        self.model_text.setMaximumHeight(220)  # Taller to fit sky predictions
        self.model_text.setStyleSheet("background: #1e1b2e; font-family: monospace; border: 2px solid #8b5cf6;")
        model_layout.addWidget(self.model_text)
        scroll_layout.addWidget(model_group)
        
        # Manual labels (editable)
        labels_group = QGroupBox("Manual Labels (Edit These)")
        labels_group.setStyleSheet("QGroupBox { font-weight: bold; color: #10b981; }")
        labels_layout = QVBoxLayout(labels_group)
        
        # PRIMARY: Roof state (critical - model's main job)
        roof_frame = QFrame()
        roof_frame.setStyleSheet("background: #2d1f3d; border-radius: 5px; padding: 8px;")
        roof_layout = QVBoxLayout(roof_frame)
        roof_layout.addWidget(QLabel("ROOF STATE (from pier camera view):"))
        
        roof_row = QHBoxLayout()
        self.roof_open = QCheckBox("Roof is OPEN (sky visible)")
        self.roof_open.setStyleSheet("font-weight: bold; font-size: 14px;")
        roof_row.addWidget(self.roof_open)
        roof_row.addStretch()
        roof_layout.addLayout(roof_row)
        
        labels_layout.addWidget(roof_frame)
        
        # SKY CONDITIONS (when roof is open)
        sky_frame = QFrame()
        sky_frame.setStyleSheet("background: #1e3a5f; border-radius: 5px; padding: 8px;")
        sky_layout = QVBoxLayout(sky_frame)
        sky_layout.addWidget(QLabel("SKY CONDITIONS (label from all-sky, applies when roof open):"))
        
        # Sky condition dropdown
        sky_row = QHBoxLayout()
        sky_row.addWidget(QLabel("Overall sky:"))
        self.sky_condition = QComboBox()
        self.sky_condition.addItems(["", "Clear", "Mostly Clear", "Partly Cloudy", "Mostly Cloudy", "Overcast", "Fog/Haze"])
        sky_row.addWidget(self.sky_condition)
        sky_row.addStretch()
        sky_layout.addLayout(sky_row)
        
        self.clouds_visible = QCheckBox("Clouds visible")
        sky_layout.addWidget(self.clouds_visible)
        
        labels_layout.addWidget(sky_frame)
        
        # CELESTIAL OBJECTS
        celestial_frame = QFrame()
        celestial_frame.setStyleSheet("background: #1e293b; border-radius: 5px; padding: 8px;")
        celestial_layout = QVBoxLayout(celestial_frame)
        celestial_layout.addWidget(QLabel("CELESTIAL OBJECTS:"))
        
        # Stars
        self.stars_visible = QCheckBox("Stars visible")
        celestial_layout.addWidget(self.stars_visible)
        
        star_row = QHBoxLayout()
        star_row.addWidget(QLabel("Star density (0=none, 0.5=moderate, 1=milky way):"))
        self.star_density = QDoubleSpinBox()
        self.star_density.setRange(0, 1)
        self.star_density.setSingleStep(0.1)
        self.star_density.setDecimals(2)
        star_row.addWidget(self.star_density)
        star_row.addStretch()
        celestial_layout.addLayout(star_row)
        
        # Moon
        self.moon_visible = QCheckBox("Moon visible")
        celestial_layout.addWidget(self.moon_visible)
        
        labels_layout.addWidget(celestial_frame)
        
        # Notes (keep for edge cases)
        notes_frame = QFrame()
        notes_frame.setStyleSheet("background: #1e293b; border-radius: 5px; padding: 5px;")
        notes_layout = QVBoxLayout(notes_frame)
        notes_layout.addWidget(QLabel("Notes (optional):"))
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Edge cases, anomalies...")
        notes_layout.addWidget(self.notes_edit)
        labels_layout.addWidget(notes_frame)
        
        scroll_layout.addWidget(labels_group)
        
        # Classified mode display
        mode_group = QGroupBox("Classified Mode")
        mode_layout = QHBoxLayout(mode_group)
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f59e0b;")
        mode_layout.addWidget(self.mode_label)
        scroll_layout.addWidget(mode_group)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        right_layout.addWidget(scroll, 1)
        
        # Save button
        save_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save Labels (S)")
        self.save_btn.setStyleSheet("background: #10b981; color: white; font-weight: bold; padding: 10px;")
        self.save_btn.clicked.connect(self.save_labels)
        save_layout.addWidget(self.save_btn)
        
        self.save_next_btn = QPushButton("Save & Next (Space)")
        self.save_next_btn.setStyleSheet("background: #0EA5E9; color: white; font-weight: bold; padding: 10px;")
        self.save_next_btn.clicked.connect(self.save_and_next)
        save_layout.addWidget(self.save_next_btn)
        
        right_layout.addLayout(save_layout)
        
        # Status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        right_layout.addWidget(self.status_label)
        
        # Label state indicator
        self.label_state = QLabel("")
        right_layout.addWidget(self.label_state)
        
        main_layout.addWidget(right_widget, 1)
        
        # Connect change signals
        for widget in [self.roof_open, self.stars_visible, self.moon_visible, self.clouds_visible]:
            widget.stateChanged.connect(self.mark_unsaved)
        self.star_density.valueChanged.connect(self.mark_unsaved)
        self.sky_condition.currentIndexChanged.connect(self.mark_unsaved)
        self.notes_edit.textChanged.connect(self.mark_unsaved)
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        QShortcut(QKeySequence("A"), self, self.prev_sample)
        QShortcut(QKeySequence("D"), self, self.next_sample)
        QShortcut(QKeySequence("S"), self, self.save_labels)
        QShortcut(QKeySequence("Space"), self, self.save_and_next)
        QShortcut(QKeySequence("Left"), self, self.prev_sample)
        QShortcut(QKeySequence("Right"), self, self.next_sample)
    
    def is_sample_labeled(self, index: int) -> bool:
        """Check if a sample has been labeled."""
        sample = self.samples[index]
        if 'calibration' not in sample:
            return False
        try:
            with open(sample['calibration'], 'r') as f:
                cal = json.load(f)
            return bool(cal.get('labels', {}).get('labeled_at'))
        except:
            return False
    
    def count_unlabeled(self) -> int:
        """Count unlabeled samples."""
        return sum(1 for i in range(len(self.samples)) if not self.is_sample_labeled(i))
    
    def update_unlabeled_count(self):
        """Update the unlabeled count display."""
        unlabeled = self.count_unlabeled()
        total = len(self.samples)
        labeled = total - unlabeled
        self.unlabeled_count.setText(f"({labeled}/{total} labeled)")
    
    def on_skip_labeled_changed(self):
        """Handle skip labeled checkbox change."""
        self.update_unlabeled_count()
        if self.skip_labeled.isChecked():
            # Jump to next unlabeled if current is labeled
            if self.is_sample_labeled(self.current_index):
                self.next_sample()
    
    def find_next_unlabeled(self, start: int, direction: int = 1) -> int:
        """Find next unlabeled sample in given direction."""
        index = start + direction
        while 0 <= index < len(self.samples):
            if not self.is_sample_labeled(index):
                return index
            index += direction
        return -1
    
    def mark_unsaved(self):
        """Mark that there are unsaved changes."""
        self.unsaved_changes = True
        self.update_status()
    
    def update_status(self):
        """Update status bar."""
        if self.unsaved_changes:
            self.status_label.setText("⚠️ Unsaved changes")
            self.status_label.setStyleSheet("color: #f59e0b;")
        else:
            self.status_label.setText("✓ Saved")
            self.status_label.setStyleSheet("color: #10b981;")
    
    def load_sample(self, index: int):
        """Load a sample set by index."""
        if not self.samples:
            return
        
        # Check for unsaved changes
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes before moving to next sample?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self.save_labels()
            elif reply == QMessageBox.Cancel:
                return
        
        index = max(0, min(index, len(self.samples) - 1))
        self.current_index = index
        sample = self.samples[index]
        
        # Update navigation
        self.sample_label.setText(f"{index + 1} / {len(self.samples)}")
        folder_name = sample.get('folder', Path()).name
        self.timestamp_label.setText(f"[{folder_name}]  Timestamp: {sample['timestamp']}")
        
        # Update nav buttons based on skip mode
        if self.skip_labeled.isChecked():
            self.prev_btn.setEnabled(self.find_next_unlabeled(index, -1) >= 0)
            self.next_btn.setEnabled(self.find_next_unlabeled(index, 1) >= 0)
        else:
            self.prev_btn.setEnabled(index > 0)
            self.next_btn.setEnabled(index < len(self.samples) - 1)
        
        # Load images
        if 'allsky' in sample:
            pixmap = load_jpg_as_qpixmap(sample['allsky'], 380)
            self.allsky_label.setPixmap(pixmap)
        else:
            self.allsky_label.setPixmap(create_placeholder_pixmap("No all-sky image", 380))
        
        if 'lum' in sample:
            pixmap = load_fits_as_qpixmap(sample['lum'], 380)
            self.lum_label.setPixmap(pixmap)
        else:
            self.lum_label.setPixmap(create_placeholder_pixmap("No lum FITS", 380))
        
        # Load calibration
        if 'calibration' in sample:
            with open(sample['calibration'], 'r') as f:
                self.current_cal = json.load(f)
            self.populate_fields()
        else:
            self.current_cal = {}
            self.context_text.setText("No calibration file found")
        
        self.unsaved_changes = False
        self.update_status()
    
    def populate_fields(self):
        """Populate all fields from calibration data."""
        cal = self.current_cal
        
        # Build context summary
        context_lines = []
        
        # Time
        tc = cal.get('time_context', {})
        context_lines.append(f"Time: {tc.get('period', '?')} ({tc.get('detailed_period', '?')})")
        context_lines.append(f"  Daylight: {tc.get('is_daylight', '?')}, Astro Night: {tc.get('is_astronomical_night', '?')}")
        
        # Moon
        mc = cal.get('moon_context', {})
        if mc.get('available'):
            context_lines.append(f"Moon: {mc.get('phase_name', '?')} ({mc.get('illumination_pct', 0):.0f}%)")
            context_lines.append(f"  Moon up: {mc.get('moon_is_up', '?')}, Bright: {mc.get('is_bright_moon', '?')}")
        
        # Roof
        rs = cal.get('roof_state', {})
        if rs.get('available'):
            roof_str = "OPEN" if to_bool(rs.get('roof_open')) else "CLOSED"
            context_lines.append(f"Roof: {roof_str} (from {rs.get('source', '?')})")
        else:
            context_lines.append(f"Roof: Unknown ({rs.get('reason', 'no data')})")
        
        # Weather
        wc = cal.get('weather_context', {})
        if wc.get('available'):
            context_lines.append(f"Weather: {wc.get('condition', '?')} - {wc.get('description', '?')}")
            context_lines.append(f"  Clouds: {wc.get('cloud_coverage_pct', '?')}%, Humidity: {wc.get('humidity_pct', '?')}%")
            context_lines.append(f"  Clear: {wc.get('is_clear', '?')}")
        
        # Seeing
        se = cal.get('seeing_estimate', {})
        if se.get('available'):
            context_lines.append(f"Seeing: {se.get('quality', '?')} (score: {se.get('overall_score', 0):.2f})")
        
        # ML Prediction (from capture time)
        ml = cal.get('ml_prediction')
        if ml:
            ml_roof = "OPEN" if to_bool(ml.get('roof_open')) else "CLOSED"
            ml_conf = ml.get('confidence', 0) * 100
            context_lines.append(f"ML Prediction: {ml_roof} ({ml_conf:.1f}% conf) [{ml.get('model_version', '?')}]")
        
        # Image stats
        st = cal.get('stretch', {})
        context_lines.append(f"Image: median_lum={st.get('median_lum', 0):.4f}, dark_scene={st.get('is_dark_scene', '?')}")
        
        # Corner analysis
        ca = cal.get('corner_analysis', {})
        context_lines.append(f"Corner ratio: {ca.get('corner_to_center_ratio', 0):.4f}")
        
        self.context_text.setText("\n".join(context_lines))
        
        # Run ML model prediction and store results for prefill
        self.last_roof_prediction = None
        self.last_sky_prediction = None
        self.run_model_prediction()
        
        # Classified mode
        mode = self.classify_mode(cal)
        self.mode_label.setText(mode)
        
        # Load manual labels (or prefill from ML if not yet labeled)
        labels = cal.get('labels', {})
        has_labels = bool(labels.get('labeled_at'))
        
        # Block signals while setting values
        for widget in [self.roof_open, self.stars_visible, self.moon_visible, 
                       self.clouds_visible, self.star_density, self.sky_condition]:
            widget.blockSignals(True)
        
        if has_labels:
            # Use existing labels
            self.label_state.setText("✓ Previously labeled")
            self.label_state.setStyleSheet("color: #10b981; font-weight: bold;")
            
            self.roof_open.setChecked(to_bool(labels.get('roof_open', False)))
            self.stars_visible.setChecked(to_bool(labels.get('stars_visible', False)))
            self.star_density.setValue(labels.get('star_density', 0) or 0)
            self.moon_visible.setChecked(labels.get('moon_visible', False) or False)
            self.clouds_visible.setChecked(labels.get('clouds_visible', False) or False)
            
            sky_cond = labels.get('sky_condition', '')
            idx = self.sky_condition.findText(sky_cond)
            self.sky_condition.setCurrentIndex(idx if idx >= 0 else 0)
            
            self.notes_edit.setText(labels.get('notes', '') or '')
        else:
            # Pre-populate from ML predictions (much better than API heuristics)
            ml_prefilled = False
            
            # Roof from ML prediction
            if self.last_roof_prediction is not None:
                self.roof_open.setChecked(bool(self.last_roof_prediction.roof_open))
                ml_prefilled = True
            else:
                # Fallback to API/heuristic
                rs = cal.get('roof_state', {})
                ca = cal.get('corner_analysis', {})
                if rs.get('available') and rs.get('source') == 'nina_api':
                    self.roof_open.setChecked(to_bool(rs.get('roof_open', False)))
                else:
                    ratio = ca.get('corner_to_center_ratio', 1.0)
                    self.roof_open.setChecked(ratio < 0.95)
            
            # Sky condition, stars, moon from ML prediction
            if self.last_sky_prediction is not None:
                sky_pred = self.last_sky_prediction
                
                # Sky condition
                idx = self.sky_condition.findText(sky_pred.sky_condition)
                self.sky_condition.setCurrentIndex(idx if idx >= 0 else 0)
                
                # Clouds: infer from sky condition
                cloudy_conditions = ['Partly Cloudy', 'Mostly Cloudy', 'Overcast']
                self.clouds_visible.setChecked(sky_pred.sky_condition in cloudy_conditions)
                
                # Stars
                self.stars_visible.setChecked(bool(sky_pred.stars_visible))
                self.star_density.setValue(sky_pred.star_density if sky_pred.stars_visible else 0)
                
                # Moon
                self.moon_visible.setChecked(bool(sky_pred.moon_visible))
                ml_prefilled = True
            else:
                # Fallback to API heuristics
                wc = cal.get('weather_context', {})
                mc = cal.get('moon_context', {})
                tc = cal.get('time_context', {})
                
                if wc.get('available'):
                    cloud_pct = wc.get('cloud_coverage_pct', 0)
                    self.clouds_visible.setChecked(cloud_pct > 10)
                    
                    if cloud_pct <= 10:
                        sky_cond = "Clear"
                    elif cloud_pct <= 25:
                        sky_cond = "Mostly Clear"
                    elif cloud_pct <= 50:
                        sky_cond = "Partly Cloudy"
                    elif cloud_pct <= 75:
                        sky_cond = "Mostly Cloudy"
                    else:
                        sky_cond = "Overcast"
                    
                    idx = self.sky_condition.findText(sky_cond)
                    self.sky_condition.setCurrentIndex(idx if idx >= 0 else 0)
                else:
                    self.clouds_visible.setChecked(False)
                    self.sky_condition.setCurrentIndex(0)
                
                if mc.get('available'):
                    self.moon_visible.setChecked(mc.get('moon_is_up', False))
                else:
                    self.moon_visible.setChecked(False)
                
                is_night = tc.get('is_astronomical_night', False)
                roof_open = self.roof_open.isChecked()
                is_clear = wc.get('is_clear', False) if wc.get('available') else True
                stars_likely = is_night and roof_open and is_clear
                self.stars_visible.setChecked(stars_likely)
                self.star_density.setValue(0.5 if stars_likely else 0)
            
            self.notes_edit.setText('')
            
            if ml_prefilled:
                self.label_state.setText("🤖 ML-suggested (review & save)")
                self.label_state.setStyleSheet("color: #8b5cf6; font-weight: bold;")
            else:
                self.label_state.setText("⚡ API-suggested (review & save)")
                self.label_state.setStyleSheet("color: #f59e0b; font-weight: bold;")
        
        # Unblock signals
        for widget in [self.roof_open, self.stars_visible, self.moon_visible, 
                       self.clouds_visible, self.star_density, self.sky_condition]:
            widget.blockSignals(False)
    
    def classify_mode(self, cal: dict) -> str:
        """Classify image mode from calibration data."""
        tc = cal.get('time_context', {})
        rs = cal.get('roof_state', {})
        ca = cal.get('corner_analysis', {})
        
        # Determine day/night
        if tc.get('is_daylight'):
            time_period = 'day'
        elif tc.get('is_astronomical_night'):
            time_period = 'night'
        elif tc.get('period') == 'twilight':
            return 'twilight'
        else:
            hour = tc.get('hour', 12)
            time_period = 'night' if (hour >= 20 or hour < 6) else 'day'
        
        # Determine roof state
        if rs.get('available') and rs.get('source') == 'nina_api':
            roof_open = to_bool(rs.get('roof_open', False))
        else:
            ratio = ca.get('corner_to_center_ratio', 0.95)
            roof_open = ratio < 0.95
        
        roof_str = 'roof_open' if roof_open else 'roof_closed'
        return f"{time_period}_{roof_str}"
    
    def run_model_prediction(self):
        """Run ML models on the current image and display results. Stores results for prefill."""
        sample = self.samples[self.current_index]
        lines = []
        
        # Reset stored predictions
        self.last_roof_prediction = None
        self.last_sky_prediction = None
        
        if not self.roof_classifier and not self.sky_classifier:
            self.model_text.setText("⚠️ No ML models loaded\n\nTo train models:\n  python ml/train_roof_classifier.py\n  python ml/train_sky_classifier.py")
            return
        
        if 'lum' not in sample:
            self.model_text.setText("⚠️ No FITS image available for prediction")
            return
        
        # Get metadata for sky classifier
        metadata = None
        if self.current_cal:
            tc = self.current_cal.get('time_context', {})
            ca = self.current_cal.get('corner_analysis', {})
            mc = self.current_cal.get('moon_context', {})
            st = self.current_cal.get('stretch', {})
            metadata = {
                'corner_to_center_ratio': ca.get('corner_to_center_ratio', 1.0),
                'median_lum': st.get('median_lum', 0.0),
                'is_astronomical_night': tc.get('is_astronomical_night', False),
                'hour': tc.get('hour', 12),
                'moon_illumination': mc.get('illumination_pct', 0.0),
                'moon_is_up': mc.get('moon_is_up', False),
            }
        
        # === ROOF CLASSIFIER ===
        if self.roof_classifier:
            try:
                result = self.roof_classifier.predict_from_fits(sample['lum'])
                self.last_roof_prediction = result  # Store for prefill
                roof_status = "🟢 OPEN" if result.roof_open else "🔴 CLOSED"
                conf_bar = "█" * int(result.confidence * 10) + "░" * (10 - int(result.confidence * 10))
                
                lines.append("━━━ ROOF CLASSIFIER ━━━")
                lines.append(f"State:      {roof_status}")
                lines.append(f"Confidence: [{conf_bar}] {result.confidence:.1%}")
                
                # Compare with context/label
                rs = self.current_cal.get('roof_state', {})
                if rs.get('available'):
                    ctx_roof = to_bool(rs.get('roof_open', False))
                    match = "✓" if ctx_roof == result.roof_open else "✗"
                    lines.append(f"vs API:     {match}")
                
                labels = self.current_cal.get('labels', {})
                if labels.get('labeled_at'):
                    lbl_roof = to_bool(labels.get('roof_open', False))
                    match = "✓" if lbl_roof == result.roof_open else "✗"
                    lines.append(f"vs Label:   {match}")
                    
            except Exception as e:
                lines.append(f"━━━ ROOF CLASSIFIER ━━━")
                lines.append(f"⚠️ Error: {e}")
        
        # === SKY CLASSIFIER ===
        # Only run if roof is OPEN (pier camera can't see sky through closed roof)
        roof_is_open = self.last_roof_prediction and self.last_roof_prediction.roof_open
        
        if self.sky_classifier:
            lines.append("")
            lines.append("━━━ SKY CLASSIFIER ━━━")
            
            if not roof_is_open:
                # Can't predict sky/weather through closed roof
                lines.append("⛔ N/A - Roof is CLOSED")
                lines.append("   (Pier camera cannot see sky)")
                lines.append("")
                lines.append("   Note: Manual labels still work")
                lines.append("   (use all-sky camera reference)")
                # Don't store prediction - can't be used for prefill
                self.last_sky_prediction = None
            else:
                try:
                    result = self.sky_classifier.predict_from_fits(sample['lum'], metadata)
                    self.last_sky_prediction = result  # Store for prefill
                    
                    # Sky condition with probabilities
                    lines.append(f"Sky:     {result.sky_condition} ({result.sky_confidence:.0%})")
                    
                    # Show top 3 probabilities as mini-bars
                    sorted_probs = sorted(result.sky_probabilities.items(), key=lambda x: -x[1])
                    for cond, prob in sorted_probs[:3]:
                        bar = "█" * int(prob * 10) + "░" * (10 - int(prob * 10))
                        marker = "◄" if cond == result.sky_condition else " "
                        lines.append(f"  [{bar}] {prob:5.1%} {cond[:12]:<12}{marker}")
                    
                    # Stars
                    stars_icon = "⭐" if result.stars_visible else "  "
                    lines.append(f"Stars:   {stars_icon} {'Yes' if result.stars_visible else 'No'} ({result.stars_confidence:.0%})")
                    if result.stars_visible:
                        density_bar = "★" * int(result.star_density * 5) + "☆" * (5 - int(result.star_density * 5))
                        lines.append(f"         Density: [{density_bar}] {result.star_density:.2f}")
                    
                    # Moon
                    moon_icon = "🌙" if result.moon_visible else "  "
                    lines.append(f"Moon:    {moon_icon} {'Yes' if result.moon_visible else 'No'} ({result.moon_confidence:.0%})")
                    
                    # Compare with labels if present
                    labels = self.current_cal.get('labels', {})
                    if labels.get('labeled_at'):
                        lines.append("")
                        lines.append("vs Manual Labels:")
                        
                        # Sky condition match
                        lbl_sky = labels.get('sky_condition', '')
                        if lbl_sky:
                            match = "✓" if lbl_sky == result.sky_condition else "✗"
                            lines.append(f"  Sky:   {match} (label: {lbl_sky})")
                        
                        # Stars match
                        lbl_stars = to_bool(labels.get('stars_visible', False))
                        match = "✓" if lbl_stars == result.stars_visible else "✗"
                        lines.append(f"  Stars: {match}")
                        
                        # Moon match
                        lbl_moon = to_bool(labels.get('moon_visible', False))
                        match = "✓" if lbl_moon == result.moon_visible else "✗"
                        lines.append(f"  Moon:  {match}")
                        
                except Exception as e:
                    lines.append(f"⚠️ Error: {e}")
        
        self.model_text.setText("\n".join(lines))
    
    def save_labels(self):
        """Save labels to calibration file."""
        if not self.current_cal:
            return
        
        sample = self.samples[self.current_index]
        if 'calibration' not in sample:
            return
        
        # Update labels (simplified structure)
        if 'labels' not in self.current_cal:
            self.current_cal['labels'] = {}
        
        labels = self.current_cal['labels']
        labels['roof_open'] = self.roof_open.isChecked()
        labels['stars_visible'] = self.stars_visible.isChecked()
        labels['star_density'] = self.star_density.value() if self.stars_visible.isChecked() else 0
        labels['moon_visible'] = self.moon_visible.isChecked()
        labels['clouds_visible'] = self.clouds_visible.isChecked()
        
        sky_cond = self.sky_condition.currentText()
        if sky_cond:
            labels['sky_condition'] = sky_cond
        
        notes = self.notes_edit.text().strip()
        if notes:
            labels['notes'] = notes
        
        labels['labeled_at'] = datetime.now().isoformat()
        
        # Save file
        with open(sample['calibration'], 'w') as f:
            json.dump(self.current_cal, f, indent=2)
        
        self.unsaved_changes = False
        self.update_status()
        self.update_unlabeled_count()
        
        # Update label state indicator
        self.label_state.setText("✓ Previously labeled")
        self.label_state.setStyleSheet("color: #10b981; font-weight: bold;")
    
    def save_and_next(self):
        """Save and move to next sample."""
        self.save_labels()
        self.next_sample()
    
    def prev_sample(self):
        """Go to previous sample."""
        if self.skip_labeled.isChecked():
            next_idx = self.find_next_unlabeled(self.current_index, -1)
            if next_idx >= 0:
                self.load_sample(next_idx)
        elif self.current_index > 0:
            self.load_sample(self.current_index - 1)
    
    def next_sample(self):
        """Go to next sample."""
        if self.skip_labeled.isChecked():
            next_idx = self.find_next_unlabeled(self.current_index, 1)
            if next_idx >= 0:
                self.load_sample(next_idx)
            else:
                QMessageBox.information(self, "Done", "All samples have been labeled!")
        elif self.current_index < len(self.samples) - 1:
            self.load_sample(self.current_index + 1)
    
    def closeEvent(self, event):
        """Handle window close."""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self.save_labels()
                event.accept()
            elif reply == QMessageBox.No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="ML Labeling Tool for calibration data")
    parser.add_argument("data_dir", nargs="?", default=r"E:\Pier Camera ML Data",
                        help="Directory containing calibration files")
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Directory not found: {data_dir}")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Dark theme
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
