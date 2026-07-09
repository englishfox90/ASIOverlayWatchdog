"""
Single-frame streak intensity analysis for meteor/plane discrimination.

A meteor in a long exposure leaves a brief ionisation trail that typically
brightens to a peak near the centre of the streak and fades toward the ends
(ablation profile). A plane with strobing nav lights leaves a regular
dashed/periodic pattern along the streak.

Both scores are in [0, 1]. Higher peak_fade_score = more meteor-like.
Higher dash_score = more plane-like. The controller applies configurable
thresholds to decide whether to pass or discard a detection.
"""
import numpy as np

from .detector import MeteorDetection


def sample_profile(
    gray: np.ndarray,
    det: MeteorDetection,
    half_width: int = 2,
) -> np.ndarray:
    """
    Sample mean intensity along the streak, averaged over a cross-section
    of ±*half_width* pixels perpendicular to the streak direction.

    Returns a 1-D float32 array with one sample per pixel of streak length.
    """
    n = max(int(det.length), 4)
    xs = np.linspace(det.x1, det.x2, n, dtype=float)
    ys = np.linspace(det.y1, det.y2, n, dtype=float)
    h, w = gray.shape[:2]

    length = det.length or 1.0
    dx, dy = (det.x2 - det.x1) / length, (det.y2 - det.y1) / length
    px, py = -dy, dx  # perpendicular unit vector

    samples = []
    for i in range(n):
        vals = []
        for offset in range(-half_width, half_width + 1):
            xi = int(np.clip(xs[i] + offset * px, 0, w - 1))
            yi = int(np.clip(ys[i] + offset * py, 0, h - 1))
            vals.append(float(gray[yi, xi]))
        samples.append(float(np.mean(vals)))
    return np.array(samples, dtype=np.float32)


def dash_score(profile: np.ndarray) -> float:
    """
    Autocorrelation-based periodicity score.

    Returns 0.0 for a uniform/smooth profile and approaches 1.0 for a
    strongly periodic (dashed) profile — the hallmark of plane nav-light strobes.

    Secondary autocorrelation peaks at lags ≥ 5% of the profile length are
    examined; the maximum such peak is the score.
    """
    if len(profile) < 10:
        return 0.0
    p = profile - float(np.mean(profile))
    if float(np.std(p)) < 1e-3:
        return 0.0
    ac = np.correlate(p, p, mode='full')
    ac = ac[len(ac) // 2:]   # positive lags only
    norm = ac[0] + 1e-6
    ac = ac / norm

    min_lag = max(3, len(profile) // 20)
    max_lag = max(min_lag + 1, len(ac) // 2)
    secondary = float(np.max(ac[min_lag:max_lag])) if max_lag > min_lag else 0.0
    return float(np.clip(secondary, 0.0, 1.0))


def dash_count(
    profile: np.ndarray,
    rel_threshold: float = 0.45,
    min_gap: int = 2,
) -> int:
    """
    Count distinct bright dashes along the streak.

    A meteor leaves a single continuous bright run (count == 1). A plane with
    strobing nav lights leaves several separated bright segments — the dark
    gaps between blinks split the profile into multiple runs. This is more
    robust than :func:`dash_score` for *irregular* strobes, where the
    autocorrelation finds no clean period and scores only weakly even though
    the row of dots is obvious to the eye.

    A sample counts as bright when it exceeds
    ``min + rel_threshold * (max - min)`` of the smoothed profile. Dark gaps
    shorter than *min_gap* samples are ignored so a single-sample noise dip
    inside one continuous trail does not split it into two dashes.
    """
    if len(profile) < 6:
        return 0

    # Guard on the raw range: a flat streak has no dashes. Do this before
    # smoothing, whose 'same'-mode boundary ramp would otherwise manufacture
    # a spurious peak from a genuinely uniform profile.
    if float(profile.max() - profile.min()) < 1e-3:
        return 0

    win = max(1, len(profile) // 16)
    kernel = np.ones(win, dtype=np.float32) / win
    smoothed = np.convolve(profile, kernel, mode='same')

    ptp = float(smoothed.max() - smoothed.min())
    if ptp < 1e-3:
        return 0

    norm = (smoothed - smoothed.min()) / ptp
    bright = norm >= rel_threshold

    runs = 0
    gap = min_gap  # start "in a gap" so the first bright sample opens a run
    for b in bright:
        if b:
            if gap >= min_gap:
                runs += 1
            gap = 0
        else:
            gap += 1
    return runs


def peak_fade_score(profile: np.ndarray) -> float:
    """
    Unimodality score of the intensity envelope.

    Meteors ablate with a roughly Gaussian brightness profile — bright at the
    peak of ablation and fading toward both ends. Planes are flat or periodic.

    Score = fraction of the smoothed profile that is monotonically increasing
    on the left of the peak and monotonically decreasing on the right.
    Returns 0.5 for profiles that are too short to analyse.
    """
    if len(profile) < 6:
        return 0.5

    win = max(1, len(profile) // 8)
    kernel = np.ones(win, dtype=np.float32) / win
    smoothed = np.convolve(profile, kernel, mode='same')

    peak_idx = int(np.argmax(smoothed))
    ptp = float(smoothed.max() - smoothed.min())
    if ptp < 1e-3:
        return 0.0

    s = (smoothed - smoothed.min()) / ptp
    left = s[:peak_idx + 1]
    right = s[peak_idx:]

    left_score = float(np.sum(np.diff(left) >= 0)) / max(1, len(left) - 1)
    right_score = float(np.sum(np.diff(right) <= 0)) / max(1, len(right) - 1)
    return float((left_score + right_score) / 2.0)
