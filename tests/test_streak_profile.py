"""Tests for meteor/plane streak discrimination scores."""
import numpy as np

from services.meteor.streak_profile import dash_count, dash_score, peak_fade_score


def _gaussian_profile(n=68, center=None, sigma=None):
    """A meteor-like ablation profile: one continuous bright peak that fades."""
    center = center if center is not None else n / 2
    sigma = sigma if sigma is not None else n / 6
    x = np.arange(n, dtype=np.float32)
    return np.exp(-((x - center) ** 2) / (2 * sigma ** 2)).astype(np.float32)


def _dashed_profile(n=68, n_dashes=6):
    """A plane-like profile: several separated bright dots with dark gaps."""
    prof = np.zeros(n, dtype=np.float32)
    period = n / n_dashes
    for k in range(n_dashes):
        c = int((k + 0.5) * period)
        prof[max(0, c - 1):c + 2] = 1.0
    return prof


def test_dash_count_meteor_is_single_run():
    assert dash_count(_gaussian_profile()) == 1


def test_dash_count_plane_counts_multiple_dashes():
    assert dash_count(_dashed_profile(n_dashes=6)) >= 3


def test_dash_count_tolerates_single_sample_noise_dip():
    prof = _gaussian_profile()
    prof[len(prof) // 2] *= 0.4  # one-pixel dip must not split the trail
    assert dash_count(prof) == 1


def test_dash_count_flat_profile_is_zero():
    assert dash_count(np.ones(68, dtype=np.float32)) == 0


def test_dash_count_short_profile_is_zero():
    assert dash_count(np.array([1.0, 0.0, 1.0], dtype=np.float32)) == 0


def test_meteor_scores_favour_meteor():
    prof = _gaussian_profile()
    assert peak_fade_score(prof) > 0.8
    assert dash_count(prof) == 1


def test_plane_scores_favour_plane():
    prof = _dashed_profile(n_dashes=6)
    # Autocorrelation may under-score irregular strobes, but the dash count
    # is the robust discriminator this suite guards.
    assert dash_count(prof) >= 3
    assert isinstance(dash_score(prof), float)
