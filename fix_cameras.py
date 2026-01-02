"""
Camera Settings Reset Script
=============================

This script detects all connected ZWO cameras and resets them to safe default
settings with proper per-camera profiles. Use this to fix cameras that have
been contaminated with wrong settings from other cameras.

Usage:
    python fix_cameras.py

What it does:
    1. Backs up current config.json
    2. Detects all connected ZWO cameras
    3. For each camera, creates a profile with safe defaults:
       - Exposure: 100ms (0.1s)
       - Gain: 100
       - Auto Exposure: Disabled
       - White Balance: ASI Auto (R=75, B=99)
       - Offset: 20
       - Flip: None (0)
       - Bayer Pattern: BGGR
    4. Saves new profiles to config

IMPORTANT: Close PFRSentinel before running this script!
"""

import os
import sys
import shutil
import json
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils_paths import get_app_data_dir


def backup_config():
    """Backup current config.json"""
    config_dir = get_app_data_dir()
    config_path = os.path.join(config_dir, 'config.json')
    
    if not os.path.exists(config_path):
        print(f"⚠ No config file found at: {config_path}")
        return None
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(config_dir, f'config_backup_{timestamp}.json')
    
    try:
        shutil.copy2(config_path, backup_path)
        print(f"✓ Config backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"✗ Failed to backup config: {e}")
        return None


def detect_cameras(sdk_path):
    """Detect all connected ZWO cameras"""
    print("\n=== Detecting Cameras ===")
    
    try:
        import zwoasi as asi
        
        # Initialize SDK
        if not os.path.exists(sdk_path):
            print(f"✗ SDK not found at: {sdk_path}")
            return []
        
        print(f"Initializing SDK: {sdk_path}")
        asi.init(sdk_path)
        
        # Get camera count
        num_cameras = asi.get_num_cameras()
        print(f"Found {num_cameras} camera(s)")
        
        if num_cameras == 0:
            return []
        
        # Get camera names
        cameras = []
        for i in range(num_cameras):
            try:
                name = asi.list_cameras()[i]
                print(f"  [{i}] {name}")
                cameras.append({'index': i, 'name': name})
            except Exception as e:
                print(f"  [{i}] Error reading camera: {e}")
        
        return cameras
        
    except ImportError:
        print("✗ zwoasi library not installed. Run: pip install zwoasi")
        return []
    except Exception as e:
        print(f"✗ Error detecting cameras: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_safe_defaults(camera_name):
    """Get safe default settings for a camera"""
    # Most ZWO color cameras use BGGR pattern
    # Monochrome cameras don't need debayering but pattern won't hurt
    bayer_pattern = "BGGR"
    
    # ASI cameras with known patterns (add more as needed)
    if "ASI224" in camera_name or "ASI1600" in camera_name:
        bayer_pattern = "RGGB"
    
    # NOTE: auto_exposure is NOT in camera profiles - it's a global algorithm setting
    # NOTE: auto_wb/WB mode is NOT in camera profiles - stored in global white_balance config
    return {
        'exposure_ms': 100.0,  # 100ms = 0.1 second (safe starting point)
        'gain': 100,           # Mid-range gain
        'max_exposure_ms': 30000.0,  # 30 seconds max
        'target_brightness': 100,
        'wb_r': 75,            # Conservative white balance
        'wb_b': 99,
        'offset': 20,          # Standard offset
        'flip': 0,             # No flip
        'bayer_pattern': bayer_pattern
    }


def create_camera_profiles(cameras):
    """Create safe profiles for all detected cameras"""
    print("\n=== Creating Camera Profiles ===")
    
    profiles = {}
    for cam in cameras:
        name = cam['name']
        defaults = get_safe_defaults(name)
        profiles[name] = defaults
        
        print(f"\n{name}:")
        print(f"  Exposure: {defaults['exposure_ms']}ms")
        print(f"  Gain: {defaults['gain']}")
        print(f"  Bayer Pattern: {defaults['bayer_pattern']}")
        print(f"  White Balance: R={defaults['wb_r']}, B={defaults['wb_b']}")
        print(f"  Flip: {defaults['flip']}")
        print(f"  Offset: {defaults['offset']}")
    
    return profiles


def update_config(profiles):
    """Update config.json with new camera profiles"""
    print("\n=== Updating Config ===")
    
    config_dir = get_app_data_dir()
    config_path = os.path.join(config_dir, 'config.json')
    
    # Load existing config
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            print(f"✓ Loaded existing config from: {config_path}")
        except Exception as e:
            print(f"⚠ Error loading config: {e}")
            config = {}
    else:
        print("ℹ No existing config, will create new one")
    
    # Add/update camera profiles
    if 'camera_profiles' not in config:
        config['camera_profiles'] = {}
    
    for name, profile in profiles.items():
        config['camera_profiles'][name] = profile
        print(f"✓ Added profile for: {name}")
    
    # Save updated config
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"\n✓ Config saved to: {config_path}")
        return True
    except Exception as e:
        print(f"\n✗ Failed to save config: {e}")
        return False


def main():
    """Main script execution"""
    print("=" * 60)
    print("PFR Sentinel - Camera Settings Reset Script")
    print("=" * 60)
    print("\nThis script will reset all camera settings to safe defaults.")
    print("Each camera will get its own profile to prevent cross-contamination.")
    print("\n⚠ IMPORTANT: Close PFRSentinel before continuing!")
    print()
    
    # Confirm before proceeding
    response = input("Continue? [y/N]: ").strip().lower()
    if response != 'y':
        print("\nAborted.")
        return 1
    
    # Backup config
    backup_path = backup_config()
    if not backup_path:
        print("\n⚠ Warning: Could not backup config, but continuing anyway...")
    
    # Get SDK path from config or use default
    config_dir = get_app_data_dir()
    config_path = os.path.join(config_dir, 'config.json')
    sdk_path = 'ASICamera2.dll'  # Default
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                sdk_path = config.get('zwo_sdk_path', sdk_path)
        except:
            pass
    
    # Detect cameras
    cameras = detect_cameras(sdk_path)
    
    if not cameras:
        print("\n✗ No cameras detected!")
        print("\nTroubleshooting:")
        print("  1. Ensure cameras are connected via USB")
        print("  2. Check that ASICamera2.dll exists in app directory")
        print("  3. Try closing any other software using the cameras")
        return 1
    
    # Create profiles
    profiles = create_camera_profiles(cameras)
    
    # Update config
    if not update_config(profiles):
        print("\n✗ Failed to update config!")
        if backup_path:
            print(f"\nYou can restore from backup: {backup_path}")
        return 1
    
    # Success
    print("\n" + "=" * 60)
    print("✓ Camera settings reset complete!")
    print("=" * 60)
    print("\nWhat was done:")
    print(f"  • Detected {len(cameras)} camera(s)")
    print(f"  • Created {len(profiles)} camera profile(s)")
    print(f"  • Saved profiles to: {config_path}")
    if backup_path:
        print(f"  • Backup saved to: {backup_path}")
    
    print("\nNext steps:")
    print("  1. Start PFRSentinel")
    print("  2. Select each camera in the Capture tab")
    print("  3. Verify settings look correct")
    print("  4. Adjust settings as needed for each camera")
    print("\nEach camera now has its own settings profile!")
    print("Settings won't be shared between cameras anymore.")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAborted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
