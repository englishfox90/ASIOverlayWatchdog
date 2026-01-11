"""
Image Analysis for Dev Mode

Functions for analyzing raw image data:
- Bit depth normalization inference
- Luminance computation
- Corner vs center analysis for mode detection
- Per-channel statistics logging
"""
import numpy as np

from services.logger import app_logger


def infer_normalization_denom(raw_array: np.ndarray, image_bit_depth: int, camera_bit_depth: int):
    """
    Infer the correct normalization denominator based on actual data.
    
    Analyzes actual pixel values to detect:
    - 8-bit payload in 16-bit container
    - 12-bit data (max <= 4095)
    - 12-bit left-shifted to 16-bit (many multiples of 16)
    - True 16-bit data
    
    Args:
        raw_array: Raw image data array
        image_bit_depth: Image bit depth from metadata
        camera_bit_depth: Camera ADC bit depth from metadata
        
    Returns:
        tuple: (denom, reason, details_dict)
    """
    # Early exit for 8-bit capture mode
    if image_bit_depth == 8:
        return 255.0, "8-bit capture mode (IMAGE_BIT_DEPTH=8)", {
            'raw_min': int(np.min(raw_array)),
            'raw_max': int(np.max(raw_array)),
            'mul16_rate': 0.0,
            'unique_ratio': 1.0,
            'unique_count': 0,
        }
    
    # For 16-bit container, analyze actual values
    if raw_array.dtype == np.uint8:
        return 255.0, "8-bit array dtype despite IMAGE_BIT_DEPTH=16", {
            'raw_min': int(np.min(raw_array)),
            'raw_max': int(np.max(raw_array)),
            'mul16_rate': 0.0,
            'unique_ratio': 1.0,
            'unique_count': 0,
        }
    
    # Compute statistics on flattened array
    flat = raw_array.flatten().astype(np.uint16)
    
    raw_min = int(np.min(flat))
    raw_max = int(np.max(flat))
    raw_median = int(np.median(flat))
    raw_p99 = int(np.percentile(flat, 99))
    
    # Sample for expensive computations
    sample_size = min(100000, flat.size)
    if flat.size > sample_size:
        sample = flat[np.random.choice(flat.size, sample_size, replace=False)]
    else:
        sample = flat
    
    # Detect left-shifted 12-bit data (values are multiples of 16 = 2^4)
    mul16_rate = float(np.mean(sample % 16 == 0))
    
    # Unique value analysis
    unique_vals = np.unique(sample)
    unique_count = len(unique_vals)
    unique_ratio = unique_count / len(sample)
    
    # Build base details dict
    details = {
        'raw_min': raw_min,
        'raw_max': raw_max,
        'raw_median': raw_median,
        'raw_p99': raw_p99,
        'mul16_rate': round(mul16_rate, 4),
        'unique_count': unique_count,
        'unique_ratio': round(unique_ratio, 6),
        'sample_size': len(sample),
    }
    
    # === Inference rules (in priority order) ===
    
    # Rule 1: 8-bit payload in 16-bit container
    if raw_max <= 255:
        details['suggested_downshift_bits'] = 0
        return 255.0, f"8-bit payload detected (max={raw_max})", details
    
    # Rule 2: 12-bit range (max <= 4095)
    if raw_max <= 4095:
        details['suggested_downshift_bits'] = 0
        return 4095.0, f"12-bit range detected (max={raw_max})", details
    
    # Rule 3: Left-shifted 12-bit data
    if mul16_rate >= 0.90:
        details['suggested_downshift_bits'] = 4
        return 65535.0, f"12-bit left-shifted (mul16_rate={mul16_rate:.2f})", details
    
    # Rule 4: Default to 16-bit
    details['suggested_downshift_bits'] = 0
    return 65535.0, f"16-bit range detected (max={raw_max})", details


def compute_luminance(norm_array: np.ndarray) -> np.ndarray:
    """
    Compute luminance from normalized RGB array using Rec.601 coefficients.
    
    Args:
        norm_array: Normalized image array (0-1 range), shape (H,W) or (H,W,3)
        
    Returns:
        2D luminance array
    """
    if norm_array.ndim == 2:
        return norm_array
    elif norm_array.ndim == 3 and norm_array.shape[2] == 3:
        return 0.299 * norm_array[:,:,0] + 0.587 * norm_array[:,:,1] + 0.114 * norm_array[:,:,2]
    else:
        app_logger.warning(f"DEV MODE: Unexpected array shape {norm_array.shape}")
        return norm_array.mean(axis=-1) if norm_array.ndim > 2 else norm_array


def compute_corner_analysis(lum: np.ndarray, norm_array: np.ndarray = None, 
                           roi_size: int = 50, margin: int = 5) -> dict:
    """
    Compute corner-vs-center analysis for mode classification.
    
    This analysis helps detect:
    - Roof open vs closed (corners ~= center when closed)
    - Day vs night (absolute brightness levels)
    - Overscan bias levels (corner medians)
    
    Args:
        lum: Luminance array (H, W)
        norm_array: Optional normalized RGB array for per-channel bias
        roi_size: Size of corner ROI squares (default 50)
        margin: Pixels from edge to start ROI (default 5)
        
    Returns:
        dict with corner analysis metrics
    """
    h, w = lum.shape
    
    # Define corner ROIs (50x50, 5px margin from edge)
    corners = {
        'tl': lum[margin:margin+roi_size, margin:margin+roi_size],
        'tr': lum[margin:margin+roi_size, w-margin-roi_size:w-margin],
        'bl': lum[h-margin-roi_size:h-margin, margin:margin+roi_size],
        'br': lum[h-margin-roi_size:h-margin, w-margin-roi_size:w-margin],
    }
    
    all_corners = np.concatenate([c.flatten() for c in corners.values()])
    
    # Define center ROI (central 25% of image)
    ch, cw = h // 4, w // 4
    center = lum[ch:3*ch, cw:3*cw]
    
    # Compute corner stats
    corner_med = float(np.median(all_corners))
    corner_p90 = float(np.percentile(all_corners, 90))
    corner_mad = float(np.median(np.abs(all_corners - corner_med)))
    corner_stddev = float(corner_mad * 1.4826)
    
    corner_meds = {k: float(np.median(c)) for k, c in corners.items()}
    
    # Compute center stats
    center_flat = center.flatten()
    center_med = float(np.median(center_flat))
    center_p90 = float(np.percentile(center_flat, 90))
    
    # Ratios for mode classification
    corner_to_center_ratio = corner_med / center_med if center_med > 0.001 else 1.0
    center_minus_corner = center_med - corner_med
    
    result = {
        'roi_size': roi_size,
        'margin': margin,
        'corner_med': round(corner_med, 6),
        'corner_p90': round(corner_p90, 6),
        'corner_stddev': round(corner_stddev, 6),
        'corner_meds': {k: round(v, 6) for k, v in corner_meds.items()},
        'center_med': round(center_med, 6),
        'center_p90': round(center_p90, 6),
        'corner_to_center_ratio': round(corner_to_center_ratio, 4),
        'center_minus_corner': round(center_minus_corner, 6),
    }
    
    # Per-channel RGB corner bias (if RGB array provided)
    if norm_array is not None and norm_array.ndim == 3 and norm_array.shape[2] == 3:
        rgb_bias = {}
        for c, name in enumerate(['bias_r', 'bias_g', 'bias_b']):
            channel = norm_array[:,:,c]
            ch_corners = np.concatenate([
                channel[margin:margin+roi_size, margin:margin+roi_size].flatten(),
                channel[margin:margin+roi_size, w-margin-roi_size:w-margin].flatten(),
                channel[h-margin-roi_size:h-margin, margin:margin+roi_size].flatten(),
                channel[h-margin-roi_size:h-margin, w-margin-roi_size:w-margin].flatten(),
            ])
            rgb_bias[name] = round(float(np.median(ch_corners)), 6)
        result['rgb_corner_bias'] = rgb_bias
    
    return result


def log_channel_statistics(norm_array: np.ndarray, raw_array: np.ndarray):
    """
    Log detailed per-channel statistics for debugging.
    
    Args:
        norm_array: Normalized image array (0-1 range)
        raw_array: Original raw array (for raw value range)
    """
    channel_names = ['R', 'G', 'B'] if norm_array.ndim == 3 and norm_array.shape[2] == 3 else ['Y']
    
    for c, channel_name in enumerate(channel_names):
        if norm_array.ndim == 3:
            channel = norm_array[:, :, c]
            raw_channel = raw_array[:, :, c]
        else:
            channel = norm_array
            raw_channel = raw_array
        
        median = np.median(channel)
        mean = np.mean(channel)
        std = np.std(channel)
        min_val = np.min(channel)
        max_val = np.max(channel)
        p1 = np.percentile(channel, 1)
        p99 = np.percentile(channel, 99)
        mad = np.median(np.abs(channel - median))
        
        raw_min = int(np.min(raw_channel))
        raw_max = int(np.max(raw_channel))
        
        app_logger.info(
            f"DEV MODE {channel_name}: median={median:.4f}, mean={mean:.4f}, "
            f"std={std:.4f}, MAD={mad:.4f}, min={min_val:.4f}, max={max_val:.4f}, "
            f"p1={p1:.4f}, p99={p99:.4f}, raw_range=[{raw_min}-{raw_max}]"
        )
        
        if norm_array.ndim == 2:
            break
    
    # Log luminance stats for RGB
    if norm_array.ndim == 3 and norm_array.shape[2] == 3:
        lum = compute_luminance(norm_array)
        app_logger.info(
            f"DEV MODE Luminance: median={np.median(lum):.4f}, mean={np.mean(lum):.4f}, "
            f"MAD={np.median(np.abs(lum - np.median(lum))):.4f}"
        )
        
        r_mean = np.mean(norm_array[:,:,0])
        g_mean = np.mean(norm_array[:,:,1])
        b_mean = np.mean(norm_array[:,:,2])
        app_logger.info(
            f"DEV MODE Color Balance: R/G={r_mean/g_mean:.3f}, B/G={b_mean/g_mean:.3f} "
            f"(1.0 = neutral)"
        )
