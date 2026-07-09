"""Composition root: builds and holds the app's services.

Keeping construction here means the UI receives ready-to-use services and does
not reach into storage or provider internals directly.
"""

from __future__ import annotations

from pathlib import Path

from spiced.ai import DEFAULT_PROVIDER, AIProvider, build_provider
from spiced.core.projects_service import ProjectsService
from spiced.core.usage_counter import UsageCounter
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.settings import SettingsRepository
from spiced.storage.usage import UsageRepository

PROVIDER_SETTING_KEY = "ai_provider"


class Services:
    """Holds the database, repositories, and core services for one app run."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path)
        self.projects = ProjectsService(ProjectRepository(self.db))
        self._settings = SettingsRepository(self.db)
        self.usage = UsageCounter(UsageRepository(self.db), self._settings)

    def provider_name(self) -> str:
        import os

        return self._settings.get(
            PROVIDER_SETTING_KEY, os.environ.get("SPICED_AI_PROVIDER", DEFAULT_PROVIDER)
        )

    def set_provider_name(self, name: str) -> None:
        self._settings.set(PROVIDER_SETTING_KEY, name)

    def build_provider(self) -> AIProvider:
        return build_provider(self.provider_name())

    def close(self) -> None:
        self.db.close()
