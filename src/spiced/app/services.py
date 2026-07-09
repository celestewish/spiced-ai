"""Composition root: builds and holds the app's services.

Keeping construction here means the UI receives ready-to-use services and does
not reach into storage or provider internals directly.
"""

from __future__ import annotations

from pathlib import Path

from spiced.ai import DEFAULT_PROVIDER, AIProvider, build_provider
from spiced.core.debugging import DebuggingService
from spiced.core.feedback import FeedbackService
from spiced.core.projects_service import ProjectsService
from spiced.core.testing import TestingService
from spiced.core.usage_counter import UsageCounter
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.projects import Project, ProjectRepository
from spiced.storage.settings import SettingsRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository
from spiced.storage.usage import UsageRepository

PROVIDER_SETTING_KEY = "ai_provider"
ACTIVE_PROJECT_SETTING_KEY = "active_project_id"


class Services:
    """Holds the database, repositories, and core services for one app run."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path)
        self.projects = ProjectsService(ProjectRepository(self.db))
        self._settings = SettingsRepository(self.db)
        self.usage = UsageCounter(UsageRepository(self.db), self._settings)
        self.debugging = DebuggingService(DebugSessionRepository(self.db))
        self.testing = TestingService(
            TestCaseRepository(self.db), TestRunRepository(self.db)
        )
        self.feedback = FeedbackService(FeedbackBatchRepository(self.db))

    def provider_name(self) -> str:
        import os

        return self._settings.get(
            PROVIDER_SETTING_KEY, os.environ.get("SPICED_AI_PROVIDER", DEFAULT_PROVIDER)
        )

    def set_provider_name(self, name: str) -> None:
        self._settings.set(PROVIDER_SETTING_KEY, name)

    def build_provider(self) -> AIProvider:
        return build_provider(self.provider_name())

    def active_project(self) -> Project | None:
        """Return the developer's currently selected project, if still present."""
        raw = self._settings.get(ACTIVE_PROJECT_SETTING_KEY)
        if not raw:
            return None
        try:
            project_id = int(raw)
        except (TypeError, ValueError):
            return None
        try:
            return self.projects.get_project(project_id)
        except KeyError:
            return None

    def set_active_project(self, project_id: int | None) -> None:
        if project_id is None:
            self._settings.set(ACTIVE_PROJECT_SETTING_KEY, "")
        else:
            self._settings.set(ACTIVE_PROJECT_SETTING_KEY, str(project_id))

    def close(self) -> None:
        self.db.close()
