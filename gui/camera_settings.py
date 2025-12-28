"""
Camera settings dataclass module
MAINT-002: Centralized camera settings to eliminate duplicate code
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class CameraSettings:
    """
    Camera configuration settings.
    
    Provides a single source of truth for camera parameters,
    eliminating duplicate settings parsing code across modules.
    """
    exposure_ms: float
    gain: int
    wb_r: int
    wb_b: int
    offset: int
    flip: int
    interval: float
    auto_exposure: bool
    max_exposure_sec: float
    target_brightness: int
    bayer_pattern: str
    wb_config: Dict[str, Any]
    scheduled_capture_enabled: bool
    scheduled_start_time: str
    scheduled_end_time: str
    saved_camera_name: Optional[str]
    
    @classmethod
    def from_app(cls, app) -> 'CameraSettings':
        """
        Build settings from app tkinter variables.
        
        Args:
            app: ModernOverlayApp instance with *_var attributes
            
        Returns:
            CameraSettings instance with current GUI values
        """
        # Handle exposure unit conversion
        exposure_value = app.exposure_var.get()
        if app.exposure_unit_var.get() == 's':
            exposure_ms = exposure_value * 1000.0
        else:
            exposure_ms = exposure_value
        
        # Map flip string to SDK integer
        flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
        
        # Load white balance config with defaults
        wb_config = app.config.get('white_balance', {
            'mode': 'asi_auto',
            'manual_red_gain': 1.0,
            'manual_blue_gain': 1.0,
            'gray_world_low_pct': 5,
            'gray_world_high_pct': 95
        })
        
        return cls(
            exposure_ms=exposure_ms,
            gain=app.gain_var.get(),
            wb_r=app.wb_r_var.get(),
            wb_b=app.wb_b_var.get(),
            offset=app.offset_var.get(),
            flip=flip_map.get(app.flip_var.get(), 0),
            interval=app.interval_var.get(),
            auto_exposure=app.auto_exposure_var.get(),
            max_exposure_sec=app.max_exposure_var.get(),
            target_brightness=app.target_brightness_var.get(),
            bayer_pattern=app.bayer_pattern_var.get(),
            wb_config=wb_config,
            scheduled_capture_enabled=app.config.get('scheduled_capture_enabled', False),
            scheduled_start_time=app.config.get('scheduled_start_time', '17:00'),
            scheduled_end_time=app.config.get('scheduled_end_time', '09:00'),
            saved_camera_name=app.config.get('zwo_selected_camera_name', None),
        )
    
    @property
    def exposure_sec(self) -> float:
        """Get exposure in seconds (for SDK)"""
        return self.exposure_ms / 1000.0
    
    def log_summary(self, logger) -> None:
        """Log a summary of current settings"""
        logger.info(f"Camera settings: Exposure={self.exposure_ms}ms, Gain={self.gain}, WB(R={self.wb_r}, B={self.wb_b})")
        logger.info(f"  Auto-exposure: {self.auto_exposure}, Max={self.max_exposure_sec}s, Target brightness={self.target_brightness}")
        logger.info(f"  Bayer pattern: {self.bayer_pattern}, Flip: {self.flip}, Offset: {self.offset}")
        logger.info(f"  Capture interval: {self.interval}s")
        logger.info(f"White balance mode: {self.wb_config.get('mode', 'asi_auto')}")
        
        if self.scheduled_capture_enabled:
            logger.info(f"Scheduled capture enabled: {self.scheduled_start_time} - {self.scheduled_end_time}")
        else:
            logger.info("Scheduled capture disabled: continuous operation")
