"""Tests for core.widget_preferences (pure, GUI-free) plus a headless
round-trip through ContextPanel/DashboardScreen's persistence.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core.widget_preferences import (  # noqa: E402
    CONTEXT_PANEL_WIDGETS,
    DASHBOARD_WIDGETS,
    WidgetPreference,
    WidgetSpec,
    dump_preferences,
    load_preferences,
    merge_and_dump,
    ordered_visible_ids,
)
from spiced.ui.context_panel import ContextPanel  # noqa: E402
from spiced.ui.screens.dashboard import DashboardScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])

_SPECS = [WidgetSpec("a", "Widget A"), WidgetSpec("b", "Widget B"), WidgetSpec("c", "Widget C")]


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


# --- load_preferences ---------------------------------------------------------


def test_load_preferences_defaults_when_nothing_saved():
    prefs = load_preferences(None, _SPECS)
    assert prefs["a"] == WidgetPreference(visible=True, order=0)
    assert prefs["b"] == WidgetPreference(visible=True, order=1)
    assert prefs["c"] == WidgetPreference(visible=True, order=2)


def test_load_preferences_defaults_on_corrupt_json():
    prefs = load_preferences("{not valid json", _SPECS)
    assert all(p.visible for p in prefs.values())


def test_load_preferences_defaults_when_json_is_not_a_dict():
    prefs = load_preferences("[1, 2, 3]", _SPECS)
    assert all(p.visible for p in prefs.values())


def test_load_preferences_reads_saved_visibility_and_order():
    raw = dump_preferences(
        {
            "a": WidgetPreference(visible=False, order=2),
            "b": WidgetPreference(visible=True, order=0),
        }
    )
    prefs = load_preferences(raw, _SPECS)
    assert prefs["a"] == WidgetPreference(visible=False, order=2)
    assert prefs["b"] == WidgetPreference(visible=True, order=0)
    # "c" wasn't in the saved blob -- falls back to its declared default.
    assert prefs["c"] == WidgetPreference(visible=True, order=2)


def test_load_preferences_ignores_malformed_per_widget_entry():
    raw = '{"a": "not-a-dict", "b": {"visible": "yes", "order": "not-a-number"}}'
    prefs = load_preferences(raw, _SPECS)
    assert prefs["a"] == WidgetPreference(visible=True, order=0)  # malformed -> default
    assert prefs["b"].visible is True  # truthy string coerces to True
    assert prefs["b"].order == 1  # bad order falls back to declared default


# --- merge_and_dump -----------------------------------------------------------


def test_merge_and_dump_preserves_other_groups_entries():
    existing = dump_preferences({"context_a": WidgetPreference(visible=False, order=0)})
    merged = merge_and_dump(existing, {"dashboard_a": WidgetPreference(visible=True, order=0)})
    reloaded = load_preferences(
        merged, [WidgetSpec("context_a", "x"), WidgetSpec("dashboard_a", "y")]
    )
    assert reloaded["context_a"].visible is False
    assert reloaded["dashboard_a"].visible is True


def test_merge_and_dump_overwrites_only_given_ids():
    existing = dump_preferences({"a": WidgetPreference(visible=True, order=0)})
    merged = merge_and_dump(existing, {"a": WidgetPreference(visible=False, order=5)})
    reloaded = load_preferences(merged, _SPECS)
    assert reloaded["a"] == WidgetPreference(visible=False, order=5)


def test_merge_and_dump_handles_missing_existing_blob():
    merged = merge_and_dump(None, {"a": WidgetPreference(visible=False, order=1)})
    reloaded = load_preferences(merged, _SPECS)
    assert reloaded["a"].visible is False


# --- ordered_visible_ids -------------------------------------------------------


def test_ordered_visible_ids_hides_and_sorts():
    prefs = {
        "a": WidgetPreference(visible=True, order=2),
        "b": WidgetPreference(visible=False, order=0),
        "c": WidgetPreference(visible=True, order=1),
    }
    assert ordered_visible_ids(prefs, _SPECS) == ["c", "a"]


def test_ordered_visible_ids_ignores_unknown_ids():
    prefs = {
        "a": WidgetPreference(visible=True, order=0),
        "not_a_known_widget": WidgetPreference(visible=True, order=1),
    }
    assert ordered_visible_ids(prefs, _SPECS) == ["a"]


# --- Round trip through Services + real screens (headless) -------------------


def test_context_panel_widget_ids_are_all_real_context_panel_sections(tmp_path):
    """Every declared id must have a real, built section -- otherwise a
    saved preference for it would silently do nothing."""
    services = _services(tmp_path)
    panel = ContextPanel(services)
    for spec in CONTEXT_PANEL_WIDGETS:
        assert spec.id in panel._section_widgets


def test_context_panel_hides_a_section_per_saved_preference(tmp_path):
    services = _services(tmp_path)
    prefs = {
        spec.id: WidgetPreference(visible=True, order=i)
        for i, spec in enumerate(CONTEXT_PANEL_WIDGETS)
    }
    prefs["usage"] = WidgetPreference(visible=False, order=prefs["usage"].order)
    services.set_widget_preferences_json(merge_and_dump(None, prefs))

    panel = ContextPanel(services)
    assert panel._section_widgets["usage"].isHidden() is True
    assert panel._section_widgets["session"].isHidden() is False


def test_context_panel_reorders_sections_per_saved_preference(tmp_path):
    services = _services(tmp_path)
    # Put "role_dashboard" first, everything else after.
    prefs = {
        spec.id: WidgetPreference(visible=True, order=i + 1)
        for i, spec in enumerate(CONTEXT_PANEL_WIDGETS)
    }
    prefs["role_dashboard"] = WidgetPreference(visible=True, order=0)
    services.set_widget_preferences_json(merge_and_dump(None, prefs))

    panel = ContextPanel(services)
    first_widget = panel._sections_layout.itemAt(0).widget()
    assert first_widget is panel._section_widgets["role_dashboard"]


def test_dashboard_module_card_hidden_when_preference_says_so(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)

    prefs = {
        spec.id: WidgetPreference(visible=True, order=i)
        for i, spec in enumerate(DASHBOARD_WIDGETS)
    }
    prefs["module_feedback"] = WidgetPreference(
        visible=False, order=prefs["module_feedback"].order
    )
    services.set_widget_preferences_json(merge_and_dump(None, prefs))

    screen = DashboardScreen(services)
    visible_ids = ordered_visible_ids(
        load_preferences(services.widget_preferences_json(), DASHBOARD_WIDGETS), DASHBOARD_WIDGETS
    )
    assert "module_feedback" not in visible_ids
    assert "module_debugging" in visible_ids
    screen.refresh()  # confirm it doesn't raise with a hidden module
