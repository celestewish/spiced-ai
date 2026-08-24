"""Composition root: builds and holds the app's services.

Keeping construction here means the UI receives ready-to-use services and does
not reach into storage or provider internals directly.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from spiced.ai import DEFAULT_PROVIDER, AIProvider, build_provider
from spiced.automation.animation_bug_detection_live import LiveAnimationBugDetectionService
from spiced.automation.asset_technical_qa import AssetTechnicalQaService
from spiced.automation.gpu_shader_profiling import GpuShaderProfilingService
from spiced.automation.localization_content_verification import (
    LocalizationContentVerificationService,
)
from spiced.automation.loudness_normalize import LoudnessNormalizeService
from spiced.automation.mix_technical_qa import MixTechnicalQaService
from spiced.automation.mocap_cleanup_assist import MocapCleanupAssistService
from spiced.automation.palette_drift import PaletteDriftService
from spiced.automation.retopology_assist import RetopologyAssistService
from spiced.automation.shader_variant_analysis import ShaderVariantAnalysisService
from spiced.automation.state_machine_validation import StateMachineValidationService
from spiced.automation.uv_lod_generation import UvLodGenerationService
from spiced.automation.visual_regression_capture import VisualRegressionCaptureService
from spiced.backend_client import telemetry_client
from spiced.backend_client.api_client import BackendAPIError, NotAuthenticatedError
from spiced.core import community as community_module
from spiced.core import git_integration
from spiced.core.accessibility import AccessibilityService
from spiced.core.animation_state_machine_check import AnimationStateMachineCheckService
from spiced.core.asset_review_queue import AssetReviewQueueService
from spiced.core.asset_scan import AssetScanService
from spiced.core.audio_implementation_checklist import AudioImplementationChecklistService
from spiced.core.auth_service import AuthService
from spiced.core.budget_tracker import BudgetTrackerService
from spiced.core.build_pipeline import run_build_pipeline
from spiced.core.changelog_draft import ChangelogService
from spiced.core.code_health import CodeHealthService
from spiced.core.community.base import CommunitySource
from spiced.core.community.discord_poster import DiscordPoster
from spiced.core.community_pulse import CommunityPulseService
from spiced.core.competitive_landscape import CompetitiveLandscapeService
from spiced.core.contract_checklist import ContractChecklistService
from spiced.core.dashboard import DashboardService
from spiced.core.debugging import DebuggingService
from spiced.core.demo_data import DemoDataService
from spiced.core.dependency_check import DependencyCheckService
from spiced.core.design_doc_sync import DesignDocSyncService
from spiced.core.dev_docs import DevDocsService
from spiced.core.draft_translation import DraftTranslationService
from spiced.core.economy_simulator import EconomySimulationService
from spiced.core.feedback import FeedbackService
from spiced.core.localization_readiness import LocalizationReadinessService
from spiced.core.mix_level_qa import MixLevelQaService
from spiced.core.performance import PerformanceService
from spiced.core.player_crash_reports import PlayerCrashSyncService
from spiced.core.playtester_recruitment import PlaytesterRecruitmentService
from spiced.core.precommit_hook import HookInstallResult, install_hook, uninstall_hook
from spiced.core.projects_service import ProjectsService
from spiced.core.regression import RegressionService
from spiced.core.roadmap_service import RoadmapService
from spiced.core.save_load_tester import SaveLoadTesterService
from spiced.core.session_summary import SessionSummaryService, now_sqlite
from spiced.core.shader_performance_profiling import ShaderPerformanceProfilingService
from spiced.core.store_page_advisor import StorePageAdvisorService
from spiced.core.team_service import TeamService
from spiced.core.test_generator import TestGeneratorService
from spiced.core.testing import TestingService
from spiced.core.trailer_screenshot_checklist import TrailerScreenshotChecklistService
from spiced.core.usage_counter import UsageCounter
from spiced.core.version_check import VersionCheckService
from spiced.core.visual_regression import VisualRegressionService
from spiced.core.wishlist_analytics import WishlistAnalyticsService
from spiced.storage.accessibility_reports import AccessibilityReportRepository
from spiced.storage.animation_state_machine_reports import AnimationStateMachineReportRepository
from spiced.storage.asset_review_reports import AssetReviewReportRepository
from spiced.storage.asset_scan_reports import AssetScanReportRepository
from spiced.storage.audio_checklist_reports import AudioChecklistReportRepository
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.budget_entries import BudgetRepository
from spiced.storage.build_reports import BuildReport, BuildReportRepository
from spiced.storage.changelog_drafts import ChangelogDraftRepository
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.storage.community_pulse import CommunityPulseRepository
from spiced.storage.competitive_landscape_reports import CompetitiveLandscapeReportRepository
from spiced.storage.contract_checklist_reviews import ContractChecklistReviewRepository
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.dependency_check_reports import DependencyCheckReportRepository
from spiced.storage.design_doc_sync_reports import DesignDocSyncReportRepository
from spiced.storage.design_doc_uploads import DesignDocUploadRepository
from spiced.storage.dev_docs_snapshots import DevDocsSnapshotRepository
from spiced.storage.draft_translations import DraftTranslationRepository
from spiced.storage.economy_simulation_reports import EconomySimulationReportRepository
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.feedback_tasks import FeedbackTaskRepository
from spiced.storage.generated_test_drafts import GeneratedTestDraftRepository
from spiced.storage.known_issues import KnownIssueRepository
from spiced.storage.localization_readiness_reports import LocalizationReadinessReportRepository
from spiced.storage.mix_qa_reports import MixQaReportRepository
from spiced.storage.palette_reference_colors import PaletteReferenceColorRepository
from spiced.storage.performance_reports import PerformanceReportRepository
from spiced.storage.player_crash_sync import PlayerCrashSyncRepository
from spiced.storage.playtester_signups import PlaytesterSignupRepository
from spiced.storage.precommit_reviews import PrecommitReviewRepository
from spiced.storage.projects import Project, ProjectRepository
from spiced.storage.save_integrity_reports import SaveIntegrityReportRepository
from spiced.storage.screenshot_checklist_reports import ScreenshotChecklistReportRepository
from spiced.storage.session_summaries import SessionSummary, SessionSummaryRepository
from spiced.storage.settings import SettingsRepository
from spiced.storage.shader_profiling_reports import ShaderProfilingReportRepository
from spiced.storage.store_page_reviews import StorePageReviewRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository
from spiced.storage.usage import UsageRepository
from spiced.storage.version_check_reports import VersionCheckReportRepository
from spiced.storage.visual_regression_captures import VisualRegressionCaptureRepository
from spiced.storage.visual_regression_key_scenes import VisualRegressionKeySceneRepository
from spiced.storage.visual_regression_reports import VisualRegressionReportRepository
from spiced.storage.wishlist_analytics_imports import WishlistAnalyticsImportRepository

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
# Discord/Community Bot Integration (Phase G, section 7): posting is a
# separate, bigger trust boundary than the existing read-only Community
# Pulse toggle, so it gets its own opt-in settings. Off by default.
DISCORD_POSTING_ENABLED_KEY = "discord_posting_enabled"
# Documented future option (see core.community.discord_poster / the
# Debugging Buddy screen's "Post to Discord" action): when on, skips the
# confirm-before-send dialog. Off by default — approval-required is the
# default path per spec.
DISCORD_AUTO_POST_ENABLED_KEY = "discord_auto_post_enabled"
# Rapid Prototyping Mode (Phase H, section 7 part 2, Core tier). Off by
# default, same opt-in shape as the other app-wide toggles above. When on,
# the Testing screen foregrounds a minimal Quick Smoke Test panel and
# de-emphasizes (collapses) the full functional/performance/accessibility/
# economy QA suite — nothing is removed, only what's foregrounded changes.
PROTOTYPE_MODE_ENABLED_KEY = "prototype_mode_enabled"
# In-App Accessibility Settings (Phase L, section 9 part 2, Core tier). Kept
# as plain strings/bools here, same as every other settings-toggle group in
# this class -- ``services.py`` deliberately never imports ``spiced.ui.*``
# (see this module's own docstring on the UI receiving ready-to-use
# services, not the other way around), so the actual stylesheet-building
# (``spiced.ui.theme.build_stylesheet``) is left to the UI layer, which
# reads these values back via the getters below.
ACCESSIBILITY_TEXT_SIZE_KEY = "accessibility_text_size"
ACCESSIBILITY_HIGH_CONTRAST_KEY = "accessibility_high_contrast"
ACCESSIBILITY_COLORBLIND_SAFE_KEY = "accessibility_colorblind_safe"
ACCESSIBILITY_REDUCE_MOTION_KEY = "accessibility_reduce_motion"
DEFAULT_ACCESSIBILITY_TEXT_SIZE = "normal"
# Customizable Dashboard Widgets (Phase L, Phase 2 tier, scoped down to
# show/hide + reorder -- see ui.widget_preferences for the full scope-down
# note) and Keyboard Shortcuts for Power Users (Phase L, Phase 2 tier) both
# store a small JSON blob keyed by id -- the simplest shape for this kind of
# flexible, per-id preference data, matching how ``app_settings`` already
# stores single opaque values for everything else in this class rather than
# needing a dedicated table (see ``storage.database.SCHEMA`` -- there's no
# existing JSON-blob-in-app_settings precedent to follow exactly, but a
# dedicated table would be overkill for what's genuinely just a small,
# whole-value preference document per feature).
WIDGET_PREFERENCES_KEY = "widget_preferences_v1"
KEYBOARD_SHORTCUTS_KEY = "keyboard_shortcuts_v1"


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

        # Depends on self.regression and self.session_summaries above, so it
        # has to be built after both -- see DashboardService.summarize.
        self.dashboard = DashboardService(
            self.debugging, self.testing, self.feedback, self.regression, self.session_summaries
        )

        # Code & Repo Hygiene + Systems & Balance (Phase E, section 6).
        self.dependency_check = DependencyCheckService(DependencyCheckReportRepository(self.db))
        self.test_generator = TestGeneratorService(GeneratedTestDraftRepository(self.db))
        self.precommit_reviews = PrecommitReviewRepository(self.db)
        self.economy_simulator = EconomySimulationService(
            EconomySimulationReportRepository(self.db)
        )
        self.save_load_tester = SaveLoadTesterService(SaveIntegrityReportRepository(self.db))

        # Documentation + Dev Wellbeing (Phase F, section 6). Dev Docs,
        # Design Doc Sync, and Scope-Creep Flagging are all local-only (no
        # backend sync described for any of them). Crunch-Pattern Awareness
        # (core.crunch_awareness) is deliberately *not* wired here as a
        # service — the Context Panel calls it directly over
        # self.session_summaries.history(), reusing Phase B's existing
        # table with no new capture mechanism and, per the plan's explicit
        # judgment call #5, no path to TeamService/BackendClient at all.
        self.dev_docs = DevDocsService(DevDocsSnapshotRepository(self.db))
        self.design_doc_sync = DesignDocSyncService(
            DesignDocUploadRepository(self.db),
            DesignDocSyncReportRepository(self.db),
            self.dev_docs,
        )

        # Marketing & Discoverability + Community & Playtesting (Phase G,
        # section 7).
        self.store_page_advisor = StorePageAdvisorService(StorePageReviewRepository(self.db))
        self.wishlist_analytics = WishlistAnalyticsService(
            WishlistAnalyticsImportRepository(self.db)
        )
        self.screenshot_checklist = TrailerScreenshotChecklistService(
            ScreenshotChecklistReportRepository(self.db)
        )
        self.playtester_recruitment = PlaytesterRecruitmentService(
            PlaytesterSignupRepository(self.db)
        )
        # Player Crash & Error Reporting: only meaningful for a team-linked
        # project, same reachability constraint as team_prompt_context above.
        self.player_crash_sync = PlayerCrashSyncService(
            self.teams, self.regression, PlayerCrashSyncRepository(self.db)
        )

        # Business & Legal Support + Prototyping & Pre-Production +
        # Localization (Phase H, section 7 part 2). Grant/Funding Finder
        # (core.grant_finder) follows the same stateless pattern as
        # core.release_checklist and is deliberately not wired here — it's
        # called directly, same as build_checklist/analyze_checklist.
        self.contract_checklist = ContractChecklistService(
            ContractChecklistReviewRepository(self.db)
        )
        self.budget_tracker = BudgetTrackerService(BudgetRepository(self.db))
        self.competitive_landscape = CompetitiveLandscapeService(
            CompetitiveLandscapeReportRepository(self.db)
        )
        self.localization_readiness = LocalizationReadinessService(
            LocalizationReadinessReportRepository(self.db)
        )
        self.draft_translation = DraftTranslationService(DraftTranslationRepository(self.db))

        # Team Collaboration by Role: Art + Audio + Animation (Phase I,
        # section 8 part 1). All eight features are local, deterministic
        # scans -- no AI provider or backend call is involved anywhere in
        # this group. Style Consistency Checker, In-Engine Placement
        # Preview, Localization Audio Sync, and Animation Bug Detection have
        # no dedicated report table (per the plan, they're live/un-persisted
        # scans, the same pattern as Code Health's Naming Consistency / Dead
        # Reference Detection) and so are deliberately not wired here as
        # services -- they're called directly from the Art/Audio/Animation
        # screens, same as core.grant_finder.
        self.asset_review_queue = AssetReviewQueueService(AssetReviewReportRepository(self.db))
        self.audio_implementation_checklist = AudioImplementationChecklistService(
            AudioChecklistReportRepository(self.db)
        )
        self.mix_level_qa = MixLevelQaService(MixQaReportRepository(self.db))

        # Art/Audio/Animation/VFX Automation (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 1: Batch Processing & Loudness Normalization). First
        # feature on the Bible's separate track: unlike every local/
        # deterministic scan above, this drives a real external tool
        # (ffmpeg) and persists into the shared automation_findings table
        # (AutomationFindingRepository) rather than a one-off per-feature
        # report table, since every future Bible feature reuses that same
        # table.
        self.loudness_normalize = LoudnessNormalizeService(AutomationFindingRepository(self.db))

        # Asset Technical QA Scan (SPICED_IMPLEMENTATION_BIBLE.md, Feature 3).
        # Third feature on the Bible's track: reuses self.asset_review_queue
        # (below) for its already-built/verified resolution/file-size/format/
        # mipmap checks rather than duplicating them, and adds naming-
        # convention + live-engine pivot checking on top.
        self.asset_technical_qa = AssetTechnicalQaService(AutomationFindingRepository(self.db))

        # Texture & Palette Drift Detection (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 4). Fourth feature on the Bible's track -- needs no
        # external tool or engine connection, unlike Features 1-3.
        self.palette_drift = PaletteDriftService(
            PaletteReferenceColorRepository(self.db), AutomationFindingRepository(self.db)
        )

        # Mix Technical QA (SPICED_IMPLEMENTATION_BIBLE.md, Feature 5). Fifth
        # feature on the Bible's track -- reuses
        # core.mix_level_qa._read_pcm_channel0 for WAV decoding (see that
        # service, self.mix_level_qa, above) rather than re-deriving it.
        self.mix_technical_qa = MixTechnicalQaService(AutomationFindingRepository(self.db))

        # Shader Variant & Compile Bloat Analysis (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 6). Sixth feature on the Bible's track -- shares the "VFX
        # analyzer" territory with self.visual_regression_capture (Feature 2,
        # below) and self.shader_performance_profiling (the existing static
        # scan), but drives a real headless Unity call for variant counts.
        self.shader_variant_analysis = ShaderVariantAnalysisService(
            AutomationFindingRepository(self.db)
        )

        # State Machine & Retarget Validation (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 7). Seventh feature on the Bible's track -- reuses
        # self.animation_state_machine_check (below) / core.animation_
        # state_machine_check for its already-verified unreachable-state and
        # missing-transition-target checks rather than duplicating them, and
        # adds dead-end-state detection plus live-engine retarget validation.
        self.state_machine_validation = StateMachineValidationService(
            AutomationFindingRepository(self.db)
        )

        # UV Unwrapping + LOD Generation (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 8). Eighth feature on the Bible's track -- the first that
        # writes real mesh file artifacts, not just a report. No dedicated
        # per-project config table: LOD ratios are a per-run parameter, not
        # a persisted setting.
        self.uv_lod_generation = UvLodGenerationService(AutomationFindingRepository(self.db))

        # Shader Performance Profiling (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 9). Ninth and final Ship First feature -- analyzes an
        # existing RenderDoc capture (see
        # connectors.renderdoc_analysis's docstring for the significant
        # caveat: unverified against a real RenderDoc install).
        self.gpu_shader_profiling = GpuShaderProfilingService(AutomationFindingRepository(self.db))

        self.animation_state_machine_check = AnimationStateMachineCheckService(
            AnimationStateMachineReportRepository(self.db)
        )

        # Shaders & VFX + Cross-Role & Team Glue (Phase J, section 8 part 2).
        # Shader Performance Profiling and Visual Regression Testing are
        # local, deterministic (no AI call) -- same shape as the Phase I
        # scans above. Unified Task Board / Comment Threads / discipline /
        # notification routing are all thin orchestration over
        # TeamService/BackendClient (already constructed above) plus
        # core.notification_routing -- no dedicated local report table for
        # any of them, since that data lives on the team backend, not
        # per-machine SQLite.
        self.shader_performance_profiling = ShaderPerformanceProfilingService(
            ShaderProfilingReportRepository(self.db)
        )
        self.visual_regression = VisualRegressionService(VisualRegressionReportRepository(self.db))

        # Visual Regression Testing -- Live Capture (SPICED_IMPLEMENTATION_BIBLE.md,
        # Feature 2). Second feature on the Bible's live-engine-integration
        # track: unlike the paste/import Visual Regression Testing above,
        # this drives a real headless Unity capture
        # (connectors.unity_visual_capture) and persists into the shared
        # automation_findings table, same as loudness_normalize.
        self.visual_regression_capture = VisualRegressionCaptureService(
            VisualRegressionKeySceneRepository(self.db),
            VisualRegressionCaptureRepository(self.db),
            AutomationFindingRepository(self.db),
        )

        # Phase 2 of the Bible's live-engine-integration track (Features
        # 10-13), built in process order 11, 12, 10, 13 (11 builds the
        # shared foot-sliding/velocity helper -- automation.motion_quality
        # -- that 12 then reuses; 10 and 13 are independent of both and of
        # each other).
        #
        # Automated Animation Bug Detection, Live Capture (Feature 11):
        # Spiced's one deliberate, considered exception to the local-first/
        # read-only principle documented on core.animation_bug_detection --
        # a real Unity Play Mode capture, kept side by side with that
        # existing static scan rather than replacing it.
        self.live_animation_bug_detection = LiveAnimationBugDetectionService(
            AutomationFindingRepository(self.db)
        )

        # Mocap Cleanup Assist (Feature 12): detection-only offline BVH
        # scan, reusing Feature 11's foot-sliding helper
        # (automation.motion_quality) against forward-kinematics positions
        # computed from the raw mocap file (automation.bvh_mocap) -- no
        # live engine connection needed at all.
        self.mocap_cleanup_assist = MocapCleanupAssistService(AutomationFindingRepository(self.db))

        # Retopology Assist (Feature 10): headless Blender + QuadriFlow,
        # subprocess-isolated exactly like Feature 8's xatlas worker (a
        # native remesh crash must not take down the app). UNVERIFIED
        # against a real Blender install in this environment -- see
        # automation.retopology_assist's module docstring.
        self.retopology_assist = RetopologyAssistService(AutomationFindingRepository(self.db))

        # Localization Audio Sync Checker, Content Verification (Feature
        # 13): self-hosted faster-whisper, subprocess-isolated, kept side
        # by side with core.localization_audio_sync's existing staleness/
        # coverage heuristic rather than replacing it -- this is the real
        # content-verification path that module's docstring says is out of
        # scope for it.
        self.localization_content_verification = LocalizationContentVerificationService(
            AutomationFindingRepository(self.db)
        )

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

    # --- Discord/Community Bot Integration: posting (opt-in, off by default)

    def discord_posting_enabled(self) -> bool:
        return self._settings.get(DISCORD_POSTING_ENABLED_KEY, "") == "1"

    def set_discord_posting_enabled(self, enabled: bool) -> None:
        self._settings.set(DISCORD_POSTING_ENABLED_KEY, "1" if enabled else "")

    def discord_auto_post_enabled(self) -> bool:
        return self._settings.get(DISCORD_AUTO_POST_ENABLED_KEY, "") == "1"

    def set_discord_auto_post_enabled(self, enabled: bool) -> None:
        self._settings.set(DISCORD_AUTO_POST_ENABLED_KEY, "1" if enabled else "")

    def build_discord_poster(self) -> DiscordPoster:
        return DiscordPoster()

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

    # --- Rapid Prototyping Mode (opt-in, off by default) -------------------

    def prototype_mode_enabled(self) -> bool:
        return self._settings.get(PROTOTYPE_MODE_ENABLED_KEY, "") == "1"

    def set_prototype_mode_enabled(self, enabled: bool) -> None:
        self._settings.set(PROTOTYPE_MODE_ENABLED_KEY, "1" if enabled else "")

    # --- In-App Accessibility Settings --------------------------------------

    def accessibility_text_size(self) -> str:
        saved = self._settings.get(ACCESSIBILITY_TEXT_SIZE_KEY, "")
        return saved or DEFAULT_ACCESSIBILITY_TEXT_SIZE

    def set_accessibility_text_size(self, size: str) -> None:
        self._settings.set(ACCESSIBILITY_TEXT_SIZE_KEY, size)

    def accessibility_high_contrast_enabled(self) -> bool:
        return self._settings.get(ACCESSIBILITY_HIGH_CONTRAST_KEY, "") == "1"

    def set_accessibility_high_contrast_enabled(self, enabled: bool) -> None:
        self._settings.set(ACCESSIBILITY_HIGH_CONTRAST_KEY, "1" if enabled else "")

    def accessibility_colorblind_safe_enabled(self) -> bool:
        return self._settings.get(ACCESSIBILITY_COLORBLIND_SAFE_KEY, "") == "1"

    def set_accessibility_colorblind_safe_enabled(self, enabled: bool) -> None:
        self._settings.set(ACCESSIBILITY_COLORBLIND_SAFE_KEY, "1" if enabled else "")

    def accessibility_reduce_motion_enabled(self) -> bool:
        return self._settings.get(ACCESSIBILITY_REDUCE_MOTION_KEY, "") == "1"

    def set_accessibility_reduce_motion_enabled(self, enabled: bool) -> None:
        self._settings.set(ACCESSIBILITY_REDUCE_MOTION_KEY, "1" if enabled else "")

    # --- Customizable Dashboard Widgets / Keyboard Shortcuts: raw JSON -----
    #
    # Thin, Qt-free persistence only -- see core.widget_preferences and
    # core.keyboard_shortcuts for the actual (de)serialization/validation
    # logic these two just store the result of.

    def widget_preferences_json(self) -> str | None:
        return self._settings.get(WIDGET_PREFERENCES_KEY)

    def set_widget_preferences_json(self, raw_json: str) -> None:
        self._settings.set(WIDGET_PREFERENCES_KEY, raw_json)

    def keyboard_shortcuts_json(self) -> str | None:
        return self._settings.get(KEYBOARD_SHORTCUTS_KEY)

    def set_keyboard_shortcuts_json(self, raw_json: str) -> None:
        self._settings.set(KEYBOARD_SHORTCUTS_KEY, raw_json)

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
        on_progress=None,
    ) -> BuildReport:
        """One choke point for every build trigger (manual button, the
        in-app scheduler, and later the Phase E commit hook) so the opt-in
        gate in ``core.build_pipeline.run_build_pipeline`` is always applied
        the same way, no matter who's asking. ``on_progress`` (Phase L, Live
        Task Progress Transparency) is an optional passthrough -- see
        ``core.build_pipeline.run_build_pipeline``."""
        return run_build_pipeline(
            project,
            self.build_reports,
            trigger=trigger,
            target_platform=target_platform,
            editor_override=editor_override,
            on_progress=on_progress,
        )

    # --- Pre-Commit Review (opt-in per project) -----------------------------

    def install_precommit_hook(self, project: Project) -> HookInstallResult:
        """Install the .git/hooks/pre-commit script for a project that has
        opted in. Raises NotAGitRepoError / ForeignHookExistsError (see
        core.precommit_hook) — this is a thin pass-through, not a new gate;
        the caller (Projects screen) is expected to have already checked
        ``project.precommit_review_enabled`` before calling this."""
        return install_hook(project.path)

    def uninstall_precommit_hook(self, project: Project) -> bool:
        return uninstall_hook(project.path)

    # --- Version Control (opt-in per project) -------------------------------
    #
    # Thin pass-throughs to core.git_integration, which re-checks
    # ``project.git_integration_enabled`` itself on every call (the actual
    # gate) — these exist only so screen code depends on Services, the same
    # convention every other feature in this class follows.

    def git_repo_status(self, project: Project):
        return git_integration.repo_status(project)

    def git_file_history(self, project: Project, relative_path: str, limit: int = 20):
        return git_integration.file_history(project, relative_path, limit)

    def git_diff_for_path(self, project: Project, relative_path: str, *, staged: bool = False):
        return git_integration.diff_for_path(project, relative_path, staged=staged)

    def git_stage_paths(self, project: Project, relative_paths: list[str]):
        return git_integration.stage_paths(project, relative_paths)

    def git_commit_staged(
        self,
        project: Project,
        message: str,
        *,
        author_name: str | None = None,
        author_email: str | None = None,
    ):
        return git_integration.commit_staged(
            project, message, author_name=author_name, author_email=author_email
        )

    def git_discard_unstaged_changes(
        self, project: Project, relative_paths: list[str], *, confirmed: bool = False
    ):
        return git_integration.discard_unstaged_changes(
            project, relative_paths, confirmed=confirmed
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

    def display_name(self) -> str:
        """A real, non-fabricated name for the Dashboard's "Welcome back"
        greeting. Solo-Dev Mode (the default) has no account at all, so
        there's no app-level identity to draw on there -- this prefers the
        Small-Team Mode signed-in email's local part when logged in, and
        otherwise falls back to the actual OS account name (the one real
        piece of "who is this" Spiced can see without requiring a sign-in).
        Never returns a hardcoded or placeholder name."""
        user = self.auth.current_user()
        if user is not None and user.email:
            return user.email.split("@", 1)[0]
        try:
            import getpass

            name = getpass.getuser()
            if name:
                return name
        except Exception:
            pass
        return "dev"

    def set_active_project(self, project_id: int | None) -> None:
        if project_id is None:
            self._settings.set(ACTIVE_PROJECT_SETTING_KEY, "")
        else:
            self._settings.set(ACTIVE_PROJECT_SETTING_KEY, str(project_id))

    def close(self) -> None:
        self.db.close()
