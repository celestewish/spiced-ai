"""Tests for core.grant_finder: the static, curated dataset and its filtering logic."""

from __future__ import annotations

from spiced.core.grant_finder import GRANTS, find_grants


def test_dataset_has_exactly_the_three_verified_entries():
    keys = {g.key for g in GRANTS}
    assert keys == {"epic_megagrants", "uk_games_fund", "igda_foundation"}


def test_every_entry_has_a_verify_note_and_url():
    for grant in GRANTS:
        assert grant.url.startswith("https://")
        assert "verify" in grant.verify_note.lower()
        assert grant.url in grant.verify_note


def test_find_grants_with_no_filters_returns_everything():
    assert find_grants() == list(GRANTS)


def test_find_grants_filters_out_region_locked_entry_for_other_regions():
    results = find_grants(region="United States")
    names = {g.name for g in results}
    assert "UK Games Fund" not in names
    assert "Epic MegaGrants" in names
    assert "IGDA Foundation" in names


def test_find_grants_matches_region_locked_entry_for_its_region():
    results = find_grants(region="UK")
    names = {g.name for g in results}
    assert "UK Games Fund" in names


def test_find_grants_filters_by_project_type():
    results = find_grants(project_type="Unity")
    names = {g.name for g in results}
    # Epic MegaGrants is scoped to Unreal/UEFN, not Unity.
    assert "Epic MegaGrants" not in names
    assert "UK Games Fund" in names
    assert "IGDA Foundation" in names


def test_find_grants_matches_project_type_for_its_engine():
    results = find_grants(project_type="Unreal")
    names = {g.name for g in results}
    assert "Epic MegaGrants" in names


def test_find_grants_broadly_applicable_entry_always_included():
    # IGDA Foundation has no region/project_type/stage tags, so it should
    # always be returned regardless of filters.
    for kwargs in (
        {"region": "Japan"},
        {"project_type": "Godot"},
        {"stage": "post-launch"},
    ):
        names = {g.name for g in find_grants(**kwargs)}
        assert "IGDA Foundation" in names
