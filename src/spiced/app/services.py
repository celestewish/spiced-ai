"""Composition root: builds and holds the app's services.

Keeping construction here means the UI receives ready-to-use services and does
not reach into storage or provider internals directly.
"""

from __future__ import annotations

from pathlib import Path

from spiced.ai import DEFAULT_PROVIDER, AIProvider, build_provider
from spiced.core import community as community_module
from spiced.core.accessibility import AccessibilityService
from spiced.core.code_health import CodeHealthService
from spiced.core.community.base import CommunitySource
from spiced.core.community_pulse import CommunityPulseService
from spiced.core.dashboard import DashboardService
from spiced.core.debugging import DebuggingService
from spiced.core.demo_data import DemoDataService
from spiced.core.feedback import FeedbackService
from spiced.core.performance import PerformanceService
from spiced.core.projects_service import ProjectsService
from spiced.core.regression import RegressionService
from spiced.core.testing import TestingService
from spiced.core.usage_counter import UsageCounter
from spiced.core.version_check import VersionCheckService
from spiced.storage.accessibility_reports import AccessibilityReportRepository
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.storage.community_pulse import CommunityPulseRepository
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.feedback_tasks import FeedbackTaskRepository
from spiced.storage.known_issues import KnownIssueRepository
from spiced.storage.performance_reports import PerformanceReportRepository
from spiced.storage.projects import Project, ProjectRepository
from spiced.storage.settings import SettingsRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository
from spiced.storage.usage import UsageRepository
from spiced.storage.version_check_reports import VersionCheckReportRepository

PROVIDER_SETTING_KEY = "ai_provider"
ACTIVE_PROJECT_SETTING_KEY = "active_project_id"
COMMUNITY_SOURCE_SETTING_KEY = "community_source"
COMMUNITY_PULSE_ENABLED_KEY = "community_pulse_enabled"


class Services:
    """Holds the database, repositories, and core services for one app run."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path)
        self.projects = ProjectsService(ProjectRepository(self.db))
        self._settings = SettingsRepository(self.db)
        self.usage = UsageCounter(UsageRepository(self.db), self._settings)
        self.regression = RegressionService(KnownIssueRepository(self.db))
        self.debugging = DebuggingService(DebugSessionRepository(self.db), self.regression)
        self.testing = TestingService(
            TestCaseRepository(self.db), TestRunRepository(self.db), self.regression
        )
        self.feedback = FeedbackService(
            FeedbackBatchRepository(self.db), FeedbackTaskRepository(self.db)
        )
        self.performance = PerformanceService(PerformanceReportRepository(self.db))
        self.accessibility = AccessibilityService(AccessibilityReportRepository(self.db))
        self.version_check = VersionCheckService(VersionCheckReportRepository(self.db))
        self.code_health = CodeHealthService(CodeHealthReportRepository(self.db))
        self.community_pulse = CommunityPulseService(CommunityPulseRepository(self.db))
        self.dashboard = DashboardService(self.debugging, self.testing, self.feedback)
        self.demo = DemoDataService(self.db)

    def load_demo_project(self, *, fresh: bool = False) -> Project:
        """Seed the bundled demo project and make it active.

        Repeat-safe by default (reuses the existing demo project). Pass
        ``fresh=True`` to reset the demo data first. Never touches real projects.
        """
        project = self.demo.load_fresh_demo() if fresh else self.demo.seed()
        self.set_active_project(project.id)
        return project

    def provider_name(self) -> str:
        import os

        return self._settings.get(
            PROVIDER_SETTING_KEY, os.environ.get("SPICED_AI_PROVIDER", DEFAULT_PROVIDER)
        )

    def set_provider_name(self, name: str) -> None:
        self._settings.set(PROVIDER_SETTING_KEY, name)

    def build_provider(self) -> AIProvider:
        return build_provider(self.provider_name())

    # --- Community Pulse (opt-in, off by default) --------------------------

    def community_pulse_enabled(self) -> bool:
        return self._settings.get(COMMUNITY_PULSE_ENABLED_KEY, "") == "1"

    def set_community_pulse_enabled(self, enabled: bool) -> None:
        self._settings.set(COMMUNITY_PULSE_ENABLED_KEY, "1" if enabled else "")

    def community_source_name(self) -> str:
        return self._settings.get(COMMUNITY_SOURCE_SETTING_KEY, community_module.DEFAULT_SOURCE)

    def set_community_source_name(self, name: str) -> None:
        self._settings.set(COMMUNITY_SOURCE_SETTING_KEY, name)

    def build_community_source(self) -> CommunitySource:
        return community_module.build_source(self.community_source_name())

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
