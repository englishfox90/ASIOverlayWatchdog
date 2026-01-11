# VirusTotal Scanning for Release Builds

## Why Scan with VirusTotal?

Windows Defender and other antivirus software often flag **unsigned** PyInstaller executables as potentially malicious. This is a **false positive** because:

1. The executable is not digitally signed (code signing costs $200-500/year)
2. PyInstaller bundles Python into the executable, which looks suspicious to heuristic scanners
3. New releases don't have download reputation yet

VirusTotal scans your installer with **70+ antivirus engines** and provides a shareable report link you can include in GitHub releases to prove it's safe.

## Quick Start

### 1. Get a Free VirusTotal API Key

1. Go to https://www.virustotal.com/gui/join-us
2. Sign up for a free account
3. Navigate to your profile → API Key
4. Copy your API key

### 2. Set Your API Key

```powershell
# Option A: Set environment variable (persists in session)
$env:VIRUSTOTAL_API_KEY = "your_api_key_here"

# Option B: Pass on command line (one-time)
python scripts\upload_to_virustotal.py --api-key your_api_key_here
```

### 3. Build and Scan

```powershell
# Build the installer
.\build_sentinel_installer.bat

# Upload to VirusTotal and get results
python scripts\upload_to_virustotal.py
```

## Output Example

```
🔍 PFR Sentinel - VirusTotal Scanner
======================================================================
File: PFR Sentinel-3.1.3-setup.exe
Size: 127.3 MB

🔐 Calculating SHA-256 hash...
SHA-256: a1b2c3d4e5f6...

📤 Uploading PFR Sentinel-3.1.3-setup.exe...
✓ Upload successful! Analysis ID: abc123...

⏳ Waiting for scan to complete (this can take 2-5 minutes)...

======================================================================
📊 VirusTotal Scan Results
======================================================================
Malicious:     2 / 72
Suspicious:    0 / 72
Undetected:   45 / 72
Harmless:     25 / 72

⚠️  LIKELY FALSE POSITIVE - Very few detections
   Common with unsigned PyInstaller executables

Full report: https://www.virustotal.com/gui/file/a1b2c3d4e5f6...
======================================================================

📋 Add this to your GitHub release notes:

**VirusTotal Scan Results:** [2/72 detections](https://www.virustotal.com/gui/file/a1b2c3d4e5f6...)
⚠️ False positive from unsigned executable. Safe to use.
```

## Adding Results to GitHub Release

Copy the generated markdown to your release notes:

```markdown
## Download

- **Installer:** PFR Sentinel-3.1.3-setup.exe

### Security Notice

**VirusTotal Scan Results:** [2/72 detections](https://www.virustotal.com/gui/file/...)
⚠️ **False positive** - This is a common issue with unsigned Python executables.

The detections are from heuristic analysis (behavioral patterns), not actual malware signatures. 
The application is open source and safe to use. If you're concerned:
- Check the [full VirusTotal report](https://www.virustotal.com/gui/file/...)
- Build from source using `build_sentinel_installer.bat`
- Review the source code in this repository
```

## Understanding False Positives

### Why Do They Happen?

1. **No Code Signature** - We don't pay for a code signing certificate ($200-500/year)
2. **PyInstaller Patterns** - Bundled Python executables trigger heuristics
3. **UPX Compression** - ~~Executable compression~~ (now disabled in v3.1.3+)
4. **Low Reputation** - New releases haven't been downloaded enough times

### What's Normal?

- **0-5 detections:** Excellent - typical for open source projects
- **5-10 detections:** Good - mostly generic heuristics
- **10+ detections:** Investigate - might be a real issue or overly aggressive scanners

### Which Engines Matter?

**Trust these engines most:**
- Microsoft Defender
- Kaspersky
- Bitdefender
- ESET-NOD32
- Avast/AVG
- McAfee

**Less reliable (many false positives):**
- Generic ML-based engines
- Lesser-known antivirus products
- Cloud-based heuristics

## Changes in v3.1.3

To reduce false positives, we:
1. **Disabled UPX compression** - UPX is a major trigger for antivirus heuristics
2. **Excluded unused modules** - Reduced attack surface by removing unnecessary PySide6 components
3. **Added VirusTotal scanning** - Automated scanning to prove safety

## Alternatives to VirusTotal

If you don't want to use VirusTotal:

1. **Build from source** - Use `build_sentinel_installer.bat` to build it yourself
2. **Check source code** - Review the Python code in this repository
3. **Windows Defender exclusion** - Add `c:\Program Files\PFRSentinel\` to exclusions (after verifying source)

## Troubleshooting

### API Rate Limits

Free accounts: **4 requests/minute**, **500 requests/day**

If you hit the limit, wait 1 minute and try again.

### File Already Scanned

If you rebuild with the exact same version number, VirusTotal will return the cached results. Increment the version number in `version.py` to force a new scan.

### Upload Fails

- Check your internet connection
- Verify API key is correct
- Ensure file size < 650 MB (VirusTotal limit)

## Resources

- [VirusTotal API Documentation](https://developers.virustotal.com/reference/overview)
- [PyInstaller False Positives](https://pyinstaller.org/en/stable/operating-mode.html#anti-virus-software)
- [Code Signing Guide](CODE_SIGNING.md)
