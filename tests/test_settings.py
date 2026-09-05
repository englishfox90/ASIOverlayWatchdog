"""
Test settings persistence - save, load, and callback
"""
import pytest
import json
import os
import sys
import threading

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.config import Config, DEFAULT_CONFIG


class TestConfigPersistence:
    """Test configuration save/load functionality"""
    
    def test_default_config_loaded(self, temp_config):
        """Test that default config is loaded when no file exists"""
        config = Config(temp_config)
        
        # Should have all default keys
        assert 'capture_mode' in config.data
        assert 'output_directory' in config.data
        assert 'overlays' in config.data
    
    def test_config_save_and_load(self, temp_config):
        """Test that config is saved and can be reloaded"""
        config = Config(temp_config)

        # Modify globals that survive round-trip (per-camera settings belong in profiles now)
        config.set('zwo_interval', 7.5)
        config.set('capture_mode', 'camera')
        config.save()

        # Create new config instance to load
        config2 = Config(temp_config)

        assert config2.get('zwo_interval') == 7.5
        assert config2.get('capture_mode') == 'camera'
    
    def test_config_merge_preserves_new_defaults(self, temp_config):
        """Test that new default keys are added when loading old config"""
        # Create an old-style config with missing keys
        old_config = {
            'capture_mode': 'camera',
            'zwo_interval': 10.0,
            # Missing many new keys
        }

        with open(temp_config, 'w') as f:
            json.dump(old_config, f)

        config = Config(temp_config)

        # Old values should be preserved
        assert config.get('capture_mode') == 'camera'
        assert config.get('zwo_interval') == 10.0

        # New default keys should be added
        assert 'output' in config.data
        assert 'discord' in config.data
        assert 'weather' in config.data
    
    def test_nested_config_merge(self, temp_config):
        """Test that nested config objects merge correctly"""
        # Create config with partial nested data
        partial_config = {
            'capture_mode': 'camera',
            'output': {
                'mode': 'webserver'
                # Missing other output keys
            }
        }
        
        with open(temp_config, 'w') as f:
            json.dump(partial_config, f)
        
        config = Config(temp_config)
        
        # User value should be preserved
        assert config.data['output']['mode'] == 'webserver'
        
        # Default values should be filled in
        assert 'webserver_host' in config.data['output']
        assert 'webserver_port' in config.data['output']

    def test_new_nested_default_backfilled_into_existing_block(self, temp_config):
        """A sub-key added to DEFAULT_CONFIG reaches users whose saved config
        already has the parent block (allsky_overlay.burn_into_output)."""
        with open(temp_config, 'w') as f:
            json.dump({'allsky_overlay': {'enabled': True}}, f)

        config = Config(temp_config)

        overlay = config.data['allsky_overlay']
        assert overlay['enabled'] is True
        assert overlay['burn_into_output'] == {
            'saved_file': False, 'web': False, 'timelapse': False}

    def test_overlay_config_preserved(self, temp_config):
        """Test that overlay configurations are preserved"""
        config = Config(temp_config)
        
        test_overlays = [
            {
                'type': 'text',
                'text': 'Test Overlay',
                'anchor': 'Top-Left',
                'font_size': 24
            }
        ]
        
        config.set_overlays(test_overlays)
        config.save()
        
        config2 = Config(temp_config)
        overlays = config2.get_overlays()
        
        assert len(overlays) == 1
        assert overlays[0]['text'] == 'Test Overlay'
    
    def test_config_get_with_default(self, temp_config):
        """Test get() returns default for missing keys"""
        config = Config(temp_config)
        
        result = config.get('nonexistent_key', 'default_value')
        assert result == 'default_value'
    
    def test_output_settings_saved(self, temp_config):
        """Test output mode settings are persisted correctly"""
        config = Config(temp_config)
        
        config.data['output'] = {
            'mode': 'webserver',
            'webserver_enabled': True,
            'webserver_host': '0.0.0.0',
            'webserver_port': 9090,
            'webserver_path': '/image',
            'webserver_status_path': '/status'
        }
        config.save()
        
        config2 = Config(temp_config)
        output = config2.get('output', {})
        
        assert output['mode'] == 'webserver'
        assert output['webserver_host'] == '0.0.0.0'
        assert output['webserver_port'] == 9090


class TestConfigThreadSafety:
    """Test configuration thread safety"""

    def test_concurrent_get_set_no_corruption(self, temp_config):
        """Test concurrent get/set from multiple threads don't corrupt state"""
        config = Config(temp_config)
        errors = []

        def writer(key_suffix, count):
            try:
                for i in range(count):
                    config.set(f'thread_key_{key_suffix}', i)
            except Exception as e:
                errors.append(e)

        def reader(count):
            try:
                for _ in range(count):
                    config.get('capture_mode', 'default')
            except Exception as e:
                errors.append(e)

        threads = []
        for t_id in range(4):
            threads.append(threading.Thread(target=writer, args=(t_id, 100)))
            threads.append(threading.Thread(target=reader, args=(100,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_concurrent_save_produces_valid_json(self, temp_config):
        """Test concurrent save calls produce valid JSON (not truncated)"""
        config = Config(temp_config)
        errors = []

        def saver(count):
            try:
                for i in range(count):
                    config.set('counter', i)
                    config.save()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=saver, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

        # Verify final file is valid JSON
        with open(temp_config, 'r') as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert 'counter' in data

    def test_rlock_reentrance(self, temp_config):
        """Test RLock reentrance (save() calls get() internally via self.data)"""
        config = Config(temp_config)
        config.set('test_key', 'test_value')

        # save() acquires lock, and internally accesses self.data
        # This should not deadlock thanks to RLock
        result = config.save()
        assert result is True

        # Verify via reload
        config2 = Config(temp_config)
        assert config2.get('test_key') == 'test_value'


class TestConfigValidation:
    """Test configuration validation"""
    
    def test_default_config_has_required_keys(self):
        """Verify DEFAULT_CONFIG has all required keys"""
        required_keys = [
            'capture_mode',
            'output_directory',
            'output_format',
            'overlays',
            'output',
            'zwo_interval',
            'zwo_auto_exposure',
            'camera_profiles',
        ]

        for key in required_keys:
            assert key in DEFAULT_CONFIG, f"Missing required key: {key}"
    
    def test_output_config_structure(self):
        """Verify output config has correct structure"""
        output = DEFAULT_CONFIG.get('output', {})

        assert 'mode' in output
        assert 'webserver_host' in output
        assert 'webserver_port' in output


class TestConfigValidateMethod:
    """Test Config.validate() method"""

    def test_valid_config_no_warnings(self, temp_config, temp_dir):
        """Test valid config passes validation with no warnings"""
        config = Config(temp_config)
        # Point output_directory to an existing writable dir
        config.set('output_directory', temp_dir)
        config.set('capture_mode', 'camera')

        warnings = config.validate()
        assert len(warnings) == 0

    def test_invalid_output_directory(self, temp_config):
        """Test invalid output directory produces warning"""
        config = Config(temp_config)
        config.set('output_directory', '/nonexistent/path/that/does/not/exist')

        warnings = config.validate()
        assert any('Output directory' in w for w in warnings)

    def test_invalid_port_range(self, temp_config, temp_dir):
        """Test out-of-range port number produces warning"""
        config = Config(temp_config)
        config.set('output_directory', temp_dir)
        config.data['output']['webserver_port'] = 99999

        warnings = config.validate()
        assert any('webserver_port' in w for w in warnings)

    def test_missing_required_key(self, temp_config, temp_dir):
        """Test missing required key produces warning"""
        config = Config(temp_config)
        config.set('output_directory', temp_dir)
        # Remove a required key
        del config.data['overlays']

        warnings = config.validate()
        assert any('overlays' in w for w in warnings)

    def test_validation_returns_list(self, temp_config):
        """Test validation returns structured list of warnings"""
        config = Config(temp_config)
        warnings = config.validate()
        assert isinstance(warnings, list)

    def test_validation_does_not_block(self, temp_config):
        """Test validation doesn't block app startup (warnings only, not errors)"""
        config = Config(temp_config)
        # Even with bad config, validate should not raise
        config.set('output_directory', '/bad/path')
        config.data['output']['webserver_port'] = -1
        del config.data['overlays']

        warnings = config.validate()
        # Should return warnings, not raise
        assert len(warnings) >= 2

    def test_discord_enabled_no_webhook_warns(self, temp_config, temp_dir):
        """Test Discord enabled with empty webhook URL produces warning"""
        config = Config(temp_config)
        config.set('output_directory', temp_dir)
        config.data['discord']['enabled'] = True
        config.data['discord']['webhook_url'] = ''

        warnings = config.validate()
        assert any('Discord' in w and 'webhook' in w.lower() for w in warnings)
