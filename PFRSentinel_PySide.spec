# -*- mode: python ; coding: utf-8 -*-
r"""
PyInstaller spec file for PFR Sentinel (PySide6 UI)
Builds a windowed application with modern Fluent design

Build command:
    pyinstaller PFRSentinel_PySide.spec

Output:
    dist/PFRSentinel/PFRSentinel.exe
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# Collect PySide6 and FluentWidgets
try:
    pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all('PySide6')
    print(f"✓ Collected PySide6: {len(pyside6_datas)} data files, {len(pyside6_hiddenimports)} hidden imports")
except Exception as e:
    print(f"Warning: Could not collect PySide6: {e}")
    pyside6_datas = []
    pyside6_binaries = []
    pyside6_hiddenimports = []

try:
    fluent_datas, fluent_binaries, fluent_hiddenimports = collect_all('qfluentwidgets')
    print(f"✓ Collected qfluentwidgets: {len(fluent_datas)} data files, {len(fluent_hiddenimports)} hidden imports")
except Exception as e:
    print(f"Warning: Could not collect qfluentwidgets: {e}")
    fluent_datas = []
    fluent_binaries = []
    fluent_hiddenimports = []

# Collect requests for Discord webhooks
try:
    requests_datas, requests_binaries, requests_hiddenimports = collect_all('requests')
    print(f"✓ Collected requests: {len(requests_datas)} data files, {len(requests_hiddenimports)} hidden imports")
except Exception as e:
    print(f"Warning: Could not collect requests: {e}")
    requests_datas = []
    requests_binaries = []
    requests_hiddenimports = []

# Additional data files to include
added_files = [
    ('ASICamera2.dll', '.'),           # ZWO ASI SDK library
    ('version.py', '.'),                # Version file
    ('assets/app_icon.ico', 'assets'), # Application icon
    ('assets/app_icon.png', 'assets'), # PNG icon for tray
]

# Hidden imports (modules not automatically detected)
hiddenimports = [
    # Core dependencies
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageEnhance',
    'numpy',
    'cv2',
    
    # PySide6 modules
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    
    # Fluent Widgets
    'qfluentwidgets',
    
    # HTTP requests (for Discord webhooks)
    'requests',
    'requests.adapters',
    'requests.auth',
    'requests.cookies',
    'requests.exceptions',
    'requests.models',
    'requests.sessions',
    'requests.structures',
    'requests.utils',
    'urllib3',
    'urllib3.util',
    'urllib3.util.retry',
    'urllib3.util.ssl_',
    'urllib3.connectionpool',
    'urllib3.poolmanager',
    'certifi',
    'charset_normalizer',
    'idna',
    
    # ZWO camera
    'zwoasi',
    
    # Watchdog
    'watchdog',
    'watchdog.observers',
    'watchdog.events',
    
    # Services (shared backend)
    'services',
    'services.config',
    'services.logger',
    'services.processor',
    'services.watcher',
    'services.zwo_camera',
    'services.camera_connection',
    'services.camera_calibration',
    'services.camera_utils',
    'services.cleanup',
    'services.color_balance',
    'services.web_output',
    'services.rtsp_output',
    'services.discord_alerts',
    'services.headless_runner',
    'services.weather',
    
    # UI modules (PySide6)
    'ui',
    'ui.main_window',
    'ui.theme',
    'ui.components',
    'ui.panels',
    'ui.controllers',
    'ui.system_tray_qt',
    
    # System tray
    'pystray',
] + pyside6_hiddenimports + fluent_hiddenimports + requests_hiddenimports

a = Analysis(
    ['main_pyside.py'],
    pathex=[],
    binaries=pyside6_binaries + fluent_binaries + requests_binaries,
    datas=added_files + pyside6_datas + fluent_datas + requests_datas,
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
    name='PFRSentinel',
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
    icon='assets/app_icon.ico',  # Application icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PFRSentinel',
)
