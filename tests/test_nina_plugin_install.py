"""Tests for services/nina_plugin_install.py.

Everything runs against ``tmp_path`` — the real ``%LOCALAPPDATA%\\NINA`` is
never read or written. DLLs are synthesised: :func:`write_fake_dll` builds a
minimal but structurally valid PE with an RT_VERSION resource, so the
FileVersion reader and the update comparison are exercised for real rather
than mocked.
"""
import os
import subprocess

import pytest

from services import nina_plugin_install as npi
from tests.test_pe_version import write_fake_dll


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plugins_root(tmp_path):
    """A NINA install with one 3.0.0 plugin folder, like the real machine."""
    root = tmp_path / "NINA" / "Plugins"
    (root / "3.0.0").mkdir(parents=True)
    return str(root)


@pytest.fixture
def bundled_dll(tmp_path):
    return write_fake_dll(str(tmp_path / "bundle" / npi.PLUGIN_DLL_NAME), (2, 0, 0, 0))


def _installed_dll(plugins_root, version="3.0.0"):
    return os.path.join(plugins_root, version, npi.PLUGIN_FOLDER_NAME, npi.PLUGIN_DLL_NAME)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def test_plugins_root_derives_from_local_app_data(tmp_path):
    root = npi.get_plugins_root(str(tmp_path))
    assert root == os.path.join(str(tmp_path), "NINA", "Plugins")


def test_plugins_root_empty_without_local_app_data():
    assert npi.get_plugins_root("") == ""
    assert npi.get_nina_root("") == ""


def test_resolve_follows_where_other_plugins_live(tmp_path):
    # NINA's real layout: every plugin sits under the 3.0.0 baseline, while a
    # stray higher-numbered folder (left by an older installer that read
    # NINA.exe's four-part FileVersion) holds only our own plugin. Resolution
    # must follow the populated folder, not the higher number.
    root = tmp_path / "Plugins"
    for name in ("Advanced API", "Hocus Focus", "Target Scheduler"):
        (root / "3.0.0" / name).mkdir(parents=True)
    (root / "3.2.0.9001" / npi.PLUGIN_FOLDER_NAME).mkdir(parents=True)
    assert npi.resolve_plugin_api_version(str(root)) == "3.0.0"


def test_resolve_picks_most_populated_folder(tmp_path):
    # When two folders host real plugins, the busier one wins even if lower.
    root = tmp_path / "Plugins"
    for name in ("PluginA", "PluginB", "PluginC"):
        (root / "3.0.0" / name).mkdir(parents=True)
    (root / "4.0.0" / "LonePlugin").mkdir(parents=True)
    assert npi.resolve_plugin_api_version(str(root)) == "3.0.0"


def test_resolve_ties_prefer_lowest_baseline(tmp_path):
    # Equal population: the lowest (most canonical) baseline wins.
    root = tmp_path / "Plugins"
    (root / "3.9.0" / "PluginX").mkdir(parents=True)
    (root / "3.10.0" / "PluginY").mkdir(parents=True)
    assert npi.resolve_plugin_api_version(str(root)) == "3.9.0"


def test_resolve_defaults_when_only_our_stray_folder_exists(tmp_path):
    # A stray folder containing only our plugin must not be selected; with no
    # other plugins anywhere, fall back to the canonical baseline.
    root = tmp_path / "Plugins"
    (root / "3.2.0.9001" / npi.PLUGIN_FOLDER_NAME).mkdir(parents=True)
    assert npi.resolve_plugin_api_version(str(root)) == npi.DEFAULT_PLUGIN_API_VERSION


def test_malformed_folder_names_are_ignored(tmp_path):
    root = tmp_path / "Plugins"
    for name in ("3.0.0", "beta", "3.x.1", "", "1.2.3.4.5", "notes"):
        if name:
            (root / name).mkdir(parents=True)
    (root / "3.5.0.txt").write_text("not a folder", encoding="utf-8")
    assert npi.resolve_plugin_api_version(str(root)) == "3.0.0"
    assert npi.list_plugin_api_versions(str(root)) == ["3.0.0"]


def test_empty_plugins_root_defaults(tmp_path):
    root = tmp_path / "Plugins"
    root.mkdir()
    assert npi.resolve_plugin_api_version(str(root)) == npi.DEFAULT_PLUGIN_API_VERSION


def test_missing_plugins_root_defaults(tmp_path):
    missing = str(tmp_path / "nope" / "Plugins")
    assert npi.list_plugin_api_versions(missing) == []
    assert npi.resolve_plugin_api_version(missing) == npi.DEFAULT_PLUGIN_API_VERSION


def test_target_dir_layout(plugins_root):
    target = npi.resolve_target_dir(plugins_root)
    assert target == os.path.join(plugins_root, "3.0.0", npi.PLUGIN_FOLDER_NAME)


def test_bundled_path_is_under_the_app_root():
    bundled = npi.get_bundled_dll_path()
    assert bundled.endswith(os.path.join(npi.BUNDLED_SUBDIR, npi.PLUGIN_DLL_NAME))
    assert os.path.isabs(bundled)


def test_bundled_path_uses_meipass_when_frozen(monkeypatch):
    monkeypatch.setattr("sys._MEIPASS", r"C:\frozen", raising=False)
    assert npi.get_bundled_dll_path() == os.path.join(
        r"C:\frozen", npi.BUNDLED_SUBDIR, npi.PLUGIN_DLL_NAME)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_reports_nina_missing(tmp_path, bundled_dll):
    status = npi.get_status(str(tmp_path / "no-nina" / "Plugins"), bundled_dll)
    assert status.status == npi.STATUS_NINA_NOT_FOUND
    assert status.nina_installed is False
    assert status.can_install is False


def test_status_not_installed(plugins_root, bundled_dll):
    status = npi.get_status(plugins_root, bundled_dll)
    assert status.status == npi.STATUS_NOT_INSTALLED
    assert status.nina_installed is True
    assert status.target_version == "3.0.0"
    assert status.bundled_version == "2.0.0.0"
    assert status.can_install is True
    assert status.can_remove is False


def test_status_reports_missing_bundle(plugins_root, tmp_path):
    status = npi.get_status(plugins_root, str(tmp_path / "absent.dll"))
    assert status.status == npi.STATUS_NOT_INSTALLED
    assert status.bundled_available is False
    assert status.can_install is False


def test_status_installed_after_install(plugins_root, bundled_dll):
    npi.install_plugin(plugins_root, bundled_dll)
    status = npi.get_status(plugins_root, bundled_dll)
    assert status.status == npi.STATUS_INSTALLED
    assert status.installed_version == "2.0.0.0"
    assert status.can_remove is True
    assert status.as_dict()["status"] == npi.STATUS_INSTALLED


def test_status_update_available_on_newer_bundle(plugins_root, tmp_path):
    old = write_fake_dll(str(tmp_path / "old" / npi.PLUGIN_DLL_NAME), (1, 0, 0, 0))
    npi.install_plugin(plugins_root, old)
    new = write_fake_dll(str(tmp_path / "new" / npi.PLUGIN_DLL_NAME), (1, 1, 0, 0))
    status = npi.get_status(plugins_root, new)
    assert status.status == npi.STATUS_UPDATE_AVAILABLE
    assert status.installed_version == "1.0.0.0"
    assert status.bundled_version == "1.1.0.0"


def test_status_update_when_versions_match_but_bytes_differ(plugins_root, tmp_path):
    """The C# build may not bump AssemblyFileVersion on every rebuild."""
    first = write_fake_dll(str(tmp_path / "a" / npi.PLUGIN_DLL_NAME), (1, 0, 0, 1))
    npi.install_plugin(plugins_root, first)
    rebuilt = write_fake_dll(str(tmp_path / "b" / npi.PLUGIN_DLL_NAME), (1, 0, 0, 1),
                             filler=b"recompiled")
    status = npi.get_status(plugins_root, rebuilt)
    assert status.status == npi.STATUS_UPDATE_AVAILABLE
    assert "1.0.0.1" in status.message


def test_status_installed_when_bytes_are_identical(plugins_root, bundled_dll):
    npi.install_plugin(plugins_root, bundled_dll)
    assert npi.get_status(plugins_root, bundled_dll).status == npi.STATUS_INSTALLED


def test_status_no_update_when_bundle_is_older(plugins_root, tmp_path):
    new = write_fake_dll(str(tmp_path / "new" / npi.PLUGIN_DLL_NAME), (2, 0, 0, 0))
    npi.install_plugin(plugins_root, new)
    old = write_fake_dll(str(tmp_path / "old" / npi.PLUGIN_DLL_NAME), (1, 0, 0, 0))
    assert npi.get_status(plugins_root, old).status == npi.STATUS_INSTALLED


def test_update_falls_back_to_content_when_version_unreadable(plugins_root, tmp_path):
    target = _installed_dll(plugins_root)
    os.makedirs(os.path.dirname(target))
    with open(target, "wb") as handle:
        handle.write(b"old bytes")
    bundled = tmp_path / "b.dll"
    bundled.write_bytes(b"new bytes")
    assert npi.get_status(plugins_root, str(bundled)).status == npi.STATUS_UPDATE_AVAILABLE
    bundled.write_bytes(b"old bytes")
    assert npi.get_status(plugins_root, str(bundled)).status == npi.STATUS_INSTALLED


def test_status_stale_when_installed_under_other_version(tmp_path, bundled_dll):
    root = tmp_path / "NINA" / "Plugins"
    (root / "3.0.0").mkdir(parents=True)
    npi.install_plugin(str(root), bundled_dll)
    stale = root / "3.0.0" / npi.PLUGIN_FOLDER_NAME
    assert stale.is_dir()

    # NINA moves its compatibility baseline: its other plugins now live under
    # 4.0.0, so that is where NINA loads from and where we must reinstall. Our
    # copy under 3.0.0 is left behind (stale). An empty 4.0.0 folder alone would
    # NOT move the target — only real plugins living there are evidence.
    (root / "4.0.0" / "Some Other Plugin").mkdir(parents=True)

    status = npi.get_status(str(root), bundled_dll)
    assert status.status == npi.STATUS_STALE
    assert status.target_version == "4.0.0"
    assert status.stale_dirs == [str(stale)]
    assert status.can_install is True
    assert status.can_remove is True


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def test_install_creates_folder_and_copies_dll(plugins_root, bundled_dll):
    result = npi.install_plugin(plugins_root, bundled_dll)
    target = _installed_dll(plugins_root)
    assert result.ok and result.code == npi.RESULT_OK
    assert os.path.isfile(target)
    assert os.listdir(os.path.dirname(target)) == [npi.PLUGIN_DLL_NAME]


def test_install_creates_plugins_root_when_nina_has_no_plugins(tmp_path, bundled_dll):
    nina = tmp_path / "NINA"
    nina.mkdir()
    root = str(nina / "Plugins")
    result = npi.install_plugin(root, bundled_dll)
    assert result.ok
    assert os.path.isfile(os.path.join(
        root, npi.DEFAULT_PLUGIN_API_VERSION, npi.PLUGIN_FOLDER_NAME, npi.PLUGIN_DLL_NAME))


def test_install_is_idempotent(plugins_root, bundled_dll):
    first = npi.install_plugin(plugins_root, bundled_dll)
    second = npi.install_plugin(plugins_root, bundled_dll)
    assert first.ok and second.ok
    assert "Installed" in first.message and "Updated" in second.message
    assert npi.get_status(plugins_root, bundled_dll).status == npi.STATUS_INSTALLED


def test_install_overwrites_older_dll(plugins_root, tmp_path):
    old = write_fake_dll(str(tmp_path / "old" / npi.PLUGIN_DLL_NAME), (1, 0, 0, 0))
    npi.install_plugin(plugins_root, old)
    new = write_fake_dll(str(tmp_path / "new" / npi.PLUGIN_DLL_NAME), (1, 2, 0, 0))
    assert npi.install_plugin(plugins_root, new).ok
    assert npi.read_file_version(_installed_dll(plugins_root)) == "1.2.0.0"


def test_install_refuses_without_nina(tmp_path, bundled_dll):
    result = npi.install_plugin(str(tmp_path / "nowhere" / "Plugins"), bundled_dll)
    assert not result.ok and result.code == npi.RESULT_NINA_NOT_FOUND


def test_install_reports_missing_bundle(plugins_root, tmp_path):
    result = npi.install_plugin(plugins_root, str(tmp_path / "absent.dll"))
    assert not result.ok and result.code == npi.RESULT_BUNDLE_MISSING


def test_install_reports_nina_running_when_dll_locked(plugins_root, bundled_dll, monkeypatch):
    def locked(*_args, **_kwargs):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(npi.shutil, "copyfile", locked)
    result = npi.install_plugin(plugins_root, bundled_dll)
    assert not result.ok
    assert result.code == npi.RESULT_NINA_RUNNING
    assert "Close NINA" in result.message


def test_install_refuses_a_junctioned_version_folder(plugins_root, tmp_path, bundled_dll):
    """A junction named like a version must not take the copy out of the root."""
    outside = tmp_path / "Elsewhere"
    outside.mkdir()
    # Populate it so resolution selects this (junctioned) version folder as the
    # target — only then does install reach, and refuse at, the containment guard.
    (outside / "Some Other Plugin").mkdir()
    link = os.path.join(plugins_root, "9.9.9")
    made = subprocess.run(["cmd", "/c", "mklink", "/J", link, str(outside)],
                          capture_output=True, shell=False)
    if made.returncode != 0 or not os.path.exists(link):
        pytest.skip("junctions unavailable on this platform")

    result = npi.install_plugin(plugins_root, bundled_dll)
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert not (outside / npi.PLUGIN_FOLDER_NAME).exists()


def test_install_surfaces_other_errors_as_error(plugins_root, bundled_dll, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(npi.shutil, "copyfile", boom)
    result = npi.install_plugin(plugins_root, bundled_dll)
    assert not result.ok and result.code == npi.RESULT_ERROR


# ---------------------------------------------------------------------------
# Remove — safety guards
# ---------------------------------------------------------------------------

def test_remove_deletes_the_plugin_folder(plugins_root, bundled_dll):
    npi.install_plugin(plugins_root, bundled_dll)
    target = npi.resolve_target_dir(plugins_root)
    result = npi.remove_plugin(plugins_root)
    assert result.ok and result.code == npi.RESULT_OK
    assert not os.path.exists(target)
    assert os.path.isdir(os.path.join(plugins_root, "3.0.0"))  # version folder kept


def test_remove_is_idempotent(plugins_root, bundled_dll):
    npi.install_plugin(plugins_root, bundled_dll)
    assert npi.remove_plugin(plugins_root).ok
    again = npi.remove_plugin(plugins_root)
    assert again.ok and "not installed" in again.message


def test_remove_refuses_path_outside_plugins_root(plugins_root, tmp_path):
    outside = tmp_path / "Documents" / npi.PLUGIN_FOLDER_NAME
    outside.mkdir(parents=True)
    (outside / npi.PLUGIN_DLL_NAME).write_bytes(b"precious")

    assert npi.check_removable(str(outside), plugins_root) is not None
    result = npi.remove_plugin(plugins_root, target_dir=str(outside))
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert outside.is_dir()


def test_remove_refuses_folder_with_a_different_name(plugins_root):
    other = os.path.join(plugins_root, "3.0.0", "SomeOtherPlugin")
    os.makedirs(other)
    assert "not a PFRSentinel.NINA folder" in npi.check_removable(other, plugins_root)
    result = npi.remove_plugin(plugins_root, target_dir=other)
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert os.path.isdir(other)


def test_remove_refuses_the_plugins_root_itself(plugins_root):
    result = npi.remove_plugin(plugins_root, target_dir=plugins_root)
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert os.path.isdir(plugins_root)


def test_remove_refuses_a_correctly_named_folder_at_the_wrong_depth(plugins_root):
    shallow = os.path.join(plugins_root, npi.PLUGIN_FOLDER_NAME)
    os.makedirs(shallow)
    assert npi.check_removable(shallow, plugins_root) is not None
    assert not npi.remove_plugin(plugins_root, target_dir=shallow).ok
    assert os.path.isdir(shallow)


def test_remove_refuses_folder_without_our_dll(plugins_root):
    target = npi.resolve_target_dir(plugins_root)
    os.makedirs(target)
    with open(os.path.join(target, "SomeoneElses.dll"), "wb") as handle:
        handle.write(b"not ours")
    result = npi.remove_plugin(plugins_root)
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert os.path.isdir(target)


def test_remove_allows_an_empty_plugin_folder(plugins_root):
    target = npi.resolve_target_dir(plugins_root)
    os.makedirs(target)
    assert npi.check_removable(target, plugins_root) is None
    assert npi.remove_plugin(plugins_root).ok
    assert not os.path.exists(target)


def test_remove_refuses_a_symlinked_plugin_folder(plugins_root, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / npi.PLUGIN_DLL_NAME).write_bytes(b"precious")
    link = os.path.join(plugins_root, "3.0.0", npi.PLUGIN_FOLDER_NAME)
    try:
        os.symlink(str(real), link, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink creation not permitted on this machine")

    result = npi.remove_plugin(plugins_root)
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert (real / npi.PLUGIN_DLL_NAME).exists()


def test_remove_refuses_when_target_reports_as_a_link(plugins_root, monkeypatch):
    """Deterministic twin of the symlink test — no privileges needed."""
    target = npi.resolve_target_dir(plugins_root)
    os.makedirs(target)
    monkeypatch.setattr(npi.os.path, "islink", lambda path: True)
    refusal = npi.check_removable(target, plugins_root)
    assert refusal is not None and "link" in refusal
    assert not npi.remove_plugin(plugins_root).ok
    assert os.path.isdir(target)


def test_remove_reports_nina_running_when_locked(plugins_root, bundled_dll, monkeypatch):
    npi.install_plugin(plugins_root, bundled_dll)

    def locked(*_args, **_kwargs):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(npi.shutil, "rmtree", locked)
    result = npi.remove_plugin(plugins_root)
    assert not result.ok
    assert result.code == npi.RESULT_NINA_RUNNING
    assert "Close NINA" in result.message


def test_remove_clears_a_stale_install_by_default(tmp_path, bundled_dll):
    """A stale install lives in the one folder the resolved target is not."""
    root = tmp_path / "NINA" / "Plugins"
    (root / "3.0.0").mkdir(parents=True)
    npi.install_plugin(str(root), bundled_dll)          # -> 3.0.0 (default)
    stale = root / "3.0.0" / npi.PLUGIN_FOLDER_NAME
    # NINA moves its baseline: its other plugins now live under 4.0.0.
    (root / "4.0.0" / "Some Other Plugin").mkdir(parents=True)
    assert npi.get_status(str(root), bundled_dll).status == npi.STATUS_STALE

    result = npi.remove_plugin(str(root))
    assert result.ok
    assert not stale.exists()
    assert npi.get_status(str(root), bundled_dll).status == npi.STATUS_NOT_INSTALLED


def test_remove_reports_what_it_managed_to_delete(tmp_path, bundled_dll):
    root = tmp_path / "NINA" / "Plugins"
    # NINA loads from 4.0.0 (its other plugins live there); install targets it.
    (root / "4.0.0" / "Some Other Plugin").mkdir(parents=True)
    npi.install_plugin(str(root), bundled_dll)              # -> 4.0.0
    stale = root / "3.0.0" / npi.PLUGIN_FOLDER_NAME
    os.makedirs(stale)
    (stale / "SomeoneElses.dll").write_bytes(b"not ours")   # refused

    result = npi.remove_plugin(str(root))
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert result.removed_paths == [str(root / "4.0.0" / npi.PLUGIN_FOLDER_NAME)]
    assert "Already removed" in result.message
    assert stale.is_dir()


def test_remove_matches_the_dll_name_case_insensitively(plugins_root):
    target = npi.resolve_target_dir(plugins_root)
    os.makedirs(target)
    with open(os.path.join(target, npi.PLUGIN_DLL_NAME.lower()), "wb") as handle:
        handle.write(b"ours, lowercased by robocopy")
    assert npi.check_removable(target, plugins_root) is None


def test_remove_refuses_a_junctioned_plugin_folder(plugins_root, tmp_path):
    """Junctions are the realistic Windows case — islink() alone misses them."""
    real = tmp_path / "Documents"
    real.mkdir()
    (real / npi.PLUGIN_DLL_NAME).write_bytes(b"precious")
    link = os.path.join(plugins_root, "3.0.0", npi.PLUGIN_FOLDER_NAME)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", link, str(real)],
                          capture_output=True, shell=False)
    if made.returncode != 0 or not os.path.exists(link):
        pytest.skip("junctions unavailable on this platform")

    assert npi._is_reparse_point(link) is True
    result = npi.remove_plugin(plugins_root)
    assert not result.ok and result.code == npi.RESULT_REFUSED
    assert (real / npi.PLUGIN_DLL_NAME).exists()


def test_remove_refuses_a_name_match_directly_under_a_drive_root():
    """dirname() twice saturates at a drive root; the depth check must not."""
    refusal = npi.check_removable("C:\\" + npi.PLUGIN_FOLDER_NAME, "C:\\")
    assert refusal is not None and "outside" in refusal


def test_remove_include_stale_clears_old_version_folders(tmp_path, bundled_dll):
    root = tmp_path / "NINA" / "Plugins"
    # NINA loads from 4.0.0 (its other plugins live there); install targets it.
    (root / "4.0.0" / "Some Other Plugin").mkdir(parents=True)
    npi.install_plugin(str(root), bundled_dll)
    target = root / "4.0.0" / npi.PLUGIN_FOLDER_NAME
    assert target.is_dir()

    # A copy left behind under an older baseline must be swept too.
    stale = root / "3.0.0" / npi.PLUGIN_FOLDER_NAME
    os.makedirs(stale)
    write_fake_dll(str(stale / npi.PLUGIN_DLL_NAME), (2, 0, 0, 0))

    assert npi.remove_plugin(str(root), include_stale=True).ok
    assert not target.exists()
    assert not stale.exists()


def test_remove_without_nina_reports_it(tmp_path):
    result = npi.remove_plugin("")
    assert not result.ok and result.code == npi.RESULT_NINA_NOT_FOUND
