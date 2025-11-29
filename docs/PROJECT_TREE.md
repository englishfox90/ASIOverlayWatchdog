# AllSky Overlay Watchdog - Project Tree

```
ASIOverlayWatchDog/
│
├── 📁 gui/                         # Modern Modular GUI (9 files, ~1800 lines)
│   ├── __init__.py                # Package entry point
│   ├── main_window.py             # Main application + business logic (1024 lines)
│   ├── header.py                  # Status & live monitoring (87 lines)
│   ├── capture_tab.py             # Capture controls (218 lines)
│   ├── settings_tab.py            # Settings UI (153 lines)
│   ├── overlay_tab.py             # Overlay editor (185 lines)
│   ├── preview_tab.py             # Image preview (45 lines)
│   ├── logs_tab.py                # Log viewer (37 lines)
│   ├── overlay_list_item.py       # List widget (48 lines)
│   └── README.md                  # GUI architecture docs
│
├── 📁 services/                    # Core Processing Modules (6 files)
│   ├── __init__.py                # Services package
│   ├── config.py                  # Configuration management
│   ├── logger.py                  # Thread-safe logging
│   ├── processor.py               # Image overlay engine
│   ├── watcher.py                 # Directory monitoring
│   ├── zwo_camera.py              # ZWO ASI camera interface
│   └── cleanup.py                 # Disk space management
│
├── 📁 docs/                        # Documentation (5 files)
│   ├── README.md                  # Full documentation
│   ├── QUICKSTART.md              # Quick setup guide
│   ├── ZWO_SETUP_GUIDE.md         # Camera setup
│   ├── MODERNIZATION.md           # UI development notes
│   └── PROJECT_STRUCTURE.md       # Architecture overview
│
├── 📁 archive/                     # Legacy Code (2 files)
│   ├── gui_modern.py              # Previous monolithic GUI (1573 lines)
│   └── gui_new.py                 # Earlier GUI version
│
├── 📁 .github/                     # GitHub configuration
│   └── copilot-instructions.md    # AI agent instructions
│
├── 📄 main.py                      # Application entry point (8 lines)
├── 📄 config.json                  # Runtime configuration (auto-generated)
├── 📄 requirements.txt             # Python dependencies
├── 📄 start.bat                    # Windows quick-launch script
├── 📄 README.md                    # Project overview
├── 🔧 ASICamera2.dll               # ZWO ASI SDK library
│
└── 📁 venv/                        # Python virtual environment (auto-generated)
```

## File Statistics

### Before Refactoring
- **1 monolithic file**: `gui_modern.py` (1573 lines)
- All code in root directory
- No organized documentation

### After Refactoring
- **GUI**: 9 modular files (37-1024 lines each, avg 200 lines)
- **Services**: 6 backend modules with clear responsibilities
- **Docs**: 5 organized documentation files
- **Archive**: 2 legacy files preserved for reference

### Lines of Code Distribution
```
GUI Package:          ~1800 lines (9 files, avg 200 lines/file)
Services Package:     ~1200 lines (6 files, avg 200 lines/file)
Documentation:        ~800 lines (5 markdown files)
Legacy (archived):    ~2500 lines (2 files, not used)
Total Active Code:    ~3000 lines in 15 modular files
```

## Quick Navigation

- **Start Here**: [README.md](../README.md)
- **Get Started**: [docs/QUICKSTART.md](QUICKSTART.md)
- **GUI Details**: [gui/README.md](../gui/README.md)
- **Architecture**: [docs/PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- **Camera Setup**: [docs/ZWO_SETUP_GUIDE.md](ZWO_SETUP_GUIDE.md)

## Color Key

📁 Folder/Package  
📄 Code File  
🔧 Binary/DLL  
📝 Documentation
