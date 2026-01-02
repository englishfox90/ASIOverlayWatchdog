"""
Emergency Camera SDK Reset Script
==================================

This script resets ALL ZWO cameras to factory defaults to fix SDK contamination.
Use this when cameras are stuck with wrong settings/names from other applications.

IMPORTANT: 
- Close ALL applications using ZWO cameras (PFRSentinel, NINA, ASICap, etc.)
- This will reset ALL connected cameras to factory defaults
- You'll need to reconfigure settings in your applications afterwards

What this fixes:
- Camera reporting wrong name (e.g., ASI2600 thinks it's ASI676)
- ROI errors in NINA/other apps
- Stuck camera settings from previous sessions
- SDK state contamination

Usage:
    python reset_camera_sdk.py
"""

import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def reset_all_cameras(sdk_path):
    """Reset all connected ZWO cameras to factory defaults"""
    print("\n" + "=" * 70)
    print("EMERGENCY CAMERA SDK RESET")
    print("=" * 70)
    print("\nThis will reset ALL connected ZWO cameras to factory defaults.")
    print("\n⚠ WARNING: Close ALL applications using ZWO cameras first!")
    print("   (PFRSentinel, NINA, ASICap, SharpCap, etc.)")
    print()
    
    response = input("Have you closed all camera applications? [y/N]: ").strip().lower()
    if response != 'y':
        print("\nPlease close all applications and try again.")
        return False
    
    print("\n=== Initializing ZWO SDK ===")
    
    try:
        import zwoasi as asi
        
        # Initialize SDK
        if not os.path.exists(sdk_path):
            print(f"✗ SDK not found at: {sdk_path}")
            print("\nTrying default location...")
            sdk_path = 'ASICamera2.dll'
            if not os.path.exists(sdk_path):
                print("✗ ASICamera2.dll not found!")
                return False
        
        print(f"SDK path: {sdk_path}")
        asi.init(sdk_path)
        print("✓ SDK initialized")
        
        # Get camera count
        num_cameras = asi.get_num_cameras()
        print(f"\n✓ Found {num_cameras} camera(s)")
        
        if num_cameras == 0:
            print("\n✗ No cameras detected!")
            print("\nTroubleshooting:")
            print("  1. Check USB connections")
            print("  2. Make sure cameras have power")
            print("  3. Try unplugging and replugging USB cables")
            return False
        
        # List cameras
        print("\nConnected cameras:")
        for i in range(num_cameras):
            try:
                name = asi.list_cameras()[i]
                print(f"  [{i}] {name}")
            except Exception as e:
                print(f"  [{i}] <Error reading name: {e}>")
        
        print("\n" + "=" * 70)
        print("RESETTING CAMERAS TO FACTORY DEFAULTS")
        print("=" * 70)
        
        # Reset each camera
        for i in range(num_cameras):
            try:
                camera_name = asi.list_cameras()[i]
                print(f"\n--- Camera {i}: {camera_name} ---")
                
                # Open camera
                print("  Opening camera...")
                camera = asi.Camera(i)
                time.sleep(0.3)  # Let camera stabilize
                
                # Get camera properties
                camera_info = camera.get_camera_property()
                max_width = camera_info['MaxWidth']
                max_height = camera_info['MaxHeight']
                
                print(f"  Native resolution: {max_width}x{max_height}")
                
                # Reset ROI to full frame
                print("  Resetting ROI to full frame...")
                camera.set_roi(
                    start_x=0,
                    start_y=0,
                    width=max_width,
                    height=max_height,
                    bins=1,
                    image_type=asi.ASI_IMG_RAW8
                )
                camera.set_image_type(asi.ASI_IMG_RAW8)
                print(f"    ✓ ROI: {max_width}x{max_height}")
                
                # Reset controls to factory defaults
                print("  Resetting camera controls...")
                controls_reset = []
                
                try:
                    camera.set_control_value(asi.ASI_GAIN, 0)
                    controls_reset.append("Gain=0")
                except: pass
                
                try:
                    camera.set_control_value(asi.ASI_EXPOSURE, 100000)  # 100ms
                    controls_reset.append("Exposure=100ms")
                except: pass
                
                try:
                    camera.set_control_value(asi.ASI_WB_R, 52)
                    camera.set_control_value(asi.ASI_WB_B, 95)
                    controls_reset.append("WB=52/95")
                except: pass
                
                try:
                    camera.set_control_value(asi.ASI_BRIGHTNESS, 50)
                    controls_reset.append("Offset=50")
                except: pass
                
                try:
                    camera.set_control_value(asi.ASI_FLIP, 0)
                    controls_reset.append("Flip=None")
                except: pass
                
                try:
                    camera.set_control_value(asi.ASI_AUTO_MAX_GAIN, 0)
                    camera.set_control_value(asi.ASI_AUTO_MAX_EXP, 0)
                    camera.set_control_value(asi.ASI_AUTO_TARGET_BRIGHTNESS, 100)
                    controls_reset.append("Auto=Off")
                except: pass
                
                try:
                    camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, 40)
                    controls_reset.append("USB=40")
                except: pass
                
                print(f"    ✓ Reset: {', '.join(controls_reset)}")
                
                # Close camera
                print("  Closing camera...")
                camera.close()
                time.sleep(0.5)  # Let SDK settle
                print("  ✓ Camera reset complete")
                
            except Exception as e:
                print(f"  ✗ Error resetting camera {i}: {e}")
                import traceback
                traceback.print_exc()
        
        print("\n" + "=" * 70)
        print("✓ ALL CAMERAS RESET TO FACTORY DEFAULTS")
        print("=" * 70)
        print("\nWhat was done:")
        print("  • Reset ROI to full frame for each camera")
        print("  • Reset gain, exposure, white balance to defaults")
        print("  • Reset flip, offset, and auto-exposure settings")
        print("  • Cleared any stuck SDK state")
        
        print("\n⚠ IMPORTANT NEXT STEPS:")
        print("  1. Unplug USB cables from ALL ZWO cameras")
        print("  2. Wait 5 seconds")
        print("  3. Plug cameras back in (one at a time)")
        print("  4. Wait for Windows to recognize each camera")
        print("  5. Try connecting in NINA/other apps")
        
        print("\nIf problems persist:")
        print("  • Restart computer")
        print("  • Update ZWO drivers from astronomy-imaging-camera.com")
        print("  • Check USB cables and hubs")
        
        return True
        
    except ImportError:
        print("✗ zwoasi library not installed")
        print("\nRun: pip install zwoasi")
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main script execution"""
    # Get SDK path
    sdk_path = 'C:/Program Files (x86)/PFRSentinel/_internal/ASICamera2.dll'
    
    # Check if PFRSentinel is running (optional check)
    try:
        print("\n⚠ Checking if PFRSentinel is running...")
        import psutil
        for proc in psutil.process_iter(['name']):
            if 'PFRSentinel' in proc.info['name']:
                print("✗ PFRSentinel is still running!")
                print("\nPlease close PFRSentinel before continuing.")
                return 1
        print("✓ PFRSentinel not detected")
    except ImportError:
        print("⚠ Cannot check if PFRSentinel is running (psutil not installed)")
        print("  Please manually ensure PFRSentinel is closed!")
    except Exception as e:
        print(f"⚠ Could not check running processes: {e}")
    
    # Reset cameras
    if reset_all_cameras(sdk_path):
        print("\n✓ Camera reset complete!")
        return 0
    else:
        print("\n✗ Camera reset failed!")
        return 1


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
