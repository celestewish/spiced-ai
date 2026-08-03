"""Import-cleanliness checks for the Team Mode / Phase B UI.

No display is available in CI/agent environments, so these only confirm the
modules import without error (catching missing imports, syntax errors, and
circular-import issues) rather than instantiating widgets.
"""

from __future__ import annotations

import importlib


def test_auth_dialog_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.auth_dialog")
    assert hasattr(module, "AuthDialog")


def test_projects_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.projects")
    assert hasattr(module, "ProjectsScreen")


def test_settings_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.settings")
    assert hasattr(module, "SettingsScreen")


def test_context_panel_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.context_panel")
    assert hasattr(module, "ContextPanel")


def test_readiness_badge_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.widgets.readiness_badge")
    assert hasattr(module, "ReadinessBadge")


def test_testing_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.testing")
    assert hasattr(module, "TestingScreen")


def test_debugging_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.debugging")
    assert hasattr(module, "DebuggingScreen")


def test_feedback_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.feedback")
    assert hasattr(module, "FeedbackScreen")


def test_main_window_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.main_window")
    assert hasattr(module, "MainWindow")
