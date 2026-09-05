"""
Sub-pixel star centroid detection for all-sky camera calibration.

Uses OpenCV blob detection followed by weighted-moment refinement
to achieve ~0.3px centroid accuracy on moderately bright stars.

Sky circle auto-detection
-------------------------
All-sky fisheye images have a circular sky region surrounded by black
corners. ``estimate_sky_circle()`` detects that circle automatically
so detections are restricted to the actual sky, avoiding equipment,
buildings and corner noise.  ``detect_stars()`` calls it automatically
when no sky circle is supplied.
"""
import numpy as np
from typing import List, Tuple, Optional

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def estimate_sky_circle(
    image,
    trim_fraction: float = 0.15,
) -> Tuple[float, float, float]:
    """
    Automatically estimate the sky circle in an all-sky fisheye image.

    The fisheye lens produces a circular sky region surrounded by
    black/dark corners.  This function finds that circle by:
      1. Heavy Gaussian blur — suppresses stars, planets, equipment
      2. Adaptive threshold using corner floor vs mid-ring sky brightness
      3. Radial scan from outside→in to find the boundary edge points
      4. Outlier filtering (removes mount shadows and bright-building outliers)
      5. Algebraic circle fit to recover the true (possibly off-centre) optical centre
      6. Inward trim by trim_fraction to exclude horizon buildings/equipment

    Args:
        image: PIL Image, numpy uint8 array (H×W or H×W×3), or file path.
        trim_fraction: Fraction of the fitted radius to trim inward (default 0.15 = 15%).
                       Increase to exclude more horizon buildings/equipment.
                       Range: 0.0 (use raw fit) to 0.40 (very aggressive crop).

    Returns:
        (cx, cy, radius) in pixels.
        Falls back to (w/2, h/2, min(w,h)*0.45) on failure.
    """
    if not _CV2_AVAILABLE:
        raise RuntimeError("opencv-python is required for sky circle detection")

    gray = _to_gray(image)
    if gray is None:
        return 960.0, 540.0, 480.0

    h, w = gray.shape
    half = min(h, w) / 2.0

    # ---------------------------------------------------------------
    # Strategy: radial edge scan + algebraic circle fit
    #
    # Shoot 72 rays outward from the image centre; find where the blurred
    # signal drops below 12% of the mid-ring sky brightness.  Collect those
    # edge points, filter outliers (bright buildings push some edges out),
    # then fit a circle with algebraic least-squares to recover the TRUE
    # optical centre — which is often physically off-centre in the frame.
    #
    # KEY: sample sky brightness from the 20–40% radial band, NOT from the
    # image centre.  The centre is often blocked by a telescope mount/pier
    # which gives near-zero brightness → thresh collapses to the 6.0 floor
    # → buildings at the edge are never detected as outside-sky → all 72
    # edges land at max_r → circle fit returns the image centre.
    # Sampling from the mid-ring where open sky is reliably visible gives a
    # realistic reference brightness so the threshold actually fires.
    # ---------------------------------------------------------------
    k = max(51, (min(h, w) // 20)) | 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0).astype(np.float32)

    img_cx = w / 2.0
    img_cy = h / 2.0
    n_angles = 72
    max_r = int(min(img_cx, img_cy, w - img_cx, h - img_cy) * 0.99)
    step = 2

    edge_pts: List[Tuple[float, float]] = []
    raw_radii: List[float] = []

    # Compute two reference levels that bracket the fisheye boundary:
    #
    # corner_ref: typical brightness of genuinely dark outside-sky pixels.
    #   p10 of the full blurred image captures the dark corners/margins, even
    #   if ~30% of pixels are inside the bright sky circle.
    #
    # sky_ref: typical brightness well inside the fisheye circle.
    #   Sampled from the 20–40% radial band (above the telescope-mount shadow)
    #   over all angles combined so shadow angles don't dominate.
    #
    # thresh_global: sits at 50% above the corner floor (corner_ref × 1.5) OR
    #   45% of the way from corner to sky — whichever is lower — ensuring it
    #   clears the JPEG noise floor / ambient corner glow while still being
    #   below the dimmest in-sky regions near the horizon.
    flat_blurred = blurred.flatten()
    corner_ref = float(np.percentile(flat_blurred, 10))
    corner_ref = max(corner_ref, 5.0)

    mid_vals: List[float] = []
    for angle in np.linspace(0, 2 * np.pi, n_angles, endpoint=False):
        rs  = np.arange(0, max_r, step)
        xs  = np.clip((img_cx + rs * np.cos(angle)).astype(int), 0, w - 1)
        ys  = np.clip((img_cy + rs * np.sin(angle)).astype(int), 0, h - 1)
        vals = blurred[ys, xs]
        lo = int(len(vals) * 0.20)
        hi = int(len(vals) * 0.40)
        if hi > lo:
            mid_vals.extend(vals[lo:hi].tolist())

    sky_ref = float(np.median(mid_vals)) if mid_vals else corner_ref * 2.5
    sky_ref = max(sky_ref, corner_ref * 1.5, 15.0)

    thresh_global = min(
        corner_ref * 1.5,                                    # 50% above corner floor
        corner_ref + (sky_ref - corner_ref) * 0.45,         # 45% into sky-corner gap
    )
    thresh_global = max(thresh_global, corner_ref + 5.0)

    for angle in np.linspace(0, 2 * np.pi, n_angles, endpoint=False):
        rs  = np.arange(0, max_r, step)
        xs  = np.clip((img_cx + rs * np.cos(angle)).astype(int), 0, w - 1)
        ys  = np.clip((img_cy + rs * np.sin(angle)).astype(int), 0, h - 1)
        vals = blurred[ys, xs]

        for j in range(len(vals) - 1, 0, -1):
            if vals[j] >= thresh_global:
                raw_radii.append(float(rs[j]))
                ex = img_cx + rs[j] * np.cos(angle)
                ey = img_cy + rs[j] * np.sin(angle)
                edge_pts.append((float(ex), float(ey)))
                break

    if len(edge_pts) < n_angles // 3:
        return img_cx, img_cy, half * 0.88

    # Filter outliers in BOTH directions:
    #   High outliers: bright buildings just outside the fisheye push the edge
    #     outward → cut anything > 1.15× median.
    #   Low outliers: telescope mount / pier blocks some rays well inside the
    #     sky circle, making the scan return the last bright point of the pier
    #     body rather than the fisheye boundary → cut anything < 0.50× median.
    median_r = float(np.median(raw_radii))
    clean_pts = [pt for pt, r in zip(edge_pts, raw_radii)
                 if median_r * 0.50 <= r <= median_r * 1.15]
    if len(clean_pts) < n_angles // 4:
        clean_pts = edge_pts

    # Algebraic least-squares circle fit — recovers the true off-centre
    # optical centre instead of assuming it equals the image centre.
    cx_fit, cy_fit, r_fit = _fit_circle(clean_pts)

    # Sanity: fitted centre within 30% of half-frame; radius plausible.
    # Relaxed to 30% (was 25%) to allow for genuinely off-centre lenses.
    if (abs(cx_fit - img_cx) > half * 0.30 or
            abs(cy_fit - img_cy) > half * 0.30 or
            r_fit < half * 0.3 or r_fit > half * 1.05):
        cx_fit, cy_fit = img_cx, img_cy
        r_fit = median_r

    # Trim inward by trim_fraction — excludes buildings/equipment at the horizon.
    trim_fraction = float(np.clip(trim_fraction, 0.0, 0.40))
    radius = r_fit * (1.0 - trim_fraction)
    radius = min(radius, half * 0.92)

    return cx_fit, cy_fit, radius


def detect_stars(
    image,
    max_stars: int = 200,
    min_area: int = 4,
    max_area: int = 500,
    threshold_sigma: float = 4.0,
    border_px: int = 20,
    sky_cx: Optional[float] = None,
    sky_cy: Optional[float] = None,
    sky_radius: Optional[float] = None,
    sky_trim_fraction: float = 0.15,
) -> List[Tuple[float, float, float]]:
    """
    Detect star centroids in an all-sky camera image.

    Args:
        image: PIL Image, numpy uint8 array (H×W or H×W×3), or file path str.
        max_stars: Maximum number of stars to return (brightest first).
        min_area: Minimum blob area in pixels (reference: 750 px image).
        max_area: Maximum blob area in pixels (reference: 750 px image).
                  Both are auto-scaled by (sky_radius/375)² so they remain
                  correct for any image resolution.
        threshold_sigma: Detection threshold as multiples of background sigma.
        border_px: Ignore sources within this many pixels of the sky circle edge.
        sky_cx: Sky circle centre x.  Auto-detected if None.
        sky_cy: Sky circle centre y.  Auto-detected if None.
        sky_radius: Sky circle radius.  Auto-detected if None.
        sky_trim_fraction: Inward trim applied when auto-detecting the sky circle
                           (ignored if sky_radius is supplied).  0.15 = 15% inward.

    Returns:
        List of (x, y, flux) tuples sorted by decreasing flux.
        (x, y) are sub-pixel pixel coordinates.
    """
    if not _CV2_AVAILABLE:
        raise RuntimeError("opencv-python is required for star detection")

    gray = _to_gray(image)
    if gray is None:
        return []

    h, w = gray.shape

    # --- Auto-detect sky circle if not supplied ---
    if sky_cx is None or sky_cy is None or sky_radius is None:
        sky_cx, sky_cy, sky_radius = estimate_sky_circle(gray, trim_fraction=sky_trim_fraction)

    # Build circular sky mask
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (int(round(sky_cx)), int(round(sky_cy))),
               int(round(sky_radius)), 255, -1)

    # --- Scale area thresholds by sky_radius / reference_radius ---
    # Stars are optical point sources; their pixel size is driven by PSF/JPEG,
    # not image scale.  Scale linearly (not quadratically) to stay permissive
    # at large image sizes while still rejecting extended sources.
    # Reference radius is 375 px (half of a 750 px image).
    linear_scale = max(1.0, sky_radius / 375.0)
    min_area_eff = max(4, int(min_area * linear_scale))
    max_area_eff = max(min_area_eff + 1, int(max_area * linear_scale * 2))

    # --- Local background subtraction ---
    # A large Gaussian captures the slowly-varying sky glow (light pollution,
    # moon haze) without following individual stars.  Subtracting it leaves
    # stars as sharp positive residuals regardless of sky brightness level.
    # This prevents the global-median approach from raising the threshold to
    # 227 on bright hazy nights (median=85, sigma=35 → threshold=227).
    bkg_k = max(31, int(sky_radius // 6)) | 1
    background = cv2.GaussianBlur(gray, (bkg_k, bkg_k), 0).astype(np.float32)
    gray_float = gray.astype(np.float32) - background
    gray_float = np.clip(gray_float, 0, None)

    # Noise sigma from the residual within the sky circle
    sky_resid = gray_float[mask > 0]
    sigma_val = max(1.5, 1.4826 * float(np.median(np.abs(sky_resid - np.median(sky_resid)))))

    # Threshold on the background-subtracted image
    threshold = max(1, int(threshold_sigma * sigma_val))
    gray_resid_u8 = np.clip(gray_float, 0, 255).astype(np.uint8)
    _, binary = cv2.threshold(gray_resid_u8, threshold, 255, cv2.THRESH_BINARY)

    # Morphological open to remove single-pixel noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # Apply sky circle mask — eliminates all out-of-circle detections
    binary = cv2.bitwise_and(binary, mask)

    # Connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    results: List[Tuple[float, float, float]] = []

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area_eff or area > max_area_eff:
            continue

        cx, cy = centroids[i]

        # Reject detections too close to the sky circle edge (horizon noise)
        dist_from_centre = np.hypot(cx - sky_cx, cy - sky_cy)
        if dist_from_centre > sky_radius - border_px:
            continue

        # Sub-pixel centroid via weighted moments
        cx_sub, cy_sub, flux = _weighted_centroid(
            gray_float, int(round(cx)), int(round(cy)), radius=8
        )
        if cx_sub is None:
            cx_sub, cy_sub = float(cx), float(cy)
            flux = float(np.sum(gray_float[labels == i]))

        results.append((cx_sub, cy_sub, flux))

    results.sort(key=lambda t: -t[2])
    return results[:max_stars]


def _weighted_centroid(
    image: np.ndarray,
    cx: int,
    cy: int,
    radius: int = 8,
) -> Tuple[Optional[float], Optional[float], float]:
    """
    Compute flux-weighted centroid in a local patch.
    Returns (x_sub, y_sub, total_flux) or (None, None, 0) on failure.
    """
    h, w = image.shape
    x0 = max(0, cx - radius)
    x1 = min(w, cx + radius + 1)
    y0 = max(0, cy - radius)
    y1 = min(h, cy + radius + 1)

    patch = image[y0:y1, x0:x1]
    if patch.size == 0:
        return None, None, 0.0

    total = float(np.sum(patch))
    if total <= 0:
        return None, None, 0.0

    ys, xs = np.mgrid[y0:y1, x0:x1]
    x_sub = float(np.sum(xs * patch) / total)
    y_sub = float(np.sum(ys * patch) / total)

    return x_sub, y_sub, total


def _fit_circle(points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    """
    Algebraic least-squares circle fit.

    Solves  x² + y² + Dx + Ey + F = 0  in the least-squares sense.
    Returns (cx, cy, radius).  Requires ≥ 3 points.
    """
    pts = np.array(points, dtype=np.float64)
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    b = -(x ** 2 + y ** 2)
    result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    D, E, F = result
    cx = -D / 2.0
    cy = -E / 2.0
    r  = float(np.sqrt(max(cx ** 2 + cy ** 2 - F, 0.0)))
    return float(cx), float(cy), r


def _to_gray(image) -> Optional[np.ndarray]:
    """Convert various image types to uint8 grayscale numpy array."""
    if isinstance(image, str):
        # Try OpenCV first (handles JPEG/PNG/BMP/TIFF)
        arr = cv2.imread(image, cv2.IMREAD_GRAYSCALE)
        if arr is not None:
            return arr
        # Fallback: try FITS via astropy (raw astronomical files)
        if image.lower().endswith('.fits') or image.lower().endswith('.fit'):
            try:
                from astropy.io import fits as astrofits
                with astrofits.open(image) as hdu:
                    data = hdu[0].data
                if data is not None:
                    return _numpy_to_gray(data)
            except Exception:
                pass
        return None

    if _PIL_AVAILABLE and isinstance(image, Image.Image):
        if image.mode == 'L':
            return np.array(image, dtype=np.uint8)
        return np.array(image.convert('L'), dtype=np.uint8)

    if isinstance(image, np.ndarray):
        return _numpy_to_gray(image)

    return None


def _numpy_to_gray(arr: np.ndarray) -> Optional[np.ndarray]:
    """
    Convert a numpy array of any common shape/dtype to uint8 grayscale.

    Supported layouts:
      (H, W)        — already grayscale
      (H, W, 3/4)   — channels-last RGB/RGBA  (standard OpenCV/PIL order)
      (3, H, W)     — channels-first RGB       (common in FITS / astropy)

    Scaling:
      uint8 arrays  — used as-is (no rescaling)
      all others    — percentile stretch (p1→0, p99→255) so that the sky
                       background sits at a usable mid-level.  Linear min-max
                       stretch collapses FITS sky backgrounds to ~2-5 ADU
                       (indistinguishable from corner noise), breaking sky
                       circle detection.
    """
    if arr.ndim == 2:
        if arr.dtype == np.uint8:
            return arr
        return _percentile_stretch(arr)

    if arr.ndim == 3:
        # Channels-first (C, H, W) → (H, W, C)
        if arr.shape[0] in (1, 3, 4) and arr.shape[0] < arr.shape[1]:
            arr = np.moveaxis(arr, 0, -1)

        if arr.dtype != np.uint8:
            arr = _percentile_stretch(arr)

        if arr.shape[2] == 1:
            return arr[:, :, 0]
        if arr.shape[2] == 3:
            return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        if arr.shape[2] == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)

    return None


def percentile_stretch(arr: np.ndarray) -> np.ndarray:
    """
    Stretch array to uint8 using 1st–99th percentile clipping.

    Maps p1 → 0, p99 → 255 and clips.  Far more useful than linear
    min-max for astronomical images where bright stars span orders of
    magnitude above the sky background.
    """
    flat = arr.flatten().astype(np.float32)
    lo = float(np.percentile(flat, 1))
    hi = float(np.percentile(flat, 99))
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (arr.astype(np.float32) - lo) / (hi - lo) * 255.0
    return scaled.clip(0, 255).astype(np.uint8)


_percentile_stretch = percentile_stretch  # re-exported for existing callers


def stretch_for_display(image):
    """Return a PIL RGB copy of a linear frame, stretched for human viewing.

    The guided-calibration dialog shows the raw pre-stretch frame so clicks
    land in the same pixel space the solver fits in. On a correctly exposed
    all-sky rig that frame has a median around 2/255 and renders as solid
    black (issue #10), so the user cannot see the stars they are asked to
    identify. Applying the *same* percentile stretch the detector uses means
    what the user sees is what the centroider sees.

    Display only — never feed the result back into detection or fitting.
    """
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for stretch_for_display")

    arr = np.asarray(image.convert('RGB') if hasattr(image, 'convert') else image)
    return Image.fromarray(percentile_stretch(arr))


def _estimate_background(gray: np.ndarray) -> Tuple[float, float]:
    """Estimate background median and sigma (robust via MAD). Whole-image fallback."""
    flat = gray.flatten().astype(np.float32)
    median = float(np.median(flat))
    mad = float(np.median(np.abs(flat - median)))
    sigma = 1.4826 * mad
    return median, max(sigma, 2.0)
