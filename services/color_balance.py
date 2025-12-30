"""
Color balance / white balance algorithms
"""
import cv2
import numpy as np


def apply_gray_world_robust(img_bgr: np.ndarray,
                            low_pct: float = 5,
                            high_pct: float = 95) -> np.ndarray:
    """
    Robust Gray World white balance.
    - Ignores extremes based on intensity percentiles.
    - Uses masked means for each channel.
    
    Args:
        img_bgr: Input BGR image (uint8)
        low_pct: Lower percentile for intensity masking (0-20)
        high_pct: Upper percentile for intensity masking (80-100)
    
    Returns:
        White-balanced BGR image (uint8)
    """
    img = img_bgr.astype(np.float32)
    b, g, r = cv2.split(img)

    # Compute intensity to find reasonable mid-tone pixels
    intensity = 0.299 * r + 0.587 * g + 0.114 * b

    low = np.percentile(intensity, low_pct)
    high = np.percentile(intensity, high_pct)

    mask = (intensity >= low) & (intensity <= high)

    # Fallback in case mask is too small
    if np.count_nonzero(mask) < 100:
        mask = np.ones_like(intensity, dtype=bool)

    avg_r = np.mean(r[mask])
    avg_g = np.mean(g[mask])
    avg_b = np.mean(b[mask])

    target = (avg_r + avg_g + avg_b) / 3.0

    gain_r = target / (avg_r + 1e-6)
    gain_g = target / (avg_g + 1e-6)
    gain_b = target / (avg_b + 1e-6)

    r *= gain_r
    g *= gain_g
    b *= gain_b
    
    # Add triangular dither to reduce banding from gain scaling
    # This is especially important when gains differ significantly
    max_gain = max(gain_r, gain_g, gain_b)
    if max_gain > 1.05:  # Only dither if significant gain applied
        dither_r = np.random.uniform(-0.5, 0.5, r.shape) + np.random.uniform(-0.5, 0.5, r.shape)
        dither_g = np.random.uniform(-0.5, 0.5, g.shape) + np.random.uniform(-0.5, 0.5, g.shape)
        dither_b = np.random.uniform(-0.5, 0.5, b.shape) + np.random.uniform(-0.5, 0.5, b.shape)
        r += dither_r
        g += dither_g
        b += dither_b

    balanced = cv2.merge([b, g, r])
    return np.clip(balanced, 0, 255).astype(np.uint8)


def apply_manual_gains(img_bgr: np.ndarray,
                       red_gain: float,
                       blue_gain: float) -> np.ndarray:
    """
    Apply manual red/blue gains for white balance with dithering to reduce banding.
    
    Args:
        img_bgr: Input BGR image (uint8)
        red_gain: Multiplier for red channel (0.1-4.0)
        blue_gain: Multiplier for blue channel (0.1-4.0)
    
    Returns:
        White-balanced BGR image (uint8)
    """
    img = img_bgr.astype(np.float32)
    b, g, r = cv2.split(img)
    
    # Apply gains
    r *= red_gain
    b *= blue_gain
    
    # Add small triangular dither noise before rounding to reduce banding
    # This is especially important when gains > 1.0 cause quantization
    if red_gain > 1.0 or blue_gain > 1.0:
        # Triangular PDF dither: sum of two uniform distributions
        dither_r = np.random.uniform(-0.5, 0.5, r.shape) + np.random.uniform(-0.5, 0.5, r.shape)
        dither_b = np.random.uniform(-0.5, 0.5, b.shape) + np.random.uniform(-0.5, 0.5, b.shape)
        r += dither_r
        b += dither_b
    
    balanced = cv2.merge([b, g, r])
    return np.clip(balanced, 0, 255).astype(np.uint8)
