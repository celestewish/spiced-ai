"""Offscreen Qt smoke test for the Art screen's Retopology Assist section
(Implementation Bible, Feature 10) -- exercises the wiring methods
directly with a real Finding, the same convention as this app's other
screen tests (see tests/test_diff_viewer_consumers.py)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.automation.retopology_assist import (  # noqa: E402
    Finding,
    FindingItem,
    RetopologyRunResult,
)
from spiced.ui.screens.art import ArtScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_retopology_section_constructs_with_placeholders(tmp_path):
    screen = ArtScreen(_services(tmp_path))
    assert screen._retopo_run_btn.isEnabled() is True
    assert screen._retopo_result.toPlainText() == ""


def test_retopology_on_done_renders_plain_language_not_json(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = ArtScreen(services)

    finding = Finding(
        feature_id="art.retopology_assist", project_id=str(project.id), status="flagged",
        summary="Remeshed to 5000 face(s), 96.0% quad, 3 non-manifold edge(s).",
        items=[
            FindingItem(asset_path="mesh.obj", severity="info", message="320 -> 5000 face(s)."),
            FindingItem(asset_path="mesh.obj", severity="warning",
                        message="3 non-manifold edge(s) in the remesh."),
        ],
    )
    result = RetopologyRunResult(finding=finding, output_path="mesh_retopo.obj")

    screen._on_retopo_done(result)

    text = screen._retopo_result.toPlainText()
    assert "{" not in text  # not raw JSON
    assert "non-manifold" in text
    assert finding.summary in text


def test_retopology_run_requires_a_mesh_file(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = ArtScreen(services)

    shown = []
    monkeypatch.setattr(
        "spiced.ui.screens.art.QMessageBox.information", lambda *a, **k: shown.append(True)
    )
    screen._retopo_mesh_input.setText("")
    screen._on_retopo_run()
    assert shown == [True]


def test_retopology_history_before_project_selected(tmp_path):
    screen = ArtScreen(_services(tmp_path))
    screen._refresh_retopo_history()
    assert "active project" in screen._retopo_history.toPlainText()


def test_retopology_history_refreshes_after_done(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = ArtScreen(services)

    finding = Finding(
        feature_id="art.retopology_assist", project_id=str(project.id), status="pass",
        summary="Remeshed to 5000 face(s), 98.0% quad, 0 non-manifold edge(s).",
    )
    services.retopology_assist._findings.create(project.id, finding)

    screen._refresh_retopo_history()
    assert "No runs saved yet." not in screen._retopo_history.toPlainText()
