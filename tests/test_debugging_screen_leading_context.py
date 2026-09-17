"""DebuggingScreen's "What was happening before this" leading-context
expander.

Unity Alpha Readiness Spec, Priority 3b: a local, AI-free parse populated
as soon as a log is pasted/imported, before Analyze is ever clicked --
reuses SourceLinkExpander (same widget as the post-analysis "Why am I
seeing this?" disclosure) rather than a new one.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching every other screen test.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_leading_context_expander_hidden_with_empty_log(tmp_path):
    screen = DebuggingScreen(_services(tmp_path))
    assert screen._leading_context_expander.isHidden() is True


def test_pasting_a_log_with_no_errors_keeps_it_hidden(tmp_path):
    screen = DebuggingScreen(_services(tmp_path))
    screen._log_input.setPlainText("Everything compiled fine.\nAll good.")
    assert screen._leading_context_expander.isHidden() is True


def test_pasting_a_log_with_leading_lines_populates_the_expander(tmp_path):
    screen = DebuggingScreen(_services(tmp_path))
    screen._log_input.setPlainText(
        "Loading scene DungeonLevel1\n"
        "Player spawned at (0, 1, 0)\n"
        "NullReferenceException: Object reference not set to an instance of an object\n"
        "HealthPickup.OnTriggerEnter2D () (at Assets/Scripts/HealthPickup.cs:24)\n"
    )

    assert screen._leading_context_expander.isHidden() is False
    assert screen._leading_context_expander._description.text() == "What was happening before this"
    body = screen._leading_context_expander._body.text()
    assert "Loading scene DungeonLevel1" in body
    assert "Player spawned at (0, 1, 0)" in body
    # Deliberately not filtered through the exception/compiler regexes --
    # the error line itself shouldn't appear in the "before this" context.
    assert "NullReferenceException" not in body


def test_error_as_the_very_first_line_keeps_expander_hidden(tmp_path):
    # No preceding lines to show -- nothing to disclose.
    screen = DebuggingScreen(_services(tmp_path))
    screen._log_input.setPlainText(
        "NullReferenceException: boom\nFoo.Bar () (at Assets/Scripts/Foo.cs:1)\n"
    )
    assert screen._leading_context_expander.isHidden() is True


def test_clearing_the_log_hides_the_expander_again(tmp_path):
    screen = DebuggingScreen(_services(tmp_path))
    screen._log_input.setPlainText(
        "Loading scene\nNullReferenceException: boom\nFoo.Bar () (at Assets/Scripts/Foo.cs:1)\n"
    )
    assert screen._leading_context_expander.isHidden() is False

    screen._log_input.setPlainText("")

    assert screen._leading_context_expander.isHidden() is True


def test_importing_a_file_populates_the_expander_too(tmp_path):
    """_refresh_leading_context is wired to textChanged, so the import
    buttons (which call setPlainText) trigger it the same as pasting."""
    log_file = tmp_path / "crash.log"
    log_file.write_text(
        "Loading scene\nNullReferenceException: boom\nFoo.Bar () (at Assets/Scripts/Foo.cs:1)\n",
        encoding="utf-8",
    )
    screen = DebuggingScreen(_services(tmp_path))

    screen._log_input.setPlainText(log_file.read_text(encoding="utf-8"))
    screen._pending_filename = log_file.name

    assert screen._leading_context_expander.isHidden() is False
