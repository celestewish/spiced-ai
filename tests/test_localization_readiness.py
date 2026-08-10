"""Tests for core.localization_readiness: the hardcoded-string/prefab-text heuristic."""

from __future__ import annotations

import pytest

from spiced.core.localization_readiness import (
    HEURISTIC_CAVEAT,
    LocalizationReadinessService,
    NoUnityFolderError,
    scan_localization_readiness,
)
from spiced.storage.database import Database
from spiced.storage.localization_readiness_reports import LocalizationReadinessReportRepository
from spiced.storage.projects import ProjectRepository


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_flags_hardcoded_ui_string_with_high_confidence(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "DialogueBox.cs",
        'public class DialogueBox {\n'
        '    void Show() {\n'
        '        dialogueText.text = "Welcome to the dungeon, traveler!";\n'
        '    }\n'
        '}\n',
    )
    scan = scan_localization_readiness(tmp_path)
    assert scan.scripts_scanned == 1
    matches = [f for f in scan.hardcoded_strings if f.text == "Welcome to the dungeon, traveler!"]
    assert len(matches) == 1
    assert matches[0].confidence == "high"


def test_scan_does_not_flag_short_identifier_like_or_path_literals(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "SaveSystem.cs",
        'public class SaveSystem {\n'
        '    const string Key = "PlayerPrefsKey";\n'
        '    string iconPath = "Assets/Resources/icon.png";\n'
        '    void Log() { Debug.Log("ok"); }\n'
        '}\n',
    )
    scan = scan_localization_readiness(tmp_path)
    assert scan.scripts_scanned == 1
    flagged_texts = {f.text for f in scan.hardcoded_strings}
    assert "PlayerPrefsKey" not in flagged_texts
    assert "Assets/Resources/icon.png" not in flagged_texts
    assert "ok" not in flagged_texts  # too short (below MIN_STRING_LENGTH)


def test_scan_flags_long_sentence_like_literal_as_low_confidence_without_ui_hint(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "Notes.cs",
        'public class Notes {\n'
        '    string note = "This is a fairly long comment string in the code";\n'
        '}\n',
    )
    scan = scan_localization_readiness(tmp_path)
    matches = [
        f for f in scan.hardcoded_strings
        if f.text == "This is a fairly long comment string in the code"
    ]
    assert len(matches) == 1
    assert matches[0].confidence == "low"


def test_scan_flags_prefab_text_without_placeholder(tmp_path):
    _write(
        tmp_path / "Assets" / "UI" / "StartButton.prefab",
        "MonoBehaviour:\n"
        "  m_Text: Press Start to Begin\n"
        "  m_FontSize: 24\n",
    )
    scan = scan_localization_readiness(tmp_path)
    assert scan.prefabs_scanned == 1
    texts = [f.text for f in scan.prefab_texts]
    assert "Press Start to Begin" in texts


def test_scan_does_not_flag_prefab_text_with_placeholder(tmp_path):
    _write(
        tmp_path / "Assets" / "UI" / "ScoreLabel.prefab",
        "MonoBehaviour:\n"
        "  m_Text: '{0} Points'\n",
    )
    scan = scan_localization_readiness(tmp_path)
    assert scan.prefabs_scanned == 1
    assert scan.prefab_texts == []


def test_scan_returns_empty_result_for_missing_assets_folder(tmp_path):
    scan = scan_localization_readiness(tmp_path)
    assert scan.scripts_scanned == 0
    assert scan.prefabs_scanned == 0
    assert scan.hardcoded_strings == []
    assert scan.prefab_texts == []


def test_service_scan_raises_without_project_path():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")  # no path set
    service = LocalizationReadinessService(LocalizationReadinessReportRepository(db))
    with pytest.raises(NoUnityFolderError):
        service.scan(project)


def test_service_scan_saves_a_report(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "DialogueBox.cs",
        'dialogueText.text = "Welcome to the dungeon, traveler!";\n',
    )
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    service = LocalizationReadinessService(LocalizationReadinessReportRepository(db))

    scan, report = service.scan(project)
    assert scan.scripts_scanned == 1
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].id == report.id
    assert history[0].findings["scripts_scanned"] == 1


def test_heuristic_caveat_explains_the_real_limits_without_hedging():
    caveat = HEURISTIC_CAVEAT.lower()
    # Still honest about what the heuristic can miss/over-flag...
    assert "can miss" in caveat
    assert "can flag" in caveat
    # ...but doesn't fall back on vague "not certainty" hedge framing.
    assert "not certainty" not in caveat
    assert "not a confirmed defect" not in caveat
