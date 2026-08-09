"""Tests for storage.automation_findings.AutomationFindingRepository: the
shared persistence table every Bible automation feature's Finding is saved
into (SPICED_IMPLEMENTATION_BIBLE.md, Feature 0 foundation)."""

from __future__ import annotations

import pytest

from spiced.automation.finding import STATUS_FLAGGED, STATUS_PASS, Finding, FindingItem
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _setup():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths", engine="Unity")
    return projects, findings, project


def test_create_and_get_round_trips():
    _, findings, project = _setup()
    item = FindingItem(asset_path="sfx/hit.wav", severity="warning", message="too quiet")
    finding = Finding(
        feature_id="audio.loudness_normalize",
        project_id=str(project.id),
        status=STATUS_FLAGGED,
        summary="1 file flagged",
        items=[item],
    )

    record = findings.create(project.id, finding)

    assert record.id is not None
    assert record.run_id == finding.run_id
    assert record.feature_id == "audio.loudness_normalize"
    assert record.project_id == project.id
    assert record.status == STATUS_FLAGGED
    assert record.summary == "1 file flagged"
    assert record.items == [item.as_dict()]


def test_get_by_run_id():
    _, findings, project = _setup()
    finding = Finding(
        feature_id="vfx.visual_regression",
        project_id=str(project.id),
        status=STATUS_PASS,
        summary="no changes",
    )
    findings.create(project.id, finding)

    fetched = findings.get_by_run_id(finding.run_id)
    assert fetched is not None
    assert fetched.feature_id == "vfx.visual_regression"


def test_get_by_run_id_missing_returns_none():
    _, findings, _project = _setup()
    assert findings.get_by_run_id("does-not-exist") is None


def test_get_missing_id_raises_key_error():
    _, findings, _project = _setup()
    with pytest.raises(KeyError):
        findings.get(999)


def test_list_for_project_orders_newest_first_and_filters_by_feature():
    _, findings, project = _setup()
    f1 = Finding(
        feature_id="audio.mix_qa", project_id=str(project.id), status=STATUS_PASS, summary="a"
    )
    f2 = Finding(
        feature_id="vfx.visual_regression",
        project_id=str(project.id),
        status=STATUS_PASS,
        summary="b",
    )
    findings.create(project.id, f1)
    findings.create(project.id, f2)

    all_records = findings.list_for_project(project.id)
    assert len(all_records) == 2

    audio_only = findings.list_for_project(project.id, feature_id="audio.mix_qa")
    assert len(audio_only) == 1
    assert audio_only[0].feature_id == "audio.mix_qa"


def test_list_for_project_scoped_per_project():
    projects, findings, project_a = _setup()
    project_b = projects.create("Second Project")
    findings.create(
        project_a.id,
        Finding(
            feature_id="audio.mix_qa",
            project_id=str(project_a.id),
            status=STATUS_PASS,
            summary="a",
        ),
    )

    assert len(findings.list_for_project(project_a.id)) == 1
    assert len(findings.list_for_project(project_b.id)) == 0
