"""
Test camera profile management (config-level operations)
"""
import pytest
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.config import Config


class TestCameraProfileListing:
    """Test listing camera profiles from config"""

    def test_list_profiles_empty_by_default(self, temp_config):
        """Test listing profiles from config returns empty when no cameras connected"""
        config = Config(temp_config)
        profiles = config.list_camera_profiles()
        assert isinstance(profiles, list)
        assert len(profiles) == 0

    def test_list_profiles_returns_names(self, temp_config):
        """Test listing profiles returns correct camera names"""
        config = Config(temp_config)
        config.data['camera_profiles'] = {
            'ZWO ASI676MC': {'exposure_ms': 100, 'gain': 100},
            'ZWO ASI294MC Pro': {'exposure_ms': 200, 'gain': 150},
        }
        config.save()

        profiles = config.list_camera_profiles()
        assert 'ZWO ASI676MC' in profiles
        assert 'ZWO ASI294MC Pro' in profiles
        assert len(profiles) == 2


class TestCameraProfileCreation:
    """Test creating camera profiles"""

    def test_get_profile_creates_if_missing(self, temp_config):
        """Test get_camera_profile auto-creates from global defaults"""
        config = Config(temp_config)
        profile = config.get_camera_profile('ZWO ASI676MC')

        assert profile is not None
        assert 'exposure_ms' in profile
        assert 'gain' in profile
        assert 'bayer_pattern' in profile

    def test_get_profile_returns_none_for_empty_name(self, temp_config):
        """Test get_camera_profile returns None for empty name"""
        config = Config(temp_config)
        assert config.get_camera_profile('') is None
        assert config.get_camera_profile(None) is None

    def test_profile_structure_matches_schema(self, temp_config):
        """Test profile data structure matches expected schema"""
        config = Config(temp_config)
        profile = config.get_camera_profile('TestCamera')

        expected_keys = [
            'exposure_ms', 'gain', 'max_exposure_ms', 'target_brightness',
            'wb_r', 'wb_b', 'offset', 'flip', 'bayer_pattern'
        ]
        for key in expected_keys:
            assert key in profile, f"Missing profile key: {key}"


class TestCameraProfileDeletion:
    """Test deleting camera profiles"""

    def test_delete_profile_removes_from_config(self, temp_config):
        """Test deleting a profile removes it from config"""
        config = Config(temp_config)
        # Create a profile first
        config.get_camera_profile('ZWO ASI676MC')
        assert 'ZWO ASI676MC' in config.list_camera_profiles()

        # Delete it
        config.delete_camera_profile('ZWO ASI676MC')
        assert 'ZWO ASI676MC' not in config.list_camera_profiles()

    def test_delete_nonexistent_profile_is_safe(self, temp_config):
        """Test deleting a profile that doesn't exist doesn't crash"""
        config = Config(temp_config)
        # Should not raise
        config.delete_camera_profile('NonexistentCamera')

    def test_delete_preserves_other_profiles(self, temp_config):
        """Test deleting one profile preserves others"""
        config = Config(temp_config)
        config.get_camera_profile('Camera A')
        config.get_camera_profile('Camera B')

        config.delete_camera_profile('Camera A')

        profiles = config.list_camera_profiles()
        assert 'Camera A' not in profiles
        assert 'Camera B' in profiles


class TestCameraProfileUpdate:
    """Test updating camera profiles"""

    def test_update_profile_changes_values(self, temp_config):
        """Test update_camera_profile modifies specific settings"""
        config = Config(temp_config)
        config.get_camera_profile('TestCam')

        config.update_camera_profile('TestCam', gain=250, exposure_ms=5000)

        profile = config.get_camera_profile('TestCam')
        assert profile['gain'] == 250
        assert profile['exposure_ms'] == 5000

    def test_profile_persists_across_reload(self, temp_config):
        """Test profiles survive config save/load cycle"""
        config = Config(temp_config)
        config.get_camera_profile('ZWO ASI676MC')
        config.update_camera_profile('ZWO ASI676MC', gain=300)
        config.save()

        config2 = Config(temp_config)
        profile = config2.get_camera_profile('ZWO ASI676MC')
        assert profile['gain'] == 300


class TestSerialKeyedProfiles:
    """Profiles key off the hardware serial when known, so two same-model
    bodies don't collide and settings follow the physical camera."""

    def test_profile_keyed_by_serial_with_name_embedded(self, temp_config):
        config = Config(temp_config)
        prof = config.get_camera_profile('ZWO ASI676MC', '340b43071a020900')
        prof['gain'] = 300
        config.save_camera_profile('ZWO ASI676MC', prof, '340b43071a020900')

        assert '340b43071a020900' in config.list_camera_profiles()
        stored = config.data['camera_profiles']['340b43071a020900']
        assert stored['gain'] == 300
        assert stored['name'] == 'ZWO ASI676MC'  # name kept for readability

    def test_same_model_bodies_get_separate_profiles(self, temp_config):
        config = Config(temp_config)
        config.update_camera_profile('ZWO ASI676MC', serial='aaaa', gain=300)
        config.update_camera_profile('ZWO ASI676MC', serial='bbbb', gain=120)

        assert config.get_camera_profile('ZWO ASI676MC', 'aaaa')['gain'] == 300
        assert config.get_camera_profile('ZWO ASI676MC', 'bbbb')['gain'] == 120

    def test_legacy_name_profile_migrates_to_serial(self, temp_config):
        config = Config(temp_config)
        # Pre-existing name-keyed profile (as on disk before this change).
        config.data['camera_profiles'] = {'ZWO ASI676MC': {'gain': 300, 'exposure_ms': 100.0}}
        config.save()

        prof = config.get_camera_profile('ZWO ASI676MC', '340b43071a020900')
        assert prof['gain'] == 300  # tuned settings carried over
        assert '340b43071a020900' in config.list_camera_profiles()
        assert 'ZWO ASI676MC' in config.list_camera_profiles()  # template kept

    def test_no_serial_falls_back_to_name(self, temp_config):
        config = Config(temp_config)
        config.update_camera_profile('ZWO ASI676MC', gain=300)
        # Pre-serial selection: name key is used, not a serial key.
        assert config.get_camera_profile('ZWO ASI676MC')['gain'] == 300
        assert config.list_camera_profiles() == ['ZWO ASI676MC']

    def test_prune_drops_name_bug_artefacts(self, temp_config):
        from services.camera_profiles import prune_bogus_profiles
        data = {'camera_profiles': {
            'ZWO ASI676MC': {'gain': 300},
            'Camera 0': {'gain': 100},
            'Camera 2': {'gain': 100},
            'ZWO ASI676MC (Index: 2)': {'gain': 120},
            '340b43071a020900': {'gain': 300, 'name': 'ZWO ASI676MC'},
        }}
        prune_bogus_profiles(data)
        keys = set(data['camera_profiles'])
        assert keys == {'ZWO ASI676MC', '340b43071a020900'}
