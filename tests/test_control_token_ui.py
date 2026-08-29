"""Tests for the capture-control token lifecycle behind the Output panel.

The panel is layout-only, so the behaviour worth pinning lives on the window
mixin: minting on enable, regenerating, and — the easy bug — pushing a changed
token to an already-running server.
"""
import pytest

from services import api_auth
from ui.main_window.settings import _MainWindowSettingsMixin


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saves = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saves += 1


class _FakeServer:
    def __init__(self):
        self.tokens = []
        self.raises = False

    def set_control_token(self, token):
        if self.raises:
            raise RuntimeError("server is wedged")
        self.tokens.append(token)


class _Window(_MainWindowSettingsMixin):
    """Just the mixin under test — no Qt, no real MainWindow."""

    def __init__(self, config, web_server=None):
        self.config = config
        self.web_server = web_server
        self.settings_emitted = 0


@pytest.fixture(scope="module", autouse=False)
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _qt_window_cls():
    """MainWindow stand-in that is a real QWidget, so the panel can parent to it."""
    from PySide6.QtWidgets import QWidget

    class _QtWindowImpl(_MainWindowSettingsMixin, QWidget):
        def __init__(self, config, web_server=None):
            super().__init__()
            self.config = config
            self.web_server = web_server
            self.notes = []

        def _notify(self, message, category='info'):
            self.notes.append((category, message))

    return _QtWindowImpl


def enabled_config(**extra):
    output = {"webserver_control_enabled": True}
    output.update(extra)
    return _FakeConfig({"output": output})


# --- minting --------------------------------------------------------------

def test_enabling_mints_a_token():
    cfg = enabled_config()
    win = _Window(cfg)
    token = win.ensure_control_token()
    assert token
    assert cfg.data["output"]["api_token"] == token


def test_minting_is_idempotent():
    cfg = enabled_config(api_token="existing-token")
    win = _Window(cfg)
    assert win.ensure_control_token() == "existing-token"
    assert cfg.saves == 0


def test_disabled_control_yields_no_token():
    """Fail closed: a disabled API must hand the server an empty token."""
    cfg = _FakeConfig({"output": {"webserver_control_enabled": False,
                                  "api_token": "still-stored"}})
    win = _Window(cfg)
    assert win.ensure_control_token() == ""


def test_disabling_does_not_erase_the_stored_token():
    """Re-enabling later should not invalidate a token NINA already has."""
    cfg = _FakeConfig({"output": {"webserver_control_enabled": False,
                                  "api_token": "keep-me"}})
    _Window(cfg).ensure_control_token()
    assert cfg.data["output"]["api_token"] == "keep-me"


# --- regeneration ---------------------------------------------------------

def test_regenerate_replaces_the_token():
    cfg = enabled_config(api_token="old-token")
    win = _Window(cfg)
    new = win.regenerate_control_token()
    assert new != "old-token"
    assert cfg.data["output"]["api_token"] == new


def test_regenerate_preserves_sibling_output_keys():
    cfg = enabled_config(api_token="old", webserver_port=9999)
    win = _Window(cfg)
    win.regenerate_control_token()
    assert cfg.data["output"]["webserver_port"] == 9999
    assert cfg.data["output"]["webserver_control_enabled"] is True


def test_regenerate_persists():
    cfg = enabled_config(api_token="old")
    _Window(cfg).regenerate_control_token()
    assert cfg.saves >= 1


# --- pushing to a live server (the bug this exists to prevent) ------------

def test_new_token_reaches_a_running_server():
    """Server reconciliation only watches the enabled flag — push explicitly."""
    server = _FakeServer()
    cfg = enabled_config(api_token="old")
    win = _Window(cfg, web_server=server)
    new = win.regenerate_control_token()
    assert server.tokens[-1] == new


def test_disabling_pushes_an_empty_token_to_a_running_server():
    server = _FakeServer()
    cfg = _FakeConfig({"output": {"webserver_control_enabled": False,
                                  "api_token": "stored"}})
    _Window(cfg, web_server=server).ensure_control_token()
    assert server.tokens[-1] == ""


def test_panel_disarms_a_running_server_when_the_api_is_switched_off(qapp):
    """The disable edge is the one that matters and the one that was broken.

    Server reconciliation only watches `webserver_enabled`, so turning the
    control API off must push an empty token itself — otherwise
    POST /capture/start stays fully live until the app restarts.
    """
    from ui.panels.output_settings import OutputSettingsPanel

    server = _FakeServer()
    cfg = enabled_config(api_token="live-token")
    win = _qt_window_cls()(cfg, web_server=server)
    panel = OutputSettingsPanel(win)
    panel.load_from_config(cfg)

    assert panel.control_token_input.text() == "live-token"

    panel.control_enabled_switch.set_checked(False)
    panel._on_control_enabled_changed(False)

    assert cfg.data["output"]["webserver_control_enabled"] is False
    assert server.tokens[-1] == "", "running server still armed after disable"
    assert panel.control_token_input.text() == ""


def test_no_server_is_not_an_error():
    cfg = enabled_config()
    assert _Window(cfg, web_server=None).ensure_control_token()


def test_server_failure_does_not_break_the_settings_flow():
    server = _FakeServer()
    server.raises = True
    cfg = enabled_config()
    token = _Window(cfg, web_server=server).ensure_control_token()
    assert token  # config still updated; the error is logged, not raised


# --- the token the UI displays matches what the server checks -------------

def test_displayed_token_authenticates():
    cfg = enabled_config()
    win = _Window(cfg)
    token = win.ensure_control_token()
    displayed = cfg.data["output"]["api_token"]
    assert api_auth.check_bearer(f"Bearer {displayed}", token) == api_auth.AUTH_OK


def test_old_token_stops_working_after_regeneration():
    cfg = enabled_config()
    win = _Window(cfg)
    old = win.ensure_control_token()
    new = win.regenerate_control_token()
    assert api_auth.check_bearer(f"Bearer {old}", new) == api_auth.AUTH_INVALID
