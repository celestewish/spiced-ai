"""Automated Testing: functional test cases, performance, and accessibility.

Three tabs, each following the same pattern: local/deterministic parsing and
(for Functional) manual test-case tracking work fully offline with no AI
provider; the AI review runs the selected provider on a worker thread. Only a
trimmed excerpt is ever sent — never project files. The one exception is the
opt-in "Run Unity tests" section: when a project has explicitly enabled it
(on the Projects screen), Spiced launches that project's own Unity Editor
headlessly to run its tests, then feeds the results through the same local
parser and AI review as a pasted result.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.connectors import unity_build
from spiced.core.accessibility import AccessibilityReview
from spiced.core.accessibility import ProviderNotReadyError as AccessibilityNotReadyError
from spiced.core.build_pipeline import BuildNotEnabledError, BuildUnavailableError
from spiced.core.economy_simulator import (
    ECONOMY_SCHEMA_DOC,
    EconomySimulationFindings,
    EconomySimulationReview,
    InvalidEconomyDataError,
)
from spiced.core.economy_simulator import ProviderNotReadyError as EconomyNotReadyError
from spiced.core.hardware_simulation import available_tiers
from spiced.core.performance import PerformanceReview
from spiced.core.performance import ProviderNotReadyError as PerformanceNotReadyError
from spiced.core.player_crash_reports import PlayerCrashSyncResult
from spiced.core.release_checklist import (
    PLATFORM_LABELS,
    PLATFORMS,
    ReleaseChecklist,
    analyze_checklist,
    build_checklist,
)
from spiced.core.testing import (
    SOURCE_FILE,
    SOURCE_PASTE,
    SOURCE_UNITY_RUN,
    ProviderNotReadyError,
    TestReview,
)
from spiced.core.unity_test_runner import EDIT_MODE, PLAY_MODE, resolve_unity_editor, run_tests
from spiced.storage.build_reports import TRIGGER_MANUAL, BuildReport
from spiced.storage.known_issues import SOURCE_PLAYER, STATUS_RESOLVED
from spiced.storage.test_cases import CATEGORIES, PRIORITIES, STATUSES
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.bar_chart import FrameRateBarChart
from spiced.ui.widgets.comments_widget import CommentsWidget
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.pill_tab_widget import PillTabWidget
from spiced.ui.widgets.progress_trail import ProgressTrail
from spiced.ui.widgets.readiness_badge import ReadinessBadge
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox
from spiced.ui.widgets.source_link import SourceLinkExpander

_USER_ROLE = 0x0100
# Distinguishes a "case" row from an "issue" row in the merged Test Cases &
# Known Issues list (ui.screens.testing._build_case_and_issue_list) -- both
# kinds share one QListWidget/status-row visual, but keep their existing,
# separate selection state (_selected_case_id/_selected_issue_id) and
# action controls underneath.
_ITEM_KIND_ROLE = 0x0101
_NO_HARDWARE = "(none — no simulation)"
_BOTH_PLATFORMS = "Both"


def _path_size_bytes(path_str: str | None) -> int | None:
    """Best-effort total size of a build output file/folder, or None."""
    if not path_str:
        return None
    path = Path(path_str)
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return None
    return None


def _format_economy_findings(findings: EconomySimulationFindings) -> str:
    lines = [f"Simulated playthroughs: {findings.playthroughs}", "", "Dominant strategies:"]
    if findings.dominant_strategies:
        for d in findings.dominant_strategies:
            lines.append(
                f"- {d.item_name} (unlocks at level {d.from_level}): "
                f"{d.pick_rate * 100:.0f}% of playthroughs"
            )
    else:
        lines.append("- None found.")
    lines.append("")
    lines.append("Never purchased in any playthrough:")
    if findings.never_purchased:
        lines.extend(f"- {name}" for name in findings.never_purchased)
    else:
        lines.append("- Every item was bought in at least one playthrough.")
    return "\n".join(lines)


_CASE_STATUS_STATE = {
    "Pass": "pass",
    "Fail": "fail",
    "Blocked": "warn",
    "Not Run": "neutral",
}


# --- Frutiger Aqua visual-alignment helpers ---------------------------------
#
# Reusable pieces for the restyle: a dark-glass "hero card" wrapper for a
# tab's one primary action (Run Unity Tests, Build Pipeline), a colored
# status-orb row (Known Issues, Test cases), and a checklist row (label left,
# colored status right -- Accessibility, Economy Dominant Strategies). None
# of these touch how their data is computed -- only how it's laid out.


def _hero_section(parent_layout: QVBoxLayout) -> QVBoxLayout:
    """Wraps whatever gets built into the returned layout in a dark-glass
    hero card (reusing ui.theme's QFrame#ToolHeroCard recipe from the
    Debugging Buddy tool switcher) and adds that card to ``parent_layout``."""
    card = QFrame()
    card.setObjectName("ToolHeroCard")
    inner = QVBoxLayout(card)
    inner.setContentsMargins(20, 18, 20, 18)
    inner.setSpacing(10)
    parent_layout.addWidget(card)
    return inner


def _card_section(parent_layout: QVBoxLayout) -> QVBoxLayout:
    """Wraps whatever gets built into the returned layout in a light glass
    card (ui.theme's QFrame#Card recipe, with real drop-shadow elevation --
    Qt QSS has no box-shadow) and adds that card to ``parent_layout``. Every
    tab's sections used to just stack straight onto the page background
    with only a heading to separate them; wrapping each in its own card is
    what actually makes the screen read as distinct, compact sections
    instead of one long undifferentiated scroll."""
    card = QFrame()
    card.setObjectName("Card")
    inner = QVBoxLayout(card)
    inner.setContentsMargins(18, 16, 18, 16)
    inner.setSpacing(8)
    shadow = QGraphicsDropShadowEffect(card)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 5)
    shadow.setColor(QColor(20, 10, 40, 80))
    card.setGraphicsEffect(shadow)
    parent_layout.addWidget(card)
    return inner


def _status_row(state: str, title: str, subtitle: str) -> QWidget:
    """A colored status-orb list row: used as a QListWidget item widget for
    both Known Issues and Test cases (see _refresh_known_issues/_refresh_cases)."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setSpacing(10)
    dot = QLabel()
    dot.setObjectName("StatusDot")
    dot.setProperty("state", state)
    dot.setFixedSize(14, 14)
    layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
    text_col = QVBoxLayout()
    text_col.setSpacing(1)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: 700;")
    title_label.setWordWrap(True)
    text_col.addWidget(title_label)
    if subtitle:
        sub_label = QLabel(subtitle)
        sub_label.setObjectName("Muted")
        sub_label.setWordWrap(True)
        text_col.addWidget(sub_label)
    layout.addLayout(text_col, 1)
    return row


def _checklist_row(label: str, status_text: str, state: str) -> QWidget:
    """A checklist row: label left, bold colored status right -- used for
    Accessibility's WCAG/caption/control checks and Economy's dominant-
    strategy findings."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(10)
    left = QLabel(label)
    left.setWordWrap(True)
    layout.addWidget(left, 1)
    right = QLabel(status_text)
    right.setObjectName("ChecklistStatus")
    right.setProperty("state", state)
    layout.addWidget(right, 0)
    return row


def _progress_row(label: str, pct: float, caption: str) -> QWidget:
    """A labeled progress-bar row -- Economy Dominant Strategies' pick-rate
    bars, same "item name, N% of playthroughs, gradient bar" shape as the
    Feedback screen's theme cards."""
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(2)
    top = QHBoxLayout()
    name = QLabel(label)
    name.setStyleSheet("font-weight: 700;")
    top.addWidget(name, 1)
    caption_label = QLabel(caption)
    caption_label.setObjectName("Muted")
    top.addWidget(caption_label, 0)
    layout.addLayout(top)
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(round(max(0.0, min(100.0, pct))))
    bar.setTextVisible(False)
    layout.addWidget(bar)
    return row


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class _FunctionalWorker(QObject):
    done = Signal(object)  # TestReview
    failed = Signal(str)

    def __init__(
        self, services: Services, results_text: str, source_type: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._results_text = results_text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            project = self._services.active_project()
            team_mode = self._services.team_mode_enabled()
            review = self._services.testing.analyze(
                provider,
                self._results_text,
                project=project,
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
                team_mode=team_mode,
                team_members=self._services.team_prompt_context(project) if team_mode else None,
            )
            # Opt-In Only Telemetry (Phase C): a bare, anonymous event name —
            # no test content or project data. No-op unless enabled.
            self._services.record_telemetry_event("testing.test_review_run")
            self.done.emit(review)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class _UnityRunWorker(QObject):
    """Runs one or more Unity test platforms sequentially on a worker thread.

    Emits per-platform so a failure on one platform (e.g. PlayMode timing out)
    doesn't hide a result already obtained from another (e.g. EditMode).

    Also emits ``progress`` (Live Task Progress Transparency, Phase L) with a
    plain-language description of each real step -- launching a platform,
    then reviewing its results -- since a full Unity test run naturally has
    several minutes-long steps a developer benefits from seeing named, not
    just a spinner. Purely additive: ``platform_started``/``platform_done``/
    ``platform_failed`` still carry the exact same information they always
    did, for callers that don't care about the progress trail.
    """

    platform_started = Signal(str)
    platform_done = Signal(str, object)  # platform, TestReview
    platform_failed = Signal(str, str)  # platform, message
    progress = Signal(str)
    finished = Signal()

    def __init__(self, services: Services, project, editor_path: str, platforms: list[str]) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._editor_path = editor_path
        self._platforms = platforms

    def run(self) -> None:
        total = len(self._platforms)
        try:
            provider = self._services.build_provider()
        except Exception as exc:
            self.platform_failed.emit(
                self._platforms[0], f"Could not set up the AI provider: {exc}"
            )
            self.finished.emit()
            return
        if not provider.is_available():
            # Checked before launching Unity at all: a run can take a long time, and
            # there's no point spending it only to fail on the AI review afterward.
            self.platform_failed.emit(
                self._platforms[0],
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file, or switch to the Mock provider in Settings, before running "
                "tests — this is checked first so a run isn't wasted.",
            )
            self.finished.emit()
            return

        team_mode = self._services.team_mode_enabled()
        team_members = self._services.team_prompt_context(self._project) if team_mode else None
        for index, platform in enumerate(self._platforms, start=1):
            self.platform_started.emit(platform)
            self.progress.emit(f"Running {platform} tests… ({index} of {total})")
            try:
                result = run_tests(self._editor_path, self._project.path, platform)
                if not result.succeeded:
                    message = result.error or "Unity did not produce a results file."
                    if result.log_tail:
                        message += f"\n\nLog excerpt:\n{result.log_tail}"
                    self.platform_failed.emit(platform, message)
                    self.progress.emit(f"{platform} tests did not complete successfully.")
                    continue
                self.progress.emit(f"Reviewing {platform} results with the AI provider…")
                review = self._services.testing.analyze(
                    provider,
                    result.results_xml,
                    project=self._project,
                    source_type=SOURCE_UNITY_RUN,
                    source_filename=f"unity-{platform.lower()}-run.xml",
                    record_usage=self._services.usage.record_prompt,
                    team_mode=team_mode,
                    team_members=team_members,
                )
                self.platform_done.emit(platform, review)
                self.progress.emit(f"{platform} tests complete.")
            except ProviderNotReadyError as exc:
                self.platform_failed.emit(platform, str(exc))
            except Exception as exc:  # surfaced calmly to the user
                self.platform_failed.emit(platform, f"Something went wrong: {exc}")
        self.progress.emit("All platforms finished.")
        self.finished.emit()


class _PerformanceWorker(QObject):
    done = Signal(object)  # PerformanceReview
    failed = Signal(str)

    def __init__(
        self,
        services: Services,
        text: str,
        source_type: str,
        source_filename: str | None,
        target_hardware: str | None,
    ) -> None:
        super().__init__()
        self._services = services
        self._text = text
        self._source_type = source_type
        self._source_filename = source_filename
        self._target_hardware = target_hardware

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.performance.analyze(
                provider,
                self._text,
                project=self._services.active_project(),
                target_hardware=self._target_hardware,
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("testing.performance_review_run")
            self.done.emit(review)
        except PerformanceNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class _AccessibilityWorker(QObject):
    done = Signal(object)  # AccessibilityReview
    failed = Signal(str)

    def __init__(
        self, services: Services, text: str, source_type: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._text = text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.accessibility.analyze(
                provider,
                self._text,
                project=self._services.active_project(),
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except AccessibilityNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class _PlayerCrashSyncWorker(QObject):
    """Player Crash & Error Reporting: pulls new reports for a team-linked
    project and merges them into Known Issues (see core.player_crash_reports).
    """

    done = Signal(object)  # PlayerCrashSyncResult
    failed = Signal(str)

    def __init__(self, services: Services, project_id: int, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_id = project_id
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            result = self._services.player_crash_sync.sync(self._project_id, self._project_uuid)
            self.done.emit(result)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while syncing player crash reports: {exc}")


class _BuildWorker(QObject):
    """Also emits ``progress`` (Live Task Progress Transparency, Phase L)
    with a plain-language description of each real pipeline step -- see
    ``core.build_pipeline.run_build_pipeline``'s ``on_progress`` param. A
    manual "Run build now" click is exactly the kind of multi-minute action
    (resolve Editor, prepare script, run the headless build, save the
    report) worth naming steps for, not just a bare spinner.
    """

    done = Signal(object)  # BuildReport
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, services: Services, project, target_platform: str) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._target_platform = target_platform

    def run(self) -> None:
        try:
            report = self._services.run_build(
                self._project,
                trigger=TRIGGER_MANUAL,
                target_platform=self._target_platform,
                editor_override=self._project.unity_editor_path_override,
                on_progress=self.progress.emit,
            )
            self.done.emit(report)
        except (BuildNotEnabledError, BuildUnavailableError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while building: {exc}")


class _ChecklistAIWorker(QObject):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, services: Services, checklist: ReleaseChecklist) -> None:
        super().__init__()
        self._services = services
        self._checklist = checklist

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            if not provider.is_available():
                self.failed.emit(
                    f"The {provider.display_name()} provider isn't ready. The checklist above "
                    "still works with no provider — add its API key to a local .env file, or "
                    "switch to the Mock provider in Settings, for an AI take."
                )
                return
            project = self._services.active_project()
            text = analyze_checklist(
                provider, self._checklist, project_name=project.name if project else None
            )
            self._services.usage.record_prompt(provider.name)
            self.done.emit(text)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong: {exc}")


class _EconomySimulationAIWorker(QObject):
    done = Signal(object)  # EconomySimulationReview
    failed = Signal(str)

    def __init__(self, services: Services, project, data: dict) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._data = data

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.economy_simulator.analyze(
                provider, self._project, self._data, record_usage=self._services.usage.record_prompt
            )
            self.done.emit(review)
        except (EconomyNotReadyError, InvalidEconomyDataError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong: {exc}")


# "Send to Team Board" routing entry point (Phase J, #3) for Known Issues.
# Best-effort discipline inference from the issue's own free-text category
# -- falls back to "programmer" (bugs/regressions are the default routing
# target per core.notification_routing's known_issue_opened default) rather
# than leaving it unassigned, since an unassigned task is easy to miss on
# the board.
_KNOWN_ISSUE_CATEGORY_DISCIPLINE_HINTS = {
    "audio": "audio", "sound": "audio",
    "animation": "animation", "anim": "animation",
    "art": "artist", "visual": "artist", "graphic": "artist",
    "ui": "design", "design": "design",
}


def _infer_known_issue_discipline(category: str | None) -> str:
    lowered = (category or "").lower()
    for hint, discipline in _KNOWN_ISSUE_CATEGORY_DISCIPLINE_HINTS.items():
        if hint in lowered:
            return discipline
    return "programmer"


class _SendKnownIssueToTeamBoardWorker(QObject):
    done = Signal(object)  # TeamTask | None
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str, issue) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid
        self._issue = issue

    def run(self) -> None:
        try:
            issue = self._issue
            task = self._services.teams.send_finding_to_team_board(
                self._project_uuid,
                f"Known Issue: {issue.title}",
                description=(
                    f"Source: {issue.source}. Status: {issue.status}. "
                    f"Seen {issue.occurrences} time(s), first {issue.first_seen_at}, "
                    f"last {issue.last_seen_at}."
                ),
                assigned_discipline=_infer_known_issue_discipline(issue.category),
                source_type="known_issue",
                source_ref=f"known_issue:{issue.id}",
            )
            self.done.emit(task)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't send to the Team board: {exc}")


class TestingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._pending_filename: str | None = None
        self._selected_case_id: int | None = None
        self._selected_issue_id: int | None = None
        self._known_issues_cache: list = []
        self._perf_pending_filename: str | None = None
        self._access_pending_filename: str | None = None
        self._last_checklist: ReleaseChecklist | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        header = QVBoxLayout()
        header.setContentsMargins(28, 28, 28, 0)
        title = QLabel("Automated Testing")
        title.setObjectName("ScreenTitle")
        header.addWidget(title)
        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        header.addWidget(self._context_label)
        # Build Health Score (Phase 2): a persistent, always-visible header —
        # the spec calls for this placement specifically, reusing
        # core.dashboard.assess_readiness() rather than a new scoring model.
        badge_row = QHBoxLayout()
        self._readiness_badge = ReadinessBadge()
        badge_row.addWidget(self._readiness_badge, 1)
        # Store Page / Build Checklist (Phase D): reachable right from the
        # Build Health Score area, per spec, rather than only buried in a tab.
        self._ready_to_ship_btn = PillButton("Ready to Ship checklist", ghost=True)
        self._ready_to_ship_btn.clicked.connect(self._on_open_ready_to_ship)
        badge_row.addWidget(self._ready_to_ship_btn)
        header.addLayout(badge_row)
        outer.addLayout(header)

        # Rapid Prototyping Mode (Phase H, section 7 part 2, Core tier): a
        # minimal pass/fail check-in, foregrounded only while the app-wide
        # toggle (Settings screen) is on. Hidden entirely otherwise — see
        # refresh() / _apply_prototype_mode.
        self._smoke_test_panel = self._build_quick_smoke_test()
        outer.addWidget(self._smoke_test_panel)
        self._smoke_test_panel.setVisible(False)

        # Collapsed by default whenever Rapid Prototyping Mode is on — see
        # _apply_prototype_mode. Irrelevant while the mode is off, since the
        # suite is always shown then regardless of this flag.
        self._qa_suite_expanded = False
        self._qa_toggle_btn = PillButton("▸ Full QA suite (click to expand)", ghost=True)
        self._qa_toggle_btn.clicked.connect(self._on_toggle_qa_suite)
        self._qa_toggle_btn.setVisible(False)
        outer.addWidget(self._qa_toggle_btn)

        self._tabs = PillTabWidget()
        outer.addWidget(self._tabs, 1)
        self._tabs.addTab(self._build_functional_tab(), "Functional")
        self._tabs.addTab(self._build_performance_tab(), "Performance")
        self._tabs.addTab(self._build_accessibility_tab(), "Accessibility")
        self._release_tab_index = self._tabs.addTab(self._build_release_tab(), "Build & Release")
        self._tabs.addTab(self._build_economy_tab(), "Economy Simulation")

        self.refresh()

    def _on_open_ready_to_ship(self) -> None:
        self._tabs.setCurrentIndex(self._release_tab_index)
        self._on_show_checklist()

    # --- Rapid Prototyping Mode: Quick Smoke Test panel -----------------------

    def _build_quick_smoke_test(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 8, 28, 8)
        layout.setSpacing(8)

        heading = QLabel("Quick Smoke Test")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Rapid Prototyping Mode is on (Settings screen). Skip deep testing for now — just "
            "record whether the idea works at all. The full QA suite below still has "
            "everything; it's just collapsed out of the way while you're prototyping."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._smoke_input = QLineEdit()
        self._smoke_input.setPlaceholderText("What did you just try?")
        row.addWidget(self._smoke_input, 1)
        self._smoke_works_btn = PillButton("Works")
        self._smoke_works_btn.clicked.connect(lambda: self._on_smoke_result(True))
        row.addWidget(self._smoke_works_btn)
        self._smoke_fails_btn = PillButton("Doesn't work yet", ghost=True)
        self._smoke_fails_btn.clicked.connect(lambda: self._on_smoke_result(False))
        row.addWidget(self._smoke_fails_btn)
        layout.addLayout(row)

        self._smoke_status = QLabel("")
        self._smoke_status.setObjectName("Muted")
        self._smoke_status.setWordWrap(True)
        layout.addWidget(self._smoke_status)

        return panel

    def _on_smoke_result(self, passed: bool) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        description = self._smoke_input.text().strip()
        if not description:
            QMessageBox.information(
                self, "Nothing to record", "Describe what you just tried first."
            )
            return
        case = self._services.testing.create_case(project.id, title=description)
        self._services.testing.update_case(
            case.id,
            title=case.title,
            category=case.category,
            priority=case.priority,
            status="Pass" if passed else "Fail",
        )
        self._smoke_input.clear()
        verdict = "works" if passed else "doesn't work yet"
        self._smoke_status.setText(f'Recorded: "{description}" — {verdict}.')
        self._refresh_cases()

    def _on_toggle_qa_suite(self) -> None:
        self._qa_suite_expanded = not self._qa_suite_expanded
        self._apply_prototype_mode()

    def _apply_prototype_mode(self) -> None:
        """Foreground the smoke-test panel and de-emphasize (collapse) the
        full QA suite while Rapid Prototyping Mode is on -- nothing about
        the full suite is removed, only what's foregrounded by default."""
        enabled = self._services.prototype_mode_enabled()
        self._smoke_test_panel.setVisible(enabled)
        self._qa_toggle_btn.setVisible(enabled)
        if enabled:
            arrow = "▾" if self._qa_suite_expanded else "▸"
            action = "collapse" if self._qa_suite_expanded else "expand"
            self._qa_toggle_btn.setText(f"{arrow} Full QA suite (click to {action})")
            self._tabs.setVisible(self._qa_suite_expanded)
        else:
            self._tabs.setVisible(True)

    def _scrollable(self) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 12, 28, 28)
        layout.setSpacing(12)
        return container, layout

    # --- Functional tab ------------------------------------------------

    def _build_functional_tab(self) -> QWidget:
        # Save Compatibility and Test Generation aren't shown in this pass
        # (per the design handoff).
        container, layout = self._scrollable()
        self._build_case_form(_card_section(layout))
        self._build_unity_run(_hero_section(layout))
        self._build_case_and_issue_list(_card_section(layout))
        self._build_analyze(_card_section(layout))
        return container

    def _build_case_form(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Add a test case")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("e.g. Player takes damage from spikes")
        self._category_input = ScrollSafeComboBox()
        self._category_input.addItems(CATEGORIES)
        self._category_input.setCurrentText("General")
        self._priority_input = ScrollSafeComboBox()
        self._priority_input.addItems(PRIORITIES)
        self._priority_input.setCurrentText("Medium")
        self._steps_input = QPlainTextEdit()
        self._steps_input.setPlaceholderText("Steps to reproduce / perform the check…")
        self._steps_input.setFixedHeight(60)
        self._expected_input = QPlainTextEdit()
        self._expected_input.setPlaceholderText("What should happen…")
        self._expected_input.setFixedHeight(60)

        form.addRow("Title", self._title_input)
        form.addRow("Category", self._category_input)
        form.addRow("Priority", self._priority_input)
        form.addRow("Steps", self._steps_input)
        form.addRow("Expected", self._expected_input)
        layout.addLayout(form)

        row = QHBoxLayout()
        self._selection_hint = QLabel("Editing a new test case.")
        self._selection_hint.setObjectName("Muted")
        row.addWidget(self._selection_hint)
        row.addStretch(1)
        self._clear_btn = PillButton("New / clear")
        self._clear_btn.clicked.connect(self._on_clear_selection)
        row.addWidget(self._clear_btn)
        self._delete_btn = PillButton("Delete")
        self._delete_btn.clicked.connect(self._on_delete_case)
        row.addWidget(self._delete_btn)
        self._add_btn = PillButton("Add test case")
        self._add_btn.clicked.connect(self._on_add_case)
        row.addWidget(self._add_btn)
        self._save_btn = PillButton("Save changes")
        self._save_btn.clicked.connect(self._on_save_case)
        row.addWidget(self._save_btn)
        layout.addLayout(row)


    def _build_unity_run(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Run Unity tests")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Opt-in per project (Projects screen). Launches your project's Unity Editor "
            "headlessly to run its own tests, then feeds the results into the same review "
            "and Known Issues matching as a pasted result — nothing else about how Spiced "
            "handles results changes."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._unity_run_status = QLabel()
        self._unity_run_status.setObjectName("Muted")
        self._unity_run_status.setWordWrap(True)
        layout.addWidget(self._unity_run_status)

        row = QHBoxLayout()
        self._unity_platform_group = QButtonGroup(self)
        self._unity_platform_group.setExclusive(True)
        self._unity_platform_buttons: dict[str, QPushButton] = {}
        for platform in (EDIT_MODE, PLAY_MODE, _BOTH_PLATFORMS):
            btn = PillButton(platform)
            btn.setObjectName("PlatformPill")
            btn.setCheckable(True)
            self._unity_platform_group.addButton(btn)
            self._unity_platform_buttons[platform] = btn
            row.addWidget(btn)
        self._unity_platform_buttons[EDIT_MODE].setChecked(True)
        row.addStretch(1)
        self._unity_run_btn = PillButton("Run Tests Now")
        self._unity_run_btn.clicked.connect(self._on_run_unity_tests)
        row.addWidget(self._unity_run_btn)
        layout.addLayout(row)

        # Live Task Progress Transparency (Phase L): a Unity test run
        # naturally has several minutes-long steps (launch each platform,
        # review its results) worth naming, not just a spinner -- see
        # _UnityRunWorker.progress.
        self._unity_progress_trail = ProgressTrail()
        layout.addWidget(self._unity_progress_trail)

        self._unity_run_result = QTextEdit()
        self._unity_run_result.setReadOnly(True)
        self._unity_run_result.setPlaceholderText(
            "Unity test-run output and review will appear here."
        )
        self._unity_run_result.setFixedHeight(180)
        layout.addWidget(self._unity_run_result)

    def _build_analyze(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Analyze Test Results")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Paste test output or import a .txt/.log/.json/.xml file. Spiced reads it locally, "
            "then summarizes pass/fail and suggests a retest checklist — it never ran the tests."
        )
        layout.addWidget(heading)

        self._results_input = QPlainTextEdit()
        self._results_input.setPlaceholderText("Paste your test-run output here…")
        self._results_input.setFixedHeight(120)
        layout.addWidget(self._results_input)

        row = QHBoxLayout()
        self._import_btn = PillButton("Import result file…", ghost=True)
        self._import_btn.clicked.connect(self._on_import)
        row.addWidget(self._import_btn)
        row.addStretch(1)
        self._analyze_btn = PillButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self._analyze_btn)
        layout.addLayout(row)

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText("Your structured test-result review will appear here.")
        self._result.setFixedHeight(200)
        layout.addWidget(self._result)

        # Transparent AI Reasoning (Phase C): matched known issue(s), or the
        # raw results excerpt that was actually sent.
        self._source_link = SourceLinkExpander()
        layout.addWidget(self._source_link)

        history_title = QLabel("Recent test runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(110)
        layout.addWidget(self._history)

    def _build_case_and_issue_list(self, layout: QVBoxLayout) -> None:
        """Test cases and Known Issues, merged into one status-orb list
        (design handoff) -- each row is a colored gel orb + bold title +
        muted description, whichever kind it is (see _status_row /
        _ITEM_KIND_ROLE). The two kinds keep their own separate selection
        state and action controls underneath (status update for a case;
        resolve/reopen/team-board/comments for an issue) -- only the list
        display and the empty state are actually shared."""
        heading = QLabel("Test Cases & Known Issues")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Your manual test cases, plus bugs Spiced has flagged before from debugging "
            "sessions and test failures -- new failures are checked against known issues so "
            "repeats surface as \"this resembles a bug from before\" instead of starting over."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._combined_list = QListWidget()
        self._combined_list.setMinimumHeight(220)
        self._combined_list.currentItemChanged.connect(self._on_combined_selected)
        layout.addWidget(self._combined_list)

        self._combined_empty = QLabel("No test cases or known issues yet.")
        self._combined_empty.setObjectName("Muted")
        layout.addWidget(self._combined_empty)

        case_row = QHBoxLayout()
        case_row.addWidget(QLabel("Set test case status:"))
        self._status_input = ScrollSafeComboBox()
        self._status_input.addItems(STATUSES)
        self._status_input.currentTextChanged.connect(self._on_status_choice_changed)
        case_row.addWidget(self._status_input)
        self._failure_note_input = QLineEdit()
        self._failure_note_input.setPlaceholderText("Failure note (used when status is Fail)")
        case_row.addWidget(self._failure_note_input, 1)
        self._update_status_btn = PillButton("Update")
        self._update_status_btn.clicked.connect(self._on_update_status)
        case_row.addWidget(self._update_status_btn)
        layout.addLayout(case_row)

        row = QHBoxLayout()
        row.addStretch(1)
        self._resolve_btn = PillButton("Mark resolved")
        self._resolve_btn.clicked.connect(self._on_mark_resolved)
        row.addWidget(self._resolve_btn)
        self._reopen_btn = PillButton("Reopen")
        self._reopen_btn.clicked.connect(self._on_mark_open)
        row.addWidget(self._reopen_btn)
        # "Send to Team Board" routing entry point (Phase J, #3): only
        # enabled with a selected issue AND a team-linked active project --
        # creates a TeamTask with a best-effort discipline inferred from the
        # issue's category and a source_ref back to the known_issue id.
        self._issue_send_btn = PillButton("Send to Team Board", ghost=True)
        self._issue_send_btn.setEnabled(False)
        self._issue_send_btn.clicked.connect(self._on_send_issue_to_team_board)
        row.addWidget(self._issue_send_btn)
        layout.addLayout(row)

        self._issue_send_status = QLabel("")
        self._issue_send_status.setObjectName("Muted")
        self._issue_send_status.setWordWrap(True)
        layout.addWidget(self._issue_send_status)

        # Comment Threads on Assets/Builds (Phase J, #5): attached to
        # whichever Known Issue is currently selected above.
        self._issue_comments = CommentsWidget(self._services)
        layout.addWidget(self._issue_comments)

        # Player Crash & Error Reporting (Phase G, section 7): only
        # reachable for a team-linked project — see
        # docs/player_crash_reporting.md for why a solo/local-only project
        # has no project_uuid to sync against at all.
        self._player_crash_status = QLabel()
        self._player_crash_status.setObjectName("Muted")
        self._player_crash_status.setWordWrap(True)
        layout.addWidget(self._player_crash_status)

        sync_row = QHBoxLayout()
        sync_row.addStretch(1)
        self._player_crash_sync_btn = PillButton("Sync player crash reports")
        self._player_crash_sync_btn.clicked.connect(self._on_sync_player_crashes)
        sync_row.addWidget(self._player_crash_sync_btn)
        layout.addLayout(sync_row)

    # --- Economy Simulation tab ---------------------------------------------

    def _build_economy_tab(self) -> QWidget:
        container, layout = self._scrollable()
        self._build_economy_dominant_strategies(_card_section(layout))
        self._build_economy_simulate(_card_section(layout))
        return container

    def _build_economy_dominant_strategies(self, layout: QVBoxLayout) -> None:
        # The headline visual -- reuses the Feedback screen's "item name, N%
        # of playthroughs, gradient bar" pattern (see _progress_row) instead
        # of a plain text dump, straight from the already-computed
        # EconomySimulationFindings once a simulation has run below.
        self._economy_dominant_layout = layout
        heading = QLabel("Dominant Strategies")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        dominant_empty = QLabel("Simulate below to see dominant strategies here.")
        dominant_empty.setObjectName("Muted")
        dominant_empty.setWordWrap(True)
        layout.addWidget(dominant_empty)

    def _build_economy_simulate(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Simulate Economy")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Only useful for projects with a buy-with-currency progression system (items, "
            "costs, unlock levels). Paste economy data below and Spiced runs a local, "
            "deterministic simulation across many simulated playthroughs, flagging any item "
            f"that turns out to be the mathematically dominant choice.\n\n{ECONOMY_SCHEMA_DOC}"
        )
        layout.addWidget(heading)

        self._economy_input = QPlainTextEdit()
        self._economy_input.setPlaceholderText("Paste economy JSON here…")
        self._economy_input.setFixedHeight(100)
        layout.addWidget(self._economy_input)

        row = QHBoxLayout()
        self._economy_simulate_btn = PillButton("Simulate (local, free)")
        self._economy_simulate_btn.clicked.connect(self._on_economy_simulate)
        row.addWidget(self._economy_simulate_btn)
        row.addStretch(1)
        self._economy_ai_btn = PillButton("Get AI summary", ghost=True)
        self._economy_ai_btn.clicked.connect(self._on_economy_ai)
        row.addWidget(self._economy_ai_btn)
        layout.addLayout(row)

        result_label = QLabel("Result")
        result_label.setObjectName("SectionTitle")
        layout.addWidget(result_label)
        self._economy_result = QTextEdit()
        self._economy_result.setReadOnly(True)
        self._economy_result.setPlaceholderText("Simulation results will appear here.")
        self._economy_result.setFixedHeight(160)
        layout.addWidget(self._economy_result)

        history_title = QLabel("Recent simulations")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._economy_history = QTextEdit()
        self._economy_history.setReadOnly(True)
        self._economy_history.setFixedHeight(90)
        layout.addWidget(self._economy_history)

    # --- Performance tab -------------------------------------------------

    def _build_performance_tab(self) -> QWidget:
        container, layout = self._scrollable()
        self._build_performance_chart(_card_section(layout))
        self._build_performance_analyze(_card_section(layout))
        return container

    def _build_performance_chart(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Frame Rate")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        self._perf_chart_caption = QLabel(
            "Analyze performance numbers below to see a per-location chart here."
        )
        self._perf_chart_caption.setObjectName("Muted")
        self._perf_chart_caption.setWordWrap(True)
        layout.addWidget(self._perf_chart_caption)
        self._perf_chart = FrameRateBarChart()
        layout.addWidget(self._perf_chart)

    def _build_performance_analyze(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Analyze Performance Numbers")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Paste or import numbers you already gathered (fps, memory, load time per "
            "location) as text, CSV, or JSON — Spiced never profiles your build itself."
        )
        layout.addWidget(heading)

        self._perf_input = QPlainTextEdit()
        self._perf_input.setPlaceholderText(
            "e.g. Waterfall Area: fps=42, memory=850MB, load=3.2s"
        )
        self._perf_input.setFixedHeight(90)
        layout.addWidget(self._perf_input)

        hw_row = QHBoxLayout()
        hw_row.addWidget(QLabel("Target hardware (optional simulation, not a real device test):"))
        self._hardware_input = ScrollSafeComboBox()
        self._hardware_input.addItem(_NO_HARDWARE)
        self._hardware_input.addItems(available_tiers())
        hw_row.addWidget(self._hardware_input, 1)
        layout.addLayout(hw_row)

        row = QHBoxLayout()
        self._perf_import_btn = PillButton("Import performance file…", ghost=True)
        self._perf_import_btn.clicked.connect(self._on_perf_import)
        row.addWidget(self._perf_import_btn)
        row.addStretch(1)
        self._perf_analyze_btn = PillButton("Analyze")
        self._perf_analyze_btn.clicked.connect(self._on_perf_analyze)
        row.addWidget(self._perf_analyze_btn)
        layout.addLayout(row)

        result_label = QLabel("Result")
        result_label.setObjectName("SectionTitle")
        layout.addWidget(result_label)
        self._perf_result = QTextEdit()
        self._perf_result.setReadOnly(True)
        self._perf_result.setPlaceholderText("Your performance review will appear here.")
        self._perf_result.setFixedHeight(160)
        layout.addWidget(self._perf_result)

        self._perf_source_link = SourceLinkExpander()
        layout.addWidget(self._perf_source_link)

        history_title = QLabel("Recent performance reports")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._perf_history = QTextEdit()
        self._perf_history.setReadOnly(True)
        self._perf_history.setFixedHeight(90)
        layout.addWidget(self._perf_history)

    # --- Accessibility tab -------------------------------------------------

    def _build_accessibility_tab(self) -> QWidget:
        container, layout = self._scrollable()
        self._build_accessibility_checklist(_card_section(layout))
        self._build_accessibility_analyze(_card_section(layout))
        return container

    def _build_accessibility_checklist(self, layout: QVBoxLayout) -> None:
        # The headline visual, per the design handoff -- populated from the
        # already-computed ParsedAccessibility once an analysis has run (see
        # _on_access_done/_render_access_checklist), not a separate AI call.
        self._access_checklist_layout = layout
        heading = QLabel("Accessibility Checklist")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        checklist_empty = QLabel("Paste and analyze a checklist below to see results here.")
        checklist_empty.setObjectName("Muted")
        checklist_empty.setWordWrap(True)
        layout.addWidget(checklist_empty)

    def _build_accessibility_analyze(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Analyze for Accessibility")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Paste a small JSON description of your HUD colors, audio captions, and control/"
            "text-scaling support. Spiced runs real WCAG contrast math and a colorblind-"
            "simulation check locally, then scores the checklist — never a shaming grade. "
            'Example: {"hud_elements": [{"name": "HealthBar", "foreground": "#FF4040", '
            '"background": "#550000"}], "audio_files": [{"name": "vo_01.wav", '
            '"captioned": true}], "controls_remappable": true, "text_scaling_supported": false}'
        )
        layout.addWidget(heading)

        self._access_input = QPlainTextEdit()
        self._access_input.setPlaceholderText("Paste a script, UI text dump, or notes to check…")
        self._access_input.setFixedHeight(90)
        layout.addWidget(self._access_input)

        row = QHBoxLayout()
        self._access_import_btn = PillButton("Import checklist file…", ghost=True)
        self._access_import_btn.clicked.connect(self._on_access_import)
        row.addWidget(self._access_import_btn)
        row.addStretch(1)
        self._access_analyze_btn = PillButton("Analyze")
        self._access_analyze_btn.clicked.connect(self._on_access_analyze)
        row.addWidget(self._access_analyze_btn)
        layout.addLayout(row)

        result_label = QLabel("Result")
        result_label.setObjectName("SectionTitle")
        layout.addWidget(result_label)
        self._access_result = QTextEdit()
        self._access_result.setReadOnly(True)
        self._access_result.setPlaceholderText("Your accessibility review will appear here.")
        self._access_result.setFixedHeight(160)
        layout.addWidget(self._access_result)

        self._access_source_link = SourceLinkExpander()
        layout.addWidget(self._access_source_link)

        history_title = QLabel("Recent accessibility passes")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._access_history = QTextEdit()
        self._access_history.setReadOnly(True)
        self._access_history.setFixedHeight(90)
        layout.addWidget(self._access_history)

    # --- Build & Release tab (Automated Build Pipeline + Store Checklist) --

    def _build_release_tab(self) -> QWidget:
        container, layout = self._scrollable()
        self._build_checklist_section(_card_section(layout))
        self._build_build_pipeline_section(_hero_section(layout))
        return container

    def _build_build_pipeline_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Build Pipeline")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Opt-in per project (Projects screen). When enabled, Spiced writes a standard "
            "Editor build script into this project if one doesn't already exist, then triggers "
            "a headless build here or nightly while Spiced is open (in-app scheduler only — "
            "no Windows Task Scheduler entry is ever registered). A quiet success never "
            "interrupts you; only a failure does.\n"
            "Note: if Spiced found and reused your own existing build script instead of "
            "writing one, it can only tell success from failure if that script writes back "
            "Spiced's small result file — otherwise a real success may show here as \"no "
            "result file\" until the script adopts that convention (see the build log)."
        )
        layout.addWidget(heading)

        self._build_status = QLabel()
        self._build_status.setObjectName("Muted")
        self._build_status.setWordWrap(True)
        layout.addWidget(self._build_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("Target platform:"))
        self._build_platform_input = ScrollSafeComboBox()
        self._build_platform_input.addItems(list(unity_build.BUILD_TARGETS))
        row.addWidget(self._build_platform_input)
        row.addStretch(1)
        self._build_run_btn = PillButton("Run build now")
        self._build_run_btn.clicked.connect(self._on_run_build)
        row.addWidget(self._build_run_btn)
        layout.addLayout(row)

        # Live Task Progress Transparency (Phase L): a manual build has
        # several real, minutes-long steps -- see _BuildWorker.progress.
        self._build_progress_trail = ProgressTrail()
        layout.addWidget(self._build_progress_trail)

        self._build_result = QTextEdit()
        self._build_result.setReadOnly(True)
        self._build_result.setPlaceholderText("Build output will appear here.")
        self._build_result.setFixedHeight(140)
        layout.addWidget(self._build_result)

        history_title = QLabel("Recent builds")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._build_history = QListWidget()
        self._build_history.setFixedHeight(120)
        layout.addWidget(self._build_history)

        stable_row = QHBoxLayout()
        self._stable_status = QLabel()
        self._stable_status.setObjectName("Muted")
        self._stable_status.setWordWrap(True)
        stable_row.addWidget(self._stable_status, 1)
        self._mark_stable_btn = PillButton("Mark latest successful build stable", ghost=True)
        self._mark_stable_btn.clicked.connect(self._on_mark_stable)
        stable_row.addWidget(self._mark_stable_btn)
        layout.addLayout(stable_row)

    def _build_checklist_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Store Page / Build Checklist")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "A small, deterministic \"ready to ship\" checklist per store — works fully "
            "offline, no AI needed. Platform specifics change over time, so every checklist "
            "ends with a reminder to verify against the platform's current docs."
        )
        layout.addWidget(heading)

        row = QHBoxLayout()
        row.addWidget(QLabel("Platform:"))
        self._checklist_platform_input = ScrollSafeComboBox()
        for platform in PLATFORMS:
            self._checklist_platform_input.addItem(PLATFORM_LABELS[platform], platform)
        row.addWidget(self._checklist_platform_input)
        row.addStretch(1)
        self._checklist_btn = PillButton("Show checklist")
        self._checklist_btn.clicked.connect(self._on_show_checklist)
        row.addWidget(self._checklist_btn)
        self._checklist_ai_btn = PillButton("Get AI take", ghost=True)
        self._checklist_ai_btn.clicked.connect(self._on_checklist_ai)
        row.addWidget(self._checklist_ai_btn)
        layout.addLayout(row)

        result_label = QLabel("Result")
        result_label.setObjectName("SectionTitle")
        layout.addWidget(result_label)
        self._checklist_result = QTextEdit()
        self._checklist_result.setReadOnly(True)
        self._checklist_result.setPlaceholderText("Click \"Show checklist\" to see it.")
        self._checklist_result.setFixedHeight(160)
        layout.addWidget(self._checklist_result)

    # --- Refresh & state ---------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        if not has_project:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "add test cases and save results."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")

        summary = self._services.dashboard.summarize(project)
        team_linked = bool(project and project.project_uuid and self._services.team_mode_enabled())
        self._readiness_badge.set_readiness(
            summary.readiness if summary else None, team_linked=team_linked
        )
        self._apply_prototype_mode()

        for widget in (self._add_btn, self._title_input, self._update_status_btn):
            widget.setEnabled(has_project)

        self._refresh_cases()
        self._refresh_history()
        self._refresh_known_issues()
        self._refresh_player_crash_status()
        self._refresh_perf_history()
        self._refresh_access_history()
        self._refresh_unity_run_status()
        self._refresh_build_pipeline_status()
        self._refresh_build_history()
        self._refresh_economy_history()
        self._update_edit_buttons()

    def _update_edit_buttons(self) -> None:
        has_selection = self._selected_case_id is not None
        self._save_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._clear_btn.setEnabled(has_selection)
        if has_selection:
            self._selection_hint.setText("Editing the selected test case.")
        else:
            self._selection_hint.setText("Editing a new test case.")
        has_issue = self._selected_issue_id is not None
        self._resolve_btn.setEnabled(has_issue)
        self._reopen_btn.setEnabled(has_issue)
        project = self._services.active_project()
        team_linked = bool(project and project.project_uuid)
        self._issue_send_btn.setEnabled(has_issue and team_linked)

    def _remove_combined_items(self, kind: str) -> None:
        """Removes only rows of the given kind from the merged list --
        _refresh_cases and _refresh_known_issues each own one kind and run
        independently (from many call sites), so a full clear() would lose
        the other kind's rows and its current selection every time."""
        for index in reversed(range(self._combined_list.count())):
            item = self._combined_list.item(index)
            if item.data(_ITEM_KIND_ROLE) == kind:
                self._combined_list.takeItem(index)

    def _update_combined_empty_state(self) -> None:
        has_rows = self._combined_list.count() > 0
        self._combined_empty.setVisible(not has_rows)
        self._combined_list.setVisible(has_rows)

    def _refresh_cases(self) -> None:
        self._combined_list.blockSignals(True)
        self._remove_combined_items("case")
        project = self._services.active_project()
        cases = self._services.testing.list_cases(project.id) if project else []
        for index, case in enumerate(cases):
            note = f" — {case.failure_note}" if case.status == "Fail" and case.failure_note else ""
            subtitle = f"{case.category} · {case.priority}{note}"
            item = QListWidgetItem()
            item.setData(_USER_ROLE, case.id)
            item.setData(_ITEM_KIND_ROLE, "case")
            # Cases sort before issues -- insert at the front rather than
            # appending, since issue rows may already be sitting at the end.
            self._combined_list.insertItem(index, item)
            row = _status_row(_CASE_STATUS_STATE.get(case.status, "neutral"), case.title, subtitle)
            item.setSizeHint(row.sizeHint())
            self._combined_list.setItemWidget(item, row)
        self._combined_list.blockSignals(False)
        self._update_combined_empty_state()

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Test runs are saved once you select an active project.")
            return
        runs = self._services.testing.history(project.id, limit=10)
        if not runs:
            self._history.setPlainText("No test runs saved for this project yet.")
            return
        lines = []
        for run in runs:
            s = run.parsed_summary
            counts = f"{s.get('passed', 0)} passed / {s.get('failed', 0)} failed"
            name = f" · {run.source_filename}" if run.source_filename else ""
            summary = run.ai_summary or ""
            lines.append(f"[{run.created_at}]{name} · {counts}\n    {summary}")
        self._history.setPlainText("\n".join(lines))

    def _refresh_known_issues(self) -> None:
        self._combined_list.blockSignals(True)
        self._remove_combined_items("issue")
        project = self._services.active_project()
        issues = self._services.testing.known_issues(project.id) if project else []
        self._known_issues_cache = list(issues)
        for issue in issues:
            when = issue.resolved_at or issue.last_seen_at
            when_label = "resolved" if issue.status == STATUS_RESOLVED else "last seen"
            subtitle = f"seen {issue.occurrences}x · {when_label} {when}"
            if issue.source == SOURCE_PLAYER:
                subtitle += " · from players"
            state = "pass" if issue.status == STATUS_RESOLVED else "fail"
            item = QListWidgetItem()
            item.setData(_USER_ROLE, issue.id)
            item.setData(_ITEM_KIND_ROLE, "issue")
            # Issues sort after cases -- always appended at the end.
            self._combined_list.addItem(item)
            row = _status_row(state, issue.title, subtitle)
            item.setSizeHint(row.sizeHint())
            self._combined_list.setItemWidget(item, row)
        self._combined_list.blockSignals(False)
        self._update_combined_empty_state()
        self._selected_issue_id = None
        self._issue_comments.set_subject(None, "known_issue", "")
        self._update_edit_buttons()

    def _refresh_perf_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._perf_history.setPlainText(
                "Performance reports are saved once you select a project."
            )
            return
        reports = self._services.performance.history(project.id, limit=10)
        if not reports:
            self._perf_history.setPlainText("No performance reports saved for this project yet.")
            return
        lines = []
        for r in reports:
            s = r.parsed_summary
            hw = f" · {r.target_hardware}" if r.target_hardware else ""
            lines.append(
                f"[{r.created_at}]{hw} · avg {s.get('avg_fps')} fps · {len(r.spikes)} spike(s)\n"
                f"    {r.ai_summary or ''}"
            )
        self._perf_history.setPlainText("\n".join(lines))

    def _refresh_access_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._access_history.setPlainText(
                "Accessibility passes are saved once you select a project."
            )
            return
        reports = self._services.accessibility.history(project.id, limit=10)
        if not reports:
            self._access_history.setPlainText("No accessibility passes saved for this project yet.")
            return
        lines = []
        for r in reports:
            score = f"{r.score}/100" if r.score is not None else "n/a"
            lines.append(f"[{r.created_at}] score {score}\n    {r.ai_summary or ''}")
        self._access_history.setPlainText("\n".join(lines))

    def _refresh_unity_run_status(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._unity_run_status.setText("Select a project to run its Unity tests.")
            self._unity_run_btn.setEnabled(False)
            return
        if not project.unity_test_run_enabled:
            self._unity_run_status.setText(
                "Not enabled for this project. Turn on \"Allow Spiced to run this project's "
                "Unity tests\" on the Projects screen."
            )
            self._unity_run_btn.setEnabled(False)
            return
        if not project.path:
            self._unity_run_status.setText("Connect a Unity folder for this project first.")
            self._unity_run_btn.setEnabled(False)
            return
        required_version = project.engine_metadata.get("unity_version")
        editor = resolve_unity_editor(required_version, project.unity_editor_path_override)
        if editor is None:
            self._unity_run_status.setText(
                f"Unity {required_version or '(unknown version)'} isn't available. Install it "
                "via Unity Hub, or set a manual Editor path on the Projects screen."
            )
            self._unity_run_btn.setEnabled(False)
            return
        self._unity_run_status.setText(f"Will run Unity {editor.version} at {editor.path}")
        self._unity_run_btn.setEnabled(True)

    # --- Functional handlers -------------------------------------------------

    def _on_add_case(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.information(self, "Title needed", "Please enter a test case title.")
            return
        self._services.testing.create_case(
            project_id=project.id,
            title=title,
            category=self._category_input.currentText(),
            priority=self._priority_input.currentText(),
            steps=self._steps_input.toPlainText().strip() or None,
            expected_result=self._expected_input.toPlainText().strip() or None,
        )
        self._selected_case_id = None
        self._combined_list.setCurrentItem(None)
        self._title_input.clear()
        self._steps_input.clear()
        self._expected_input.clear()
        self._refresh_cases()
        self._update_edit_buttons()

    def _on_combined_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        """Routes a selection in the merged Test Cases & Known Issues list
        to whichever kind of row it actually is -- clearing the other
        kind's selection, same as when each had its own separate list."""
        kind = current.data(_ITEM_KIND_ROLE) if current is not None else None
        self._on_case_selected(current if kind == "case" else None)
        self._on_issue_selected(current if kind == "issue" else None)

    def _on_case_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            self._selected_case_id = None
            self._update_edit_buttons()
            return
        case_id = current.data(_USER_ROLE)
        if case_id is None:
            return
        case = self._services.testing.get_case(int(case_id))
        self._selected_case_id = case.id
        self._title_input.setText(case.title)
        self._category_input.setCurrentText(case.category)
        self._priority_input.setCurrentText(case.priority)
        self._steps_input.setPlainText(case.steps or "")
        self._expected_input.setPlainText(case.expected_result or "")
        self._status_input.setCurrentText(case.status)
        self._failure_note_input.setText(case.failure_note or "")
        self._on_status_choice_changed(case.status)
        self._update_edit_buttons()

    def _on_clear_selection(self) -> None:
        self._selected_case_id = None
        self._combined_list.setCurrentItem(None)
        self._title_input.clear()
        self._category_input.setCurrentText("General")
        self._priority_input.setCurrentText("Medium")
        self._steps_input.clear()
        self._expected_input.clear()
        self._status_input.setCurrentText("Not Run")
        self._failure_note_input.clear()
        self._on_status_choice_changed("Not Run")
        self._update_edit_buttons()

    def _on_save_case(self) -> None:
        if self._selected_case_id is None:
            return
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.information(self, "Title needed", "Please enter a test case title.")
            return
        status = self._status_input.currentText()
        self._services.testing.update_case(
            self._selected_case_id,
            title=title,
            category=self._category_input.currentText(),
            priority=self._priority_input.currentText(),
            steps=self._steps_input.toPlainText().strip() or None,
            expected_result=self._expected_input.toPlainText().strip() or None,
            status=status,
            failure_note=self._failure_note_input.text().strip() or None,
        )
        self._refresh_cases()
        self._update_edit_buttons()

    def _on_delete_case(self) -> None:
        if self._selected_case_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete test case?",
            "Delete this test case? Saved test-run history is not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._services.testing.delete_case(self._selected_case_id)
        self._on_clear_selection()
        self._refresh_cases()

    def _on_status_choice_changed(self, status: str) -> None:
        self._failure_note_input.setEnabled(status == "Fail")

    def _on_update_status(self) -> None:
        item = self._combined_list.currentItem()
        if item is None or item.data(_ITEM_KIND_ROLE) != "case":
            QMessageBox.information(self, "Select a test case", "Pick a test case from the list.")
            return
        case_id = int(item.data(_USER_ROLE))
        status = self._status_input.currentText()
        note = self._failure_note_input.text().strip() or None
        self._services.testing.set_status(case_id, status, note)
        self._refresh_cases()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import test results",
            "",
            "Result files (*.txt *.log *.json *.xml);;All files (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not read file", f"Sorry, I couldn't open that file:\n{exc}"
            )
            return
        self._results_input.setPlainText(text)
        self._pending_filename = Path(path).name

    def _on_analyze(self) -> None:
        results_text = self._results_input.toPlainText().strip()
        if not results_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste test output or import a file first."
            )
            return
        source_type = SOURCE_FILE if self._pending_filename else SOURCE_PASTE
        filename = self._pending_filename
        self._set_busy(True)
        self._result.setPlainText("Reading the results and thinking it through…")

        worker = _FunctionalWorker(self._services, results_text, source_type, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_done(self, review: TestReview) -> None:
        text = review.response_text
        matches = [o for o in review.regression_outcomes if o.match is not None]
        if matches:
            lines = ["", "Known-issue matches:"]
            lines.extend(f"- {o.match.note}" for o in matches)
            text = text + "\n" + "\n".join(lines)
        self._result.setPlainText(text)
        if matches:
            description = " ".join(o.match.note for o in matches)
        else:
            description = "From the pasted/imported test results below."
        self._source_link.set_source(description, review.parsed.excerpt)
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()
        self._refresh_known_issues()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._source_link.set_source(None, None)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")

    # --- Run Unity tests handlers --------------------------------------------

    def _on_run_unity_tests(self) -> None:
        project = self._services.active_project()
        if project is None or not project.unity_test_run_enabled or not project.path:
            return
        required_version = project.engine_metadata.get("unity_version")
        editor = resolve_unity_editor(required_version, project.unity_editor_path_override)
        if editor is None:
            QMessageBox.information(
                self,
                "Unity Editor not found",
                "Spiced couldn't resolve a Unity Editor to run — see the status above.",
            )
            return

        platform_choice = next(
            (p for p, btn in self._unity_platform_buttons.items() if btn.isChecked()), EDIT_MODE
        )
        if platform_choice == _BOTH_PLATFORMS:
            platforms = [EDIT_MODE, PLAY_MODE]
        else:
            platforms = [platform_choice]

        self._unity_run_btn.setEnabled(False)
        for btn in self._unity_platform_buttons.values():
            btn.setEnabled(False)
        self._unity_run_result.setPlainText(
            "Launching Unity — this can take a while, especially on a first run…"
        )
        self._unity_progress_trail.reset()

        worker = _UnityRunWorker(self._services, project, editor.path, platforms)
        thread = launch_worker(self, worker, progress_slot=self._unity_progress_trail.add_step)
        thread.started.connect(worker.run)
        worker.platform_started.connect(self._on_unity_platform_started)
        worker.platform_done.connect(self._on_unity_platform_done)
        worker.platform_failed.connect(self._on_unity_platform_failed)
        worker.finished.connect(self._on_unity_run_finished)
        worker.finished.connect(thread.quit)
        thread.start()

    def _on_unity_platform_started(self, platform: str) -> None:
        self._unity_run_result.append(f"\n--- Running {platform} tests… ---")

    def _on_unity_platform_done(self, platform: str, review: TestReview) -> None:
        text = f"[{platform}] {review.response_text}"
        matches = [o for o in review.regression_outcomes if o.match is not None]
        if matches:
            lines = ["", "Known-issue matches:"]
            lines.extend(f"- {o.match.note}" for o in matches)
            text = text + "\n" + "\n".join(lines)
        # Transparent AI Reasoning (Phase C): this panel is an appended
        # timeline of multiple platform runs rather than one result card, so
        # the "why" is shown inline instead of via a separate SourceLinkExpander.
        if review.parsed.excerpt:
            text += (
                f"\n(Why: from the {platform} run's results excerpt below.)\n"
                f"{review.parsed.excerpt}"
            )
        self._unity_run_result.append(text)
        self.usage_changed.emit()
        self._refresh_history()
        self._refresh_known_issues()

    def _on_unity_platform_failed(self, platform: str, message: str) -> None:
        self._unity_run_result.append(f"[{platform}] {message}")

    def _on_unity_run_finished(self) -> None:
        self._unity_run_btn.setEnabled(True)
        for btn in self._unity_platform_buttons.values():
            btn.setEnabled(True)

    # --- Known Issues handlers ----------------------------------------------

    def _on_issue_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        self._selected_issue_id = int(current.data(_USER_ROLE)) if current is not None else None
        self._update_edit_buttons()
        project = self._services.active_project()
        project_uuid = project.project_uuid if project else None
        if self._selected_issue_id is None:
            self._issue_comments.set_subject(None, "known_issue", "")
        else:
            self._issue_comments.set_subject(
                project_uuid, "known_issue", str(self._selected_issue_id)
            )

    def _selected_known_issue(self):
        return next(
            (i for i in self._known_issues_cache if i.id == self._selected_issue_id), None
        )

    def _on_send_issue_to_team_board(self) -> None:
        project = self._services.active_project()
        issue = self._selected_known_issue()
        if project is None or not project.project_uuid or issue is None:
            return
        self._issue_send_btn.setEnabled(False)
        self._issue_send_status.setText("Sending…")

        worker = _SendKnownIssueToTeamBoardWorker(self._services, project.project_uuid, issue)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_issue_sent)
        worker.failed.connect(self._on_issue_send_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_issue_sent(self, task) -> None:
        self._issue_send_btn.setEnabled(True)
        self._issue_send_status.setText(
            "Sent to the Team board." if task is not None
            else "This project isn't linked to a team."
        )

    def _on_issue_send_failed(self, message: str) -> None:
        self._issue_send_btn.setEnabled(True)
        self._issue_send_status.setText(message)

    def _on_mark_resolved(self) -> None:
        if self._selected_issue_id is None:
            return
        self._services.testing.mark_issue_resolved(self._selected_issue_id)
        self._refresh_known_issues()

    def _on_mark_open(self) -> None:
        if self._selected_issue_id is None:
            return
        self._services.testing.mark_issue_open(self._selected_issue_id)
        self._refresh_known_issues()

    def _refresh_player_crash_status(self) -> None:
        project = self._services.active_project()
        eligible = bool(
            project
            and project.project_uuid
            and self._services.team_mode_enabled()
            and self._services.auth.is_logged_in()
        )
        self._player_crash_sync_btn.setEnabled(eligible)
        if project is None:
            self._player_crash_status.setText(
                "Player crash reports need a team-linked project — select one first."
            )
        elif not eligible:
            self._player_crash_status.setText(
                "Only available for a project linked to a Small-Team Mode team (see "
                "docs/player_crash_reporting.md) — solo/local-only projects have no reachable "
                "project_uuid for players to report against."
            )
        else:
            self._player_crash_status.setText(
                "Pulls crash reports real players sent in for this team-linked project and "
                "merges them into the list above, tagged \"from players\"."
            )

    def _on_sync_player_crashes(self) -> None:
        project = self._services.active_project()
        if project is None or not project.project_uuid:
            return
        self._player_crash_sync_btn.setEnabled(False)
        self._player_crash_sync_btn.setText("Syncing…")

        worker = _PlayerCrashSyncWorker(self._services, project.id, project.project_uuid)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_player_crash_sync_done)
        worker.failed.connect(self._on_player_crash_sync_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_player_crash_sync_done(self, result: PlayerCrashSyncResult) -> None:
        self._player_crash_sync_btn.setText("Sync player crash reports")
        self._player_crash_sync_btn.setEnabled(True)
        new_count = len(result.new_outcomes)
        self._player_crash_status.setText(
            f"Synced {result.fetched_count} report(s) from players — {new_count} new."
        )
        self._refresh_known_issues()

    def _on_player_crash_sync_failed(self, message: str) -> None:
        self._player_crash_sync_btn.setText("Sync player crash reports")
        self._player_crash_sync_btn.setEnabled(True)
        self._player_crash_status.setText(message)

    # --- Performance handlers ------------------------------------------------

    def _on_perf_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import performance data", "", "Data files (*.txt *.csv *.json);;All files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not read file", f"Sorry, I couldn't open that file:\n{exc}"
            )
            return
        self._perf_input.setPlainText(text)
        self._perf_pending_filename = Path(path).name

    def _on_perf_analyze(self) -> None:
        text = self._perf_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste or import performance data first."
            )
            return
        hardware = self._hardware_input.currentText()
        target_hardware = None if hardware == _NO_HARDWARE else hardware
        source_type = SOURCE_FILE if self._perf_pending_filename else SOURCE_PASTE
        filename = self._perf_pending_filename
        self._perf_analyze_btn.setEnabled(False)
        self._perf_analyze_btn.setText("Analyzing…")
        self._perf_result.setPlainText("Reading the numbers and thinking it through…")

        worker = _PerformanceWorker(
            self._services, text, source_type, filename, target_hardware
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_perf_done)
        worker.failed.connect(self._on_perf_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_perf_done(self, review: PerformanceReview) -> None:
        self._perf_result.setPlainText(review.response_text)
        description = "From the pasted/imported performance data below."
        if review.simulation is not None:
            description += f" Includes a {review.simulation.tier} hardware simulation estimate."
        self._perf_source_link.set_source(description, review.parsed.excerpt)
        self._render_perf_chart(review.parsed)
        self._perf_pending_filename = None
        self._perf_analyze_btn.setEnabled(True)
        self._perf_analyze_btn.setText("Analyze")
        self.usage_changed.emit()
        self._refresh_perf_history()

    def _render_perf_chart(self, parsed) -> None:
        fps_spike_locations = {s.location for s in parsed.spikes if s.metric == "fps"}
        bars = [
            (sample.location, sample.fps, sample.location in fps_spike_locations)
            for sample in parsed.samples
            if sample.fps is not None
        ]
        self._perf_chart.set_data(bars)
        if not bars:
            self._perf_chart_caption.setText("No fps values found in the pasted/imported data.")
        elif fps_spike_locations:
            worst = min(
                (s for s in parsed.spikes if s.metric == "fps"), key=lambda s: s.value
            )
            self._perf_chart_caption.setText(worst.message)
        else:
            self._perf_chart_caption.setText("No frame-rate dips flagged across these locations.")

    def _on_perf_failed(self, message: str) -> None:
        self._perf_result.setPlainText(message)
        self._perf_source_link.set_source(None, None)
        self._perf_analyze_btn.setEnabled(True)
        self._perf_analyze_btn.setText("Analyze")

    # --- Accessibility handlers ------------------------------------------------

    def _on_access_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import accessibility checklist", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not read file", f"Sorry, I couldn't open that file:\n{exc}"
            )
            return
        self._access_input.setPlainText(text)
        self._access_pending_filename = Path(path).name

    def _on_access_analyze(self) -> None:
        text = self._access_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste or import checklist JSON first."
            )
            return
        source_type = SOURCE_FILE if self._access_pending_filename else SOURCE_PASTE
        filename = self._access_pending_filename
        self._access_analyze_btn.setEnabled(False)
        self._access_analyze_btn.setText("Analyzing…")
        self._access_result.setPlainText("Running the checklist and thinking it through…")

        worker = _AccessibilityWorker(self._services, text, source_type, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_access_done)
        worker.failed.connect(self._on_access_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_access_done(self, review: AccessibilityReview) -> None:
        self._access_result.setPlainText(review.response_text)
        self._render_access_checklist(review.parsed)
        self._access_source_link.set_source(
            "From the pasted/imported accessibility checklist below (real WCAG contrast "
            "math and a colorblind-simulation check ran locally on this data).",
            review.parsed.excerpt,
        )
        self._access_pending_filename = None
        self._access_analyze_btn.setEnabled(True)
        self._access_analyze_btn.setText("Analyze")
        self.usage_changed.emit()
        self._refresh_access_history()

    def _render_access_checklist(self, parsed) -> None:
        """The Accessibility checklist card: label left, bold colored status
        right, straight from the already-computed ParsedAccessibility --
        deterministic and local, no extra AI call."""
        _clear_layout(self._access_checklist_layout)
        heading = QLabel("Accessibility Checklist")
        heading.setObjectName("CardTitle")
        self._access_checklist_layout.addWidget(heading)

        rows_added = False
        if parsed.contrast_checks:
            passing = sum(1 for c in parsed.contrast_checks if c.passes)
            total = len(parsed.contrast_checks)
            state = "pass" if passing == total else ("fail" if passing == 0 else "warn")
            self._access_checklist_layout.addWidget(
                _checklist_row("Contrast (WCAG)", f"{passing}/{total} pass", state)
            )
            rows_added = True
        if parsed.caption_total:
            pct = parsed.caption_coverage_pct or 0.0
            state = "pass" if pct >= 100 else ("fail" if pct < 50 else "warn")
            status = f"{parsed.caption_covered}/{parsed.caption_total} ({pct:.0f}%)"
            self._access_checklist_layout.addWidget(
                _checklist_row("Caption coverage", status, state)
            )
            rows_added = True
        if parsed.controls_remappable is not None:
            state = "pass" if parsed.controls_remappable else "warn"
            status = "Yes" if parsed.controls_remappable else "No"
            self._access_checklist_layout.addWidget(
                _checklist_row("Remappable controls", status, state)
            )
            rows_added = True
        if parsed.text_scaling_supported is not None:
            state = "pass" if parsed.text_scaling_supported else "warn"
            status = "Yes" if parsed.text_scaling_supported else "No"
            self._access_checklist_layout.addWidget(
                _checklist_row("Text scaling", status, state)
            )
            rows_added = True
        if not rows_added:
            empty = QLabel("No checklist data recognized in the pasted/imported JSON.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self._access_checklist_layout.addWidget(empty)

    def _on_access_failed(self, message: str) -> None:
        self._access_result.setPlainText(message)
        self._access_source_link.set_source(None, None)
        self._access_analyze_btn.setEnabled(True)
        self._access_analyze_btn.setText("Analyze")

    # --- Build Pipeline handlers ---------------------------------------------

    def _refresh_build_pipeline_status(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._build_status.setText("Select a project to use the Build Pipeline.")
            self._build_run_btn.setEnabled(False)
            return
        if not project.build_pipeline_enabled:
            self._build_status.setText(
                "Not enabled for this project. Turn on the Build Pipeline opt-in on the "
                "Projects screen."
            )
            self._build_run_btn.setEnabled(False)
            return
        if not project.path:
            self._build_status.setText("Connect a Unity folder for this project first.")
            self._build_run_btn.setEnabled(False)
            return
        self._build_status.setText(f"Ready. Builds are written under {project.path}\\Builds\\.")
        self._build_run_btn.setEnabled(True)
        if project.build_target_platform:
            idx = self._build_platform_input.findText(project.build_target_platform)
            if idx >= 0:
                self._build_platform_input.setCurrentIndex(idx)

    def _refresh_build_history(self) -> None:
        self._build_history.clear()
        project = self._services.active_project()
        reports = (
            self._services.build_reports.list_for_project(project.id, limit=10)
            if project
            else []
        )
        for r in reports:
            status = "succeeded" if r.succeeded else ("failed" if r.succeeded is False else "…")
            stable = " · stable" if r.marked_stable else ""
            label = f"[{r.created_at}] {r.trigger} · {r.target_platform or '?'} · {status}{stable}"
            item = QListWidgetItem(label)
            item.setData(_USER_ROLE, r.id)
            self._build_history.addItem(item)
        stable = (
            self._services.build_reports.latest_stable_for_project(project.id)
            if project
            else None
        )
        if stable:
            self._stable_status.setText(
                f"Stable build: [{stable.created_at}] {stable.output_path or '(no output path)'}"
            )
        else:
            self._stable_status.setText(
                "No build marked stable yet — used as the changelog's default starting point."
            )

    def _on_run_build(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        platform = self._build_platform_input.currentText()
        self._build_run_btn.setEnabled(False)
        self._build_result.setPlainText(
            "Launching Unity to build — this can take a while, especially on a first build…"
        )
        self._build_progress_trail.reset()

        worker = _BuildWorker(self._services, project, platform)
        thread = launch_worker(self, worker, progress_slot=self._build_progress_trail.add_step)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_build_done)
        worker.failed.connect(self._on_build_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_build_done(self, report: BuildReport) -> None:
        self._build_run_btn.setEnabled(True)
        if report.succeeded:
            self._build_result.setPlainText(
                f"Build succeeded.\nOutput: {report.output_path or '(unknown path)'}"
            )
        else:
            self._build_result.setPlainText(
                f"Build failed.\n\n{report.log_tail or '(no log captured)'}"
            )
        self._refresh_build_history()

    def _on_build_failed(self, message: str) -> None:
        self._build_run_btn.setEnabled(True)
        self._build_result.setPlainText(message)

    def _on_mark_stable(self) -> None:
        project = self._services.active_project()
        if project is None:
            return
        latest = self._services.build_reports.latest_for_project(project.id)
        if latest is None or not latest.succeeded:
            QMessageBox.information(
                self,
                "No successful build yet",
                "Run a successful build first, then mark it stable.",
            )
            return
        self._services.build_reports.mark_stable(latest.id)
        self._refresh_build_history()

    # --- Store Page / Build Checklist handlers --------------------------------

    def _current_checklist(self) -> ReleaseChecklist:
        platform = self._checklist_platform_input.currentData()
        build_size = None
        project = self._services.active_project()
        if project is not None:
            latest = self._services.build_reports.latest_for_project(project.id)
            if latest is not None:
                build_size = _path_size_bytes(latest.output_path)
        return build_checklist(platform, build_size_bytes=build_size)

    def _on_show_checklist(self) -> None:
        checklist = self._current_checklist()
        self._last_checklist = checklist
        lines = [f"{checklist.platform_label} checklist:", ""]
        for item in checklist.items:
            line = f"- {item.text}"
            if item.note:
                line += f"\n    ({item.note})"
            lines.append(line)
        lines.append("")
        lines.append(checklist.verify_note)
        self._checklist_result.setPlainText("\n".join(lines))

    def _on_checklist_ai(self) -> None:
        checklist = self._last_checklist or self._current_checklist()
        self._last_checklist = checklist
        self._checklist_ai_btn.setEnabled(False)
        self._checklist_ai_btn.setText("Thinking…")

        worker = _ChecklistAIWorker(self._services, checklist)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_checklist_ai_done)
        worker.failed.connect(self._on_checklist_ai_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_checklist_ai_done(self, text: str) -> None:
        self._checklist_ai_btn.setEnabled(True)
        self._checklist_ai_btn.setText("Get AI take")
        current = self._checklist_result.toPlainText()
        self._checklist_result.setPlainText(f"{current}\n\n--- AI take ---\n{text}")
        self.usage_changed.emit()

    def _on_checklist_ai_failed(self, message: str) -> None:
        self._checklist_ai_btn.setEnabled(True)
        self._checklist_ai_btn.setText("Get AI take")
        current = self._checklist_result.toPlainText()
        self._checklist_result.setPlainText(f"{current}\n\n{message}")

    # --- Economy Simulation handlers ----------------------------------------

    def _current_economy_data(self) -> dict | None:
        text = self._economy_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to simulate", "Paste economy JSON above first."
            )
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "Invalid JSON", str(exc))
            return None
        return data

    def _on_economy_simulate(self) -> None:
        data = self._current_economy_data()
        if data is None:
            return
        try:
            findings = self._services.economy_simulator.simulate(data)
        except InvalidEconomyDataError as exc:
            self._economy_result.setPlainText(f"That doesn't match the expected format: {exc}")
            return
        self._economy_result.setPlainText(_format_economy_findings(findings))
        self._render_dominant_strategies(findings)

    def _render_dominant_strategies(self, findings: EconomySimulationFindings) -> None:
        _clear_layout(self._economy_dominant_layout)
        heading = QLabel("Dominant Strategies")
        heading.setObjectName("CardTitle")
        self._economy_dominant_layout.addWidget(heading)
        if not findings.dominant_strategies:
            empty = QLabel("None found — no item dominated the simulated playthroughs.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self._economy_dominant_layout.addWidget(empty)
            return
        for d in findings.dominant_strategies:
            pct = d.pick_rate * 100
            self._economy_dominant_layout.addWidget(
                _progress_row(
                    d.item_name, pct, f"{pct:.0f}% of playthroughs · unlocks lvl {d.from_level}"
                )
            )

    def _on_economy_ai(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        data = self._current_economy_data()
        if data is None:
            return
        self._economy_ai_btn.setEnabled(False)
        self._economy_ai_btn.setText("Thinking…")
        self._economy_result.setPlainText("Simulating and thinking it through…")

        worker = _EconomySimulationAIWorker(self._services, project, data)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_economy_ai_done)
        worker.failed.connect(self._on_economy_ai_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_economy_ai_done(self, review: EconomySimulationReview) -> None:
        self._economy_ai_btn.setEnabled(True)
        self._economy_ai_btn.setText("Get AI summary")
        text = _format_economy_findings(review.findings)
        if review.response_text:
            text += f"\n\n--- AI summary ---\n{review.response_text}"
        self._economy_result.setPlainText(text)
        self.usage_changed.emit()
        self._refresh_economy_history()

    def _on_economy_ai_failed(self, message: str) -> None:
        self._economy_ai_btn.setEnabled(True)
        self._economy_ai_btn.setText("Get AI summary")
        self._economy_result.setPlainText(message)

    def _refresh_economy_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._economy_history.setPlainText(
                "AI-summarized simulations are saved once you select an active project."
            )
            return
        reports = self._services.economy_simulator.history(project.id, limit=5)
        if not reports:
            self._economy_history.setPlainText(
                "No AI-summarized simulations saved yet (a local-only simulation isn't saved)."
            )
            return
        lines = []
        for r in reports:
            f = r.findings
            dominant_count = len(f.get("dominant_strategies", []))
            lines.append(f"[{r.created_at}] {dominant_count} dominant strategy finding(s)")
        self._economy_history.setPlainText("\n".join(lines))
