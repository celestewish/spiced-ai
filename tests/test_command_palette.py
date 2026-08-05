"""Command Palette filtering tests (Phase K, section 9 part 1, Core tier).

Tests ``filter_items`` directly -- no GUI event simulation needed, per the
phase brief. ``CommandPalette`` (the QDialog itself) is only covered by the
import-cleanliness check in test_team_ui_imports.py, since there's no
display available in this environment.
"""

from __future__ import annotations

from spiced.ui.command_palette import PaletteItem, filter_items


def _item(label: str, subtitle: str = "", kind: str = "page") -> PaletteItem:
    return PaletteItem(kind=kind, label=label, subtitle=subtitle, action=lambda: None)


def test_empty_query_returns_every_item_in_order():
    items = [_item("Dashboard"), _item("Projects"), _item("Settings")]
    assert filter_items(items, "") == items
    assert filter_items(items, "   ") == items


def test_substring_match_is_case_insensitive():
    items = [_item("Debugging Buddy"), _item("Automated Testing")]
    assert filter_items(items, "debug") == [items[0]]
    assert filter_items(items, "DEBUG") == [items[0]]


def test_substring_match_checks_subtitle_too():
    items = [
        _item("Moonlit Depths", subtitle="Switch to this project", kind="project"),
        _item("Dashboard", subtitle="Page", kind="page"),
    ]
    assert filter_items(items, "switch") == [items[0]]


def test_no_substring_hit_falls_back_to_fuzzy_match():
    items = [_item("Debugging Buddy"), _item("Feedback Review")]
    # A typo close to "Debugging" but not a substring anywhere.
    result = filter_items(items, "Debuging")
    assert items[0] in result


def test_no_match_at_all_returns_empty():
    items = [_item("Dashboard"), _item("Settings")]
    assert filter_items(items, "zzzzzzzzzzzz") == []


def test_multiple_substring_hits_preserve_input_order():
    items = [_item("Automated Testing"), _item("Testing history"), _item("Dashboard")]
    result = filter_items(items, "test")
    assert result == [items[0], items[1]]
