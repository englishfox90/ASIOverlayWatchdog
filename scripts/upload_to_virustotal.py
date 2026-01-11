"""
Upload PFR Sentinel installer to VirusTotal and get scan results
Requires VirusTotal API key (free account at virustotal.com)

Usage:
    python scripts/upload_to_virustotal.py
    python scripts/upload_to_virustotal.py --api-key YOUR_KEY_HERE
    python scripts/upload_to_virustotal.py --check-only SCAN_ID
"""

import os
import sys
import time
import hashlib
import requests
from pathlib import Path

# VirusTotal API v3 endpoints
VT_UPLOAD_URL = "https://www.virustotal.com/api/v3/files"
VT_ANALYSIS_URL = "https://www.virustotal.com/api/v3/analyses/{}"
VT_FILE_URL = "https://www.virustotal.com/api/v3/files/{}"

def get_api_key():
    """Get API key from environment or command line"""
    api_key = os.environ.get('VIRUSTOTAL_API_KEY')
    
    if '--api-key' in sys.argv:
        idx = sys.argv.index('--api-key')
        if idx + 1 < len(sys.argv):
            api_key = sys.argv[idx + 1]
    
    if not api_key:
        print("❌ VirusTotal API key not found!")
        print()
        print("Get a free API key at: https://www.virustotal.com/gui/join-us")
        print()
        print("Then set it via:")
        print("  1. Environment variable: set VIRUSTOTAL_API_KEY=your_key_here")
        print("  2. Command line: python upload_to_virustotal.py --api-key YOUR_KEY")
        sys.exit(1)
    
    return api_key

def calculate_sha256(file_path):
    """Calculate SHA-256 hash of file"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def check_existing_scan(api_key, file_hash):
    """Check if file already has a scan result"""
    headers = {"x-apikey": api_key}
    response = requests.get(VT_FILE_URL.format(file_hash), headers=headers)
    
    if response.status_code == 200:
        data = response.json()['data']['attributes']
        return {
            'found': True,
            'scan_date': data.get('last_analysis_date'),
            'stats': data.get('last_analysis_stats'),
            'permalink': f"https://www.virustotal.com/gui/file/{file_hash}"
        }
    return {'found': False}

def upload_file(api_key, file_path):
    """Upload file to VirusTotal"""
    print(f"📤 Uploading {os.path.basename(file_path)}...")
    
    # Check file size (free API has 32 MB limit)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > 32:
        print(f"⚠️  WARNING: File is {file_size_mb:.1f} MB")
        print(f"   Free VirusTotal API has 32 MB limit")
        print()
        print("Alternatives:")
        print("1. Use web upload: https://www.virustotal.com/gui/home/upload")
        print("2. Upload the standalone EXE instead (smaller):")
        print(f"   dist\\PFRSentinel\\PFRSentinel.exe")
        print()
        user_input = input("Try uploading via web API anyway? (y/n): ")
        if user_input.lower() != 'y':
            print("Cancelled. Please use web upload or standalone EXE.")
            sys.exit(0)
    
    headers = {"x-apikey": api_key}
    
    with open(file_path, 'rb') as f:
        files = {"file": (os.path.basename(file_path), f)}
        response = requests.post(VT_UPLOAD_URL, headers=headers, files=files)
    
    if response.status_code == 200:
        analysis_id = response.json()['data']['id']
        print(f"✓ Upload successful! Analysis ID: {analysis_id}")
        return analysis_id
    else:
        print(f"❌ Upload failed: {response.status_code}")
        print(response.text)
        sys.exit(1)

def wait_for_results(api_key, analysis_id, timeout=300):
    """Wait for scan to complete"""
    headers = {"x-apikey": api_key}
    start_time = time.time()
    
    print("⏳ Waiting for scan to complete (this can take 2-5 minutes)...")
    
    while time.time() - start_time < timeout:
        response = requests.get(VT_ANALYSIS_URL.format(analysis_id), headers=headers)
        
        if response.status_code == 200:
            data = response.json()['data']['attributes']
            status = data.get('status')
            
            if status == 'completed':
                return {
                    'stats': data.get('stats'),
                    'file_hash': data.get('meta', {}).get('file_info', {}).get('sha256')
                }
            
            # Show progress
            elapsed = int(time.time() - start_time)
            print(f"  Still scanning... ({elapsed}s elapsed)", end='\r')
            time.sleep(10)
        else:
            print(f"❌ Error checking status: {response.status_code}")
            print(response.text)
            sys.exit(1)
    
    print(f"❌ Timeout after {timeout}s")
    sys.exit(1)

def print_results(stats, file_hash):
    """Print scan results in a nice format"""
    malicious = stats.get('malicious', 0)
    suspicious = stats.get('suspicious', 0)
    undetected = stats.get('undetected', 0)
    harmless = stats.get('harmless', 0)
    total = malicious + suspicious + undetected + harmless
    
    permalink = f"https://www.virustotal.com/gui/file/{file_hash}"
    
    print()
    print("=" * 70)
    print("📊 VirusTotal Scan Results")
    print("=" * 70)
    print(f"Malicious:   {malicious:3d} / {total}")
    print(f"Suspicious:  {suspicious:3d} / {total}")
    print(f"Undetected:  {undetected:3d} / {total}")
    print(f"Harmless:    {harmless:3d} / {total}")
    print()
    
    if malicious == 0 and suspicious == 0:
        print("✅ CLEAN - No threats detected!")
    elif malicious <= 2:
        print("⚠️  LIKELY FALSE POSITIVE - Very few detections")
        print("   Common with unsigned PyInstaller executables")
    else:
        print("⚠️  WARNING - Multiple detections found")
    
    print()
    print("Full report: " + permalink)
    print("=" * 70)
    print()
    print("📋 Add this to your GitHub release notes:")
    print()
    print(f"**VirusTotal Scan Results:** [{malicious}/{total} detections]({permalink})")
    if malicious == 0:
        print("✅ Clean - No threats detected by any antivirus engine.")
    else:
        print("⚠️ False positive from unsigned executable. Safe to use.")
    print()

def main():
    # Check for --check-only flag
    if '--check-only' in sys.argv:
        idx = sys.argv.index('--check-only')
        if idx + 1 < len(sys.argv):
            analysis_id = sys.argv[idx + 1]
            api_key = get_api_key()
            results = wait_for_results(api_key, analysis_id)
            print_results(results['stats'], results['file_hash'])
            return
    
    # Check for --file flag
    file_to_scan = None
    if '--file' in sys.argv:
        idx = sys.argv.index('--file')
        if idx + 1 < len(sys.argv):
            file_to_scan = Path(sys.argv[idx + 1])
            if not file_to_scan.exists():
                print(f"❌ File not found: {file_to_scan}")
                sys.exit(1)
    
    # Find installer file if no file specified
    if not file_to_scan:
        installer_dir = Path(__file__).parent.parent / "installer" / "dist"
        installers = list(installer_dir.glob("PFR Sentinel-*.exe"))
        
        if not installers:
            print("❌ No installer found in installer/dist/")
            print("Run build_sentinel_installer.bat first")
            sys.exit(1)
        
        # Use most recent installer
        file_to_scan = max(installers, key=os.path.getctime)
    
    file_size_mb = os.path.getsize(file_to_scan) / (1024 * 1024)
    
    print()
    print("🔍 PFR Sentinel - VirusTotal Scanner")
    print("=" * 70)
    print(f"File: {file_to_scan.name}")
    print(f"Size: {file_size_mb:.1f} MB")
    print()
    
    # Get API key
    api_key = get_api_key()
    
    # Calculate hash and check for existing scan
    print("🔐 Calculating SHA-256 hash...")
    file_hash = calculate_sha256(file_to_scan)
    print(f"SHA-256: {file_hash}")
    print()
    
    existing = check_existing_scan(api_key, file_hash)
    if existing['found']:
        print("✓ File already scanned on VirusTotal!")
        print(f"  Last scan: {existing['scan_date']}")
        print()
        print_results(existing['stats'], file_hash)
        return
    
    # Upload file
    analysis_id = upload_file(api_key, file_to_scan)
    
    # Wait for results
    results = wait_for_results(api_key, analysis_id)
    
    # Print results
    print_results(results['stats'], results['file_hash'])

if __name__ == "__main__":
    main()
