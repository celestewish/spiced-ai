"""Tests for automation.finding: the shared Finding/FindingItem schema
every Bible automation feature (#1-13) returns (SPICED_IMPLEMENTATION_BIBLE.md,
section 0)."""

from __future__ import annotations

import pytest

from spiced.automation.finding import (
    STATUS_ERROR,
    STATUS_FLAGGED,
    STATUS_PASS,
    Finding,
    FindingItem,
    InvalidFindingError,
)


def test_finding_item_rejects_invalid_severity():
    with pytest.raises(InvalidFindingError):
        FindingItem(asset_path="a.png", severity="critical", message="bad")


def test_finding_rejects_invalid_status():
    with pytest.raises(InvalidFindingError):
        Finding(feature_id="art.asset_scan", project_id="1", status="ok", summary="x")


def test_finding_auto_fills_run_id_and_timestamp():
    f = Finding(feature_id="art.asset_scan", project_id="1", status=STATUS_PASS, summary="x")
    assert f.run_id
    assert f.timestamp


def test_status_for_rolls_up_to_error_over_warning():
    items = [
        FindingItem(asset_path="a", severity="info", message="fine"),
        FindingItem(asset_path="b", severity="warning", message="hmm"),
        FindingItem(asset_path="c", severity="error", message="broken"),
    ]
    assert Finding.status_for(items) == STATUS_ERROR


def test_status_for_flagged_when_only_warnings():
    items = [FindingItem(asset_path="a", severity="warning", message="hmm")]
    assert Finding.status_for(items) == STATUS_FLAGGED


def test_status_for_pass_when_no_items():
    assert Finding.status_for([]) == STATUS_PASS


def test_finding_as_dict_matches_bible_schema_shape():
    item = FindingItem(
        asset_path="a.png", severity="warning", message="too big", detail={"kb": 500}
    )
    f = Finding(
        feature_id="art.asset_technical_qa",
        project_id="42",
        status=STATUS_FLAGGED,
        summary="1 issue flagged",
        items=[item],
        run_id="fixed-run-id",
        timestamp="2026-08-09T00:00:00+00:00",
    )
    assert f.as_dict() == {
        "feature_id": "art.asset_technical_qa",
        "run_id": "fixed-run-id",
        "project_id": "42",
        "timestamp": "2026-08-09T00:00:00+00:00",
        "status": "flagged",
        "summary": "1 issue flagged",
        "items": [
            {
                "asset_path": "a.png",
                "severity": "warning",
                "message": "too big",
                "detail": {"kb": 500},
            }
        ],
    }


def test_severity_counts():
    items = [
        FindingItem(asset_path="a", severity="info", message="x"),
        FindingItem(asset_path="b", severity="info", message="x"),
        FindingItem(asset_path="c", severity="warning", message="x"),
    ]
    f = Finding(feature_id="x", project_id="1", status=STATUS_FLAGGED, summary="s", items=items)
    assert f.severity_counts == {"info": 2, "warning": 1, "error": 0}
