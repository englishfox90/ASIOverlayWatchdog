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

# Collect PySide6 - ONLY modules we actually use to reduce size
# We only need QtCore, QtGui, QtWidgets, QtSvg
try:
    # Collect only the modules we use instead of everything
    from PyInstaller.utils.hooks import collect_submodules
    
    # Only collect these specific PySide6 modules
    pyside6_modules = [
        'PySide6.QtCore',
        'PySide6.QtGui', 
        'PySide6.QtWidgets',
        'PySide6.QtSvg',  # Used by qfluentwidgets for icons
        'PySide6.QtXml',  # Used by qfluentwidgets for color dialogs
    ]
    
    pyside6_hiddenimports = []
    for module in pyside6_modules:
        pyside6_hiddenimports.extend(collect_submodules(module))
    
    # Get the data files and binaries only for modules we use
    pyside6_datas = []
    pyside6_binaries = []
    
    # Manually collect only essential PySide6 binaries
    import os
    import site
    site_packages = site.getsitepackages()[0]
    pyside6_path = os.path.join(site_packages, 'PySide6')
    
    if os.path.exists(pyside6_path):
        # Only include DLLs for modules we actually use
        essential_dlls = [
            'Qt6Core.dll',
            'Qt6Gui.dll', 
            'Qt6Widgets.dll',
            'Qt6Svg.dll',
            'Qt6Xml.dll',
        ]
        for dll in essential_dlls:
            dll_path = os.path.join(pyside6_path, dll)
            if os.path.exists(dll_path):
                pyside6_binaries.append((dll_path, 'PySide6'))
        
        # Include plugins folder (only what we need)
        plugins_path = os.path.join(pyside6_path, 'plugins')
        if os.path.exists(plugins_path):
            # Only include essential platform and icon plugins
            for subdir in ['platforms', 'styles', 'iconengines', 'imageformats']:
                subdir_path = os.path.join(plugins_path, subdir)
                if os.path.exists(subdir_path):
                    for root, dirs, files in os.walk(subdir_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(file_path, pyside6_path)
                            pyside6_datas.append((file_path, os.path.join('PySide6', os.path.dirname(rel_path))))
    
    print(f"✓ Collected PySide6: {len(pyside6_datas)} data files, {len(pyside6_binaries)} binaries, {len(pyside6_hiddenimports)} hidden imports")
except Exception as e:
    print(f"Warning: Could not collect PySide6: {e}")
    import traceback
    traceback.print_exc()
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

# Collect email module (required by http.server)
try:
    email_hiddenimports = collect_submodules('email')
    # CRITICAL: Python 3.13 + PyInstaller bug - email module not auto-included
    # Must manually copy email package as data files
    import email as email_module
    import os
    email_pkg_path = os.path.dirname(email_module.__file__)
    email_datas = []
    for root, dirs, files in os.walk(email_pkg_path):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, os.path.dirname(email_pkg_path))
                email_datas.append((file_path, os.path.dirname(rel_path)))
    print(f"✓ Collected email: {len(email_hiddenimports)} modules, {len(email_datas)} data files")
except Exception as e:
    print(f"Warning: Could not collect email: {e}")
    email_hiddenimports = []
    email_datas = []

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
    'PySide6.QtXml',
    
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
    
    # HTTP server (for web output)
    'http.server',
    'socketserver',
    'html',
    'html.parser',
    
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
] + pyside6_hiddenimports + fluent_hiddenimports + requests_hiddenimports + email_hiddenimports

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=pyside6_binaries + fluent_binaries + requests_binaries,
    datas=added_files + pyside6_datas + fluent_datas + requests_datas + email_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'tk',
        'tcl',
        '_tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'setuptools',
        'wheel',
        'pip',
        'distutils',
        'lib2to3',
        'email',  # Only keep what requests needs
        'xmlrpc',
        'pydoc',
        'doctest',
        'unittest',
        'xml.dom',
        'xml.sax',
        'xml.parsers.expat',
        # PySide6 modules we don't use (reduces build size significantly)
        'PySide6.QtNetwork',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3D',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DExtras',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQuickControls2',
        'PySide6.QtQml',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtXml',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtSerialPort',
        'PySide6.QtSerialBus',
        'PySide6.QtSensors',
        'PySide6.QtTextToSpeech',
        'PySide6.QtHelp',
        'PySide6.QtDesigner',
        'PySide6.QtUiTools',
        'PySide6.QtPrintSupport',
        'PySide6.QtConcurrent',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtStateMachine',
        'PySide6.QtWebSockets',
        'PySide6.QtHttpServer',
    ],
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
    upx=True,  # Compress executable
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
    upx=True,  # Compress DLLs and binaries
    upx_exclude=[
        # Don't compress these (may cause issues or no benefit)
        'vcruntime140.dll',
        'python*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
        'ASICamera2.dll',  # Camera driver - don't compress
    ],
    name='PFRSentinel',
)
