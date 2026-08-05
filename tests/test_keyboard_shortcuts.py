"""Tests for core.keyboard_shortcuts (pure, GUI-free) plus a headless check
that MainWindow actually wires a QShortcut for every action with a known
callback, and that Settings persists rebinds MainWindow picks up.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core.keyboard_shortcuts import (  # noqa: E402
    ACTIONS,
    binding_for,
    dump_bindings,
    load_bindings,
    reset_binding,
)
from spiced.ui.main_window import MainWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


# --- Defaults ------------------------------------------------------------------


def test_every_action_has_a_unique_id():
    ids = [a.id for a in ACTIONS]
    assert len(ids) == len(set(ids))


def test_command_palette_action_defaults_to_ctrl_k():
    assert binding_for("command_palette", {}) == "Ctrl+K"


def test_cheat_sheet_action_defaults_to_question_mark():
    assert binding_for("cheat_sheet", {}) == "?"


def test_at_least_nine_goto_page_actions_exist():
    goto_actions = [a for a in ACTIONS if a.id.startswith("goto_")]
    assert len(goto_actions) == 9
    bindings = {a.default_binding for a in goto_actions}
    assert bindings == {f"Ctrl+{i}" for i in range(1, 10)}


# --- load_bindings / dump_bindings / binding_for -------------------------------


def test_load_bindings_defaults_when_nothing_saved():
    bindings = load_bindings(None)
    for action in ACTIONS:
        assert bindings[action.id] == action.default_binding


def test_load_bindings_defaults_on_corrupt_json():
    bindings = load_bindings("{not valid")
    assert bindings["command_palette"] == "Ctrl+K"


def test_load_bindings_reads_a_saved_override():
    raw = dump_bindings({"command_palette": "Ctrl+Shift+P"})
    bindings = load_bindings(raw)
    assert bindings["command_palette"] == "Ctrl+Shift+P"
    # Everything else stays at its default.
    assert bindings["cheat_sheet"] == "?"


def test_load_bindings_ignores_non_string_or_blank_overrides():
    raw = '{"command_palette": "", "cheat_sheet": 42}'
    bindings = load_bindings(raw)
    assert bindings["command_palette"] == "Ctrl+K"
    assert bindings["cheat_sheet"] == "?"


def test_binding_for_unknown_action_raises_keyerror():
    try:
        binding_for("not_a_real_action", {})
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_reset_binding_removes_the_override_without_mutating_input():
    original = {"command_palette": "Ctrl+Shift+P"}
    updated = reset_binding(original, "command_palette")
    assert "command_palette" not in updated
    assert original == {"command_palette": "Ctrl+Shift+P"}  # not mutated
    assert binding_for("command_palette", updated) == "Ctrl+K"


# --- MainWindow wiring (headless) ----------------------------------------------


def test_main_window_builds_a_shortcut_for_every_actionable_action(tmp_path):
    window = MainWindow(_services(tmp_path))
    try:
        callbacks = window._shortcut_action_callbacks()
        for action_id in callbacks:
            assert action_id in window._shortcuts
    finally:
        window._build_scheduler.stop()
        window._top_bar.stop()


def test_main_window_rebuilds_shortcuts_when_settings_change(tmp_path):
    services = _services(tmp_path)
    window = MainWindow(services)
    try:
        original = window._shortcuts["command_palette"].key()
        services.set_keyboard_shortcuts_json(dump_bindings({"command_palette": "Ctrl+Shift+P"}))
        window._setup_keyboard_shortcuts()
        rebuilt = window._shortcuts["command_palette"].key()
        assert rebuilt.toString() == "Ctrl+Shift+P"
        assert rebuilt.toString() != original.toString()
    finally:
        window._build_scheduler.stop()
        window._top_bar.stop()


def test_main_window_cycle_active_project(tmp_path):
    services = _services(tmp_path)
    project_a = services.projects.create_project("Project A")
    project_b = services.projects.create_project("Project B")
    services.set_active_project(project_a.id)
    window = MainWindow(services)
    try:
        window._cycle_active_project(1)
        assert services.active_project().id == project_b.id
        window._cycle_active_project(1)
        assert services.active_project().id == project_a.id
        window._cycle_active_project(-1)
        assert services.active_project().id == project_b.id
    finally:
        window._build_scheduler.stop()
        window._top_bar.stop()
