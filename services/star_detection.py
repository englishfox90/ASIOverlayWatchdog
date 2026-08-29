"""
Star detection and seeing estimation for astrophotography images.

Uses OpenCV blob detection to count point sources (stars) and estimate
FWHM-based seeing quality from detected star profiles.
"""
import cv2
import numpy as np
from .logger import app_logger


# Seeing quality labels based on FWHM in pixels
_SEEING_LABELS = [
    (2.5, "Excellent"),
    (4.0, "Good"),
    (6.0, "Fair"),
    (8.0, "Poor"),
    (float('inf'), "Bad"),
]


def detect_stars(image, min_area=4, max_area=500, threshold=30):
    """Detect star-like point sources in an image using blob detection.

    Args:
        image: numpy array (RGB or grayscale)
        min_area: Minimum blob area in pixels
        max_area: Maximum blob area in pixels
        threshold: Minimum brightness above background for detection

    Returns:
        List of dicts with keys 'x', 'y', 'size' for each detected star.
    """
    if image is None or image.size == 0:
        return []

    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image.copy()

    # medianBlur with ksize > 5 requires 8-bit input
    if gray.dtype != np.uint8:
        if gray.dtype == np.uint16:
            gray = (gray >> 8).astype(np.uint8)
        else:
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Noise reduction
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # Background estimation via large median filter
    bg = cv2.medianBlur(gray, 31)

    # Subtract background to isolate point sources
    diff = cv2.subtract(blurred, bg)

    # Threshold to find bright spots
    _, binary = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

    # Find contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    stars = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if min_area <= area <= max_area:
            M = cv2.moments(contour)
            if M['m00'] > 0:
                cx = int(M['m10'] / M['m00'])
                cy = int(M['m01'] / M['m00'])
                size = np.sqrt(area / np.pi) * 2  # diameter
                stars.append({'x': cx, 'y': cy, 'size': size})

    return stars


def estimate_fwhm(image, stars, radius=8):
    """Estimate average FWHM from detected stars using Gaussian profile fitting.

    Args:
        image: numpy array (RGB or grayscale)
        stars: List of star dicts from detect_stars()
        radius: Pixel radius around each star to measure

    Returns:
        Average FWHM in pixels, or 0.0 if no valid measurements.
    """
    if not stars or image is None or image.size == 0:
        return 0.0

    # float32, not float64: FWHM is a half-max crossing measured on a small
    # cutout, so ~7 significant digits is already far more precision than the
    # measurement carries, and it halves a full-frame temp (50 MB vs 101 MB on
    # a 3552x3552 frame).
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    else:
        gray = image.astype(np.float32)

    h, w = gray.shape
    fwhm_values = []

    for star in stars:
        x, y = star['x'], star['y']

        # Skip stars too close to edge
        if x < radius or y < radius or x >= w - radius or y >= h - radius:
            continue

        # Extract cutout
        cutout = gray[y - radius:y + radius + 1, x - radius:x + radius + 1]

        # Measure FWHM from radial profile
        peak = cutout[radius, radius]
        bg = np.median(cutout[[0, -1], :])  # edges as background
        half_max = bg + (peak - bg) / 2

        if peak <= bg:
            continue

        # Count pixels above half-max in radial directions
        row = cutout[radius, :]
        above = np.where(row >= half_max)[0]
        if len(above) >= 2:
            fwhm = above[-1] - above[0]
            if 1.0 <= fwhm <= radius * 2:
                fwhm_values.append(float(fwhm))

    if not fwhm_values:
        return 0.0

    return float(np.median(fwhm_values))


def seeing_label(fwhm):
    """Convert FWHM value to a human-readable seeing quality label.

    Args:
        fwhm: FWHM in pixels

    Returns:
        String label: "Excellent", "Good", "Fair", "Poor", or "Bad"
    """
    if fwhm <= 0:
        return "N/A"
    for limit, label in _SEEING_LABELS:
        if fwhm <= limit:
            return label
    return "N/A"


def should_run_star_detection(config, metadata):
    from .observing_window import is_observing_window
    return is_observing_window(config, metadata, feature="Star detection")


def analyze_stars(image):
    """Run full star analysis: detection + FWHM + seeing label.

    Args:
        image: numpy array (RGB or grayscale)

    Returns:
        dict with keys 'STAR_COUNT' (int), 'FWHM' (float), 'SEEING' (str)
    """
    try:
        stars = detect_stars(image)
        star_count = len(stars)
        fwhm = estimate_fwhm(image, stars) if stars else 0.0
        seeing = seeing_label(fwhm)

        return {
            'STAR_COUNT': str(star_count),
            'FWHM': f"{fwhm:.1f}" if fwhm > 0 else "N/A",
            'SEEING': seeing,
        }
    except Exception as e:
        app_logger.debug(f"Star detection failed: {e}")
        return {
            'STAR_COUNT': '0',
            'FWHM': 'N/A',
            'SEEING': 'N/A',
        }
