"""
Library Panel — the three-screen flow over the rolling image library.

A container that swaps between:
  • the session list (nights grouped into cards),
  • the night view (hero preview + draggable scrubber across the night), and
  • a single-image dialog (opened from the night view).

Layout/UI only — every disk read happens in ``LibraryController`` on worker
threads; this panel renders what the controller emits and forwards the user's
navigation back to it. The controller's signals are wired to the handler methods
here in ``MainWindow._setup_ui``.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget

from ..theme.tokens import Colors
from .library_session_list import SessionListView
from .library_night_view import NightView

# Range filter options offered by the session list; the controller just takes
# the resolved lookback seconds (None = all time).
RANGE_OPTIONS = [
    ("All nights", None),
    ("Last 7 days", 7 * 24 * 3600),
    ("Last 30 days", 30 * 24 * 3600),
]


class LibraryPanel(QWidget):
    """Full-page Library with internal session-list ⇄ night-view navigation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._loaded_once = False
        self._setup_ui()

    def _setup_ui(self):
        # Scope the background to this widget only — a selector-less
        # 'background-color' leaks down to every child label/button (Qt
        # propagates the stylesheet), painting black boxes behind their text.
        self.setObjectName("LibraryPanel")
        self.setStyleSheet(f"#LibraryPanel {{ background-color: {Colors.bg_app}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.session_list = SessionListView(RANGE_OPTIONS, self)
        self.night_view = NightView(self)
        self.stack.addWidget(self.session_list)   # 0
        self.stack.addWidget(self.night_view)     # 1

        self.session_list.session_clicked.connect(self.open_session)
        self.session_list.refresh_requested.connect(self._reload_sessions)
        self.night_view.back_requested.connect(self.show_sessions)
        self.night_view.frame_request.connect(self._request_frame)

    # -- lifecycle ---------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self._reload_sessions()

    def _controller(self):
        return getattr(self.main_window, 'library_controller', None)

    # -- navigation --------------------------------------------------------

    def _reload_sessions(self):
        controller = self._controller()
        if controller is None:
            return
        self.session_list.set_loading()
        controller.load_sessions(since_seconds=self.session_list.current_range())

    def open_session(self, session):
        controller = self._controller()
        if controller is None:
            return
        self.night_view.begin_load(session)
        self.stack.setCurrentWidget(self.night_view)
        controller.load_session_frames(session)

    def show_sessions(self):
        self.night_view.stop()
        self.stack.setCurrentWidget(self.session_list)

    def _request_frame(self, image_id):
        controller = self._controller()
        if controller is not None:
            controller.request_frame(image_id)

    # -- controller signal handlers ---------------------------------------

    def set_sessions(self, sessions):
        self.session_list.set_sessions(sessions)

    def set_frames(self, payload):
        self.night_view.set_frames(payload)

    def on_frame_ready(self, image_id, data):
        self.night_view.on_frame_ready(image_id, data)

    def on_load_failed(self, message):
        self.session_list.set_error(message)
