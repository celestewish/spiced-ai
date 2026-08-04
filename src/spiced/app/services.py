"""Composition root: builds and holds the app's services.

Keeping construction here means the UI receives ready-to-use services and does
not reach into storage or provider internals directly.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from spiced.ai import DEFAULT_PROVIDER, AIProvider, build_provider
from spiced.backend_client import telemetry_client
from spiced.backend_client.api_client import BackendAPIError, NotAuthenticatedError
from spiced.core import community as community_module
from spiced.core.accessibility import AccessibilityService
from spiced.core.asset_scan import AssetScanService
from spiced.core.auth_service import AuthService
from spiced.core.build_pipeline import run_build_pipeline
from spiced.core.changelog_draft import ChangelogService
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
from spiced.core.roadmap_service import RoadmapService
from spiced.core.session_summary import SessionSummaryService, now_sqlite
from spiced.core.team_service import TeamService
from spiced.core.testing import TestingService
from spiced.core.usage_counter import UsageCounter
from spiced.core.version_check import VersionCheckService
from spiced.storage.accessibility_reports import AccessibilityReportRepository
from spiced.storage.asset_scan_reports import AssetScanReportRepository
from spiced.storage.build_reports import BuildReport, BuildReportRepository
from spiced.storage.changelog_drafts import ChangelogDraftRepository
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.storage.community_pulse import CommunityPulseRepository
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.feedback_tasks import FeedbackTaskRepository
from spiced.storage.known_issues import KnownIssueRepository
from spiced.storage.performance_reports import PerformanceReportRepository
from spiced.storage.projects import Project, ProjectRepository
from spiced.storage.session_summaries import SessionSummary, SessionSummaryRepository
from spiced.storage.settings import SettingsRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository
from spiced.storage.usage import UsageRepository
from spiced.storage.version_check_reports import VersionCheckReportRepository

PROVIDER_SETTING_KEY = "ai_provider"
ACTIVE_PROJECT_SETTING_KEY = "active_project_id"
COMMUNITY_SOURCE_SETTING_KEY = "community_source"
COMMUNITY_PULSE_ENABLED_KEY = "community_pulse_enabled"
# Solo-Dev Mode vs. Small-Team Mode (Phase B, section 4). Off by default —
# solo behavior never changes unless a developer explicitly opts in.
TEAM_MODE_ENABLED_KEY = "team_mode_enabled"
# Opt-In Only Telemetry (Phase C, section 5). Off by default, mirroring
# COMMUNITY_PULSE_ENABLED_KEY exactly. TELEMETRY_CLIENT_ID_KEY holds a random
# UUID minted once on first use — never a user id or email, even if the
# developer happens to be signed in elsewhere for Team Mode.
TELEMETRY_OPT_IN_ENABLED_KEY = "telemetry_opt_in_enabled"
TELEMETRY_CLIENT_ID_KEY = "telemetry_anonymous_client_id"


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

        # Build & Release Automation + Asset Pipeline (Phase D, section 6).
        self.build_reports = BuildReportRepository(self.db)
        self.changelog = ChangelogService(ChangelogDraftRepository(self.db), self.regression)
        self.asset_scan = AssetScanService(AssetScanReportRepository(self.db))

        # Small-Team Mode (opt-in): auth + team/project-linking against the
        # new backend. Solo-Dev Mode never touches these.
        self.auth = AuthService(self._settings)
        self.teams = TeamService(self.auth, self.projects)
        # Open Roadmap & Feedback Loop (Phase C): viewing needs no login;
        # submitting/voting reuses this same AuthService/account system.
        self.roadmap = RoadmapService(self.auth)

        # Session Summaries (Phase B): always local; optionally also posted
        # to the team backend when Team Mode is on and the active project is
        # team-linked (see sync_session_summary below). ``app_started_at``
        # anchors the very first summary's window when a project has none
        # saved yet — later summaries chain off the previous one's ended_at.
        self.session_summaries = SessionSummaryService(
            SessionSummaryRepository(self.db), self.testing, self.feedback
        )
        self.app_started_at = now_sqlite()

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

    # --- Opt-In Only Telemetry (opt-in, off by default) --------------------

    def telemetry_opt_in_enabled(self) -> bool:
        return self._settings.get(TELEMETRY_OPT_IN_ENABLED_KEY, "") == "1"

    def set_telemetry_opt_in_enabled(self, enabled: bool) -> None:
        self._settings.set(TELEMETRY_OPT_IN_ENABLED_KEY, "1" if enabled else "")

    def _telemetry_client_id(self) -> str:
        """A random UUID minted once and stored locally.

        Never a user id or email — kept independent of AuthService/team
        sign-in state on purpose, so an event can't be traced back to an
        account even if the developer happens to be signed in elsewhere.
        """
        existing = self._settings.get(TELEMETRY_CLIENT_ID_KEY)
        if existing:
            return existing
        new_id = str(uuid.uuid4())
        self._settings.set(TELEMETRY_CLIENT_ID_KEY, new_id)
        return new_id

    def record_telemetry_event(self, event_name: str) -> None:
        """Fire an anonymous feature-usage event, if the developer opted in.

        A no-op when telemetry is off (the default). Never raises and never
        blocks the caller on a slow/failed network call — the whole point is
        that the calling action (a crash diagnosis, a test review, ...)
        always succeeds or fails on its own terms, regardless of telemetry.
        Only ``event_name`` (a bare event name, e.g.
        "debugging.crash_diagnosis_run") and the anonymous client id are ever
        sent — never code, logs, file paths, feedback content, or any
        project/game content.
        """
        if not self.telemetry_opt_in_enabled():
            return
        try:
            telemetry_client.post_event(self._telemetry_client_id(), event_name)
        except Exception:
            pass

    # --- Solo-Dev Mode vs. Small-Team Mode (opt-in, off by default) --------

    def team_mode_enabled(self) -> bool:
        return self._settings.get(TEAM_MODE_ENABLED_KEY, "") == "1"

    def set_team_mode_enabled(self, enabled: bool) -> None:
        self._settings.set(TEAM_MODE_ENABLED_KEY, "1" if enabled else "")

    def team_prompt_context(self, project: Project | None) -> list[str] | None:
        """Other teammates' display names/emails for AI prompt context.

        Returns None whenever Team Mode doesn't apply here — solo, signed
        out, or an unlinked project — so callers can do
        ``team_mode=bool(context)`` without extra network-error handling.
        Any backend problem also degrades to None rather than failing the
        caller's primary action (e.g. a crash analysis should still work
        even if the team roster can't be fetched right now).
        """
        if not self.team_mode_enabled() or project is None or not project.project_uuid:
            return None
        if not self.auth.is_logged_in():
            return None
        try:
            team = self.teams.find_team_for_project(project.project_uuid)
            if team is None:
                return None
            members = self.teams.list_other_members(team.id)
        except (BackendAPIError, NotAuthenticatedError):
            return None
        labels = [m.email or m.invited_email or m.user_id for m in members]
        return [label for label in labels if label] or None

    def sync_session_summary(self, project: Project, summary: SessionSummary) -> bool:
        """Post a saved session summary to the team backend, if applicable.

        Only ever sends ``summary.ai_summary`` plus ``started_at``/``ended_at``
        — see the docstring on storage.database's session_summaries table for
        why nothing else about session timing is shared. Returns whether the
        sync happened; failures are swallowed so a flaky connection never
        blocks the (already-saved-locally) summary from being usable.
        """
        if not self.team_mode_enabled() or not project.project_uuid:
            return False
        if not self.auth.is_logged_in():
            return False
        try:
            result = self.teams.post_session_summary(
                project.project_uuid,
                summary.started_at,
                summary.ended_at,
                summary.ai_summary or "",
            )
        except (BackendAPIError, NotAuthenticatedError):
            return False
        if result is None:
            return False
        self.session_summaries.mark_synced(summary.id)
        return True

    # --- Automated Build Pipeline -------------------------------------------

    def run_build(
        self,
        project: Project,
        *,
        trigger: str,
        target_platform: str | None = None,
        editor_override: str | None = None,
    ) -> BuildReport:
        """One choke point for every build trigger (manual button, the
        in-app scheduler, and later the Phase E commit hook) so the opt-in
        gate in ``core.build_pipeline.run_build_pipeline`` is always applied
        the same way, no matter who's asking."""
        return run_build_pipeline(
            project,
            self.build_reports,
            trigger=trigger,
            target_platform=target_platform,
            editor_override=editor_override,
        )

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
