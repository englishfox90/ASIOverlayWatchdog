"""
Live Monitoring Panel
Always-visible panel showing preview, histogram, and activity log
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy, QTextEdit, QGridLayout
)
from PySide6.QtCore import Qt, Signal, QTimer, Slot
from PySide6.QtGui import QFont, QPixmap, QImage, QPainter, QColor, QPen
from qfluentwidgets import CardWidget, SubtitleLabel, BodyLabel, CaptionLabel, ProgressBar

from PIL import Image
import numpy as np
from datetime import datetime

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..components.cards import MonitoringCard


class PreviewWidget(QFrame):
    """Image preview widget with metadata overlay"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._metadata = {}
        self._setup_ui()
    
    def _setup_ui(self):
        self.setMinimumSize(200, 150)
        # Allow flexible sizing - image will scale to fit
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.bg_input};
                border: none;
                border-radius: {Layout.radius_md}px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Image label (centered)
        self.image_label = QLabel("No image yet")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet(f"""
            color: {Colors.text_muted};
            font-size: {Typography.size_body}px;
        """)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label)
    
    def update_image(self, pil_image: Image.Image, metadata: dict = None):
        """Update preview with new image"""
        try:
            # Convert PIL to QPixmap
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            data = pil_image.tobytes('raw', 'RGB')
            qimg = QImage(data, pil_image.width, pil_image.height, 
                         pil_image.width * 3, QImage.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qimg)
            self._metadata = metadata or {}
            
            # Scale to fit while maintaining aspect ratio
            self._update_display()
            
        except Exception as e:
            self.image_label.setText(f"Error: {e}")
    
    def _update_display(self):
        """Update displayed image scaled to fit widget (letterboxed)"""
        if self._pixmap:
            # Scale to fit - uses KeepAspectRatio to fit entire image with letterboxing
            scaled = self._pixmap.scaled(
                self.image_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()


class HistogramWidget(QFrame):
    """RGB histogram display with auto-exposure indicators"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hist_data = None
        self._auto_exposure = False
        self._target_brightness = 30
        self._setup_ui()
    
    def _setup_ui(self):
        self.setFixedHeight(100)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.bg_input};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
            }}
        """)
    
    def update_histogram(self, pil_image: Image.Image):
        """Calculate and store histogram data from image"""
        try:
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            # Calculate histograms
            np_img = np.array(pil_image)
            self._hist_data = {
                'r': np.histogram(np_img[:,:,0], bins=256, range=(0,256))[0],
                'g': np.histogram(np_img[:,:,1], bins=256, range=(0,256))[0],
                'b': np.histogram(np_img[:,:,2], bins=256, range=(0,256))[0],
            }
            
            self.update()  # Trigger repaint
            
        except Exception as e:
            print(f"Histogram error: {e}")
    
    def update_from_data(self, hist_data: dict):
        """Update histogram from pre-calculated data
        
        Args:
            hist_data: dict with 'r', 'g', 'b' keys containing histogram arrays
                       Optional: 'auto_exposure', 'target_brightness' for indicators
        """
        try:
            if hist_data and 'r' in hist_data and 'g' in hist_data and 'b' in hist_data:
                self._hist_data = hist_data
                self._auto_exposure = hist_data.get('auto_exposure', False)
                self._target_brightness = hist_data.get('target_brightness', 30)
                print(f"Histogram update - auto_exposure: {self._auto_exposure}, target: {self._target_brightness}")
                self.update()  # Trigger repaint
        except Exception as e:
            print(f"Histogram update error: {e}")
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if not self._hist_data:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        padding = 4
        
        # Normalize histograms to 0-90 range like old GUI (leaves 10% padding at bottom)
        max_val = max(
            self._hist_data['r'].max(),
            self._hist_data['g'].max(),
            self._hist_data['b'].max()
        )
        
        if max_val == 0:
            return
        
        # Normalize to 90 for consistent scaling (old GUI uses 90 not 100)
        hist_r_norm = (self._hist_data['r'] / max_val) * 90
        hist_g_norm = (self._hist_data['g'] / max_val) * 90
        hist_b_norm = (self._hist_data['b'] / max_val) * 90
        
        bin_width = (width - 2 * padding) / 256
        
        # Draw each channel as smooth path
        from PySide6.QtGui import QPainterPath
        from PySide6.QtCore import QPointF
        
        # Apply smoothing to histogram data for better visual appearance
        def smooth_histogram(hist_array, window=5):
            """Apply simple moving average smoothing"""
            import numpy as np
            smoothed = np.copy(hist_array).astype(float)
            for i in range(len(hist_array)):
                start = max(0, i - window // 2)
                end = min(len(hist_array), i + window // 2 + 1)
                smoothed[i] = np.mean(hist_array[start:end])
            return smoothed
        
        # Smooth the histograms
        hist_r_smooth = smooth_histogram(hist_r_norm, window=3)
        hist_g_smooth = smooth_histogram(hist_g_norm, window=3)
        hist_b_smooth = smooth_histogram(hist_b_norm, window=3)
        
        colors = [
            (hist_r_smooth, QColor('#ff6b6b')),
            (hist_g_smooth, QColor('#51cf66')),
            (hist_b_smooth, QColor('#339af0')),
        ]
        
        for hist, color in colors:
            pen = QPen(color, 2)
            painter.setPen(pen)
            
            # Build smooth path with cubic bezier curves
            path = QPainterPath()
            
            # Start at first point
            x0 = padding
            y0_normalized = 100 - hist[0]
            y0 = padding + (y0_normalized / 100.0 * (height - 2 * padding))
            path.moveTo(QPointF(x0, y0))
            
            # Draw smooth curve through points using cubic bezier
            for i in range(1, 256):
                x_curr = padding + i * bin_width
                y_curr_normalized = 100 - hist[i]
                y_curr = padding + (y_curr_normalized / 100.0 * (height - 2 * padding))
                
                if i < 255:
                    # Calculate control points for smooth curve
                    x_prev = padding + (i - 1) * bin_width
                    y_prev_normalized = 100 - hist[i - 1]
                    y_prev = padding + (y_prev_normalized / 100.0 * (height - 2 * padding))
                    
                    x_next = padding + (i + 1) * bin_width
                    y_next_normalized = 100 - hist[i + 1]
                    y_next = padding + (y_next_normalized / 100.0 * (height - 2 * padding))
                    
                    # Control points for cubic bezier (1/3 distance to neighbors)
                    cp1_x = x_prev + (x_curr - x_prev) * 0.67
                    cp1_y = y_prev + (y_curr - y_prev) * 0.67
                    cp2_x = x_curr + (x_next - x_curr) * 0.33
                    cp2_y = y_curr + (y_next - y_curr) * 0.33
                    
                    path.cubicTo(QPointF(cp1_x, cp1_y), QPointF(cp2_x, cp2_y), QPointF(x_curr, y_curr))
                else:
                    # Last point - just line to it
                    path.lineTo(QPointF(x_curr, y_curr))
            
            painter.drawPath(path)
        
        # Draw target brightness and clipping indicators if auto exposure enabled
        if self._auto_exposure:
            print(f"Drawing auto-exposure markers - target: {self._target_brightness}")
            
            # Target brightness line (yellow dashed) - vertical line at target brightness X position
            target_x = padding + (self._target_brightness / 255.0) * (width - 2 * padding)
            pen = QPen(QColor('#ffd700'), 2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(target_x), padding, int(target_x), height - padding)
            
            # Target label with correct color
            painter.setPen(QColor('#ffd700'))
            painter.setFont(QFont('Segoe UI', 8, QFont.Bold))
            painter.drawText(int(target_x) + 3, padding + 12, f'Target: {int(self._target_brightness)}')
            
            # Clipping threshold line (red dashed at 245)
            clip_x = padding + (245 / 255.0) * (width - 2 * padding)
            pen = QPen(QColor('#ff4444'), 1)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(clip_x), padding, int(clip_x), height - padding)
            
            # Clip label with correct color
            painter.setPen(QColor('#ff4444'))
            painter.setFont(QFont('Segoe UI', 7))
            painter.drawText(int(clip_x) + 3, padding + 22, 'Clip')


class MetadataWidget(QFrame):
    """Compact metadata display"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
            }}
        """)
        
        layout = QGridLayout(self)
        layout.setContentsMargins(0, Spacing.sm, 0, 0)
        layout.setSpacing(Spacing.sm)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        
        # Row 0: Filename, Timestamp
        self.filename_label = CaptionLabel("File:")
        self.filename_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.filename_value = BodyLabel("-")
        self.filename_value.setStyleSheet(f"color: {Colors.text_secondary};")
        
        self.time_label = CaptionLabel("Time:")
        self.time_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.time_value = BodyLabel("-")
        self.time_value.setStyleSheet(f"color: {Colors.text_secondary};")
        
        layout.addWidget(self.filename_label, 0, 0)
        layout.addWidget(self.filename_value, 0, 1)
        layout.addWidget(self.time_label, 0, 2)
        layout.addWidget(self.time_value, 0, 3)
        
        # Row 1: Exposure, Gain
        self.exp_label = CaptionLabel("Exp:")
        self.exp_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.exp_value = BodyLabel("-")
        self.exp_value.setStyleSheet(f"color: {Colors.text_secondary};")
        
        self.gain_label = CaptionLabel("Gain:")
        self.gain_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.gain_value = BodyLabel("-")
        self.gain_value.setStyleSheet(f"color: {Colors.text_secondary};")
        
        layout.addWidget(self.exp_label, 1, 0)
        layout.addWidget(self.exp_value, 1, 1)
        layout.addWidget(self.gain_label, 1, 2)
        layout.addWidget(self.gain_value, 1, 3)
    
    def update_metadata(self, metadata: dict):
        """Update displayed metadata"""
        # Handle both old format (lowercase) and camera format (uppercase)
        filename = metadata.get('filename') or metadata.get('FILENAME', '-')
        self.filename_value.setText(filename)
        
        timestamp = metadata.get('timestamp') or metadata.get('DATETIME', '-')
        self.time_value.setText(timestamp)
        
        # Format exposure - handle string format "20s" or "0.1s" from camera
        exp = metadata.get('exposure') or metadata.get('EXPOSURE', '-')
        if isinstance(exp, str):
            # Try to parse if it's a string like "20s"
            try:
                exp_num = float(exp.rstrip('sSmM'))
                exp = exp_num
            except (ValueError, AttributeError):
                self.exp_value.setText(exp)
                exp = None
        
        if isinstance(exp, (int, float)):
            # Numeric value in seconds - format dynamically
            if exp >= 60:
                # Minutes
                minutes = exp / 60.0
                self.exp_value.setText(f"{minutes:.2f}m")
            elif exp >= 1:
                # Seconds
                self.exp_value.setText(f"{exp:.2f}s")
            else:
                # Milliseconds
                ms = exp * 1000.0
                self.exp_value.setText(f"{ms:.2f}ms")
        elif exp != '-':
            self.exp_value.setText('-')
        
        gain = metadata.get('gain') or metadata.get('GAIN', '-')
        self.gain_value.setText(str(gain))


class ActivityLog(QFrame):
    """Compact scrolling activity log"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._max_lines = 100
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.bg_input};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.sm, Spacing.sm, Spacing.sm, Spacing.sm)
        layout.setSpacing(0)
        
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                color: {Colors.text_secondary};
                font-family: {Typography.family_mono};
                font-size: {Typography.size_small}px;
            }}
        """)
        layout.addWidget(self.text_area)
    
    def append_log(self, message: str):
        """Append a log message"""
        self.text_area.append(message)
        
        # Trim if too many lines
        doc = self.text_area.document()
        if doc.blockCount() > self._max_lines:
            from PySide6.QtGui import QTextCursor
            cursor = self.text_area.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 
                              doc.blockCount() - self._max_lines)
            cursor.removeSelectedText()
        
        # Auto-scroll to bottom
        scrollbar = self.text_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def append_logs(self, messages: list):
        """Append multiple log messages"""
        for msg in messages:
            self.append_log(msg)


class LiveMonitoringPanel(QScrollArea):
    """
    Live Monitoring Panel - Always visible left panel showing:
    - Large preview image
    - Histogram
    - Metadata line
    - Recent activity log
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.bg_app};
                border: none;
            }}
        """)
        
        # Content widget
        content = QWidget()
        self.setWidget(content)
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.card_gap)
        
        # === PREVIEW CARD ===
        preview_card = CardWidget()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding, 
                                         Spacing.card_padding, Spacing.card_padding)
        preview_layout.setSpacing(Spacing.element_gap)
        
        # Card header with progress bar
        header_layout = QHBoxLayout()
        header_layout.setSpacing(Spacing.element_gap)
        
        preview_header = SubtitleLabel("Preview")
        preview_header.setStyleSheet(f"color: {Colors.text_primary};")
        header_layout.addWidget(preview_header)
        
        header_layout.addStretch()
        
        # Countdown label
        self.countdown_label = BodyLabel("")
        self.countdown_label.setStyleSheet(f"""
            color: {Colors.text_primary};
            font-size: {Typography.size_body}px;
            font-weight: 600;
        """)
        self.countdown_label.setAlignment(Qt.AlignRight)
        self.countdown_label.hide()
        header_layout.addWidget(self.countdown_label)
        
        preview_layout.addLayout(header_layout)
        
        # Progress bar (below header)
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        preview_layout.addWidget(self.progress_bar)
        
        # Preview image
        self.preview = PreviewWidget()
        preview_layout.addWidget(self.preview, 1)
        
        # Metadata row
        self.metadata = MetadataWidget()
        preview_layout.addWidget(self.metadata)
        
        layout.addWidget(preview_card, 3)  # Larger stretch
        
        # === HISTOGRAM CARD ===
        self.hist_card = CardWidget()
        hist_layout = QVBoxLayout(self.hist_card)
        hist_layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                       Spacing.card_padding, Spacing.card_padding)
        hist_layout.setSpacing(Spacing.element_gap)
        
        hist_header = SubtitleLabel("Histogram")
        hist_header.setStyleSheet(f"color: {Colors.text_primary};")
        hist_layout.addWidget(hist_header)
        
        self.histogram = HistogramWidget()
        hist_layout.addWidget(self.histogram)
        
        layout.addWidget(self.hist_card)
        
        # === ACTIVITY LOG CARD ===
        self.log_card = CardWidget()
        log_layout = QVBoxLayout(self.log_card)
        log_layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                      Spacing.card_padding, Spacing.card_padding)
        log_layout.setSpacing(Spacing.element_gap)
        
        log_header = SubtitleLabel("Recent Activity")
        log_header.setStyleSheet(f"color: {Colors.text_primary};")
        log_layout.addWidget(log_header)
        
        self.activity_log = ActivityLog()
        self.activity_log.setMinimumHeight(120)
        log_layout.addWidget(self.activity_log, 1)
        
        layout.addWidget(self.log_card, 1)
    
    def set_preview_only(self, preview_only: bool):
        """Show only preview (hide histogram and activity log)"""
        self.hist_card.setVisible(not preview_only)
        self.log_card.setVisible(not preview_only)
    
    def update_exposure_progress(self, total_sec: float, remaining_sec: float):
        """Update exposure progress in preview card header"""
        if total_sec > 0 and remaining_sec > 0:
            progress = int(((total_sec - remaining_sec) / total_sec) * 100)
            self.progress_bar.setValue(progress)
            
            # Format countdown text
            if remaining_sec >= 60:
                countdown_text = f"{remaining_sec / 60:.1f}m"
            elif remaining_sec >= 1:
                countdown_text = f"{remaining_sec:.1f}s"
            elif remaining_sec > 0:
                countdown_text = f"{remaining_sec * 1000:.0f}ms"
            else:
                countdown_text = ""
            
            if countdown_text:
                self.countdown_label.setText(countdown_text)
                self.countdown_label.show()
                self.progress_bar.show()
            else:
                self.hide_progress()
        else:
            self.hide_progress()
    
    def hide_progress(self):
        """Hide progress bar and countdown"""
        self.countdown_label.hide()
        self.progress_bar.hide()
    
    def update_preview(self, pil_image: Image.Image, metadata: dict = None):
        """Update preview image and related displays"""
        self.preview.update_image(pil_image, metadata)
        self.histogram.update_histogram(pil_image)
        
        if metadata:
            self.metadata.update_metadata(metadata)
    
    def update_from_camera(self, camera_controller):
        """Update displays from camera controller state"""
        # This can be called for status updates without new images
        pass
    
    def append_logs(self, messages: list):
        """Append log messages to activity log"""
        self.activity_log.append_logs(messages)
