"""
Test the sky-observation gate in services/observing_window.py.

Covers the ml_models.roof_gates_sky_features opt-out (GitHub issue #10):
misfiring roof classifiers on roofless all-sky rigs should not have to
disable ML entirely to keep star detection / all-sky calibration alive.
"""
import os
import sys

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.config import DEFAULT_CONFIG
from services.observing_window import is_observing_window


def _config(ml_models=None, weather=None):
    """Minimal config dict. No lat/lon by default so the sun gate falls
    through and only the roof gate under test is exercised."""
    cfg = {'weather': weather or {}}
    if ml_models is not None:
        cfg['ml_models'] = ml_models
    return cfg


class TestRoofGateDefaultBehaviour:
    """Default (roof_gates_sky_features unset / True) matches today's behaviour."""

    def test_suppresses_when_roof_closed(self):
        config = _config(ml_models={'enabled': True})
        metadata = {'ROOF_STATUS': 'Closed (98%)'}

        assert is_observing_window(config, metadata, feature="test") is False

    def test_allows_when_roof_open(self):
        config = _config(ml_models={'enabled': True})
        metadata = {'ROOF_STATUS': 'Open (95%)'}

        assert is_observing_window(config, metadata, feature="test") is True

    def test_explicit_true_matches_default(self):
        config = _config(ml_models={'enabled': True, 'roof_gates_sky_features': True})
        metadata = {'ROOF_STATUS': 'Closed (98%)'}

        assert is_observing_window(config, metadata, feature="test") is False


class TestRoofGateOptOut:
    """roof_gates_sky_features: False skips the roof gate for roofless rigs."""

    def test_does_not_suppress_when_flag_disabled(self):
        config = _config(ml_models={'enabled': True, 'roof_gates_sky_features': False})
        metadata = {'ROOF_STATUS': 'Closed (98%)'}

        assert is_observing_window(config, metadata, feature="test") is True

    def test_still_allows_when_roof_open_and_flag_disabled(self):
        config = _config(ml_models={'enabled': True, 'roof_gates_sky_features': False})
        metadata = {'ROOF_STATUS': 'Open (95%)'}

        assert is_observing_window(config, metadata, feature="test") is True

    def test_ml_disabled_also_skips_roof_gate_regardless_of_flag(self):
        config = _config(ml_models={'enabled': False, 'roof_gates_sky_features': True})
        metadata = {'ROOF_STATUS': 'Closed (98%)'}

        assert is_observing_window(config, metadata, feature="test") is True


class TestTwilightGateIndependentOfRoofFlag:
    """The sun/twilight gate must apply regardless of roof_gates_sky_features."""

    def test_twilight_gate_suppresses_with_flag_disabled(self, monkeypatch):
        monkeypatch.setattr('astral.sun.elevation', lambda *a, **kw: 10.0)
        config = _config(
            ml_models={'enabled': True, 'roof_gates_sky_features': False},
            weather={'latitude': '51.5074', 'longitude': '-0.1278'},
        )
        metadata = {'ROOF_STATUS': 'Open (95%)'}

        assert is_observing_window(config, metadata, feature="test") is False

    def test_twilight_gate_suppresses_with_ml_disabled(self, monkeypatch):
        monkeypatch.setattr('astral.sun.elevation', lambda *a, **kw: 10.0)
        config = _config(weather={'latitude': '51.5074', 'longitude': '-0.1278'})
        metadata = {}

        assert is_observing_window(config, metadata, feature="test") is False

    def test_twilight_gate_allows_below_civil_twilight(self, monkeypatch):
        monkeypatch.setattr('astral.sun.elevation', lambda *a, **kw: -20.0)
        config = _config(
            ml_models={'enabled': True, 'roof_gates_sky_features': False},
            weather={'latitude': '51.5074', 'longitude': '-0.1278'},
        )
        metadata = {'ROOF_STATUS': 'Open (95%)'}

        assert is_observing_window(config, metadata, feature="test") is True


class TestResultCaching:
    def test_result_is_cached_on_metadata(self):
        config = _config(ml_models={'enabled': True})
        metadata = {'ROOF_STATUS': 'Closed (98%)'}

        first = is_observing_window(config, metadata, feature="test")
        # Flip the underlying status; cached result must not change.
        metadata['ROOF_STATUS'] = 'Open (95%)'
        second = is_observing_window(config, metadata, feature="test")

        assert first is False
        assert second is False


class TestDefaultConfigPreservesBehaviour:
    """DEFAULT_CONFIG must ship roof_gates_sky_features=True so existing
    installs keep suppressing sky features on a Closed roof prediction."""

    def test_default_config_has_flag_enabled(self):
        ml_defaults = DEFAULT_CONFIG.get('ml_models', {})
        assert ml_defaults.get('roof_gates_sky_features') is True

    def test_default_config_roof_closed_suppresses(self):
        config = {
            'weather': dict(DEFAULT_CONFIG['weather']),
            'ml_models': dict(DEFAULT_CONFIG['ml_models']),
        }
        config['ml_models']['enabled'] = True
        metadata = {'ROOF_STATUS': 'Closed (98%)'}

        assert is_observing_window(config, metadata, feature="test") is False
