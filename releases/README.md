# Release Builds

This folder contains **production-ready installer builds** for distribution.

## What Goes Here

✅ **Final release installers** (committed to Git for easy downloads)
- `ASIOverlayWatchDog-v2.0.0-Setup.exe` (if using Inno Setup or NSIS)
- `ASIOverlayWatchDog-v2.0.0-Portable.zip` (portable version)
- `ASIOverlayWatchDog-v2.0.0.msi` (if using Windows Installer)

## What's Included in Release Builds

Each release should be **completely self-contained**:

✅ **Bundled Components:**
- Python runtime (embedded via PyInstaller)
- All Python dependencies (Pillow, ttkbootstrap, OpenCV, NumPy, etc.)
- ZWO ASI SDK (`ASICamera2.dll`)
- All GUI themes and assets
- Default configuration template

✅ **User Requirements:**
- Windows 7 or later (64-bit recommended)
- ZWO ASI camera (for camera capture mode)
- **Optional:** ffmpeg (for RTSP streaming mode only)

❌ **NOT Required:**
- Python installation
- pip or package managers
- Visual C++ redistributables (Python runtime is embedded)
- Manual DLL downloads

## Creating a Release Build

### Step 1: Build with PyInstaller

```powershell
# From project root with venv activated
.\venv\Scripts\Activate.ps1
pyinstaller --clean ASIOverlayWatchDog.spec
```

Output: `dist/ASIOverlayWatchDog/` folder with all files

### Step 2: Create Portable ZIP (Simplest)

```powershell
# Navigate to dist folder
cd dist

# Create ZIP archive
Compress-Archive -Path ASIOverlayWatchDog -DestinationPath ..\releases\ASIOverlayWatchDog-v2.0.0-Portable.zip
```

**Usage:** User extracts ZIP anywhere, runs `ASIOverlayWatchDog.exe`

### Step 3: Create Installer (Advanced - Optional)

Use **Inno Setup** for a professional Windows installer:

1. Install Inno Setup: https://jrsoftware.org/isinfo.php
2. Create/use `installer/setup.iss` script
3. Compile to `.exe` installer
4. Copy output to `releases/ASIOverlayWatchDog-v2.0.0-Setup.exe`

**Benefits:**
- Start Menu shortcuts
- Desktop icon
- Uninstaller
- Version tracking
- Professional appearance

## Testing Releases

Before committing to Git:

1. **Test on clean machine** (no Python, no dev tools)
2. **Verify no console popup** (windowed application)
3. **Check logs go to APPDATA** (`%APPDATA%\ASIOverlayWatchDog\logs`)
4. **Test camera detection** (with ZWO camera connected)
5. **Test all output modes** (File, Webserver, RTSP if ffmpeg available)
6. **Verify file size** (~50-80MB for portable ZIP)

## Version Naming Convention

Use semantic versioning:
- `ASIOverlayWatchDog-v2.0.0-Portable.zip` - Major.Minor.Patch
- `ASIOverlayWatchDog-v2.1.0-Setup.exe` - Minor version bump for new features
- `ASIOverlayWatchDog-v2.0.1-Portable.zip` - Patch version for bug fixes

## GitHub Releases

When ready to publish:

1. Commit the release file(s) to `releases/` folder
2. Create a Git tag: `git tag v2.0.0`
3. Push with tags: `git push origin main --tags`
4. On GitHub: Create release from tag, attach installer as binary
5. Write release notes documenting changes

## What Users Download

**Portable Version (Recommended):**
```
ASIOverlayWatchDog-v2.0.0-Portable.zip
├── ASIOverlayWatchDog.exe          (main executable)
├── ASICamera2.dll                  (ZWO SDK - REQUIRED)
├── _internal/                      (Python runtime + dependencies)
└── README.txt                      (quick start guide)
```

**First Run:**
- User extracts ZIP to any folder (e.g., `C:\ASIWatchdog\`)
- Double-clicks `ASIOverlayWatchDog.exe`
- Application creates `config.json` in same folder
- Logs go to `%APPDATA%\ASIOverlayWatchDog\logs`

---

**Current Status:** Ready for v2.0.0 release build
