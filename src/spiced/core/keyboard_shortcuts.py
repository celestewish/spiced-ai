"""Keyboard Shortcuts for Power Users (Phase L, section 9 part 2, Phase 2 tier).

A configurable set of common actions with sensible defaults, stored as a
small JSON blob (``action id -> key sequence string``) in ``app_settings``
(see ``Services.keyboard_shortcuts_json``/``set_keyboard_shortcuts_json``).
This module is the Qt-free default/storage layer, directly unit-testable;
the actual ``QShortcut`` wiring and the ``?`` cheat-sheet overlay live in
``ui.main_window``/``ui.shortcuts_cheatsheet``.

Scope decision (documented, not silent): there are more sidebar pages
(``ui.main_window.NAV_ITEMS``, 14 today) than number keys on a standard
keyboard row. Rather than reaching for two-key chords or letter mnemonics
that would be harder to discover and remember, this covers the first 9 nav
items with ``Ctrl+1``..``Ctrl+9`` (``goto_*`` actions below, in
``NAV_ITEMS``'s own order) and leaves the rest reachable via the sidebar
itself or the Command Palette (``Ctrl+K``, Phase K) -- one or two clicks/
keystrokes away rather than a dedicated binding for literally everything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# The first 9 of ui.main_window.NAV_ITEMS, in that exact order -- see the
# module docstring for why not all 14 pages get a dedicated binding. Kept
# as plain labels here (not imported from ui.main_window) to keep this
# module Qt-free; ui.main_window is responsible for wiring each goto_*
# action to the matching NAV_ITEMS index positionally.
_GOTO_PAGE_LABELS = [
    "Dashboard",
    "Projects",
    "Debugging Buddy",
    "Automated Testing",
    "Feedback Review",
    "Marketing",
    "Business",
    "Art",
    "Audio",
]


@dataclass(frozen=True)
class ShortcutAction:
    id: str
    label: str
    default_binding: str


def _goto_actions() -> list[ShortcutAction]:
    actions = []
    for index, page_label in enumerate(_GOTO_PAGE_LABELS, start=1):
        action_id = "goto_" + page_label.lower().replace(" ", "_").replace("/", "_")
        actions.append(ShortcutAction(action_id, f"Go to {page_label}", f"Ctrl+{index}"))
    return actions


# Reuses Phase K's existing Ctrl+K Command Palette binding as one action
# here (per spec) rather than a separate, disconnected shortcut -- see
# ui.main_window wiring this action's *effective* binding to the same
# QShortcut that opens CommandPalette.
ACTIONS: list[ShortcutAction] = [
    ShortcutAction("command_palette", "Open command palette (quick search)", "Ctrl+K"),
    ShortcutAction("cheat_sheet", "Show this keyboard shortcuts list", "?"),
    ShortcutAction("run_tests", "Go to Automated Testing (to run tests)", "Ctrl+R"),
    ShortcutAction("open_chatbox", "Go to Debugging Buddy (to analyze)", "Ctrl+D"),
    ShortcutAction("next_project", "Switch to next project", "Ctrl+]"),
    ShortcutAction("previous_project", "Switch to previous project", "Ctrl+["),
    *_goto_actions(),
]

_ACTIONS_BY_ID = {a.id: a for a in ACTIONS}


def load_bindings(raw_json: str | None) -> dict[str, str]:
    """action id -> current key sequence string. Any action missing from
    (or malformed in) the saved blob defaults to its declared default
    binding -- so a corrupt/foreign blob, or a newly added action, degrades
    to "everything at its default" rather than raising.
    """
    defaults = {a.id: a.default_binding for a in ACTIONS}
    if not raw_json:
        return defaults
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    result = dict(defaults)
    for action in ACTIONS:
        value = data.get(action.id)
        if isinstance(value, str) and value.strip():
            result[action.id] = value.strip()
    return result


def dump_bindings(bindings: dict[str, str]) -> str:
    return json.dumps(bindings)


def binding_for(action_id: str, bindings: dict[str, str]) -> str:
    """The effective binding for one action: its saved override if present,
    otherwise its declared default. Raises ``KeyError`` for an unknown
    action id."""
    if action_id in bindings:
        return bindings[action_id]
    if action_id in _ACTIONS_BY_ID:
        return _ACTIONS_BY_ID[action_id].default_binding
    raise KeyError(f"Unknown shortcut action: {action_id}")


def reset_binding(bindings: dict[str, str], action_id: str) -> dict[str, str]:
    """Return a new bindings dict with ``action_id`` removed (i.e. reset to
    its default) -- does not mutate ``bindings``."""
    updated = dict(bindings)
    updated.pop(action_id, None)
    return updated
