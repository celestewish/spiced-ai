"""Tests for core.scope_creep: pure, deterministic growth detection over a
crafted Dev Docs snapshot history. No AI, no database — snapshots are built
directly as DevDocsSnapshot dataclasses."""

from __future__ import annotations

from spiced.core.scope_creep import MIN_CLASS_GROWTH, detect_scope_creep
from spiced.storage.dev_docs_snapshots import DevDocsSnapshot


def _snapshot(idx: int, class_names: list[str]) -> DevDocsSnapshot:
    import json

    summary = {
        "file_count": len(class_names),
        "class_count": len(class_names),
        "method_count": 0,
        "classes": [{"name": name, "file": f"{name}.cs", "doc_comment": None, "methods": []}
                    for name in class_names],
    }
    return DevDocsSnapshot(
        id=idx,
        project_id=1,
        source_summary_json=json.dumps(summary),
        ai_summary=None,
        provider=None,
        created_at=f"2026-01-{idx:02d} 00:00:00",
    )


def test_not_enough_snapshots_never_flags_growth():
    snapshots = [_snapshot(1, ["A"]), _snapshot(2, ["A", "B"])]
    finding = detect_scope_creep(snapshots)
    assert finding.growing is False
    assert finding.message is None


def test_stable_class_count_does_not_flag_growth():
    names = ["A", "B", "C"]
    snapshots = [_snapshot(i, names) for i in range(1, 6)]
    finding = detect_scope_creep(snapshots)
    assert finding.growing is False
    assert finding.message is None


def test_sustained_one_directional_growth_flags_scope_creep():
    base = ["A", "B", "C"]
    snapshots = [
        _snapshot(1, base),
        _snapshot(2, base + ["D"]),
        _snapshot(3, base + ["D", "E"]),
        _snapshot(4, base + ["D", "E", "F", "G", "H"]),  # total growth: +5, clears the bar
    ]
    finding = detect_scope_creep(snapshots)
    assert finding.growing is True
    assert finding.message is not None
    assert "heads-up" in finding.message
    assert set(finding.new_class_names) == {"D", "E", "F", "G", "H"}
    assert len(finding.new_class_names) == MIN_CLASS_GROWTH


def test_growth_that_shrinks_at_any_point_is_not_sustained():
    snapshots = [
        _snapshot(1, ["A", "B", "C"]),
        _snapshot(2, ["A", "B", "C", "D", "E", "F", "G"]),
        _snapshot(3, ["A", "B", "C"]),  # dropped back down -- not one-directional
    ]
    finding = detect_scope_creep(snapshots)
    assert finding.growing is False


def test_growth_below_the_noise_floor_is_not_flagged():
    base = ["A", "B", "C"]
    snapshots = [
        _snapshot(1, base),
        _snapshot(2, base + ["D"]),
        _snapshot(3, base + ["D", "E"]),  # only +2, below MIN_CLASS_GROWTH
    ]
    finding = detect_scope_creep(snapshots)
    assert finding.growing is False


def test_new_classes_not_in_design_doc_are_flagged_as_undocumented():
    base = ["PlayerController"]
    snapshots = [
        _snapshot(1, base),
        _snapshot(2, base + ["EnemyAI"]),
        _snapshot(3, base + ["EnemyAI", "LootSystem", "CraftingSystem", "GuildSystem", "PvpArena"]),
    ]
    # The undocumented-check is a plain substring match against the design
    # doc text (see core.scope_creep's docstring on that trade-off), so the
    # doc needs to reference the class name itself, not just describe its
    # behavior in different words.
    design_doc_text = "This game features a PlayerController and an EnemyAI."

    finding = detect_scope_creep(snapshots, design_doc_text=design_doc_text)

    assert finding.growing is True
    # EnemyAI is mentioned in the design doc; the rest are not.
    assert "EnemyAI" not in finding.undocumented_new_classes
    assert "LootSystem" in finding.undocumented_new_classes
    assert "GuildSystem" in finding.undocumented_new_classes
    assert finding.message is not None
    assert "design doc" in finding.message
