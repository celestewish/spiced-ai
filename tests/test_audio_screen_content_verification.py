"""Offscreen Qt smoke test for the Audio screen's Localization Content
Verification section (Implementation Bible, Feature 13) -- exercises the
wiring methods directly with a real Finding, the same convention as this
app's other screen tests (see tests/test_diff_viewer_consumers.py)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.automation.localization_content_verification import (  # noqa: E402
    FEATURE_ID,
    Finding,
    FindingItem,
)
from spiced.ui.screens.audio import AudioScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_content_verification_section_constructs_with_placeholders(tmp_path):
    screen = AudioScreen(_services(tmp_path))
    assert screen._cv_run_btn.isEnabled() is True
    assert screen._cv_result.toPlainText() == ""


def test_content_verification_on_done_renders_plain_language_not_json(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AudioScreen(services)

    finding = Finding(
        feature_id=FEATURE_ID, project_id=str(project.id), status="flagged",
        summary="Checked 2 line(s); 1 content mismatch(es) found.",
        items=[
            FindingItem(
                asset_path="line001.wav", severity="warning",
                message="line001: similarity 0.10 (below threshold 0.60).",
                detail={"issue_type": "content_mismatch", "line_id": "line001"},
            ),
            FindingItem(
                asset_path="line002.wav", severity="info",
                message="line002: similarity 0.95 (at/above threshold 0.60).",
                detail={"issue_type": "content_match", "line_id": "line002"},
            ),
        ],
    )

    screen._on_cv_done(finding)

    text = screen._cv_result.toPlainText()
    assert "{" not in text  # not raw JSON
    assert "line001" in text
    assert finding.summary in text


def test_content_verification_run_requires_script_and_folder(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AudioScreen(services)

    shown = []
    monkeypatch.setattr(
        "spiced.ui.screens.audio.QMessageBox.information", lambda *a, **k: shown.append(True)
    )
    screen._cv_script_input.setPlainText("")
    screen._cv_folder_input.setText("")
    screen._on_cv_run()
    assert shown == [True]


def test_content_verification_history_before_project_selected(tmp_path):
    screen = AudioScreen(_services(tmp_path))
    screen._refresh_cv_history()
    assert "active project" in screen._cv_history.toPlainText()


def test_content_verification_history_refreshes_after_done(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AudioScreen(services)

    finding = Finding(
        feature_id=FEATURE_ID, project_id=str(project.id), status="pass",
        summary="Checked 1 line(s); all match the script text.",
    )
    services.localization_content_verification._findings.create(project.id, finding)

    screen._refresh_cv_history()
    assert "No checks saved yet." not in screen._cv_history.toPlainText()
