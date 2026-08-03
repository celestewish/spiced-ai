"""Basic behavior for the shared "Why am I seeing this?" expander (Phase C).

No display is available in this environment, so this uses Qt's offscreen
platform plugin (set before the first PySide6 import) to instantiate real
widgets headlessly rather than skipping widget-level testing entirely.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.widgets.source_link import SourceLinkExpander  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_hidden_until_a_source_is_set():
    widget = SourceLinkExpander()
    assert widget.isVisible() is False


def test_set_source_shows_the_widget_collapsed_by_default():
    widget = SourceLinkExpander()
    widget.set_source("From the pasted crash log excerpt below.", "NullReferenceException...")
    assert widget.isVisible() is True
    assert widget._body.isVisible() is False
    assert widget._description.text() == "From the pasted crash log excerpt below."


def test_toggle_reveals_then_hides_the_excerpt():
    widget = SourceLinkExpander()
    widget.set_source("A description.", "the excerpt text")
    widget._on_toggle_expander()
    assert widget._body.isVisible() is True
    assert widget._body.text() == "the excerpt text"

    widget._on_toggle_expander()
    assert widget._body.isVisible() is False


def test_set_source_none_hides_the_widget_again():
    widget = SourceLinkExpander()
    widget.set_source("A description.", "an excerpt")
    widget.set_source(None, None)
    assert widget.isVisible() is False


def test_missing_excerpt_shows_a_placeholder_instead_of_blank_text():
    widget = SourceLinkExpander()
    widget.set_source("A description.", None)
    assert "no excerpt" in widget._body.text().lower()


def test_readiness_badge_still_toggles_via_the_shared_expander_mixin():
    from spiced.ui.widgets.readiness_badge import ReadinessBadge

    badge = ReadinessBadge()
    # A top-level widget's children only report isVisible()=True once the
    # widget itself has been shown — show() explicitly here (unlike
    # SourceLinkExpander, ReadinessBadge doesn't call setVisible itself).
    badge.show()
    assert badge._body.isVisible() is False
    badge._on_toggle_expander()
    assert badge._body.isVisible() is True
