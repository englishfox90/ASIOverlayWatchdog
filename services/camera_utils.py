"""
Utility functions for ZWO ASI camera operations
"""
import numpy as np
from datetime import datetime


def simple_debayer_rggb(raw_data, width, height):
    """
    Simple Bayer RGGB to RGB conversion using nearest neighbor interpolation
    This is a fallback for when OpenCV is not available
    
    Args:
        raw_data: Raw Bayer pattern data (numpy array)
        width: Image width
        height: Image height
        
    Returns:
        RGB image as numpy array (height, width, 3)
    """
    # Reshape to 2D array
    bayer = raw_data.reshape((height, width))
    
    # Create RGB image
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    
    # RGGB pattern (Red at even rows/even cols, Blue at odd rows/odd cols)
    # R at (0,0), G at (0,1) and (1,0), B at (1,1)
    
    # Red channel - copy from even rows, even columns
    rgb[::2, ::2, 0] = bayer[::2, ::2]  # R positions
    # Interpolate for other positions (simple nearest neighbor)
    rgb[1::2, ::2, 0] = bayer[::2, ::2]  # Copy down
    rgb[::2, 1::2, 0] = bayer[::2, ::2]  # Copy right
    rgb[1::2, 1::2, 0] = bayer[::2, ::2]  # Copy diagonal
    
    # Green channel - average of two green positions
    rgb[::2, 1::2, 1] = bayer[::2, 1::2]  # G at R row
    rgb[1::2, ::2, 1] = bayer[1::2, ::2]  # G at B row
    rgb[::2, ::2, 1] = (bayer[::2, 1::2].astype(np.uint16) + bayer[1::2, ::2].astype(np.uint16)) // 2  # Interpolate
    rgb[1::2, 1::2, 1] = (bayer[::2, 1::2].astype(np.uint16) + bayer[1::2, ::2].astype(np.uint16)) // 2  # Interpolate
    
    # Blue channel - copy from odd rows, odd columns
    rgb[1::2, 1::2, 2] = bayer[1::2, 1::2]  # B positions
    # Interpolate for other positions
    rgb[::2, 1::2, 2] = bayer[1::2, 1::2]  # Copy up
    rgb[1::2, ::2, 2] = bayer[1::2, 1::2]  # Copy left
    rgb[::2, ::2, 2] = bayer[1::2, 1::2]  # Copy diagonal
    
    return rgb


def is_within_scheduled_window(scheduled_capture_enabled, scheduled_start_time, scheduled_end_time):
    """
    Check if current time is within the scheduled capture window.
    Handles overnight captures (e.g., 17:00 - 09:00).
    Returns True if scheduled capture is disabled or if within window.
    
    Args:
        scheduled_capture_enabled: Whether scheduling is enabled
        scheduled_start_time: Start time string "HH:MM"
        scheduled_end_time: End time string "HH:MM"
        
    Returns:
        True if within window or scheduling disabled, False otherwise
    """
    if not scheduled_capture_enabled:
        return True  # Always capture if scheduling is disabled
    
    try:
        now = datetime.now()
        current_time = now.time()
        
        # Parse start and end times
        start_hour, start_min = map(int, scheduled_start_time.split(':'))
        end_hour, end_min = map(int, scheduled_end_time.split(':'))
        
        start_time = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0).time()
        end_time = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0).time()
        
        # Check if this is an overnight window (e.g., 17:00 - 09:00)
        if start_time > end_time:
            # Overnight: capture if after start OR before end (exclusive)
            return current_time >= start_time or current_time < end_time
        else:
            # Same day: capture if between start and end (end exclusive)
            return start_time <= current_time < end_time
            
    except Exception as e:
        print(f"Error checking scheduled window: {e}")
        return True  # Default to allowing capture on error


def calculate_brightness(img_array, algorithm='percentile', percentile=75):
    """
    Calculate image brightness using specified algorithm
    
    Args:
        img_array: Image as numpy array
        algorithm: 'mean', 'median', or 'percentile'
        percentile: Percentile value for percentile algorithm (0-100)
        
    Returns:
        Brightness value (0-255)
    """
    if algorithm == 'mean':
        return np.mean(img_array)
    elif algorithm == 'median':
        return np.median(img_array)
    elif algorithm == 'percentile':
        return np.percentile(img_array, percentile)
    else:
        return np.mean(img_array)  # Default to mean


def check_clipping(img_array, clipping_threshold=245):
    """
    Check if image has clipped (overexposed) pixels
    
    Args:
        img_array: Image as numpy array
        clipping_threshold: Pixel value threshold (0-255)
        
    Returns:
        Tuple of (clipped_percent, is_clipping)
            clipped_percent: Percentage of pixels above threshold
            is_clipping: True if more than 5% of pixels are clipped
    """
    clipped_pixels = np.sum(img_array > clipping_threshold)
    total_pixels = img_array.size
    clipped_percent = (clipped_pixels / total_pixels) * 100
    is_clipping = clipped_percent > 5.0  # Consider clipping if more than 5% of pixels are clipped
    
    return clipped_percent, is_clipping


def debayer_raw_image(raw_data, width, height, bayer_pattern='BGGR', bit_depth=8, return_raw16=False):
    """
    Convert raw Bayer data to RGB using OpenCV (or fallback).
    
    Args:
        raw_data: Raw byte data from camera
        width: Image width
        height: Image height
        bayer_pattern: Bayer pattern string (RGGB, BGGR, GRBG, GBRG)
        bit_depth: Bit depth of raw data (8 for RAW8, 16 for RAW16)
        return_raw16: If True and bit_depth=16, include the full uint16 RGB in tuple
        
    Returns:
        tuple: (img_rgb_uint8, img_rgb_raw16_or_None)
            - img_rgb_uint8: Always uint8 RGB array for display/processing pipeline
            - img_rgb_raw16_or_None: uint16 RGB if bit_depth=16 AND return_raw16=True, else None
    """
    # Choose dtype based on bit depth
    if bit_depth == 16:
        img_array = np.frombuffer(raw_data, dtype=np.uint16).reshape((height, width))
    else:
        img_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width))
    
    try:
        import cv2
        bayer_map = {
            'RGGB': cv2.COLOR_BayerRG2RGB,
            'BGGR': cv2.COLOR_BayerBG2RGB,
            'GRBG': cv2.COLOR_BayerGR2RGB,
            'GBRG': cv2.COLOR_BayerGB2RGB
        }
        bayer_code = bayer_map.get(bayer_pattern, cv2.COLOR_BayerBG2RGB)
        img_rgb = cv2.cvtColor(img_array, bayer_code)
        
        # For 16-bit data, create both versions
        if bit_depth == 16:
            img_rgb_raw16 = img_rgb.copy() if return_raw16 else None
            # Scale 16-bit to 8-bit for standard processing pipeline (0-65535 -> 0-255)
            img_rgb = (img_rgb / 257).astype(np.uint8)
        else:
            img_rgb_raw16 = None
        
        # Always return tuple for consistent unpacking (img_rgb, img_rgb_raw16_or_None)
        return img_rgb, img_rgb_raw16
    except ImportError:
        result = simple_debayer_rggb(img_array, width, height)
        # Always return tuple for consistent unpacking
        return result, None


def apply_white_balance(img_rgb, wb_config):
    """
    Apply software white balance adjustments to RGB image.
    
    Args:
        img_rgb: RGB numpy array
        wb_config: Dict with white balance settings
        
    Returns:
        Adjusted RGB numpy array
    """
    if not wb_config:
        return img_rgb
    
    wb_mode = wb_config.get('mode', 'asi_auto')
    
    try:
        import cv2
        
        if wb_mode == 'gray_world':
            from services.color_balance import apply_gray_world_robust
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            img_bgr = apply_gray_world_robust(
                img_bgr,
                low_pct=wb_config.get('gray_world_low_pct', 5),
                high_pct=wb_config.get('gray_world_high_pct', 95)
            )
            return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        
        elif wb_mode == 'manual' and wb_config.get('apply_software_gains', False):
            from services.color_balance import apply_manual_gains
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            img_bgr = apply_manual_gains(
                img_bgr,
                red_gain=wb_config.get('manual_red_gain', 1.0),
                blue_gain=wb_config.get('manual_blue_gain', 1.0)
            )
            return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    except ImportError:
        pass
    
    return img_rgb


def calculate_image_stats(img_array):
    """
    Calculate image statistics for metadata.
    
    Args:
        img_array: Image as numpy array
        
    Returns:
        Dict with brightness, min, max, std_dev, percentiles
    """
    return {
        'mean': np.mean(img_array),
        'median': np.median(img_array),
        'min': int(np.min(img_array)),
        'max': int(np.max(img_array)),
        'std_dev': np.std(img_array),
        'p25': np.percentile(img_array, 25),
        'p75': np.percentile(img_array, 75),
        'p95': np.percentile(img_array, 95),
    }
