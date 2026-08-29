"""Install / update / remove the bundled NINA plugin DLL.

NINA loads plugins from ``%LOCALAPPDATA%\\NINA\\Plugins\\<version>\\<PluginName>\\``.

**The version in that path is NOT NINA's own version.** It is
``PluginMinimumApplicationVersion`` — the plugin compatibility baseline, which
has stayed ``3.0.0`` across the whole NINA 3.x line. Verified on a 3.3.0.1057
install whose 25 plugins all live in ``Plugins\\3.0.0\\``: neither NINA's
FileVersion (``3.3.0\\``) nor "the highest existing folder" points there.
Taking the highest is actively wrong — an older build that read ``NINA.exe``'s
four-part FileVersion once created a stray ``Plugins\\3.2.0.9001\\`` folder;
being numerically higher than ``3.0.0`` it then wins "take highest" forever,
so every install lands in a folder NINA never scans — a silent no-op.

So the folder is resolved by finding **where NINA's other plugins already
live**: the version folder hosting the most non-PFRSentinel plugin subfolders
(see :func:`resolve_plugin_api_version`), defaulting to
:data:`DEFAULT_PLUGIN_API_VERSION` on a fresh NINA that has no plugins yet.
A copy stranded under the old folder then shows up as *stale* and is swept by
Remove / superseded on the next install.

No sidecar JSON is written: the C# plugin reads
``%LOCALAPPDATA%\\PFRSentinel\\config.json`` directly for host/port/token, the
same zero-config pairing ``scripts/nina/Invoke-SentinelCapture.ps1`` uses.

**Bundled DLL contract** (packaging follows this, it is not yet wired up):
the DLL ships at ``nina_plugin/PFRSentinel.NINA.dll`` relative to the
application root — ``sys._MEIPASS`` when frozen, the repo root from source.
The PyInstaller spec entry is
``('nina_plugin/PFRSentinel.NINA.dll', 'nina_plugin')``.

Everything here is synchronous and fast (a stat walk plus one file copy).
Callers on the GUI thread must thread it themselves.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field, asdict

from .logger import app_logger
from .pe_version import read_file_version
from .utils_paths import resource_path

# Folder NINA looks in, and the single file it must contain.
PLUGIN_FOLDER_NAME = "PFRSentinel.NINA"
PLUGIN_DLL_NAME = "PFRSentinel.NINA.dll"

# Where the DLL lives inside the app bundle / source tree.
BUNDLED_SUBDIR = "nina_plugin"

# Used when NINA is installed but has no plugin folders yet. 3.0.0 is the
# compatibility baseline every NINA 3.x ships with.
DEFAULT_PLUGIN_API_VERSION = "3.0.0"

# get_status() verdicts. A UI renders these directly — no re-derivation.
STATUS_NINA_NOT_FOUND = "nina_not_found"
STATUS_NOT_INSTALLED = "not_installed"
STATUS_INSTALLED = "installed"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_STALE = "stale"

# install_plugin() / remove_plugin() outcome codes.
RESULT_OK = "ok"
RESULT_NINA_NOT_FOUND = "nina_not_found"
RESULT_BUNDLE_MISSING = "bundle_missing"
RESULT_NINA_RUNNING = "nina_running"
RESULT_REFUSED = "refused"
RESULT_ERROR = "error"

# Windows error numbers raised when NINA holds the loaded DLL open.
_LOCKED_WINERRORS = (5, 32, 33)

# Covers every PermissionError on the plugin file, not just a live NINA:
# antivirus and a read-only attribute produce the same errno.
_NINA_RUNNING_MESSAGE = (
    "The plugin file could not be written. Close NINA and try again — if NINA "
    "is already closed, check the file is not read-only or held by antivirus."
)


@dataclass
class PluginStatus:
    """Everything a panel needs to render the install card."""

    status: str
    message: str
    nina_installed: bool = False
    plugins_root: str = ""
    target_version: str = ""
    target_dir: str = ""
    installed_dll: str = ""
    installed_version: str = ""
    bundled_dll: str = ""
    bundled_version: str = ""
    bundled_available: bool = False
    stale_dirs: list = field(default_factory=list)
    can_install: bool = False
    can_remove: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PluginActionResult:
    """Outcome of an install or remove."""

    ok: bool
    code: str
    message: str
    path: str = ""
    # Folders actually deleted. A sweep can delete one install and then be
    # refused on the next, so failure does not imply nothing happened.
    removed_paths: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------

def get_nina_root(local_app_data: str | None = None) -> str:
    """``%LOCALAPPDATA%\\NINA`` — empty string when LOCALAPPDATA is unset."""
    base = local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA", "")
    if not base:
        return ""
    return os.path.join(base, "NINA")


def get_plugins_root(local_app_data: str | None = None) -> str:
    """``%LOCALAPPDATA%\\NINA\\Plugins`` — empty when LOCALAPPDATA is unset."""
    nina_root = get_nina_root(local_app_data)
    return os.path.join(nina_root, "Plugins") if nina_root else ""


def is_nina_installed(plugins_root: str) -> bool:
    """NINA counts as present when either its root or its Plugins dir exists.

    A fresh NINA that has never loaded a plugin has the root but no Plugins
    folder; install_plugin() creates it.
    """
    if not plugins_root:
        return False
    return os.path.isdir(plugins_root) or os.path.isdir(os.path.dirname(plugins_root))


def _parse_version(text: str):
    """``"3.0.0"`` -> ``(3, 0, 0, 0)``; ``None`` for anything not numeric-dotted."""
    if not text:
        return None
    parts = text.strip().split(".")
    if not 1 <= len(parts) <= 4:
        return None
    numbers = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def list_plugin_api_versions(plugins_root: str) -> list:
    """Version folder names under ``Plugins``, lowest first. Junk names dropped."""
    if not plugins_root or not os.path.isdir(plugins_root):
        return []
    found = []
    try:
        entries = os.listdir(plugins_root)
    except OSError as exc:
        app_logger.warning(f"NINA plugin: cannot list {plugins_root}: {exc}")
        return []
    for name in entries:
        if not os.path.isdir(os.path.join(plugins_root, name)):
            continue
        parsed = _parse_version(name)
        if parsed is not None:
            found.append((parsed, name))
    found.sort()
    return [name for _, name in found]


def _count_other_plugins(version_dir: str) -> int:
    """Plugin subfolders under a version folder that are not our own.

    NINA loads a plugin from ``<version>\\<PluginName>\\``; the *count* of
    non-PFRSentinel plugin folders is our evidence that NINA actually loads from
    this version folder. Our own folder is excluded so a stray copy of just this
    plugin can never make its host folder look populated.
    """
    try:
        entries = os.listdir(version_dir)
    except OSError:
        return 0
    count = 0
    for name in entries:
        if name.casefold() == PLUGIN_FOLDER_NAME.casefold():
            continue
        if os.path.isdir(os.path.join(version_dir, name)):
            count += 1
    return count


def resolve_plugin_api_version(plugins_root: str) -> str:
    """The version folder NINA actually loads plugins from.

    NINA loads plugins from ``Plugins\\<PluginMinimumApplicationVersion>\\`` — a
    compatibility baseline that has stayed ``3.0.0`` across the whole NINA 3.x
    line, **not** NINA's own version. So the highest-numbered folder is the
    wrong signal: a stray ``3.2.0.9001`` left by an older build (whose name is
    just some past NINA's four-part FileVersion) sorts above ``3.0.0`` yet holds
    no plugin NINA ever loads — installing there is a silent no-op.

    The reliable signal is where NINA's **other** plugins already live. Pick the
    version folder hosting the most non-PFRSentinel plugins; on a tie the lowest
    (most canonical) baseline wins. Fall back to
    :data:`DEFAULT_PLUGIN_API_VERSION` when nothing is populated — a fresh NINA,
    or one where only our own stray folders exist.
    """
    versions = list_plugin_api_versions(plugins_root)  # sorted lowest-first
    best = None
    best_count = 0
    for version in versions:
        count = _count_other_plugins(os.path.join(plugins_root, version))
        if count > best_count:  # strict: first (lowest) among equal counts wins
            best_count = count
            best = version
    return best if best is not None else DEFAULT_PLUGIN_API_VERSION


def resolve_target_dir(plugins_root: str, version: str | None = None) -> str:
    """``<plugins_root>\\<version>\\PFRSentinel.NINA``."""
    if not plugins_root:
        return ""
    version = version or resolve_plugin_api_version(plugins_root)
    return os.path.join(plugins_root, version, PLUGIN_FOLDER_NAME)


def get_bundled_dll_path() -> str:
    """Frozen-aware path to the DLL we ship. May not exist in a source tree."""
    return resource_path(os.path.join(BUNDLED_SUBDIR, PLUGIN_DLL_NAME))


def find_stale_install_dirs(plugins_root: str, current_version: str) -> list:
    """Plugin folders sitting under a version folder we no longer target."""
    stale = []
    for version in list_plugin_api_versions(plugins_root):
        if version == current_version:
            continue
        candidate = os.path.join(plugins_root, version, PLUGIN_FOLDER_NAME)
        if os.path.isdir(candidate):
            stale.append(candidate)
    return stale


def _digest(path: str):
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def _needs_update(bundled_dll: str, installed_dll: str,
                  bundled_version, installed_version) -> bool:
    """True when the bundled DLL should replace the installed one."""
    bundled_parsed = _parse_version(bundled_version or "")
    installed_parsed = _parse_version(installed_version or "")
    if bundled_parsed and installed_parsed and bundled_parsed != installed_parsed:
        return bundled_parsed > installed_parsed
    # Equal versions still fall through to a byte comparison: the C# build does
    # not necessarily bump AssemblyFileVersion on every rebuild, and a stale DLL
    # that silently never updates is worse than an occasional redundant copy.
    # Same fallback when either side has no readable version resource.
    bundled_hash = _digest(bundled_dll)
    installed_hash = _digest(installed_dll)
    if bundled_hash is None or installed_hash is None:
        return False
    return bundled_hash != installed_hash


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

def get_status(plugins_root: str | None = None,
               bundled_dll: str | None = None) -> PluginStatus:
    """Structured install state. Never raises; never mutates anything."""
    if plugins_root is None:
        plugins_root = get_plugins_root()
    if bundled_dll is None:
        bundled_dll = get_bundled_dll_path()

    bundled_available = os.path.isfile(bundled_dll)
    bundled_version = read_file_version(bundled_dll) if bundled_available else None

    if not is_nina_installed(plugins_root):
        return PluginStatus(
            status=STATUS_NINA_NOT_FOUND,
            message="NINA was not found on this machine.",
            plugins_root=plugins_root or "",
            bundled_dll=bundled_dll,
            bundled_version=bundled_version or "",
            bundled_available=bundled_available,
        )

    version = resolve_plugin_api_version(plugins_root)
    target_dir = resolve_target_dir(plugins_root, version)
    installed_dll = os.path.join(target_dir, PLUGIN_DLL_NAME)
    is_installed = os.path.isfile(installed_dll)
    installed_version = read_file_version(installed_dll) if is_installed else None
    stale_dirs = find_stale_install_dirs(plugins_root, version)

    result = PluginStatus(
        status=STATUS_NOT_INSTALLED,
        message="",
        nina_installed=True,
        plugins_root=plugins_root,
        target_version=version,
        target_dir=target_dir,
        installed_dll=installed_dll if is_installed else "",
        installed_version=installed_version or "",
        bundled_dll=bundled_dll,
        bundled_version=bundled_version or "",
        bundled_available=bundled_available,
        stale_dirs=stale_dirs,
        can_install=bundled_available,
        can_remove=is_installed or bool(stale_dirs),
    )

    if is_installed:
        if bundled_available and _needs_update(bundled_dll, installed_dll,
                                               bundled_version, installed_version):
            result.status = STATUS_UPDATE_AVAILABLE
            if bundled_version and bundled_version == installed_version:
                result.message = (
                    f"Update available: the bundled plugin differs from the "
                    f"installed copy (both report {bundled_version})."
                )
            else:
                result.message = (
                    f"Update available: {installed_version or 'unknown'} installed, "
                    f"{bundled_version or 'unknown'} bundled."
                )
        else:
            result.status = STATUS_INSTALLED
            result.message = (
                f"Installed in NINA {version} "
                f"(version {installed_version or 'unknown'})."
            )
    elif stale_dirs:
        result.status = STATUS_STALE
        result.message = (
            f"Installed for an older NINA plugin version. Reinstall to put it "
            f"in {version}."
        )
    else:
        result.message = "Not installed."
        if not bundled_available:
            result.message = "The NINA plugin is not included in this build."

    return result


# --------------------------------------------------------------------------
# Install
# --------------------------------------------------------------------------

def _locked_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in _LOCKED_WINERRORS


def install_plugin(plugins_root: str | None = None,
                   bundled_dll: str | None = None) -> PluginActionResult:
    """Copy the bundled DLL into NINA's plugin folder. Idempotent."""
    if plugins_root is None:
        plugins_root = get_plugins_root()
    if bundled_dll is None:
        bundled_dll = get_bundled_dll_path()

    if not is_nina_installed(plugins_root):
        return PluginActionResult(
            False, RESULT_NINA_NOT_FOUND,
            "NINA was not found on this machine.",
        )
    if not os.path.isfile(bundled_dll):
        return PluginActionResult(
            False, RESULT_BUNDLE_MISSING,
            "The NINA plugin is not included in this build.",
            bundled_dll,
        )

    version = resolve_plugin_api_version(plugins_root)
    target_dir = resolve_target_dir(plugins_root, version)
    # Same containment test the remover uses. Without it a junctioned version
    # folder would take the copy outside the plugins root — an install that
    # remove_plugin would then (correctly) refuse to undo.
    if not _is_two_levels_under(target_dir, plugins_root):
        message = (f"Refusing to install to {target_dir}: outside the NINA "
                   f"plugins folder.")
        app_logger.warning(f"NINA plugin install refused: {message}")
        return PluginActionResult(False, RESULT_REFUSED, message, target_dir)

    target_dll = os.path.join(target_dir, PLUGIN_DLL_NAME)
    existed = os.path.isfile(target_dll)

    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copyfile(bundled_dll, target_dll)
    except OSError as exc:
        if _locked_error(exc):
            app_logger.warning(f"NINA plugin install blocked (file in use): {target_dll}")
            return PluginActionResult(False, RESULT_NINA_RUNNING,
                                      _NINA_RUNNING_MESSAGE, target_dll)
        app_logger.error(f"NINA plugin install failed: {exc}")
        return PluginActionResult(False, RESULT_ERROR,
                                  f"Could not install the plugin: {exc}", target_dll)

    verb = "Updated" if existed else "Installed"
    app_logger.info(f"NINA plugin {verb.lower()} at {target_dll}")
    return PluginActionResult(
        True, RESULT_OK,
        f"{verb} the NINA plugin in {version}. Restart NINA to load it.",
        target_dll,
    )


# --------------------------------------------------------------------------
# Remove — the only directory delete in this codebase
# --------------------------------------------------------------------------

def _is_two_levels_under(path: str, root: str) -> bool:
    """True when ``path`` resolves to exactly ``<root>\\<x>\\<y>``.

    Resolved on both sides, so a junctioned version folder pointing outside the
    plugins root fails. Counting components rather than calling ``dirname``
    twice matters: ``dirname`` saturates at a drive root, which would make
    ``C:\PFRSentinel.NINA`` look two levels under ``C:\``.
    """
    try:
        relative = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:  # different drives on Windows
        return False
    parts = [part for part in relative.split(os.sep) if part not in ("", ".")]
    return len(parts) == 2 and ".." not in parts


def _is_reparse_point(path: str) -> bool:
    """Symlink *or* NTFS junction. ``islink`` alone misses junctions."""
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)  # 3.12+
    return bool(is_junction and is_junction(path))


def check_removable(target_dir: str, plugins_root: str):
    """Gate for the one directory delete in the codebase.

    ``services/cleanup.py`` is files-only by rule, so every guard lives here.
    Returns ``None`` when the delete is allowed, otherwise a refusal reason.
    A path only qualifies when it:

    * is named exactly :data:`PLUGIN_FOLDER_NAME`;
    * resolves to exactly two components below the NINA plugins root
      (``<root>\\<version>\\PFRSentinel.NINA``);
    * is a real directory, not a symlink or junction;
    * contains our DLL, or is empty.

    The containment test runs on ``realpath`` of both sides, so a junctioned
    ``LOCALAPPDATA`` still matches while a link pointing *out* of the plugins
    root is rejected. The component count is what makes it airtight —
    ``dirname`` twice saturates at a drive root and would admit ``C:\\<name>``.
    """
    if not target_dir or not plugins_root:
        return "No plugin folder to remove."

    target_abs = os.path.abspath(target_dir)
    if os.path.basename(os.path.normpath(target_abs)).casefold() != PLUGIN_FOLDER_NAME.casefold():
        return f"Refusing to delete {target_abs}: not a {PLUGIN_FOLDER_NAME} folder."

    if _is_reparse_point(target_abs):
        return f"Refusing to delete {target_abs}: it is a link, not a real folder."

    if not _is_two_levels_under(target_abs, plugins_root):
        return f"Refusing to delete {target_abs}: outside the NINA plugins folder."

    if not os.path.isdir(target_abs):
        return f"Nothing to remove at {target_abs}."

    try:
        contents = os.listdir(target_abs)
    except OSError as exc:
        return f"Cannot inspect {target_abs}: {exc}"
    if contents and PLUGIN_DLL_NAME.casefold() not in {name.casefold() for name in contents}:
        return (f"Refusing to delete {target_abs}: it does not contain "
                f"{PLUGIN_DLL_NAME}.")

    return None


def remove_plugin(plugins_root: str | None = None,
                  target_dir: str | None = None,
                  include_stale: bool = True) -> PluginActionResult:
    """Delete the plugin folder. Idempotent; refuses anything unexpected.

    ``include_stale`` defaults to True so "Remove" clears copies left under
    older plugin-API folders too — otherwise a *stale* install could never be
    removed, since the resolved target is the one folder it is not in.
    """
    if plugins_root is None:
        plugins_root = get_plugins_root()
    if not plugins_root:
        return PluginActionResult(False, RESULT_NINA_NOT_FOUND,
                                  "NINA was not found on this machine.")

    version = resolve_plugin_api_version(plugins_root)
    targets = [target_dir] if target_dir else [resolve_target_dir(plugins_root, version)]
    if include_stale and not target_dir:
        targets.extend(find_stale_install_dirs(plugins_root, version))

    removed = []

    def _failure(code: str, message: str, path: str) -> PluginActionResult:
        if removed:
            message = f"{message} Already removed: {', '.join(removed)}."
        return PluginActionResult(False, code, message, path, list(removed))

    for candidate in targets:
        candidate = os.path.abspath(candidate)
        # lexists, not exists: a dangling link must reach check_removable and be
        # refused loudly rather than silently counted as "already gone".
        if not os.path.lexists(candidate):
            continue
        refusal = check_removable(candidate, plugins_root)
        if refusal:
            app_logger.warning(f"NINA plugin removal refused: {refusal}")
            return _failure(RESULT_REFUSED, refusal, candidate)
        try:
            shutil.rmtree(candidate)
        except OSError as exc:
            if _locked_error(exc):
                app_logger.warning(f"NINA plugin removal blocked (file in use): {candidate}")
                return _failure(RESULT_NINA_RUNNING, _NINA_RUNNING_MESSAGE, candidate)
            app_logger.error(f"NINA plugin removal failed: {exc}")
            return _failure(RESULT_ERROR, f"Could not remove the plugin: {exc}", candidate)
        removed.append(candidate)
        app_logger.info(f"NINA plugin removed from {candidate}")

    if not removed:
        return PluginActionResult(True, RESULT_OK, "The NINA plugin was not installed.")
    return PluginActionResult(
        True, RESULT_OK,
        "Removed the NINA plugin. Restart NINA to unload it.",
        removed[0], list(removed),
    )
