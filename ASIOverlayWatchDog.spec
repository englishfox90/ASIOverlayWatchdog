# -*- mode: python ; coding: utf-8 -*-
r"""
PyInstaller spec file for ASIOverlayWatchDog
Builds a windowed application (no console) with bundled resources

IMPORTANT: Always build from within the virtual environment!
    .\venv\Scripts\Activate.ps1
    pyinstaller --clean ASIOverlayWatchDog.spec

Or use the build script which handles this automatically:
    build_exe.bat

Build command:
    pyinstaller ASIOverlayWatchDog.spec

Output:
    dist/ASIOverlayWatchDog/ASIOverlayWatchDog.exe
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# Collect all data files and submodules from ttkbootstrap (themes, etc.)
try:
    ttkbootstrap_datas, ttkbootstrap_binaries, ttkbootstrap_hiddenimports = collect_all('ttkbootstrap')
    print(f"✓ Collected ttkbootstrap: {len(ttkbootstrap_datas)} data files, {len(ttkbootstrap_hiddenimports)} hidden imports")
except Exception as e:
    print(f"Warning: Could not collect ttkbootstrap: {e}")
    ttkbootstrap_datas = []
    ttkbootstrap_binaries = []
    ttkbootstrap_hiddenimports = []

# Additional data files to include
added_files = [
    ('ASICamera2.dll', '.'),  # ZWO ASI SDK library
    ('version.py', '.'),       # Version file
    ('app_icon.ico', '.'),     # Application icon
]

# Hidden imports (modules not automatically detected)
hiddenimports = [
    # Core dependencies
    'PIL._tkinter_finder',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageEnhance',
    'numpy',
    'cv2',
    
    # TTKBootstrap and all submodules
    'ttkbootstrap',
    'ttkbootstrap.themes',
    'ttkbootstrap.themes.standard',
    'ttkbootstrap.constants',
    'ttkbootstrap.style',
    'ttkbootstrap.window',
    'ttkbootstrap.widgets',
    'ttkbootstrap.tooltip',
    'ttkbootstrap.scrolled',
    'ttkbootstrap.dialogs',
    'ttkbootstrap.localization',
    'ttkbootstrap.colorutils',
    'ttkbootstrap.utility',
    'ttkbootstrap.icons',
    
    # ZWO camera
    'zwoasi',
    
    # Watchdog
    'watchdog',
    'watchdog.observers',
    'watchdog.events',
    
    # Services
    'services',
    'services.config',
    'services.logger',
    'services.processor',
    'services.watcher',
    'services.zwo_camera',
    'services.cleanup',
    'services.color_balance',
    'services.web_output',
    'services.rtsp_output',
    
    # GUI modules
    'gui',
    'gui.main_window',
    'gui.header',
    'gui.capture_tab',
    'gui.settings_tab',
    'gui.overlay_tab',
    'gui.preview_tab',
    'gui.logs_tab',
    'gui.theme',
    'gui.overlays',
    'gui.camera_controller',
    'gui.status_manager',
    'gui.image_processor',
    'gui.overlay_manager',
] + ttkbootstrap_hiddenimports

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=ttkbootstrap_binaries,
    datas=added_files + ttkbootstrap_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ASIOverlayWatchDog',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed application (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',  # Application icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ASIOverlayWatchDog',
)
