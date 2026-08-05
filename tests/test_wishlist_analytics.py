"""Tests for core.wishlist_analytics: CSV parsing + local diff logic.

No AI provider is involved here at all — the digest is a purely local,
deterministic diff, which is itself part of what's being verified (this
feature is scoped down from a live Steam/itch API to a paste/import CSV
workflow; see the module docstring).
"""

from __future__ import annotations

import pytest

from spiced.core.wishlist_analytics import (
    InvalidAnalyticsFormatError,
    WishlistAnalyticsService,
    diff_metrics,
    parse_metrics_csv,
    summarize_digest,
)
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.wishlist_analytics_imports import WishlistAnalyticsImportRepository

SAMPLE_CSV = "metric,value\nwishlists,1240\nconversion_pct,3.8\nvisits,15300\ntop_referrer,twitter"


def test_parse_metrics_csv_reads_documented_format():
    metrics = parse_metrics_csv(SAMPLE_CSV)
    assert metrics == {
        "wishlists": "1240",
        "conversion_pct": "3.8",
        "visits": "15300",
        "top_referrer": "twitter",
    }


def test_parse_metrics_csv_rejects_missing_columns():
    with pytest.raises(InvalidAnalyticsFormatError):
        parse_metrics_csv("name,count\nwishlists,1240")


def test_parse_metrics_csv_rejects_empty_input():
    with pytest.raises(InvalidAnalyticsFormatError):
        parse_metrics_csv("metric,value\n")


def test_diff_metrics_computes_numeric_delta():
    previous = {"wishlists": "1000"}
    current = {"wishlists": "1200"}
    changes = diff_metrics(previous, current)
    assert changes[0].metric == "wishlists"
    assert changes[0].delta == pytest.approx(200.0)


def test_diff_metrics_handles_no_previous():
    changes = diff_metrics(None, {"wishlists": "1200"})
    assert changes[0].previous is None
    assert changes[0].delta is None


def test_diff_metrics_flags_opaque_string_change():
    changes = diff_metrics({"top_referrer": "twitter"}, {"top_referrer": "reddit"})
    assert changes[0].delta is None
    assert changes[0].previous == "twitter"
    assert changes[0].current == "reddit"


def test_summarize_digest_first_import():
    lines = summarize_digest([], is_first_import=True)
    assert "First import" in lines[0]


def test_summarize_digest_reports_up_down_flat():
    changes = diff_metrics(
        {"wishlists": "1000", "conversion_pct": "3.8", "visits": "500"},
        {"wishlists": "1200", "conversion_pct": "3.8", "visits": "400"},
    )
    lines = summarize_digest(changes, is_first_import=False)
    joined = " ".join(lines)
    assert "wishlists: up" in joined
    assert "visits: down" in joined
    assert "conversion_pct: flat" in joined


def test_service_import_csv_diffs_against_previous():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = WishlistAnalyticsService(WishlistAnalyticsImportRepository(db))

    first = service.import_csv(project, SAMPLE_CSV)
    assert first.is_first_import is True

    second_csv = (
        "metric,value\nwishlists,1400\nconversion_pct,4.0\nvisits,16000\ntop_referrer,reddit"
    )
    second = service.import_csv(project, second_csv)
    assert second.is_first_import is False
    joined = " ".join(second.summary_lines)
    assert "wishlists: up from 1240 to 1400" in joined

    history = service.history(project.id)
    assert len(history) == 2


def test_service_import_csv_raises_on_bad_format():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = WishlistAnalyticsService(WishlistAnalyticsImportRepository(db))
    with pytest.raises(InvalidAnalyticsFormatError):
        service.import_csv(project, "not,a,valid,format")
