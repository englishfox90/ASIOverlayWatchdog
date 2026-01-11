"""
ASCOM Safety Monitor File Writer

Writes ML predictions to a file format compatible with NINA's GenericFile Safety Monitor.
This allows PFR Sentinel's ML-based roof detection to integrate with observatory automation.

File format example (configurable preamble/triggers):
    Roof Status: OPEN
    Confidence: 95%
    Sky Condition: Clear

NINA GenericFile Setup:
    - File to monitor: path to this file
    - Preamble: "Roof Status:"
    - Safe trigger: "OPEN"
    - Unsafe trigger: "CLOSED"
"""
import os
from datetime import datetime
from typing import Optional, Dict, Any

from services.logger import app_logger


class ASCOMSafetyWriter:
    """
    Writes ML predictions to ASCOM-compatible safety monitor file.
    
    Thread-safe: Uses atomic write (temp file + rename) to prevent
    NINA from reading partial data.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize safety file writer.
        
        Args:
            config: ascom_safety_file config dict with:
                - file_path: Full path to output file
                - preamble: Text before status (default "Roof Status:")
                - open_trigger: Value for open roof (default "OPEN")
                - closed_trigger: Value for closed roof (default "CLOSED")
                - include_confidence: Add confidence line
                - include_sky_condition: Add sky condition line
                - min_confidence: Minimum confidence to write (0.0-1.0)
        """
        self.file_path = config.get('file_path', '')
        self.preamble = config.get('preamble', 'Roof Status:')
        self.open_trigger = config.get('open_trigger', 'OPEN')
        self.closed_trigger = config.get('closed_trigger', 'CLOSED')
        self.include_confidence = config.get('include_confidence', True)
        self.include_sky_condition = config.get('include_sky_condition', True)
        self.min_confidence = config.get('min_confidence', 0.7)
        
        self._last_write_time = None
        self._last_status = None
    
    def is_configured(self) -> bool:
        """Check if file path is configured."""
        return bool(self.file_path)
    
    def write_status(self, ml_results: Dict[str, Any]) -> bool:
        """
        Write ML prediction results to safety file.
        
        Args:
            ml_results: Dict from MLService.analyze_image() with:
                - roof_status: "Open" | "Closed" | "N/A"
                - roof_confidence: 0.0-1.0 or None
                - sky_condition: str or "N/A"
                - sky_confidence: 0.0-1.0 or None
        
        Returns:
            True if file was written successfully
        """
        if not self.is_configured():
            return False
        
        roof_status = ml_results.get('roof_status', 'N/A')
        roof_confidence = ml_results.get('roof_confidence')
        sky_condition = ml_results.get('sky_condition', 'N/A')
        sky_confidence = ml_results.get('sky_confidence')
        
        # Skip if roof status unknown
        if roof_status == 'N/A':
            app_logger.debug("ASCOM Safety: Skipping write - roof status N/A")
            return False
        
        # Skip if confidence below threshold
        if roof_confidence is not None and roof_confidence < self.min_confidence:
            app_logger.debug(f"ASCOM Safety: Skipping write - confidence {roof_confidence:.1%} < {self.min_confidence:.1%}")
            return False
        
        # Build file content
        trigger = self.open_trigger if roof_status == 'Open' else self.closed_trigger
        lines = [f"{self.preamble} {trigger}"]
        
        if self.include_confidence and roof_confidence is not None:
            lines.append(f"Confidence: {roof_confidence:.0%}")
        
        if self.include_sky_condition and sky_condition != 'N/A':
            sky_line = f"Sky Condition: {sky_condition}"
            if sky_confidence is not None:
                sky_line += f" ({sky_confidence:.0%})"
            lines.append(sky_line)
        
        # Add timestamp
        lines.append(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        content = '\n'.join(lines) + '\n'
        
        # Write atomically
        try:
            return self._atomic_write(content)
        except Exception as e:
            app_logger.error(f"ASCOM Safety: Failed to write file: {e}")
            return False
    
    def _atomic_write(self, content: str) -> bool:
        """
        Write content atomically using temp file + rename.
        
        This prevents NINA from reading partial/corrupt data.
        """
        # Ensure directory exists
        dir_path = os.path.dirname(self.file_path)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                app_logger.error(f"ASCOM Safety: Cannot create directory {dir_path}: {e}")
                return False
        
        # Write to temp file first
        temp_path = self.file_path + '.tmp'
        
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Atomic rename
            os.replace(temp_path, self.file_path)
            
            self._last_write_time = datetime.now()
            self._last_status = content.split('\n')[0]  # First line
            
            app_logger.debug(f"ASCOM Safety: Wrote {self._last_status}")
            return True
            
        except Exception as e:
            # Clean up temp file on error
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise
    
    def get_last_status(self) -> Optional[str]:
        """Get last written status line."""
        return self._last_status
    
    def get_last_write_time(self) -> Optional[datetime]:
        """Get timestamp of last successful write."""
        return self._last_write_time


# Module-level convenience function
_writer_instance: Optional[ASCOMSafetyWriter] = None


def write_ascom_safety_file(ml_results: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """
    Convenience function to write ML results to ASCOM safety file.
    
    Args:
        ml_results: ML prediction results dict
        config: ascom_safety_file config dict
    
    Returns:
        True if file was written successfully
    """
    global _writer_instance
    
    if not config.get('enabled', False):
        return False
    
    # Create or update writer instance
    if _writer_instance is None or _writer_instance.file_path != config.get('file_path', ''):
        _writer_instance = ASCOMSafetyWriter(config)
    
    return _writer_instance.write_status(ml_results)
