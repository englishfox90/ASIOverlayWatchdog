# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for PFR Sentinel
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
- scikit-learn, matplotlib, astropy
(scipy IS bundled — required for all-sky fisheye calibration)
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# ============================================================================
# VERSION INFO - Read from version.py (single source of truth)
# ============================================================================

# Parse version from version.py
version_file = os.path.join(os.path.dirname(os.path.abspath(SPEC)), 'version.py')
version_str = "0.0.0"
try:
    with open(version_file, 'r') as f:
        for line in f:
            if line.startswith('__version__'):
                version_str = line.split('=')[1].strip().strip('"\'')
                break
    print(f"[OK] Version from version.py: {version_str}")
except Exception as e:
    print(f"[WARN] Could not read version.py: {e}")

# Parse version components (e.g., "3.2.3" -> (3, 2, 3, 0))
version_parts = version_str.split('.')
version_tuple = tuple(int(p) for p in version_parts[:3]) + (0,) * (4 - len(version_parts[:3]))

# Create Windows version info structure dynamically
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, 
    StringStruct, VarFileInfo, VarStruct
)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=version_tuple,
        prodvers=version_tuple,
        mask=0x3f,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0)
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040904B0',
                [
                    StringStruct('CompanyName', 'Paul Fox-Reeks'),
                    StringStruct('FileDescription', 'PFR Sentinel - Astrophotography Image Processor'),
                    StringStruct('FileVersion', f'{version_str}.0'),
                    StringStruct('InternalName', 'PFRSentinel'),
                    StringStruct('LegalCopyright', 'Copyright (c) 2024-2026 Paul Fox-Reeks'),
                    StringStruct('OriginalFilename', 'PFRSentinel.exe'),
                    StringStruct('ProductName', 'PFR Sentinel'),
                    StringStruct('ProductVersion', f'{version_str}.0'),
                ]
            )
        ]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])
    ]
)

print(f"[OK] Version info generated: {version_tuple}")

# ============================================================================
# COLLECT REQUIRED PACKAGES
# ============================================================================

# --- qfluentwidgets (Fluent Design UI components) ---
try:
    fluent_datas, fluent_binaries, fluent_hiddenimports = collect_all('qfluentwidgets')
    print(f"[OK] qfluentwidgets: {len(fluent_datas)} datas, {len(fluent_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] qfluentwidgets: {e}")
    fluent_datas, fluent_binaries, fluent_hiddenimports = [], [], []

# --- requests (Discord webhooks, weather API) ---
try:
    requests_datas, requests_binaries, requests_hiddenimports = collect_all('requests')
    print(f"[OK] requests: {len(requests_datas)} datas, {len(requests_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] requests: {e}")
    requests_datas, requests_binaries, requests_hiddenimports = [], [], []

# --- jaraco (required by pkg_resources/setuptools) ---
try:
    jaraco_datas, jaraco_binaries, jaraco_hiddenimports = collect_all('jaraco')
    print(f"[OK] jaraco: {len(jaraco_datas)} datas, {len(jaraco_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] jaraco: {e}")
    jaraco_datas, jaraco_binaries, jaraco_hiddenimports = [], [], []

# --- pystray (system tray) ---
try:
    pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
    print(f"[OK] pystray: {len(pystray_datas)} datas, {len(pystray_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] pystray: {e}")
    pystray_datas, pystray_binaries, pystray_hiddenimports = [], [], []

# --- platformdirs (required by pkg_resources) ---
try:
    platformdirs_datas, platformdirs_binaries, platformdirs_hiddenimports = collect_all('platformdirs')
    print(f"[OK] platformdirs: {len(platformdirs_datas)} datas, {len(platformdirs_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] platformdirs: {e}")
    platformdirs_datas, platformdirs_binaries, platformdirs_hiddenimports = [], [], []

# --- posthog (analytics) ---
try:
    posthog_datas, posthog_binaries, posthog_hiddenimports = collect_all('posthog')
    print(f"[OK] posthog: {len(posthog_datas)} datas, {len(posthog_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] posthog: {e}")
    posthog_datas, posthog_binaries, posthog_hiddenimports = [], [], []

# --- backoff (posthog dependency) ---
try:
    backoff_datas, backoff_binaries, backoff_hiddenimports = collect_all('backoff')
    print(f"[OK] backoff: {len(backoff_datas)} datas, {len(backoff_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] backoff: {e}")
    backoff_datas, backoff_binaries, backoff_hiddenimports = [], [], []

# --- Google API client (YouTube timelapse uploads) ---
google_packages = [
    'googleapiclient',
    'google_auth_oauthlib',
    'google.auth',
    'httplib2',
    'oauthlib',
    'requests_oauthlib',
    'uritemplate',
]
google_hidden_modules = [
]
google_datas, google_binaries, google_hiddenimports = [], [], []
for pkg in google_packages:
    try:
        datas, binaries, imports = collect_all(pkg)
        google_datas += datas
        google_binaries += binaries
        google_hiddenimports += imports
        print(f"[OK] {pkg}: {len(datas)} datas, {len(imports)} imports")
    except Exception as e:
        print(f"[WARN] {pkg}: {e}")

google_hiddenimports += google_hidden_modules

# --- scipy (all-sky lens calibration: optimize + spatial.distance + stats) ---
try:
    scipy_datas, scipy_binaries, scipy_hiddenimports = collect_all('scipy')
    print(f"[OK] scipy: {len(scipy_datas)} datas, {len(scipy_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] scipy: {e}")
    scipy_datas, scipy_binaries, scipy_hiddenimports = [], [], []

# --- onnxruntime (ML inference - lightweight, minimal collection) ---
try:
    # Only collect onnxruntime core, not all the tools/transformers
    from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
    onnx_datas = collect_data_files('onnxruntime')
    onnx_binaries = collect_dynamic_libs('onnxruntime')
    onnx_hiddenimports = ['onnxruntime', 'onnxruntime.capi', 'onnxruntime.capi._pybind_state']
    print(f"[OK] onnxruntime: {len(onnx_datas)} datas, {len(onnx_hiddenimports)} imports")
except Exception as e:
    print(f"[WARN] onnxruntime: {e}")
    onnx_datas, onnx_binaries, onnx_hiddenimports = [], [], []

# --- Python 3.13 critical: xml.parsers.expat binary ---
xml_binaries = []
try:
    dll_path = os.path.join(sys.base_prefix, 'DLLs')
    for pyd in ['pyexpat.pyd', '_elementtree.pyd']:
        pyd_path = os.path.join(dll_path, pyd)
        if os.path.exists(pyd_path):
            xml_binaries.append((pyd_path, '.'))
            print(f"[OK] {pyd}: found")
except Exception as e:
    print(f"[WARN] XML binaries: {e}")

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
    # All-sky overlay catalog data
    ('star_data/bsc5-short.json', 'star_data'),
    ('star_data/messier_list.json', 'star_data'),
    ('star_data/NGC.csv', 'star_data'),
    ('star_data/constellations.json', 'star_data'),
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

    # --- Analytics (PostHog) ---
    'posthog', 'posthog.client', 'posthog.consumer', 'posthog.request',
    'posthog.version', 'posthog.exception_capture', 'posthog.exception_utils',
    'posthog.feature_flags', 'posthog.poller', 'posthog.utils', 'posthog.types',
    'posthog.contexts', 'posthog.args', 'posthog.flag_definition_cache',
    'backoff', 'six', 'python_dateutil', 'dateutil', 'distro',

    # --- YouTube uploads / Google API client ---
    'googleapiclient', 'googleapiclient.discovery', 'googleapiclient.http',
    'googleapiclient.discovery_cache', 'googleapiclient.discovery_cache.documents',
    'google_auth_oauthlib', 'google_auth_oauthlib.flow',
    'google.auth', 'google.auth.transport.requests', 'google.auth.exceptions',
    'google.oauth2', 'google.oauth2.credentials',
    'httplib2', 'oauthlib', 'requests_oauthlib',
    'uritemplate',
    
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
    
    # --- Scipy (calibration) — full collection via collect_all above ---

    # --- All-sky overlay modules ---
    'services.allsky', 'services.allsky.coords', 'services.allsky.catalogs',
    'services.allsky.planets', 'services.allsky.fisheye',
    'services.allsky.calibration', 'services.allsky.star_centroid',
    'services.allsky.label_collision', 'services.allsky.overlay_renderer',
    'services.allsky.render_grid', 'services.allsky.render_constellations',
    'services.allsky.render_objects', 'services.allsky.config_schema',

    # --- App modules ---
    'services', 'services.config', 'services.logger', 'services.processor',
    'services.watcher', 'services.zwo_camera', 'services.camera_connection',
    'services.camera_calibration', 'services.camera_utils', 'services.cleanup',
    'services.color_balance', 'services.web_output',
    'services.discord_alerts', 'services.headless_runner', 'services.weather',
    'services.ml_service', 'services.ascom_safety', 'services.posthog_service',
    'services.youtube_auth', 'services.youtube_config', 'services.youtube_upload',
    'services.youtube_upload_state', 'services.timelapse_publishers',
    'ui', 'ui.main_window', 'ui.theme', 'ui.components', 'ui.panels',
    'ui.controllers', 'ui.system_tray_qt',
    
    # --- ML modules ---
    'ml', 'ml.roof_classifier', 'ml.sky_classifier',
    'onnxruntime',
] + fluent_hiddenimports + requests_hiddenimports + jaraco_hiddenimports + pystray_hiddenimports + platformdirs_hiddenimports + onnx_hiddenimports + posthog_hiddenimports + backoff_hiddenimports + scipy_hiddenimports + google_hiddenimports

# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=fluent_binaries + requests_binaries + jaraco_binaries + pystray_binaries + platformdirs_binaries + onnx_binaries + xml_binaries + posthog_binaries + backoff_binaries + scipy_binaries + google_binaries,
    datas=added_files + fluent_datas + requests_datas + jaraco_datas + pystray_datas + platformdirs_datas + onnx_datas + posthog_datas + backoff_datas + scipy_datas + google_datas,
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
        'pandas',
        'matplotlib', 'mpl_toolkits',
        'seaborn', 'plotly',
        'astropy',  # Only needed for FITS in dev mode — all-sky uses pure numpy
        # Note: scipy is intentionally NOT excluded (needed for calibration)
        'sympy',  # Not needed
        
        # === Exclude unused stdlib ===
        'tkinter', 'tk', 'tcl', '_tkinter',
        'ttkbootstrap',  # Old UI framework
        'IPython', 'jupyter', 'notebook',
        'pytest', 'doctest',
        # 'unittest' is NOT excluded — scipy imports it internally at runtime
        'setuptools', 'wheel', 'pip', 'distutils',
        'lib2to3',
        # 'pydoc', 'xmlrpc' — used transitively by scipy stdlib imports
        
        # === Exclude unused PySide6 modules ===
        # QtNetwork is NOT excluded — services/single_instance.py uses
        # QLocalServer/QLocalSocket for the single-instance guard.
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
    # Version info generated dynamically from version.py (helps AV heuristics)
    version=version_info,
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
