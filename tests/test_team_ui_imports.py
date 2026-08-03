"""Import-cleanliness checks for the new Team Mode UI.

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
