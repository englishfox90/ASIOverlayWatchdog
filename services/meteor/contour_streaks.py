"""
Contour-based streak candidate finder — complements the Hough detector.

Motivation (ASTRiDE, dwkim78): trace object boundaries and classify each by
morphology (circularity + elongation) instead of fitting straight lines.
Run on the temporal transient map — where the static star field and equipment
have already cancelled — this catches faint and slightly-curved streaks that
HoughLinesP's rigid straight-segment model misses, improving recall. The
crowded-field false positives ASTRiDE warns about on raw frames largely vanish
because the input is already background-free.

Pure OpenCV (no scikit-image / photutils dependency). Discrimination here is
morphological only; meteor-vs-satellite remains the PersistenceFilter's job
downstream, so the output is deliberately the same MeteorDetection dataclass
the Hough path emits and flows into the identical profile/persistence pipeline.
"""
import math
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .detector import MeteorDetection, _soft_sky_mask


def _circularity(area: float, perimeter: float) -> float:
    """4*pi*area / perimeter^2 — ~1 for a disc, → 0 for a thin streak."""
    if perimeter <= 0:
        return 1.0
    return float(4.0 * math.pi * area / (perimeter * perimeter))


def detect_streaks_contour(
    image: Image.Image,
    min_length: int = 50,
    exclusion_zones: Optional[List] = None,
    sky_circle: Optional[Tuple[float, float, float]] = None,
    threshold: int = 10,
    max_circularity: float = 0.35,
    min_area: int = 8,
    max_area: int = 3000,
    max_elongation: float = 0.35,
) -> List[MeteorDetection]:
    """
    Detect streak candidates by contour morphology.

    Args mirror detect_meteors() where they overlap so the controller can swap
    or run both. *image* should be a transient map (FrameStack.transient_map()
    with hot pixels masked), not a raw frame.

    max_circularity: contours rounder than this are point-like (stars) → drop.
    min_area/max_area: reject noise specks and cloud/blob regions.
    max_elongation: width/length ratio ceiling; fatter than this → blob, not streak.

    Endpoints, length and angle come from cv2.fitLine over the contour points
    (version-independent, unlike minAreaRect's angle convention).
    """
    gray = np.array(image.convert("L"))

    if sky_circle is not None:
        gray = _soft_sky_mask(gray, *sky_circle)

    if threshold > 0:
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    else:
        binary = (gray > 0).astype(np.uint8) * 255
    binary = cv2.medianBlur(binary, 3)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    if exclusion_zones:
        from .mask import apply_exclusion_zones
        binary = apply_exclusion_zones(binary, exclusion_zones)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    detections: List[MeteorDetection] = []
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_area or area > max_area:
            continue

        perimeter = float(cv2.arcLength(cnt, closed=True))
        circ = _circularity(area, perimeter)
        if circ > max_circularity:
            continue  # round-ish → star / compact blob

        pts = cnt.reshape(-1, 2).astype(np.float32)
        vx, vy, x0, y0 = (float(v) for v in cv2.fitLine(
            cnt, cv2.DIST_L2, 0, 0.01, 0.01).ravel())

        # Project contour points onto the fitted axis (t) and its normal (s).
        t = (pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy
        s = -(pts[:, 0] - x0) * vy + (pts[:, 1] - y0) * vx
        t_min, t_max = float(t.min()), float(t.max())
        length = t_max - t_min
        if length < min_length:
            continue

        width = float(s.max() - s.min())
        elongation = width / length if length > 0 else 1.0
        if elongation > max_elongation:
            continue  # too fat along its own axis → blob

        x1, y1 = x0 + vx * t_min, y0 + vy * t_min
        x2, y2 = x0 + vx * t_max, y0 + vy * t_max
        angle_deg = math.degrees(math.atan2(y2 - y1, x2 - x1))

        detections.append(MeteorDetection(
            x1=int(round(x1)), y1=int(round(y1)),
            x2=int(round(x2)), y2=int(round(y2)),
            length=float(length),
            angle_deg=float(angle_deg),
            nonline_prob=float(np.clip(elongation, 0.0, 1.0)),
        ))

    return detections
