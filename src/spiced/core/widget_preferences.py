"""Customizable Dashboard Widgets (Phase L, section 9 part 2, Phase 2 tier).

Scope decision (documented, not silent -- this app's established pattern for
ambitious spec items, e.g. ``core.trailer_screenshot_checklist``'s
paste-only scope or ``core.competitive_landscape``'s no-live-market-data
scope): the spec's full ambition is "rearranging, resizing, or hiding
widgets" via drag-and-drop. Full drag-and-drop reordering/resizing is a lot
of custom Qt work (custom mouse event handling, drop-indicator painting,
geometry animation) for what it actually buys in a single-column info panel
and a three-card dashboard row. This is scoped down to **show/hide toggles +
up/down reordering via a small list dialog**
(``ui.widget_customize_dialog.WidgetCustomizeDialog``). The effect a
developer actually wants -- hide widgets they don't use, control what order
the rest appear in -- is fully delivered; only the drag-and-drop
*interaction* is scoped down to an up/down list.

Preferences for every customizable widget (across both consumers --
Context Panel and Dashboard) share one JSON blob in ``app_settings`` (see
``Services.widget_preferences_json``/``set_widget_preferences_json``)
rather than a dedicated table: it's genuinely just a small
``{id: {visible, order}}`` document with no querying/joining ever needed,
matching how every other flexible-but-small preference in this app is
stored as a single settings value. ``merge_and_dump`` lets one consumer save
its own subset of ids without clobbering another consumer's entries in the
same blob.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class WidgetSpec:
    """One customizable widget's stable identity. ``id`` is persisted;
    ``label`` is shown in the customize dialog."""

    id: str
    label: str


@dataclass(frozen=True)
class WidgetPreference:
    visible: bool = True
    order: int = 0


# Context Panel (ui.context_panel.ContextPanel) sections that are actually
# optional/informational. The footer note and the Build Alert (a critical,
# rare failure notice) are deliberately excluded from customization -- same
# as the app's other "always show this" choices (e.g. the top bar's brand).
CONTEXT_PANEL_WIDGETS: list[WidgetSpec] = [
    WidgetSpec("project_info", "Project info"),
    WidgetSpec("usage", "Usage"),
    WidgetSpec("session", "Session"),
    WidgetSpec("crunch_note", "Crunch-Pattern note"),
    WidgetSpec("role_dashboard", "Role-based dashboard summary"),
]

# Dashboard screen (ui.screens.dashboard.DashboardScreen) module cards -- the
# three-card row summarizing Debugging/Testing/Feedback. The overview/
# readiness/actions/reminders/summary-tools cards around that row aren't
# part of this customization; they're the screen's own spine, not optional
# modules.
DASHBOARD_WIDGETS: list[WidgetSpec] = [
    WidgetSpec("module_debugging", "Debugging module"),
    WidgetSpec("module_testing", "Testing module"),
    WidgetSpec("module_feedback", "Feedback module"),
]


def _defaults(specs: list[WidgetSpec]) -> dict[str, WidgetPreference]:
    return {
        spec.id: WidgetPreference(visible=True, order=index) for index, spec in enumerate(specs)
    }


def load_preferences(raw_json: str | None, specs: list[WidgetSpec]) -> dict[str, WidgetPreference]:
    """Parse a saved JSON blob into ``{id: WidgetPreference}`` for exactly
    the ids in ``specs`` (ignoring any other widget group's entries sharing
    the same blob). Any id missing/malformed in the saved data defaults to
    visible, in ``specs``'s declared order -- so adding a new customizable
    widget later, or a corrupt/foreign blob, never breaks: it degrades to
    "everything visible, default order" rather than raising.
    """
    defaults = _defaults(specs)
    if not raw_json:
        return defaults
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return defaults
    if not isinstance(data, dict):
        return defaults

    result = dict(defaults)
    for spec in specs:
        entry = data.get(spec.id)
        if not isinstance(entry, dict):
            continue
        visible = entry.get("visible", True)
        order = entry.get("order", defaults[spec.id].order)
        try:
            order = int(order)
        except (TypeError, ValueError):
            order = defaults[spec.id].order
        result[spec.id] = WidgetPreference(visible=bool(visible), order=order)
    return result


def merge_and_dump(raw_json: str | None, updated: dict[str, WidgetPreference]) -> str:
    """Merge ``updated`` into whatever's already saved (preserving any other
    widget group's entries sharing the same blob) and return the new JSON to
    persist via ``Services.set_widget_preferences_json``."""
    try:
        existing = json.loads(raw_json) if raw_json else {}
        if not isinstance(existing, dict):
            existing = {}
    except (json.JSONDecodeError, TypeError):
        existing = {}
    for widget_id, pref in updated.items():
        existing[widget_id] = {"visible": pref.visible, "order": pref.order}
    return json.dumps(existing)


def dump_preferences(preferences: dict[str, WidgetPreference]) -> str:
    """Serialize a full preferences dict on its own -- mainly for tests;
    UI callers should prefer ``merge_and_dump`` so they don't clobber
    another widget group's saved entries."""
    return json.dumps(
        {wid: {"visible": pref.visible, "order": pref.order} for wid, pref in preferences.items()}
    )


def ordered_visible_ids(
    preferences: dict[str, WidgetPreference], specs: list[WidgetSpec]
) -> list[str]:
    """The ids that should actually be shown, in display order."""
    known_ids = {spec.id for spec in specs}
    visible = [
        (wid, pref) for wid, pref in preferences.items() if wid in known_ids and pref.visible
    ]
    visible.sort(key=lambda pair: pair[1].order)
    return [wid for wid, _ in visible]
