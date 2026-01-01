"""
App Bar Component
Top application bar with status chips and primary action
"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QPixmap, QIcon
from qfluentwidgets import (
    PushButton, ToolButton, PrimaryPushButton, 
    FluentIcon, ProgressBar, InfoBadge, CaptionLabel
)

import os
from datetime import datetime

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.styles import get_status_chip_style


class StatusChip(QFrame):
    """Small status indicator chip"""
    
    def __init__(self, label: str, status: str = 'idle', parent=None):
        super().__init__(parent)
        self._label = label
        self._status = status
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.label = QLabel(self._label)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        
        self.setFixedHeight(Layout.status_chip_height)
    
    def _apply_style(self):
        self.setStyleSheet(get_status_chip_style(self._status))
    
    def set_status(self, status: str):
        """Update chip status (changes color)"""
        self._status = status
        self._apply_style()
    
    def set_label(self, label: str):
        """Update chip label text"""
        self._label = label
        self.label.setText(label)


class AppBar(QFrame):
    """
    Top application bar with:
    - Left: App name + icon
    - Center: Status chips (Camera, Web, Discord, Device)
    - Right: Session info, image count, Start/Stop button
    """
    
    start_clicked = Signal()
    stop_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_capturing = False
        self._setup_ui()
    
    def _setup_ui(self):
        self.setFixedHeight(Layout.app_bar_height)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.bg_surface};
                border-bottom: 1px solid {Colors.border_subtle};
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.base, 0, Spacing.base, 0)
        layout.setSpacing(Spacing.lg)
        
        # === LEFT: App branding ===
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(Spacing.sm)
        
        # App icon (small)
        self.app_icon = QLabel()
        self.app_icon.setFixedSize(28, 28)
        try:
            from utils_paths import resource_path
            icon_path = resource_path('assets/app_icon.ico')
            if os.path.exists(icon_path):
                pixmap = QPixmap(icon_path).scaled(
                    28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.app_icon.setPixmap(pixmap)
        except:
            pass
        brand_layout.addWidget(self.app_icon)
        
        # App name
        self.app_name = QLabel("PFR Sentinel")
        self.app_name.setStyleSheet(f"""
            font-size: {Typography.size_subtitle}px;
            font-weight: {Typography.weight_semibold};
            color: {Colors.text_primary};
        """)
        brand_layout.addWidget(self.app_name)
        
        layout.addLayout(brand_layout)
        
        # === CENTER: Status chips ===
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(Spacing.sm)
        
        self.camera_chip = StatusChip("Camera", "idle")
        self.web_chip = StatusChip("Web", "disabled")
        self.discord_chip = StatusChip("Discord", "disabled")
        
        chips_layout.addWidget(self.camera_chip)
        chips_layout.addWidget(self.web_chip)
        chips_layout.addWidget(self.discord_chip)
        
        layout.addLayout(chips_layout)
        
        # Spacer
        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        
        # === RIGHT: Session info + Actions ===
        right_layout = QHBoxLayout()
        right_layout.setSpacing(Spacing.lg)
        
        # Session date
        self.session_label = QLabel("Session")
        self.session_label.setStyleSheet(f"color: {Colors.text_muted}; font-size: {Typography.size_caption}px;")
        self.session_value = QLabel(datetime.now().strftime('%Y-%m-%d'))
        self.session_value.setStyleSheet(f"color: {Colors.text_secondary}; font-size: {Typography.size_body}px;")
        
        session_vbox = QVBoxLayout()
        session_vbox.setSpacing(0)
        session_vbox.addWidget(self.session_label)
        session_vbox.addWidget(self.session_value)
        right_layout.addLayout(session_vbox)
        
        # Image count
        self.count_label = QLabel("Images")
        self.count_label.setStyleSheet(f"color: {Colors.text_muted}; font-size: {Typography.size_caption}px;")
        self.count_value = QLabel("0")
        self.count_value.setStyleSheet(f"""
            color: {Colors.success_text}; 
            font-size: {Typography.size_subtitle}px;
            font-weight: {Typography.weight_bold};
        """)
        
        count_vbox = QVBoxLayout()
        count_vbox.setSpacing(0)
        count_vbox.addWidget(self.count_label)
        count_vbox.addWidget(self.count_value)
        right_layout.addLayout(count_vbox)
        
        # Exposure progress with countdown
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(2)
        
        self.countdown_label = CaptionLabel("")
        self.countdown_label.setStyleSheet(f"""
            color: {Colors.text_secondary};
            font-size: {Typography.size_small}px;
        """)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setFixedWidth(100)
        self.countdown_label.hide()
        progress_layout.addWidget(self.countdown_label)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedWidth(100)
        self.progress_bar.setFixedHeight(6)  # Slightly taller for visibility
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        progress_layout.addWidget(self.progress_bar)
        
        # Add a label showing "Processing..." or similar
        self.processing_label = CaptionLabel("Processing...")
        self.processing_label.setStyleSheet(f"color: {Colors.accent_default};")
        self.processing_label.setAlignment(Qt.AlignCenter)
        self.processing_label.setFixedWidth(100)
        self.processing_label.hide()
        progress_layout.addWidget(self.processing_label)
        
        right_layout.addLayout(progress_layout)
        
        # Start/Stop buttons
        self.start_btn = PrimaryPushButton("Start Capture")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.start_btn.setFixedWidth(140)
        self.start_btn.clicked.connect(self._on_start_clicked)
        
        self.stop_btn = PushButton("Stop")
        self.stop_btn.setIcon(FluentIcon.PAUSE)
        self.stop_btn.setFixedWidth(100)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.error_default};
                color: white;
                border: none;
                border-radius: {Layout.radius_md}px;
                padding: 8px 16px 8px 32px;
            }}
            QPushButton:hover {{
                background-color: {Colors.error_hover};
            }}
            QPushButton::icon {{
                padding-right: 8px;
            }}
        """)
        self.stop_btn.hide()
        
        right_layout.addWidget(self.start_btn)
        right_layout.addWidget(self.stop_btn)
        
        layout.addLayout(right_layout)
    
    def _on_start_clicked(self):
        self.start_clicked.emit()
    
    def _on_stop_clicked(self):
        self.stop_clicked.emit()
    
    def set_capturing(self, capturing: bool):
        """Update button states for capturing mode"""
        self._is_capturing = capturing
        
        if capturing:
            self.start_btn.hide()
            self.stop_btn.show()
            self.processing_label.hide()
            self.camera_chip.set_status('capturing')
            self.camera_chip.set_label('Capturing')
        else:
            self.start_btn.show()
            self.stop_btn.hide()
            self.processing_label.hide()
            self.camera_chip.set_status('idle')
            self.camera_chip.set_label('Camera')
    
    def update_image_count(self, count: int):
        """Update image counter display"""
        self.count_value.setText(str(count))
    
    def update_exposure_progress(self, total_sec: float, remaining_sec: float):
        """Update exposure progress (forwarded to live monitoring panel)
        
        Note: This is now handled by the preview widget overlay.
        This method exists for backward compatibility with update_status calls.
        The actual progress display is in LiveMonitoringPanel.preview.
        """
        # Progress is now shown in preview overlay, not here
        # If exposure complete, show capturing status
        if remaining_sec <= 0:
            self.set_status('capturing')
    
    def update_status(self, is_capturing: bool, image_count: int, camera_controller=None, live_panel=None):
        """Update all status displays
        
        Args:
            is_capturing: Whether capture is active
            image_count: Number of images captured
            camera_controller: Camera controller instance
            live_panel: Live monitoring panel to update exposure progress
        """
        self.update_image_count(image_count)
        
        # Update camera status
        if is_capturing:
            self.camera_chip.set_status('capturing')
            if camera_controller and hasattr(camera_controller, 'zwo_camera'):
                zwo = camera_controller.zwo_camera
                if zwo and hasattr(zwo, 'exposure_seconds'):
                    # Forward to live panel for preview overlay
                    if live_panel:
                        live_panel.update_exposure_progress(
                            zwo.exposure_seconds,
                            getattr(zwo, 'exposure_remaining', 0)
                        )
        else:
            # Hide progress when not capturing
            if live_panel:
                live_panel.hide_progress()
        
        if camera_controller and hasattr(camera_controller, 'is_connected'):
            if camera_controller.is_connected:
                self.camera_chip.set_status('connected')
                self.camera_chip.set_label('Connected')
            else:
                self.camera_chip.set_status('idle')
                self.camera_chip.set_label('Camera')
    
    def set_web_status(self, enabled: bool, running: bool = False):
        """Update web server status chip"""
        if running:
            self.web_chip.set_status('enabled')
            self.web_chip.set_label('Web On')
        elif enabled:
            self.web_chip.set_status('idle')
            self.web_chip.set_label('Web')
        else:
            self.web_chip.set_status('disabled')
            self.web_chip.set_label('Web')
    
    def set_discord_status(self, enabled: bool):
        """Update Discord status chip"""
        if enabled:
            self.discord_chip.set_status('enabled')
            self.discord_chip.set_label('Discord On')
        else:
            self.discord_chip.set_status('disabled')
            self.discord_chip.set_label('Discord')
    
    def set_status(self, status: str = None):
        """Update status indicator with specific states
        
        Args:
            status: One of 'idle', 'waiting', 'capturing', 'stretching', 'processing', 'sending'
                    or None to hide status
        """
        if status:
            status_text = {
                'idle': 'Idle',
                'waiting': 'Waiting...',
                'capturing': 'Capturing...',
                'stretching': 'Stretching...',
                'processing': 'Processing...',
                'sending': 'Sending...'
            }.get(status.lower(), status.title())
            
            self.processing_label.setText(status_text)
            self.processing_label.show()
            self.countdown_label.hide()
        else:
            self.processing_label.hide()
    
    def set_processing(self, is_processing: bool):
        """Legacy method for backward compatibility"""
        if is_processing:
            self.set_status('processing')
        else:
            self.set_status(None)
