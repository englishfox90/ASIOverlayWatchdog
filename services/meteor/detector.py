"""
Meteor Detector
CV-based meteor trail detection designed for long-exposure (10–20 s) frames.

For best results pass the transient map from FrameStack.transient_map() rather
than a raw or auto-stretched frame.

Algorithm:
  1. Grayscale + feathered sky-circle mask (soft boundary prevents chord artefacts)
  2. Adaptive binary threshold + medianBlur(3)
  3. MORPH_CLOSE to connect nearby fragments (replaces the old Canny+dilate/erode)
  4. Cloud/blob mask: large-area contours suppressed
  5. Exclusion zone mask (user-rejected equipment regions)
  6. Probabilistic Hough — maxLineGap=15 (bridges gaps in faint/broken trails)
  7. nonline_prob filter: fat blobs rejected, thin streaks kept
  8. Optional minimum brightness check along the trail

Deprecated functions retained for test backward-compat (Phase 6 will remove):
  compute_frame_difference, apply_sky_circle_mask, estimate_adaptive_threshold,
  check_speed_plausibility.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


@dataclass
class MeteorDetection:
    x1: int
    y1: int
    x2: int
    y2: int
    length: float
    angle_deg: float
    nonline_prob: float = 0.0   # 0 = thin streak, 1 = fat blob (cloud/noise)


# ------------------------------------------------------------------ #
#  Soft sky-circle mask                                                #
# ------------------------------------------------------------------ #

def _soft_sky_mask(gray: np.ndarray, cx: float, cy: float, radius: float,
                   feather: int = 20) -> np.ndarray:
    """
    Multiply *gray* by a radial weight that is 1.0 inside the sky circle
    and ramps smoothly to 0.0 over *feather* pixels at the boundary.

    A hard zero creates a crisp circle edge that HoughLinesP finds as a chord.
    A feathered boundary falls below the binary threshold and disappears.
    """
    h, w = gray.shape[:2]
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(np.float32)
    weight = np.clip((radius - dist) / max(feather, 1), 0.0, 1.0)
    return (gray.astype(np.float32) * weight).astype(np.uint8)


# ------------------------------------------------------------------ #
#  nonline_prob                                                        #
# ------------------------------------------------------------------ #

def _compute_nonline_prob(binary: np.ndarray, det: MeteorDetection,
                          n_samples: int = 12, max_half_scan: int = 30) -> float:
    """
    Measure how 'fat' the binary blob is relative to the detection length.

    For each of *n_samples* points along the line, scan perpendicular until
    the binary mask reaches 0 (or the scan limit). The mean full width divided
    by the detection length is the nonline_prob.

    Thin streak (w≈3, L=200): prob ≈ 3/200 = 0.015  → pass.
    Cloud blob  (w=80, L=100): prob ≈ 80/100 = 0.8   → reject.
    """
    if det.length < 1:
        return 1.0
    h, w = binary.shape[:2]
    n = n_samples
    xs = np.linspace(det.x1, det.x2, n)
    ys = np.linspace(det.y1, det.y2, n)
    length = det.length
    dx = (det.x2 - det.x1) / length
    dy = (det.y2 - det.y1) / length
    px, py = -dy, dx  # perpendicular unit vector

    half_widths = []
    for xi, yi in zip(xs, ys):
        for side in (1, -1):
            hw = max_half_scan
            for step in range(1, max_half_scan + 1):
                nx = int(np.clip(xi + side * step * px, 0, w - 1))
                ny = int(np.clip(yi + side * step * py, 0, h - 1))
                if binary[ny, nx] == 0:
                    hw = step
                    break
            half_widths.append(hw)

    mean_full_width = 2.0 * float(np.mean(half_widths))
    return float(np.clip(mean_full_width / length, 0.0, 1.0))


# ------------------------------------------------------------------ #
#  Collinear segment merge (line NMS)                                  #
# ------------------------------------------------------------------ #

def _merge_collinear_segments(
    detections: List["MeteorDetection"],
    angle_tol_deg: float = 10.0,
    lateral_tol_px: float = 8.0,
    gap_tol_px: float = 20.0,
) -> List["MeteorDetection"]:
    """
    HoughLinesP returns several overlapping segments for one physical streak.
    Greedily merge segments that are collinear (angle + lateral offset within
    tolerance) and overlapping/near along the track into a single spanning
    detection, longest-first.
    """
    if len(detections) <= 1:
        return detections

    merged: List[MeteorDetection] = []
    for d in sorted(detections, key=lambda x: x.length, reverse=True):
        target = None
        for i, m in enumerate(merged):
            ad = abs(d.angle_deg - m.angle_deg) % 180
            if min(ad, 180 - ad) > angle_tol_deg:
                continue
            length = m.length or 1.0
            ux, uy = (m.x2 - m.x1) / length, (m.y2 - m.y1) / length
            mid_x, mid_y = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
            lateral = abs(-uy * (mid_x - m.x1) + ux * (mid_y - m.y1))
            if lateral > lateral_tol_px:
                continue
            t1 = (d.x1 - m.x1) * ux + (d.y1 - m.y1) * uy
            t2 = (d.x2 - m.x1) * ux + (d.y2 - m.y1) * uy
            if max(t1, t2) < -gap_tol_px or min(t1, t2) > length + gap_tol_px:
                continue
            target = i
            break

        if target is None:
            merged.append(d)
            continue

        m = merged[target]
        length = m.length or 1.0
        ux, uy = (m.x2 - m.x1) / length, (m.y2 - m.y1) / length
        pts = [(m.x1, m.y1), (m.x2, m.y2), (d.x1, d.y1), (d.x2, d.y2)]
        ts = [(p[0] - m.x1) * ux + (p[1] - m.y1) * uy for p in pts]
        p1 = pts[int(np.argmin(ts))]
        p2 = pts[int(np.argmax(ts))]
        new_len = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        merged[target] = MeteorDetection(
            x1=int(p1[0]), y1=int(p1[1]), x2=int(p2[0]), y2=int(p2[1]),
            length=new_len,
            angle_deg=float(np.degrees(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))),
            nonline_prob=max(m.nonline_prob, d.nonline_prob),
        )
    return merged


# ------------------------------------------------------------------ #
#  Core detection                                                      #
# ------------------------------------------------------------------ #

def detect_meteors(
    image: Image.Image,
    min_length: int = 50,
    exclusion_zones: Optional[List] = None,
    sky_circle: Optional[Tuple[float, float, float]] = None,
    threshold: int = 10,
    max_nonline_prob: float = 0.15,
    min_brightness: int = 20,
) -> List[MeteorDetection]:
    """
    Detect meteor trails in a PIL image.

    Args:
        image:            PIL Image (any mode — converted to grayscale internally).
                          For best results pass a transient map from
                          FrameStack.transient_map() rather than a raw frame.
        min_length:       Minimum trail length in pixels (detection-scale coords).
        exclusion_zones:  Optional list of ExclusionZone instances (detection coords).
        sky_circle:       Optional (cx, cy, radius) sky-circle in detection coords.
                          When supplied a feathered mask is applied before thresholding.
        threshold:        Binary threshold [0–100].  Pass 0 to skip thresholding
                          (image already binary).  Use noise.noise_to_threshold()
                          to derive this from the transient map's noise estimate.
        max_nonline_prob: Blobs with nonline_prob above this are rejected (clouds).
        min_brightness:   Minimum mean pixel value along the trail in the source
                          image.  Set to 0 to disable.

    Returns:
        List of MeteorDetection (may be empty).
    """
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)

    # --- Sky circle: feathered mask ---
    if sky_circle is not None:
        gray = _soft_sky_mask(gray, *sky_circle)

    # --- Binary threshold + smoothing ---
    if threshold > 0:
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    else:
        binary = (gray > 0).astype(np.uint8) * 255
    binary = cv2.medianBlur(binary, 3)

    # --- Morphological close: connect nearby streak fragments ---
    k3 = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k3, iterations=1)

    # --- Cloud/blob mask: large-area contours are clouds, not meteors ---
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cloud_mask = np.zeros_like(binary)
    for cnt in contours:
        if cv2.contourArea(cnt) > 2000:
            cv2.drawContours(cloud_mask, [cnt], 0, 255, -1)
    if cloud_mask.any():
        k7 = np.ones((7, 7), np.uint8)
        cloud_expanded = cv2.dilate(cloud_mask, k7, iterations=1)
        binary = cv2.bitwise_and(binary, cv2.bitwise_not(cloud_expanded))

    # --- Exclusion zones ---
    if exclusion_zones:
        from .mask import apply_exclusion_zones
        binary = apply_exclusion_zones(binary, exclusion_zones)

    # --- Hough lines: maxLineGap bridges small gaps in faint/broken trails ---
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180,
        threshold=max(5, min_length // 3),
        minLineLength=min_length,
        maxLineGap=15,
    )

    detections: List[MeteorDetection] = []
    if lines is None:
        return detections

    # OpenCV ≤4.x returns HoughLinesP lines as (N, 1, 4); 5.0 dropped the
    # middle axis to (N, 4). Normalise so the unpack works on both — on 5.0
    # `line[0]` would otherwise be a bare int and raise "cannot unpack".
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        dx, dy = x2 - x1, y2 - y1
        length = float(np.hypot(dx, dy))
        if length < min_length:
            continue

        angle = float(np.degrees(np.arctan2(dy, dx)))
        nlp = _compute_nonline_prob(binary, MeteorDetection(
            x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
            length=length, angle_deg=angle,
        ))
        if nlp > max_nonline_prob:
            continue

        if min_brightness > 0:
            if not _validate_trail_brightness(gray, x1, y1, x2, y2, length, min_brightness):
                continue

        detections.append(MeteorDetection(
            x1=int(x1), y1=int(y1),
            x2=int(x2), y2=int(y2),
            length=length,
            angle_deg=angle,
            nonline_prob=nlp,
        ))

    return _merge_collinear_segments(detections)


def _validate_trail_brightness(
    gray: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    length: float,
    min_brightness: int,
) -> bool:
    n = max(int(length), 2)
    xs = np.linspace(x1, x2, n, dtype=int)
    ys = np.linspace(y1, y2, n, dtype=int)
    h, w = gray.shape[:2]
    xs = np.clip(xs, 0, w - 1)
    ys = np.clip(ys, 0, h - 1)
    return float(np.mean(gray[ys, xs])) >= min_brightness


# ------------------------------------------------------------------ #
#  Annotate                                                            #
# ------------------------------------------------------------------ #

def annotate_image(image: Image.Image, detections: List[MeteorDetection]) -> Image.Image:
    """Return a copy of *image* with detected trails drawn in green."""
    if not detections:
        return image.copy()
    arr = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    for det in detections:
        cv2.line(bgr, (det.x1, det.y1), (det.x2, det.y2), (0, 255, 0), 3)
        mid_x = (det.x1 + det.x2) // 2
        mid_y = (det.y1 + det.y2) // 2 - 10
        cv2.putText(bgr, f"{det.length:.0f}px",
                    (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


# ------------------------------------------------------------------ #
#  Deprecated helpers — kept for test backward-compat                 #
#  Phase 6 will delete these.                                         #
# ------------------------------------------------------------------ #

def compute_frame_difference(
    current: Image.Image,
    previous: Image.Image,
    threshold: int = 25,
) -> Image.Image:
    """DEPRECATED: Use FrameStack.transient_map() instead."""
    cur_gray = cv2.cvtColor(np.array(current.convert("RGB")), cv2.COLOR_RGB2GRAY)
    prev_gray = cv2.cvtColor(np.array(previous.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if cur_gray.shape != prev_gray.shape:
        prev_gray = cv2.resize(prev_gray, (cur_gray.shape[1], cur_gray.shape[0]))
    diff = cv2.absdiff(cur_gray, prev_gray)
    if threshold > 0:
        diff[diff < threshold] = 0
    return Image.fromarray(cv2.cvtColor(diff, cv2.COLOR_GRAY2RGB))


def apply_sky_circle_mask(
    image: Image.Image,
    cx: float,
    cy: float,
    radius: float,
) -> Image.Image:
    """DEPRECATED: detect_meteors() applies the feathered mask internally."""
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    outside = (X - cx) ** 2 + (Y - cy) ** 2 > radius ** 2
    arr[outside] = 0
    return Image.fromarray(arr)


def estimate_adaptive_threshold(image: Image.Image, sample_ratio: float = 0.1) -> int:
    """DEPRECATED: Use noise.DiffNoiseEMA + noise.noise_to_threshold() instead."""
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    side = max(1, int((h * w * sample_ratio) ** 0.5))
    cy, cx = h // 2, w // 2
    half = side // 2
    crop = gray[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
    std = float(np.std(crop))
    return max(5, min(100, int(1.2 * std * std + 3.6)))


def check_speed_plausibility(
    det: MeteorDetection,
    exposure_sec: float,
    image_width: int,
    min_speed_pct: float = 2.0,
    max_speed_pct: float = 50.0,
) -> bool:
    """
    DEPRECATED — this filter is inverted for long exposures and will be
    removed in Phase 3. Do not call from new code.
    """
    if exposure_sec <= 0:
        return True
    speed_pct = (det.length / image_width) / exposure_sec * 100.0
    return min_speed_pct <= speed_pct <= max_speed_pct
