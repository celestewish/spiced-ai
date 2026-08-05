"""Tests for ui.widgets.progress_trail.ProgressTrail.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_build_scheduler.py) to construct the
real widget headlessly and inspect its state.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.widgets.progress_trail import ProgressTrail  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_progress_trail_starts_hidden_and_empty():
    # A widget never shown on screen (headless, no top-level .show()) is
    # never "visible" per Qt's ancestor-chain isVisible() -- isHidden()
    # instead reflects the explicit setVisible() flag this code actually
    # sets, regardless of whether the window itself was ever shown (same
    # approach as test_prototype_mode.py).
    trail = ProgressTrail()
    assert trail.isHidden() is True
    assert trail.steps() == []


def test_progress_trail_shows_itself_on_first_step():
    trail = ProgressTrail()
    trail.add_step("Running EditMode tests…")
    assert trail.isHidden() is False
    assert trail.steps() == ["Running EditMode tests…"]


def test_progress_trail_appends_in_order():
    trail = ProgressTrail()
    trail.add_step("step one")
    trail.add_step("step two")
    trail.add_step("step three")
    assert trail.steps() == ["step one", "step two", "step three"]


def test_progress_trail_reset_clears_and_hides():
    trail = ProgressTrail()
    trail.add_step("step one")
    trail.reset()
    assert trail.isHidden() is True
    assert trail.steps() == []


def test_progress_trail_reset_then_new_steps_starts_fresh():
    trail = ProgressTrail()
    trail.add_step("old run: step one")
    trail.reset()
    trail.add_step("new run: step one")
    assert trail.steps() == ["new run: step one"]
