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


def test_source_link_widget_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.widgets.source_link")
    assert hasattr(module, "SourceLinkExpander")


def test_roadmap_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.roadmap")
    assert hasattr(module, "RoadmapScreen")


def test_build_scheduler_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.build_scheduler")
    assert hasattr(module, "BuildScheduler")


def test_marketing_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.marketing")
    assert hasattr(module, "MarketingScreen")


def test_business_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.business")
    assert hasattr(module, "BusinessScreen")


def test_art_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.art")
    assert hasattr(module, "ArtScreen")


def test_audio_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.audio")
    assert hasattr(module, "AudioScreen")


def test_animation_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.animation")
    assert hasattr(module, "AnimationScreen")


def test_shaders_vfx_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.shaders_vfx")
    assert hasattr(module, "ShadersVfxScreen")


def test_team_screen_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.screens.team")
    assert hasattr(module, "TeamScreen")


def test_comments_widget_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.widgets.comments_widget")
    assert hasattr(module, "CommentsWidget")


def test_top_bar_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.top_bar")
    assert hasattr(module, "TopBar")


def test_notification_center_ui_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.notification_center")
    assert hasattr(module, "NotificationBell")
    assert hasattr(module, "NotificationDropdown")


def test_command_palette_module_imports_cleanly():
    module = importlib.import_module("spiced.ui.command_palette")
    assert hasattr(module, "CommandPalette")
    assert hasattr(module, "PaletteItem")
