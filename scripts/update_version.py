"""
Generate version.iss from version.py for Inno Setup
Run this before building installer to sync versions
"""
import re
from pathlib import Path

# Determine project root (handle scripts/ directory)
script_dir = Path(__file__).parent
if script_dir.name == 'scripts':
    project_root = script_dir.parent
else:
    project_root = script_dir

# Read version from version.py
version_py = project_root / "version.py"
content = version_py.read_text()
match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)

if match:
    version = match.group(1)
    
    # Write version.iss
    version_iss = project_root / "version.iss"
    version_iss.write_text(f'; Auto-generated from version.py - DO NOT EDIT MANUALLY\n#define MyAppVersion "{version}"\n')
    
    print(f"✓ Generated version.iss with version {version}")
else:
    print("✗ Could not find version in version.py")
    exit(1)
