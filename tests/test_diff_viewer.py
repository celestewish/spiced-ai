"""Tests for ui.widgets.diff_viewer.

``diff_text`` is pure/GUI-free and tested directly. The widget classes
(``DiffViewer``/``DiffViewerDialog``) are exercised headlessly via Qt's
offscreen platform plugin (same approach as test_build_scheduler.py) for
both text and image modes, using tiny Pillow-generated images so no test
fixtures are needed on disk beyond what the test itself creates.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.widgets.diff_viewer import DiffViewer, diff_text  # noqa: E402

_app = QApplication.instance() or QApplication([])


# --- diff_text (pure) --------------------------------------------------------


def test_diff_text_identical_inputs_have_no_unified_differences():
    result = diff_text("line one\nline two", "line one\nline two")
    assert result.unified == ""
    assert result.has_differences is False
    assert result.left_rows == ["line one", "line two"]
    assert result.right_rows == ["line one", "line two"]


def test_diff_text_detects_a_changed_line():
    left = "alpha\nbeta\ngamma"
    right = "alpha\nBETA\ngamma"
    result = diff_text(left, right, left_label="v1", right_label="v2")
    assert result.has_differences is True
    assert "-beta" in result.unified
    assert "+BETA" in result.unified
    assert "v1" in result.unified
    assert "v2" in result.unified


def test_diff_text_side_by_side_rows_stay_aligned_on_insertion():
    left = "one\ntwo"
    right = "one\ntwo\nthree"
    result = diff_text(left, right)
    assert len(result.left_rows) == len(result.right_rows)
    # The inserted line pads the left column with "".
    assert result.right_rows[-1] == "three"
    assert result.left_rows[-1] == ""


def test_diff_text_side_by_side_rows_stay_aligned_on_deletion():
    left = "one\ntwo\nthree"
    right = "one\ntwo"
    result = diff_text(left, right)
    assert len(result.left_rows) == len(result.right_rows)
    assert result.left_rows[-1] == "three"
    assert result.right_rows[-1] == ""


def test_diff_text_empty_inputs():
    result = diff_text("", "")
    assert result.unified == ""
    assert result.left_rows == []
    assert result.right_rows == []


# --- DiffViewer widget: text mode -------------------------------------------


def test_diff_viewer_set_text_defaults_to_side_by_side():
    viewer = DiffViewer()
    viewer.set_text("alpha\nbeta", "alpha\nBETA", left_label="Before", right_label="After")
    assert viewer._mode == "text"
    assert viewer._side_by_side is True
    assert viewer._body.count() == 1  # one wrapper widget holding the two columns


def test_diff_viewer_toggle_switches_to_unified():
    viewer = DiffViewer()
    viewer.set_text("alpha\nbeta", "alpha\nBETA")
    viewer._on_toggle()
    assert viewer._side_by_side is False
    viewer._on_toggle()
    assert viewer._side_by_side is True


# --- DiffViewer widget: image mode (reuses core.visual_regression) ---------


def _write_image(path, color) -> None:
    Image.new("RGB", (20, 20), color=color).save(path)


def test_diff_viewer_set_images_identical_reports_zero_ratio(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _write_image(before, (10, 10, 10))
    _write_image(after, (10, 10, 10))

    viewer = DiffViewer()
    viewer.set_images(before, after)
    assert viewer._mode == "image"
    assert viewer._diff_ratio == 0.0


def test_diff_viewer_set_images_changed_pixels_reports_nonzero_ratio(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _write_image(before, (0, 0, 0))
    _write_image(after, (255, 255, 255))

    viewer = DiffViewer()
    viewer.set_images(before, after)
    assert viewer._diff_ratio == 1.0


def test_diff_viewer_image_toggle_switches_to_overlay(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _write_image(before, (0, 0, 0))
    _write_image(after, (255, 255, 255))

    viewer = DiffViewer()
    viewer.set_images(before, after)
    assert viewer._side_by_side is True
    viewer._on_toggle()
    assert viewer._side_by_side is False
