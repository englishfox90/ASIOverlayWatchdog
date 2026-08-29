"""Tests for the NINA plugin install UI (Stage 3b).

Three layers, all marker-free:
  * ``NinaPluginController`` — ordering, busy gating, crash containment.
  * The real Output panel — status -> button state / label mapping.
  * The window mixin — the once-per-session stale nudge.

The controller takes an injectable service and runner, so nothing here touches
a real NINA folder or spawns a thread. The panel is built once for the whole
module: an OutputSettingsPanel is a heavy widget tree, and churning through a
dozen of them slows the shared QApplication enough to destabilise later
event-loop tests in the same session.
"""
import types

import pytest

from services.nina_plugin_install import (
    PluginActionResult, PluginStatus,
    RESULT_NINA_RUNNING, RESULT_OK,
    STATUS_INSTALLED, STATUS_NINA_NOT_FOUND, STATUS_NOT_INSTALLED,
    STATUS_STALE, STATUS_UPDATE_AVAILABLE,
)
from ui.controllers.nina_plugin_controller import NinaPluginController
from ui.main_window.settings import _MainWindowSettingsMixin


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# --- helpers --------------------------------------------------------------

def status(kind=STATUS_INSTALLED, message="Installed.", can_install=True,
           can_remove=True):
    return PluginStatus(status=kind, message=message,
                        can_install=can_install, can_remove=can_remove)


def fake_service(status_value=None, install=None, remove=None):
    calls = []

    def get_status():
        calls.append('get_status')
        return status_value if status_value is not None else status()

    def install_plugin():
        calls.append('install_plugin')
        if isinstance(install, Exception):
            raise install
        return install or PluginActionResult(True, RESULT_OK,
                                             "Installed the NINA plugin.")

    def remove_plugin():
        calls.append('remove_plugin')
        return remove or PluginActionResult(True, RESULT_OK,
                                            "Removed the NINA plugin.")

    return types.SimpleNamespace(
        get_status=get_status,
        install_plugin=install_plugin,
        remove_plugin=remove_plugin,
        PluginActionResult=PluginActionResult,
        RESULT_ERROR='error',
        calls=calls,
    )


def inline_controller(service):
    """Controller whose worker runs on the calling thread (signals stay sync)."""
    return NinaPluginController(service=service, runner=lambda job: job())


def recorder(controller):
    events = []
    controller.status_ready.connect(lambda s: events.append(('status', s)))
    controller.action_finished.connect(lambda r: events.append(('action', r)))
    controller.busy_changed.connect(lambda b: events.append(('busy', b)))
    return events


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        pass


def _build_panel(parent=None):
    from PySide6.QtWidgets import QWidget
    from ui.panels.output_settings import OutputSettingsPanel
    return OutputSettingsPanel(parent if parent is not None else QWidget())


@pytest.fixture(scope="module")
def host(qapp):
    """A MainWindow stand-in (real QWidget) with the real Output panel."""
    from PySide6.QtWidgets import QWidget

    class _QtWindowImpl(_MainWindowSettingsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.config = _FakeConfig()
            self.web_server = None
            self.notes = []

        def _notify(self, message, category='info'):
            self.notes.append((category, message))

    win = _QtWindowImpl()
    win.output_panel = _build_panel(win)
    return win


@pytest.fixture
def window(host):
    """Per-test reset of the shared window: notes, nudge latch, controller.

    The controller is dropped so a test that monkeypatches the service module
    gets a controller built against the patched one.
    """
    host.notes.clear()
    host._nina_plugin_nudged = False
    host._nina_plugin_controller = None
    host.output_panel.set_nina_plugin_busy(False)
    host.output_panel.set_nina_plugin_status(
        status(STATUS_NOT_INSTALLED, "Not installed.", can_remove=False))
    return host


@pytest.fixture
def panel(window):
    return window.output_panel


# --- controller -----------------------------------------------------------

def test_refresh_emits_the_services_status(qapp):
    svc = fake_service(status_value=status(STATUS_STALE, "old folder"))
    controller = inline_controller(svc)
    events = recorder(controller)

    assert controller.refresh_status() is True

    assert [e[0] for e in events] == ['busy', 'status', 'busy']
    assert events[1][1].status == STATUS_STALE
    assert events[0][1] is True and events[2][1] is False


def test_install_reports_the_result_then_refreshes(qapp):
    svc = fake_service()
    controller = inline_controller(svc)
    events = recorder(controller)

    controller.install()

    assert [e[0] for e in events] == ['busy', 'action', 'status', 'busy']
    assert svc.calls == ['install_plugin', 'get_status']


def test_remove_reports_the_result_then_refreshes(qapp):
    svc = fake_service()
    controller = inline_controller(svc)
    events = recorder(controller)

    controller.remove()

    assert [e[0] for e in events] == ['busy', 'action', 'status', 'busy']
    assert svc.calls == ['remove_plugin', 'get_status']


def test_result_message_is_passed_through_untouched(qapp):
    locked = PluginActionResult(False, RESULT_NINA_RUNNING,
                                "The plugin file could not be written. Close NINA…")
    controller = inline_controller(fake_service(install=locked))
    seen = []
    controller.action_finished.connect(seen.append)

    controller.install()

    assert seen[0].message == locked.message
    assert seen[0].code == RESULT_NINA_RUNNING


def test_a_second_action_is_refused_while_one_is_in_flight(qapp):
    """The runner never runs the job, so the controller stays busy."""
    pending = []
    controller = NinaPluginController(service=fake_service(),
                                      runner=pending.append)

    assert controller.install() is True
    assert controller.is_busy is True
    assert controller.remove() is False
    assert len(pending) == 1

    pending[0]()  # let the first finish
    assert controller.is_busy is False
    assert controller.install() is True


def test_a_crashing_service_releases_the_buttons(qapp):
    controller = inline_controller(
        fake_service(install=RuntimeError("disk on fire")))
    events = recorder(controller)

    controller.install()

    assert controller.is_busy is False
    assert events[-1] == ('busy', False)
    failure = [e[1] for e in events if e[0] == 'action'][0]
    assert failure.ok is False
    assert "disk on fire" in failure.message


def test_unknown_action_is_rejected(qapp):
    controller = inline_controller(fake_service())
    assert controller.run('sudo-install') is False
    assert controller.run('refresh') is True


# --- panel: status -> buttons --------------------------------------------

def test_buttons_start_disabled_before_any_status(qapp):
    fresh = _build_panel()
    assert fresh.nina_install_btn.isEnabled() is False
    assert fresh.nina_remove_btn.isEnabled() is False


def test_installed_status_offers_reinstall_and_remove(panel):
    panel.set_nina_plugin_status(status(STATUS_INSTALLED, "Installed in NINA 3.0.0."))
    assert panel.nina_install_btn.text() == "Reinstall Plugin"
    assert panel.nina_install_btn.isEnabled() is True
    assert panel.nina_remove_btn.isEnabled() is True
    assert panel.nina_status_label.text() == "Installed in NINA 3.0.0."


def test_update_available_relabels_the_install_button(panel):
    panel.set_nina_plugin_status(status(STATUS_UPDATE_AVAILABLE, "Update available: …"))
    assert panel.nina_install_btn.text() == "Update Plugin"
    assert panel.nina_install_btn.isEnabled() is True


def test_stale_status_offers_reinstall(panel):
    panel.set_nina_plugin_status(status(STATUS_STALE, "Installed for an older…"))
    assert panel.nina_install_btn.text() == "Reinstall Plugin"
    assert panel.nina_remove_btn.isEnabled() is True


def test_not_installed_offers_install_only(panel):
    panel.set_nina_plugin_status(
        status(STATUS_NOT_INSTALLED, "Not installed.", can_remove=False))
    assert panel.nina_install_btn.text() == "Install Plugin"
    assert panel.nina_install_btn.isEnabled() is True
    assert panel.nina_remove_btn.isEnabled() is False


def test_no_nina_disables_everything(panel):
    panel.set_nina_plugin_status(status(
        STATUS_NINA_NOT_FOUND, "NINA was not found on this machine.",
        can_install=False, can_remove=False))
    assert panel.nina_install_btn.isEnabled() is False
    assert panel.nina_remove_btn.isEnabled() is False
    assert panel.nina_status_label.text() == "NINA was not found on this machine."


def test_missing_bundle_cannot_be_installed(panel):
    """can_install is False when the DLL isn't in the build — trust it."""
    panel.set_nina_plugin_status(status(
        STATUS_NOT_INSTALLED, "The NINA plugin is not included in this build.",
        can_install=False, can_remove=False))
    assert panel.nina_install_btn.isEnabled() is False


def test_busy_disables_both_buttons_and_recovers(panel):
    panel.set_nina_plugin_status(status(STATUS_INSTALLED))
    panel.set_nina_plugin_busy(True)
    assert panel.nina_install_btn.isEnabled() is False
    assert panel.nina_remove_btn.isEnabled() is False
    panel.set_nina_plugin_busy(False)
    assert panel.nina_install_btn.isEnabled() is True
    assert panel.nina_remove_btn.isEnabled() is True


# --- panel + window, end to end ------------------------------------------

def _patch_service(monkeypatch, svc):
    """Point the controller module at a fake service and an inline runner."""
    from ui.controllers import nina_plugin_controller as controller_module
    monkeypatch.setattr(controller_module, '_run_detached', lambda job: job())
    monkeypatch.setattr(controller_module, 'nina_plugin_install', svc)


def test_clicking_install_runs_the_service_and_reports_verbatim(window, monkeypatch):
    """Drive the real button through the real window wiring."""
    locked = PluginActionResult(False, RESULT_NINA_RUNNING,
                                "The plugin file could not be written. Close NINA "
                                "and try again.")
    svc = fake_service(
        status_value=status(STATUS_INSTALLED, "Installed in NINA 3.0.0."),
        install=locked)
    _patch_service(monkeypatch, svc)
    panel = window.output_panel

    panel.nina_install_btn.click()

    assert 'install_plugin' in svc.calls
    assert window.notes == [('warning', locked.message)]
    # The post-action refresh landed on the panel.
    assert panel.nina_status_label.text() == "Installed in NINA 3.0.0."
    assert panel.nina_install_btn.isEnabled() is True


def test_clicking_remove_runs_the_remove_path(window, monkeypatch):
    svc = fake_service(status_value=status(STATUS_NOT_INSTALLED, "Not installed.",
                                           can_remove=False))
    _patch_service(monkeypatch, svc)
    panel = window.output_panel
    panel.set_nina_plugin_status(status(STATUS_INSTALLED))

    panel.nina_remove_btn.click()

    assert 'remove_plugin' in svc.calls
    assert window.notes[-1][0] == 'info'
    assert panel.nina_remove_btn.isEnabled() is False


def test_refresh_on_startup_populates_the_card(window, monkeypatch):
    svc = fake_service(status_value=status(STATUS_INSTALLED, "Installed in NINA 3.0.0."))
    _patch_service(monkeypatch, svc)

    assert window.refresh_nina_plugin_status() is True

    assert svc.calls == ['get_status']
    assert window.output_panel.nina_status_label.text() == "Installed in NINA 3.0.0."


def test_a_panel_without_a_window_does_not_crash(qapp):
    fresh = _build_panel()  # parent is a bare QWidget, not a MainWindow
    fresh.set_nina_plugin_status(status(STATUS_INSTALLED))
    fresh.nina_install_btn.click()


# --- the startup nudge ----------------------------------------------------

class _NudgeWindow(_MainWindowSettingsMixin):
    """Mixin only — the nudge needs no widgets."""

    def __init__(self):
        self.notes = []
        self.output_panel = None

    def _notify(self, message, category='info'):
        self.notes.append((category, message))


def test_stale_install_nudges_once():
    win = _NudgeWindow()
    win._on_nina_plugin_status(status(STATUS_STALE, "Installed for an older NINA "
                                                    "plugin version."))
    assert len(win.notes) == 1
    assert win.notes[0][0] == 'warning'
    assert "Installed for an older NINA plugin version." in win.notes[0][1]


def test_the_nudge_does_not_repeat():
    win = _NudgeWindow()
    stale = status(STATUS_STALE, "Installed for an older NINA plugin version.")
    win._on_nina_plugin_status(stale)
    win._on_nina_plugin_status(stale)
    assert len(win.notes) == 1


@pytest.mark.parametrize("kind", [
    STATUS_INSTALLED, STATUS_NOT_INSTALLED, STATUS_NINA_NOT_FOUND,
    STATUS_UPDATE_AVAILABLE,
])
def test_no_nudge_when_the_plugin_is_absent_or_current(kind):
    win = _NudgeWindow()
    win._on_nina_plugin_status(status(kind, "whatever"))
    assert win.notes == []


def test_a_stale_install_still_reaches_the_panel(window, monkeypatch):
    """The nudge must not swallow the normal status render."""
    svc = fake_service(status_value=status(STATUS_STALE,
                                           "Installed for an older NINA plugin version."))
    _patch_service(monkeypatch, svc)

    window.refresh_nina_plugin_status()

    assert window.output_panel.nina_install_btn.text() == "Reinstall Plugin"
    assert len(window.notes) == 1


def test_busy_reaches_the_panel(window):
    panel = window.output_panel
    panel.set_nina_plugin_status(status(STATUS_INSTALLED))
    window._on_nina_plugin_busy(True)
    assert panel.nina_install_btn.isEnabled() is False


def test_action_dispatch_survives_a_broken_controller(monkeypatch):
    win = _NudgeWindow()
    monkeypatch.setattr(_MainWindowSettingsMixin, 'nina_plugin_controller',
                        lambda self: (_ for _ in ()).throw(RuntimeError("no Qt")))
    assert win.run_nina_plugin_action('install') is False
