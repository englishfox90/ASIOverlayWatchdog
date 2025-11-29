# Installer Directory

This directory contains the Inno Setup installer configuration for ASIOverlayWatchDog.

## Files

- **`ASIOverlayWatchDog.iss`** - Inno Setup script (source)
- **`dist/`** - Generated installer output directory (created by build)

## Build Installer

### Quick Build (Recommended)
From project root:
```batch
build_installer.bat
```

This will:
1. Build the executable with PyInstaller
2. Create the installer with Inno Setup
3. Output to `installer/dist/ASIOverlayWatchDog-2.0.0-setup.exe`

### Manual Build
```batch
# From project root
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\ASIOverlayWatchDog.iss
```

## Requirements

- **Inno Setup 6.0+** 
  - Download: https://jrsoftware.org/isinfo.php
  - Install to default location: `C:\Program Files (x86)\Inno Setup 6\`

- **PyInstaller executable build**
  - Must exist at: `dist\ASIOverlayWatchDog\ASIOverlayWatchDog.exe`
  - Build with: `build_exe.bat`

## Output

Installer will be created at:
```
installer\dist\ASIOverlayWatchDog-2.0.0-setup.exe
```

## Installer Features

- **Install Location**: `C:\Program Files\ASIOverlayWatchDog\`
- **Start Menu**: Shortcut automatically created
- **Desktop**: Optional shortcut (user choice during install)
- **Upgrade Support**: Automatically uninstalls old version
- **Logs Preserved**: User logs in `%LOCALAPPDATA%` never deleted
- **Uninstall**: Removes Program Files, keeps logs

## Testing

1. **Fresh Install**:
   ```batch
   installer\dist\ASIOverlayWatchDog-2.0.0-setup.exe
   ```

2. **Verify**:
   - Application in `C:\Program Files\ASIOverlayWatchDog\`
   - Start Menu shortcut exists
   - Desktop shortcut (if selected)
   - Logs in `%LOCALAPPDATA%\ASIOverlayWatchDog\Logs\`

3. **Upgrade Test**:
   - Update `version.py`
   - Rebuild installer
   - Run new installer
   - Old version auto-uninstalled
   - Logs preserved

## Customization

Edit `ASIOverlayWatchDog.iss` to:
- Change installation directory
- Add/remove shortcuts
- Modify installer appearance
- Add custom setup messages
- Include additional files

## Version Updates

When releasing new version:
1. Update `version.py` in project root
2. Update `#define MyAppVersion` in `ASIOverlayWatchDog.iss`
3. Rebuild: `build_installer.bat`

## Troubleshooting

**Inno Setup not found**:
- Install from https://jrsoftware.org/isinfo.php
- Or update path in `build_installer.bat`

**Source files not found**:
- Run `build_exe.bat` first
- Verify `dist\ASIOverlayWatchDog\` exists

**Installer fails to run**:
- Check Windows SmartScreen settings
- Run as administrator if needed
