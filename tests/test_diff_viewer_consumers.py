"""Tests for the Visual Diff Viewer's two real consumers (Phase L):

1. Shaders/VFX's Visual Regression Testing report (image mode).
2. Debugging Buddy's Dev Docs snapshot history (text mode).

Headless (Qt offscreen platform) -- exercises the wiring methods directly
rather than simulating clicks, same convention as this app's other screen
tests (e.g. test_prototype_mode.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core.visual_regression import VisualRegressionResult  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen  # noqa: E402
from spiced.ui.screens.shaders_vfx import ShadersVfxScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


# --- Consumer 1: Shaders/VFX Visual Regression report -----------------------


def test_shaders_vfx_screen_pair_picker_populated_after_diff(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = ShadersVfxScreen(services)

    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(before_dir / "scene1.png")
    Image.new("RGB", (10, 10), (255, 255, 255)).save(after_dir / "scene1.png")

    result, _report = services.visual_regression.diff(project, str(before_dir), str(after_dir))
    assert isinstance(result, VisualRegressionResult)
    screen._on_vr_done(result)

    assert screen._vr_pair_picker.isEnabled() is True
    assert screen._vr_open_diff_btn.isEnabled() is True
    assert screen._vr_pair_picker.count() == 1
    assert "scene1.png" in screen._vr_pair_picker.itemText(0)
    assert "scene1.png" in screen._vr_pairs_by_name


def test_shaders_vfx_screen_pair_picker_disabled_before_any_run(tmp_path):
    services = _services(tmp_path)
    screen = ShadersVfxScreen(services)
    assert screen._vr_pair_picker.isEnabled() is False
    assert screen._vr_open_diff_btn.isEnabled() is False


def test_shaders_vfx_diff_viewer_dialog_opens_for_picked_pair(tmp_path):
    """Exercises the same DiffViewerDialog.for_images call _on_view_diff_pair
    makes, confirming it doesn't raise for a real matched pair's file paths."""
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = ShadersVfxScreen(services)

    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(before_dir / "scene1.png")
    Image.new("RGB", (10, 10), (255, 255, 255)).save(after_dir / "scene1.png")
    result, _report = services.visual_regression.diff(project, str(before_dir), str(after_dir))
    screen._on_vr_done(result)

    from spiced.ui.widgets.diff_viewer import DiffViewerDialog

    pair = screen._vr_pairs_by_name["scene1.png"]
    dialog = DiffViewerDialog.for_images(pair.before_path, pair.after_path, parent=screen)
    assert dialog.viewer._mode == "image"


# --- Consumer 2: Debugging Buddy Dev Docs snapshot comparison ---------------


def test_compare_dev_docs_snapshots_requires_two_snapshots(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = DebuggingScreen(services)

    shown = []
    monkeypatch.setattr(
        "spiced.ui.screens.debugging.QMessageBox.information",
        lambda *a, **k: shown.append(True),
    )
    screen._on_compare_dev_docs_snapshots()
    assert shown == [True]  # not enough snapshots yet


def test_compare_dev_docs_snapshots_opens_diff_dialog(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    services.dev_docs._snapshots.create(
        project_id=project.id, source_summary={"class_count": 1}, ai_summary="First summary."
    )
    services.dev_docs._snapshots.create(
        project_id=project.id, source_summary={"class_count": 2}, ai_summary="Second summary."
    )
    screen = DebuggingScreen(services)

    opened = []
    from spiced.ui.widgets.diff_viewer import DiffViewerDialog

    original_for_text = DiffViewerDialog.for_text

    def _capture(*args, **kwargs):
        dialog = original_for_text(*args, **kwargs)
        opened.append(dialog)
        return dialog

    monkeypatch.setattr(
        "spiced.ui.screens.debugging.DiffViewerDialog.for_text", staticmethod(_capture)
    )
    monkeypatch.setattr(
        "spiced.ui.screens.debugging.DiffViewerDialog.exec", lambda self: None
    )
    screen._on_compare_dev_docs_snapshots()

    assert len(opened) == 1
    assert opened[0].viewer._mode == "text"
    assert "First summary." in opened[0].viewer._text_result.left_rows
    assert "Second summary." in opened[0].viewer._text_result.right_rows
