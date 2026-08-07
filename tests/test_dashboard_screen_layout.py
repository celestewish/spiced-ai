"""Dashboard screen layout regression test.

Found via live manual testing: several QLabel widgets built by dashboard.py's
``_muted()`` helper (the readiness caveat, the health-summary description,
and others) never had word-wrap enabled, so each demanded its full unwrapped
text as a hard minimum width. The widest one alone (the "Generate a local,
Markdown-friendly summary..." description) pushed the whole scroll content's
minimumSizeHint to ~1940px -- wider than any normal window -- forcing a
horizontal scrollbar/clip that made the Dashboard look broken regardless of
window size or display scaling. Confirmed via direct offscreen introspection
of the real widget tree, not guessed from screenshots alone.

No display is available in this environment, so this uses Qt's offscreen
platform plugin to instantiate the real screen headlessly.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.dashboard import DashboardScreen, _muted  # noqa: E402

_app = QApplication.instance() or QApplication([])

# A window this narrow with an unwrapped ~1940px-wide label would be forced
# into a horizontal scrollbar; a correctly-wrapping layout should need
# nowhere near this much horizontal room regardless of window width.
_REASONABLE_MAX_MIN_WIDTH = 1000


def test_muted_label_has_word_wrap_enabled():
    label = _muted("Some plain-language planning note that could run long.")
    assert label.wordWrap() is True


def test_dashboard_content_minimum_width_stays_reasonable(tmp_path):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)

    screen = DashboardScreen(services)

    scroll = screen.findChild(QScrollArea)
    assert scroll is not None
    scroll_content = scroll.widget()
    assert scroll_content is not None

    assert scroll_content.minimumSizeHint().width() < _REASONABLE_MAX_MIN_WIDTH
