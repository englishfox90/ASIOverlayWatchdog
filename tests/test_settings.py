"""
Test settings persistence - save, load, and callback
"""
import pytest
import json
import os
import sys

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
        
        # Modify a value
        config.set('zwo_exposure_ms', 5000.0)
        config.set('zwo_gain', 150)
        config.save()
        
        # Create new config instance to load
        config2 = Config(temp_config)
        
        assert config2.get('zwo_exposure_ms') == 5000.0
        assert config2.get('zwo_gain') == 150
    
    def test_config_merge_preserves_new_defaults(self, temp_config):
        """Test that new default keys are added when loading old config"""
        # Create an old-style config with missing keys
        old_config = {
            'capture_mode': 'camera',
            'zwo_exposure_ms': 100.0
            # Missing many new keys
        }
        
        with open(temp_config, 'w') as f:
            json.dump(old_config, f)
        
        config = Config(temp_config)
        
        # Old values should be preserved
        assert config.get('capture_mode') == 'camera'
        assert config.get('zwo_exposure_ms') == 100.0
        
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
            'zwo_exposure_ms',
            'zwo_gain'
        ]
        
        for key in required_keys:
            assert key in DEFAULT_CONFIG, f"Missing required key: {key}"
    
    def test_output_config_structure(self):
        """Verify output config has correct structure"""
        output = DEFAULT_CONFIG.get('output', {})
        
        assert 'mode' in output
        assert 'webserver_host' in output
        assert 'webserver_port' in output
        assert 'rtsp_host' in output
        assert 'rtsp_port' in output
