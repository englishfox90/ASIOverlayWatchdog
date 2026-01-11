# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for PFR Sentinel v3.2.1
LEAN BUILD - Only includes packages actually used by production code

Required packages (from requirements.txt):
- PySide6, qfluentwidgets (UI)
- Pillow, numpy, opencv-python (Image processing)
- requests (HTTP/Discord)
- watchdog (File monitoring)
- pystray (System tray)
- zwoasi (ZWO camera - optional)
- onnxruntime (ML inference - lightweight)

EXCLUDED (ML/dev packages - NOT bundled):
- torch, torchvision (use ONNX models instead)
- scikit-learn, scipy, matplotlib, astropy
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# ============================================================================
# COLLECT REQUIRED PACKAGES
# ============================================================================

# --- qfluentwidgets (Fluent Design UI components) ---
try:
    fluent_datas, fluent_binaries, fluent_hiddenimports = collect_all('qfluentwidgets')
    print(f"✓ qfluentwidgets: {len(fluent_datas)} datas, {len(fluent_hiddenimports)} imports")
except Exception as e:
    print(f"⚠ qfluentwidgets: {e}")
    fluent_datas, fluent_binaries, fluent_hiddenimports = [], [], []

# --- requests (Discord webhooks, weather API) ---
try:
    requests_datas, requests_binaries, requests_hiddenimports = collect_all('requests')
    print(f"✓ requests: {len(requests_datas)} datas, {len(requests_hiddenimports)} imports")
except Exception as e:
    print(f"⚠ requests: {e}")
    requests_datas, requests_binaries, requests_hiddenimports = [], [], []

# --- jaraco (required by pkg_resources/setuptools) ---
try:
    jaraco_datas, jaraco_binaries, jaraco_hiddenimports = collect_all('jaraco')
    print(f"✓ jaraco: {len(jaraco_datas)} datas, {len(jaraco_hiddenimports)} imports")
except Exception as e:
    print(f"⚠ jaraco: {e}")
    jaraco_datas, jaraco_binaries, jaraco_hiddenimports = [], [], []

# --- pystray (system tray) ---
try:
    pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
    print(f"✓ pystray: {len(pystray_datas)} datas, {len(pystray_hiddenimports)} imports")
except Exception as e:
    print(f"⚠ pystray: {e}")
    pystray_datas, pystray_binaries, pystray_hiddenimports = [], [], []

# --- platformdirs (required by pkg_resources) ---
try:
    platformdirs_datas, platformdirs_binaries, platformdirs_hiddenimports = collect_all('platformdirs')
    print(f"✓ platformdirs: {len(platformdirs_datas)} datas, {len(platformdirs_hiddenimports)} imports")
except Exception as e:
    print(f"⚠ platformdirs: {e}")
    platformdirs_datas, platformdirs_binaries, platformdirs_hiddenimports = [], [], []

# --- onnxruntime (ML inference - lightweight, minimal collection) ---
try:
    # Only collect onnxruntime core, not all the tools/transformers
    from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
    onnx_datas = collect_data_files('onnxruntime')
    onnx_binaries = collect_dynamic_libs('onnxruntime')
    onnx_hiddenimports = ['onnxruntime', 'onnxruntime.capi', 'onnxruntime.capi._pybind_state']
    print(f"✓ onnxruntime: {len(onnx_datas)} datas, {len(onnx_hiddenimports)} imports")
except Exception as e:
    print(f"⚠ onnxruntime: {e}")
    onnx_datas, onnx_binaries, onnx_hiddenimports = [], [], []

# --- Python 3.13 critical: xml.parsers.expat binary ---
xml_binaries = []
try:
    dll_path = os.path.join(sys.base_prefix, 'DLLs')
    for pyd in ['pyexpat.pyd', '_elementtree.pyd']:
        pyd_path = os.path.join(dll_path, pyd)
        if os.path.exists(pyd_path):
            xml_binaries.append((pyd_path, '.'))
            print(f"✓ {pyd}: found")
except Exception as e:
    print(f"⚠ XML binaries: {e}")

# ============================================================================
# DATA FILES
# ============================================================================

added_files = [
    ('ASICamera2.dll', '.'),
    ('version.py', '.'),
    ('assets/app_icon.ico', 'assets'),
    ('assets/app_icon.png', 'assets'),
    # ML models (ONNX format for production)
    ('ml/models/roof_classifier_v1.onnx', 'ml/models'),
    ('ml/models/sky_classifier_v1.onnx', 'ml/models'),
]

# ============================================================================
# HIDDEN IMPORTS - Only what we actually use
# ============================================================================

hiddenimports = [
    # --- Core image processing ---
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageEnhance',
    'numpy',
    'cv2',
    
    # --- PySide6 (only modules we use) ---
    'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
    'PySide6.QtSvg', 'PySide6.QtXml',
    
    # --- Fluent Widgets ---
    'qfluentwidgets',
    
    # --- HTTP/Network ---
    'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
    'http.server', 'socketserver',
    
    # --- XML (Python 3.13 fix) ---
    'xml', 'xml.parsers', 'xml.parsers.expat',
    'xml.etree', 'xml.etree.ElementTree',
    
    # --- File monitoring ---
    'watchdog', 'watchdog.observers', 'watchdog.events',
    
    # --- System tray ---
    'pystray', 'pystray._base', 'pystray._util', 'pystray._win32',
    
    # --- ZWO Camera (optional, fails gracefully) ---
    'zwoasi',
    
    # --- Package management (Python 3.13 compatibility) ---
    'importlib.metadata', 'importlib.resources',
    'pkg_resources',
    'jaraco', 'jaraco.text', 'jaraco.context', 'jaraco.functools',
    'more_itertools', 'autocommand',
    'platformdirs',
    
    # --- App modules ---
    'services', 'services.config', 'services.logger', 'services.processor',
    'services.watcher', 'services.zwo_camera', 'services.camera_connection',
    'services.camera_calibration', 'services.camera_utils', 'services.cleanup',
    'services.color_balance', 'services.web_output', 'services.rtsp_output',
    'services.discord_alerts', 'services.headless_runner', 'services.weather',
    'services.ml_service', 'services.ascom_safety',
    'ui', 'ui.main_window', 'ui.theme', 'ui.components', 'ui.panels',
    'ui.controllers', 'ui.system_tray_qt',
    
    # --- ML modules ---
    'ml', 'ml.roof_classifier', 'ml.sky_classifier',
    'onnxruntime',
] + fluent_hiddenimports + requests_hiddenimports + jaraco_hiddenimports + pystray_hiddenimports + platformdirs_hiddenimports + onnx_hiddenimports

# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=fluent_binaries + requests_binaries + jaraco_binaries + pystray_binaries + platformdirs_binaries + onnx_binaries + xml_binaries,
    datas=added_files + fluent_datas + requests_datas + jaraco_datas + pystray_datas + platformdirs_datas + onnx_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # === CRITICAL: Exclude ML/heavy packages (use ONNX instead) ===
        'torch', 'torchvision', 'torchaudio',
        'onnx',  # onnx package (model format), NOT onnxruntime (inference)
        'tensorflow', 'keras',
        'sklearn', 'scikit-learn',
        'scipy',
        'pandas',
        'matplotlib', 'mpl_toolkits',
        'seaborn', 'plotly',
        'astropy',  # Only needed for FITS in dev mode
        'sympy',  # Not needed
        
        # === Exclude unused stdlib ===
        'tkinter', 'tk', 'tcl', '_tkinter',
        'ttkbootstrap',  # Old UI framework
        'IPython', 'jupyter', 'notebook',
        'pytest', 'unittest', 'doctest',
        'setuptools', 'wheel', 'pip', 'distutils',
        'lib2to3', 'pydoc', 'xmlrpc',
        
        # === Exclude unused PySide6 modules ===
        'PySide6.QtNetwork',
        'PySide6.QtWebEngine', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
        'PySide6.QtQml', 'PySide6.QtSql', 'PySide6.QtTest',
        'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSerialPort',
        'PySide6.QtSerialBus', 'PySide6.QtSensors', 'PySide6.QtTextToSpeech',
        'PySide6.QtHelp', 'PySide6.QtDesigner', 'PySide6.QtUiTools',
        'PySide6.QtPrintSupport', 'PySide6.QtConcurrent',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
        'PySide6.QtWebSockets', 'PySide6.QtHttpServer', 'PySide6.QtPositioning',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============================================================================
# BUILD
# ============================================================================

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
    upx=False,  # DISABLED - triggers antivirus false positives
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # DISABLED - triggers antivirus false positives
    upx_exclude=[],
    name='PFRSentinel',
)
