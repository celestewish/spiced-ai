"""Debugging Buddy: crash analysis, outdated-API checks, and code health.

Parsing/scanning happens locally and instantly; every provider call runs on a
worker thread so the window stays responsive. Only a trimmed excerpt is ever
sent — never a full log/script or any project files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.asset_scan import AssetScanFindings, AssetScanReview
from spiced.core.asset_scan import NoUnityFolderError as AssetScanNoUnityFolderError
from spiced.core.asset_scan import ProviderNotReadyError as AssetScanNotReadyError
from spiced.core.changelog_draft import ChangelogResult
from spiced.core.changelog_draft import NotAGitRepoError as ChangelogNotAGitRepoError
from spiced.core.changelog_draft import ProviderNotReadyError as ChangelogNotReadyError
from spiced.core.code_health import MAX_EXCERPT_CHARS as CODE_HEALTH_MAX_EXCERPT_CHARS
from spiced.core.code_health import CodeHealthReview
from spiced.core.code_health import NoUnityFolderError as CodeHealthNoUnityFolderError
from spiced.core.code_health import ProviderNotReadyError as CodeHealthNotReadyError
from spiced.core.debugging import (
    SOURCE_FILE,
    SOURCE_PASTE,
    DebugAnalysis,
    ProviderNotReadyError,
)
from spiced.core.dependency_check import DependencyCheckFindings, DependencyCheckReview
from spiced.core.dependency_check import NoManifestError as DependencyNoManifestError
from spiced.core.dependency_check import NoUnityFolderError as DependencyNoUnityFolderError
from spiced.core.dependency_check import ProviderNotReadyError as DependencyNotReadyError
from spiced.core.design_doc_sync import (
    DesignDocSyncNotEnabledError,
    DesignDocSyncResult,
    NoDesignDocError,
    UnsupportedDesignDocFormatError,
    import_design_doc_text,
)
from spiced.core.design_doc_sync import ProviderNotReadyError as DesignDocSyncNotReadyError
from spiced.core.dev_docs import DevDocsResult
from spiced.core.dev_docs import NoUnityFolderError as DevDocsNoUnityFolderError
from spiced.core.dev_docs import ProviderNotReadyError as DevDocsNotReadyError
from spiced.core.draft_translation import DRAFT_NOT_SHIP_READY_NOTICE, DraftTranslationResult
from spiced.core.draft_translation import NoDialogueError as DraftTranslationNoDialogueError
from spiced.core.draft_translation import (
    ProviderNotReadyError as DraftTranslationNotReadyError,
)
from spiced.core.localization_readiness import HEURISTIC_CAVEAT, LocalizationReadinessScan
from spiced.core.localization_readiness import (
    NoUnityFolderError as LocalizationNoUnityFolderError,
)
from spiced.core.scope_creep import detect_scope_creep
from spiced.core.version_check import ProviderNotReadyError as VersionCheckNotReadyError
from spiced.core.version_check import VersionCheckReview
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.diff_viewer import DiffViewerDialog
from spiced.ui.widgets.progress_trail import ProgressTrail
from spiced.ui.widgets.source_link import SourceLinkExpander


def _format_asset_findings(findings: AssetScanFindings) -> str:
    lines = ["Oversized or uncompressed-format files:"]
    if findings.oversized:
        for f in findings.oversized[:20]:
            mb = f.size_bytes / (1024 * 1024)
            lines.append(f"- [{f.kind}] {f.path} ({mb:.1f} MB): {f.reason}")
        if len(findings.oversized) > 20:
            lines.append(f"...and {len(findings.oversized) - 20} more (showing the largest 20).")
    else:
        lines.append("None found.")
    lines.append("")
    lines.append("Possibly orphaned assets:")
    if findings.orphaned_assets:
        lines.extend(f"- {p}" for p in findings.orphaned_assets)
    else:
        lines.append("None found.")
    lines.append("")
    lines.append(findings.orphan_caveat)
    return "\n".join(lines)


class _CrashWorker(QObject):
    done = Signal(object)  # DebugAnalysis
    failed = Signal(str)

    def __init__(
        self, services: Services, log_text: str, source_type: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._log_text = log_text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            project = self._services.active_project()
            team_mode = self._services.team_mode_enabled()
            analysis = self._services.debugging.analyze(
                provider,
                self._log_text,
                project=project,
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
                team_mode=team_mode,
                team_members=self._services.team_prompt_context(project) if team_mode else None,
            )
            # Opt-In Only Telemetry (Phase C): a bare, anonymous event name —
            # no log content, file paths, or project data. No-op unless the
            # developer has explicitly turned this on in Settings.
            self._services.record_telemetry_event("debugging.crash_diagnosis_run")
            self.done.emit(analysis)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class _VersionCheckWorker(QObject):
    done = Signal(object)  # VersionCheckReview
    failed = Signal(str)

    def __init__(self, services: Services, code_text: str, filename: str | None) -> None:
        super().__init__()
        self._services = services
        self._code_text = code_text
        self._filename = filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.version_check.analyze(
                provider,
                self._code_text,
                project=self._services.active_project(),
                source_filename=self._filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except VersionCheckNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during the review: {exc}")


class _CodeHealthWorker(QObject):
    done = Signal(object)  # CodeHealthReview
    failed = Signal(str)

    def __init__(self, services: Services, code_text: str, filename: str | None) -> None:
        super().__init__()
        self._services = services
        self._code_text = code_text
        self._filename = filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.code_health.analyze(
                provider,
                self._code_text,
                project=self._services.active_project(),
                source_filename=self._filename,
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("debugging.code_health_check_run")
            self.done.emit(review)
        except CodeHealthNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during the review: {exc}")


class _ProjectHealthScanWorker(QObject):
    """Naming Consistency + Dead Reference Detection, folded into Code Health.

    Emits ``progress`` (Live Task Progress Transparency, Phase L) between
    its two real, independently-timed scan passes over the project's .cs
    scripts.
    """

    done = Signal(object, object)  # NamingConventionResult, ReferenceScanResult
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            self.progress.emit("Scanning naming conventions… (1 of 2)")
            naming = self._services.code_health.scan_naming_convention(self._project)
            self.progress.emit("Scanning for dead references… (2 of 2)")
            refs = self._services.code_health.scan_dead_references(self._project)
            self.progress.emit("Project health scan complete.")
            self.done.emit(naming, refs)
        except CodeHealthNoUnityFolderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


class _ChangelogWorker(QObject):
    done = Signal(object)  # ChangelogResult
    failed = Signal(str)

    def __init__(self, services: Services, project, since_date: str | None) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._since_date = since_date

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.changelog.draft(
                provider,
                self._project,
                since_date=self._since_date,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(result)
        except (ChangelogNotReadyError, ChangelogNotAGitRepoError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while drafting the changelog: {exc}")


class _DiscordPostWorker(QObject):
    """Discord/Community Bot Integration: posting (Phase G, section 7).

    Runs on a worker thread since it's a network call. The caller is
    responsible for having already shown the developer the exact text and
    gotten an explicit confirmation before launching this — see
    ``_on_post_changelog_to_discord`` below.
    """

    done = Signal()
    failed = Signal(str)

    def __init__(self, services: Services, text: str) -> None:
        super().__init__()
        self._services = services
        self._text = text

    def run(self) -> None:
        try:
            poster = self._services.build_discord_poster()
            poster.post_message(self._text)
            self._services.record_telemetry_event("debugging.changelog_posted_to_discord")
            self.done.emit()
        except (RuntimeError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while posting to Discord: {exc}")


class _AssetScanWorker(QObject):
    done = Signal(object)  # AssetScanFindings
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            findings = self._services.asset_scan.scan(self._project)
            self.done.emit(findings)
        except AssetScanNoUnityFolderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


class _AssetScanAIWorker(QObject):
    done = Signal(object)  # AssetScanReview
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.asset_scan.analyze(
                provider, self._project, record_usage=self._services.usage.record_prompt
            )
            self.done.emit(review)
        except (AssetScanNotReadyError, AssetScanNoUnityFolderError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong: {exc}")


def _format_dependency_findings(findings: DependencyCheckFindings) -> str:
    if not findings.results:
        return "No dependencies declared in Packages/manifest.json."
    lines = []
    for r in findings.results:
        if not r.checked:
            lines.append(f"[not checked] {r.name} ({r.installed_version}): {r.note or ''}")
        elif r.outdated:
            lines.append(f"[outdated] {r.name}: {r.installed_version} -> {r.latest_version}")
        elif r.outdated is False:
            lines.append(f"[up to date] {r.name}: {r.installed_version}")
        else:
            lines.append(
                f"[unclear] {r.name}: {r.installed_version} vs {r.latest_version} "
                "(not directly comparable)"
            )
    lines.append("")
    lines.append(
        f"{findings.outdated_count} outdated, {findings.unchecked_count} couldn't be checked, "
        f"{len(findings.results)} total."
    )
    return "\n".join(lines)


class _DependencyCheckWorker(QObject):
    done = Signal(object)  # DependencyCheckFindings
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            findings = self._services.dependency_check.check(self._project)
            self.done.emit(findings)
        except (DependencyNoUnityFolderError, DependencyNoManifestError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while checking dependencies: {exc}")


class _DependencyCheckAIWorker(QObject):
    done = Signal(object)  # DependencyCheckReview
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.dependency_check.analyze(
                provider, self._project, record_usage=self._services.usage.record_prompt
            )
            self.done.emit(review)
        except (
            DependencyNotReadyError,
            DependencyNoUnityFolderError,
            DependencyNoManifestError,
        ) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong: {exc}")


class _DevDocsWorker(QObject):
    done = Signal(object)  # DevDocsResult
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.dev_docs.generate(
                provider, self._project, record_usage=self._services.usage.record_prompt
            )
            self.done.emit(result)
        except (DevDocsNotReadyError, DevDocsNoUnityFolderError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while generating docs: {exc}")


class _DesignDocSyncWorker(QObject):
    done = Signal(object)  # DesignDocSyncResult
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.design_doc_sync.compare(
                provider, self._project, record_usage=self._services.usage.record_prompt
            )
            self.done.emit(result)
        except (
            DesignDocSyncNotReadyError,
            DesignDocSyncNotEnabledError,
            NoDesignDocError,
            DevDocsNoUnityFolderError,
        ) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while checking design drift: {exc}")


class _LocalizationScanWorker(QObject):
    done = Signal(object)  # LocalizationReadinessScan
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            scan, _report = self._services.localization_readiness.scan(self._project)
            self.done.emit(scan)
        except LocalizationNoUnityFolderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


class _DraftTranslationWorker(QObject):
    done = Signal(object)  # DraftTranslationResult
    failed = Signal(str)

    def __init__(
        self, services: Services, text: str, target_language: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._text = text
        self._target_language = target_language
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.draft_translation.translate(
                provider,
                self._text,
                self._target_language,
                project=self._services.active_project(),
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("debugging.draft_translation_run")
            self.done.emit(result)
        except (DraftTranslationNotReadyError, DraftTranslationNoDialogueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while translating: {exc}")


class DebuggingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._pending_filename: str | None = None
        self._version_pending_filename: str | None = None
        self._health_pending_filename: str | None = None
        self._current_changelog_draft_id: int | None = None
        self._translation_pending_filename: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Debugging Buddy")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_crash_analysis(layout)
        self._build_version_check(layout)
        self._build_code_health(layout)
        self._build_changelog(layout)
        self._build_asset_health(layout)
        self._build_dependency_check(layout)
        self._build_dev_docs(layout)
        self._build_design_drift(layout)
        self._build_localization(layout)

        self.refresh()

    # --- Explain This Crash -------------------------------------------------

    def _build_crash_analysis(self, layout: QVBoxLayout) -> None:
        intro = QLabel(
            "Paste a Unity error log or import a .log/.txt file. I'll read it locally, point "
            "at the likely cause, and suggest safe next steps — you stay in control."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._log_input = QPlainTextEdit()
        self._log_input.setPlaceholderText(
            "Paste your Unity console output or Editor.log excerpt here…"
        )
        self._log_input.setFixedHeight(140)
        layout.addWidget(self._log_input)

        row = QHBoxLayout()
        self._import_btn = QPushButton("Import log file…")
        self._import_btn.clicked.connect(self._import_file)
        row.addWidget(self._import_btn)
        row.addStretch(1)
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self._analyze_btn)
        layout.addLayout(row)

        result_title = QLabel("Analysis")
        result_title.setObjectName("SectionTitle")
        layout.addWidget(result_title)

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText("Your structured debugging guidance will appear here.")
        self._result.setFixedHeight(220)
        layout.addWidget(self._result)

        # Transparent AI Reasoning (Phase C): "why am I seeing this?" for the
        # crash diagnosis — the matched known issue's note, or the log
        # excerpt that was actually sent, whichever applies.
        self._source_link = SourceLinkExpander()
        layout.addWidget(self._source_link)

        history_title = QLabel("Recent sessions")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(110)
        layout.addWidget(self._history)

    # --- Version-Aware Suggestions ------------------------------------------

    def _build_version_check(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Outdated-API check (Version-Aware Suggestions)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste a C# script or import a file. Scan checks it against a curated list of "
            "known-deprecated Unity APIs — fully offline, free. Analyze adds an AI narrative "
            "and one-line rationale per hit."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._version_input = QPlainTextEdit()
        self._version_input.setPlaceholderText("Paste a C# script here…")
        self._version_input.setFixedHeight(120)
        layout.addWidget(self._version_input)

        row = QHBoxLayout()
        self._version_import_btn = QPushButton("Import script…")
        self._version_import_btn.clicked.connect(self._on_version_import)
        row.addWidget(self._version_import_btn)
        self._version_scan_btn = QPushButton("Scan (local, free)")
        self._version_scan_btn.clicked.connect(self._on_version_scan)
        row.addWidget(self._version_scan_btn)
        row.addStretch(1)
        self._version_analyze_btn = QPushButton("Analyze with AI")
        self._version_analyze_btn.clicked.connect(self._on_version_analyze)
        row.addWidget(self._version_analyze_btn)
        layout.addLayout(row)

        self._version_result = QTextEdit()
        self._version_result.setReadOnly(True)
        self._version_result.setPlaceholderText("Scan results and AI review will appear here.")
        self._version_result.setFixedHeight(160)
        layout.addWidget(self._version_result)

        self._version_source_link = SourceLinkExpander()
        layout.addWidget(self._version_source_link)

        history_title = QLabel("Recent outdated-API checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._version_history = QTextEdit()
        self._version_history.setReadOnly(True)
        self._version_history.setFixedHeight(90)
        layout.addWidget(self._version_history)

    # --- Code Health Dashboard (collapsible) --------------------------------

    def _build_code_health(self, layout: QVBoxLayout) -> None:
        self._health_toggle = QPushButton("▸ Code Health summary (click to expand)")
        self._health_toggle.setObjectName("Ghost")
        self._health_toggle.clicked.connect(self._on_toggle_health)
        layout.addWidget(self._health_toggle)

        self._health_body = QWidget()
        body = QVBoxLayout(self._health_body)
        body.setContentsMargins(0, 6, 0, 0)
        body.setSpacing(8)

        intro = QLabel(
            "A non-judgmental, local read on one pasted file: function length, rough branching "
            "complexity, duplicate blocks, and TODOs. Framed as prioritized suggestions, never "
            "a score that shames you — and it only reflects this one file, not the whole project."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        body.addWidget(intro)

        self._health_input = QPlainTextEdit()
        self._health_input.setPlaceholderText("Paste a script to check its code health…")
        self._health_input.setFixedHeight(120)
        body.addWidget(self._health_input)

        row = QHBoxLayout()
        self._health_import_btn = QPushButton("Import script…")
        self._health_import_btn.clicked.connect(self._on_health_import)
        row.addWidget(self._health_import_btn)
        row.addStretch(1)
        self._health_analyze_btn = QPushButton("Check code health")
        self._health_analyze_btn.clicked.connect(self._on_health_analyze)
        row.addWidget(self._health_analyze_btn)
        body.addLayout(row)

        self._health_result = QTextEdit()
        self._health_result.setReadOnly(True)
        self._health_result.setPlaceholderText("Your code-health summary will appear here.")
        self._health_result.setFixedHeight(160)
        body.addWidget(self._health_result)

        self._health_source_link = SourceLinkExpander()
        body.addWidget(self._health_source_link)

        history_title = QLabel("Recent code-health checks")
        history_title.setObjectName("SectionTitle")
        body.addWidget(history_title)
        self._health_history = QTextEdit()
        self._health_history.setReadOnly(True)
        self._health_history.setFixedHeight(90)
        body.addWidget(self._health_history)

        # Naming/Organization Consistency + Dead Reference Detection (Phase
        # D): folded into this same card per spec, sharing the recursive
        # Assets/ walk with the Asset Optimization Sweep below. Deterministic
        # only — no AI call — since a filename-convention count and a GUID
        # cross-reference are either right or they aren't; a narrative pass
        # wouldn't add anything a provider could verify.
        project_scan_title = QLabel("Project scan: naming + dead references")
        project_scan_title.setObjectName("SectionTitle")
        body.addWidget(project_scan_title)

        project_scan_intro = QLabel(
            "A recursive, read-only scan of this project's Assets/ folder (not just the one "
            "pasted file above): the dominant filename convention and its outliers, plus "
            "broken/orphaned asset references. Fully local and free — no AI needed."
        )
        project_scan_intro.setObjectName("Muted")
        project_scan_intro.setWordWrap(True)
        body.addWidget(project_scan_intro)

        project_scan_row = QHBoxLayout()
        self._project_scan_btn = QPushButton("Scan project (naming + dead references)")
        self._project_scan_btn.clicked.connect(self._on_project_scan)
        project_scan_row.addWidget(self._project_scan_btn)
        project_scan_row.addStretch(1)
        body.addLayout(project_scan_row)

        # Live Task Progress Transparency (Phase L): the two independent
        # scan passes below -- see _ProjectHealthScanWorker.progress.
        self._project_scan_progress_trail = ProgressTrail()
        body.addWidget(self._project_scan_progress_trail)

        self._project_scan_result = QTextEdit()
        self._project_scan_result.setReadOnly(True)
        self._project_scan_result.setPlaceholderText(
            "Naming-consistency and dead-reference findings will appear here."
        )
        self._project_scan_result.setFixedHeight(180)
        body.addWidget(self._project_scan_result)

        self._health_body.setVisible(False)
        layout.addWidget(self._health_body)

    def _on_project_scan(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._project_scan_btn.setEnabled(False)
        self._project_scan_result.setPlainText(
            "Scanning Assets/ for naming patterns and references — this can take a moment on "
            "a large project…"
        )
        self._project_scan_progress_trail.reset()
        worker = _ProjectHealthScanWorker(self._services, project)
        thread = launch_worker(
            self, worker, progress_slot=self._project_scan_progress_trail.add_step
        )
        thread.started.connect(worker.run)
        worker.done.connect(self._on_project_scan_done)
        worker.failed.connect(self._on_project_scan_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_project_scan_done(self, naming, refs) -> None:
        self._project_scan_btn.setEnabled(True)
        lines = ["Naming consistency:"]
        if naming.dominant_convention:
            lines.append(
                f"- Dominant convention: {naming.dominant_convention} "
                f"({naming.total_classified}/{naming.total_files} filenames classified)"
            )
            if naming.outliers:
                lines.append(f"- {len(naming.outliers)} outlier(s), suggestion only, e.g.:")
                lines.extend(f"    • {p}" for p in naming.outliers[:10])
            else:
                lines.append("- No outliers found.")
        else:
            lines.append("- Not enough classifiable filenames under Assets/ to infer a convention.")
        lines.append("")
        lines.append("Dead reference detection:")
        if refs.broken_references:
            lines.append(f"- {len(refs.broken_references)} broken reference(s), e.g.:")
            lines.extend(
                f"    • {b.referencing_file} -> missing guid {b.missing_guid[:8]}…"
                for b in refs.broken_references[:10]
            )
        else:
            lines.append("- No broken references found.")
        if refs.orphaned_assets:
            lines.append(f"- {len(refs.orphaned_assets)} possibly orphaned asset(s), e.g.:")
            lines.extend(f"    • {p}" for p in refs.orphaned_assets[:10])
        else:
            lines.append("- No orphaned assets found.")
        lines.append("")
        lines.append(refs.caveat)
        self._project_scan_result.setPlainText("\n".join(lines))

    def _on_project_scan_failed(self, message: str) -> None:
        self._project_scan_btn.setEnabled(True)
        self._project_scan_result.setPlainText(message)

    # --- Changelog Generation ------------------------------------------------

    def _build_changelog(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Changelog Generation")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Reads your game project's own git log (never Spiced's) plus known issues Spiced "
            "has tracked as resolved, and drafts patch notes for you to review and edit below. "
            "Spiced never publishes this anywhere — copy it out yourself when you're happy with "
            "it. Needs the project's connected folder to be a git repository."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._changelog_status = QLabel()
        self._changelog_status.setObjectName("Muted")
        self._changelog_status.setWordWrap(True)
        layout.addWidget(self._changelog_status)

        row = QHBoxLayout()
        self._changelog_draft_btn = QPushButton("Draft changelog")
        self._changelog_draft_btn.clicked.connect(self._on_draft_changelog)
        row.addWidget(self._changelog_draft_btn)
        row.addStretch(1)
        self._changelog_save_btn = QPushButton("Save edits")
        self._changelog_save_btn.setObjectName("Ghost")
        self._changelog_save_btn.clicked.connect(self._on_save_changelog_edit)
        row.addWidget(self._changelog_save_btn)
        # Discord/Community Bot Integration (Phase G, section 7): posts the
        # text currently in the box below, always with an explicit confirm-
        # before-send step by default (see _on_post_changelog_to_discord).
        self._discord_post_btn = QPushButton("Post to Discord")
        self._discord_post_btn.setObjectName("Ghost")
        self._discord_post_btn.clicked.connect(self._on_post_changelog_to_discord)
        row.addWidget(self._discord_post_btn)
        layout.addLayout(row)

        self._changelog_text = QPlainTextEdit()
        self._changelog_text.setPlaceholderText(
            "Your draft changelog will appear here — edit freely before copying it out."
        )
        self._changelog_text.setFixedHeight(200)
        layout.addWidget(self._changelog_text)

        history_title = QLabel("Recent drafts")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._changelog_history = QTextEdit()
        self._changelog_history.setReadOnly(True)
        self._changelog_history.setFixedHeight(80)
        layout.addWidget(self._changelog_history)

    # --- Asset Health (Asset Optimization Sweep) ------------------------------

    def _build_asset_health(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Asset Health (Asset Optimization Sweep)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "A read-only scan of this project's Assets/ folder: oversized or uncompressed-"
            "format textures/audio, and assets that don't look referenced anywhere Spiced "
            "scanned. Suggestions only — nothing is ever resized, recompressed, or deleted."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._asset_scan_btn = QPushButton("Scan assets (local, free)")
        self._asset_scan_btn.clicked.connect(self._on_asset_scan)
        row.addWidget(self._asset_scan_btn)
        row.addStretch(1)
        self._asset_scan_ai_btn = QPushButton("Get AI summary")
        self._asset_scan_ai_btn.setObjectName("Ghost")
        self._asset_scan_ai_btn.clicked.connect(self._on_asset_scan_ai)
        row.addWidget(self._asset_scan_ai_btn)
        layout.addLayout(row)

        self._asset_scan_result = QTextEdit()
        self._asset_scan_result.setReadOnly(True)
        self._asset_scan_result.setPlaceholderText("Scan results will appear here.")
        self._asset_scan_result.setFixedHeight(200)
        layout.addWidget(self._asset_scan_result)

        history_title = QLabel("Recent AI-summarized scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._asset_scan_history = QTextEdit()
        self._asset_scan_history.setReadOnly(True)
        self._asset_scan_history.setFixedHeight(80)
        layout.addWidget(self._asset_scan_history)

    # --- Dependencies (Dependency & Plugin Update Checks) --------------------

    def _build_dependency_check(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Dependencies")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Reads this project's Packages/manifest.json and checks each package's version "
            "against the public Unity Package Registry — a read-only network lookup by "
            "package name only, nothing about your project is ever sent. Works offline (it "
            "just reports packages it couldn't check) and never installs or changes anything."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._dependency_check_btn = QPushButton("Check dependencies (local + registry)")
        self._dependency_check_btn.clicked.connect(self._on_dependency_check)
        row.addWidget(self._dependency_check_btn)
        row.addStretch(1)
        self._dependency_check_ai_btn = QPushButton("Get AI summary")
        self._dependency_check_ai_btn.setObjectName("Ghost")
        self._dependency_check_ai_btn.clicked.connect(self._on_dependency_check_ai)
        row.addWidget(self._dependency_check_ai_btn)
        layout.addLayout(row)

        self._dependency_check_result = QTextEdit()
        self._dependency_check_result.setReadOnly(True)
        self._dependency_check_result.setPlaceholderText(
            "Dependency check results will appear here."
        )
        self._dependency_check_result.setFixedHeight(180)
        layout.addWidget(self._dependency_check_result)

        history_title = QLabel("Recent AI-summarized dependency checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._dependency_check_history = QTextEdit()
        self._dependency_check_history.setReadOnly(True)
        self._dependency_check_history.setFixedHeight(80)
        layout.addWidget(self._dependency_check_history)

    # --- Dev Docs (Auto-Generated Dev Docs) -----------------------------------

    def _build_dev_docs(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Dev Docs (Auto-Generated)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Scans this project's own .cs scripts under Assets/ for class/method signatures "
            "and any doc comments, then asks the AI to turn them into a living, plain-language "
            "summary. Regenerated only when you click the button below — never a background "
            "file-watcher."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._dev_docs_btn = QPushButton("Regenerate docs")
        self._dev_docs_btn.clicked.connect(self._on_dev_docs_generate)
        row.addWidget(self._dev_docs_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._dev_docs_result = QTextEdit()
        self._dev_docs_result.setReadOnly(True)
        self._dev_docs_result.setPlaceholderText("Your generated docs will appear here.")
        self._dev_docs_result.setFixedHeight(200)
        layout.addWidget(self._dev_docs_result)

        history_title = QLabel("Snapshot history")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._dev_docs_history = QTextEdit()
        self._dev_docs_history.setReadOnly(True)
        self._dev_docs_history.setFixedHeight(90)
        layout.addWidget(self._dev_docs_history)

        # Visual Diff Viewer (Phase L, Phase 2 tier), text mode: Dev Docs
        # snapshots are explicitly a versioned history (see core.dev_docs's
        # module docstring) -- comparing the two most recent ones' AI
        # summaries is a natural "what changed since last time" moment.
        compare_row = QHBoxLayout()
        compare_row.addStretch(1)
        self._dev_docs_compare_btn = QPushButton("Compare last two snapshots")
        self._dev_docs_compare_btn.setObjectName("Ghost")
        self._dev_docs_compare_btn.clicked.connect(self._on_compare_dev_docs_snapshots)
        compare_row.addWidget(self._dev_docs_compare_btn)
        layout.addLayout(compare_row)

    def _on_dev_docs_generate(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._dev_docs_btn.setEnabled(False)
        self._dev_docs_btn.setText("Generating…")
        self._dev_docs_result.setPlainText("Scanning scripts and thinking it through…")

        worker = _DevDocsWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_dev_docs_done)
        worker.failed.connect(self._on_dev_docs_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_dev_docs_done(self, result: DevDocsResult) -> None:
        self._dev_docs_btn.setEnabled(True)
        self._dev_docs_btn.setText("Regenerate docs")
        stats = (
            f"{result.scan.file_count} script(s), {result.scan.class_count} class(es), "
            f"{result.scan.method_count} public method(s) scanned.\n\n"
        )
        self._dev_docs_result.setPlainText(stats + result.response_text)
        self.usage_changed.emit()
        self._refresh_dev_docs_history()
        # A new snapshot changes the scope-creep trend, so refresh that too.
        self._refresh_design_drift()

    def _on_dev_docs_failed(self, message: str) -> None:
        self._dev_docs_btn.setEnabled(True)
        self._dev_docs_btn.setText("Regenerate docs")
        self._dev_docs_result.setPlainText(message)

    def _refresh_dev_docs_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._dev_docs_history.setPlainText(
                "Snapshots are saved once you select an active project."
            )
            return
        snapshots = self._services.dev_docs.history(project.id, limit=5)
        if not snapshots:
            self._dev_docs_history.setPlainText("No Dev Docs snapshots generated yet.")
            return
        lines = [
            f"[{s.created_at}] {s.class_count} class(es), {s.method_count} method(s)"
            for s in snapshots
        ]
        self._dev_docs_history.setPlainText("\n".join(lines))

    def _on_compare_dev_docs_snapshots(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        snapshots = self._services.dev_docs.history(project.id, limit=2)
        if len(snapshots) < 2:
            QMessageBox.information(
                self,
                "Not enough snapshots yet",
                "Generate Dev Docs at least twice for this project before comparing.",
            )
            return
        newer, older = snapshots[0], snapshots[1]
        dialog = DiffViewerDialog.for_text(
            older.ai_summary or "",
            newer.ai_summary or "",
            left_label=f"Snapshot #{older.id} ({older.created_at})",
            right_label=f"Snapshot #{newer.id} ({newer.created_at})",
            title="Compare Dev Docs snapshots",
            parent=self,
        )
        dialog.exec()

    # --- Design Drift (Design Doc Sync) + Scope-Creep Flagging ----------------
    #
    # Paired on the same screen per spec: Scope-Creep Flagging is a pure
    # local computation over the Dev Docs snapshot history above (no AI
    # call of its own — see core.scope_creep) and is appended below the AI
    # drift check's response rather than run as a separate action.

    def _build_design_drift(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Design Drift + Scope Creep")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Opt-in per project (Projects screen). Upload or paste your own game's design doc "
            "— never Spiced's own spec — and compare it against the latest Dev Docs snapshot: "
            "flags drift either direction as a heads-up to reconcile the doc or rein in scope, "
            "paired with a gentle scope-growth note built from your Dev Docs snapshot history."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._design_drift_status = QLabel()
        self._design_drift_status.setObjectName("Muted")
        self._design_drift_status.setWordWrap(True)
        layout.addWidget(self._design_drift_status)

        self._design_doc_input = QPlainTextEdit()
        self._design_doc_input.setPlaceholderText(
            "Paste your game's design doc here, or import a .txt/.md/.docx file…"
        )
        self._design_doc_input.setFixedHeight(140)
        layout.addWidget(self._design_doc_input)

        row = QHBoxLayout()
        self._design_doc_import_btn = QPushButton("Import file…")
        self._design_doc_import_btn.clicked.connect(self._on_design_doc_import)
        row.addWidget(self._design_doc_import_btn)
        self._design_doc_save_btn = QPushButton("Save design doc")
        self._design_doc_save_btn.setObjectName("Ghost")
        self._design_doc_save_btn.clicked.connect(self._on_design_doc_save)
        row.addWidget(self._design_doc_save_btn)
        row.addStretch(1)
        self._design_drift_btn = QPushButton("Check design drift")
        self._design_drift_btn.clicked.connect(self._on_design_drift_check)
        row.addWidget(self._design_drift_btn)
        layout.addLayout(row)

        self._design_drift_result = QTextEdit()
        self._design_drift_result.setReadOnly(True)
        self._design_drift_result.setPlaceholderText(
            "The drift check and scope-creep note will appear here."
        )
        self._design_drift_result.setFixedHeight(200)
        layout.addWidget(self._design_drift_result)

        history_title = QLabel("Recent drift checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._design_drift_history = QTextEdit()
        self._design_drift_history.setReadOnly(True)
        self._design_drift_history.setFixedHeight(80)
        layout.addWidget(self._design_drift_history)

    def _on_design_doc_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import a design doc",
            "",
            "Design docs (*.txt *.md *.docx);;All files (*)",
        )
        if not path:
            return
        try:
            text = import_design_doc_text(path)
        except (OSError, UnsupportedDesignDocFormatError, KeyError) as exc:
            QMessageBox.warning(
                self, "Could not read file", f"Sorry, I couldn't read that file:\n{exc}"
            )
            return
        self._design_doc_input.setPlainText(text)

    def _on_design_doc_save(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        try:
            self._services.design_doc_sync.upload_text(
                project.id, self._design_doc_input.toPlainText()
            )
        except ValueError as exc:
            QMessageBox.information(self, "Nothing to save", str(exc))
            return
        self._refresh_design_drift()

    def _on_design_drift_check(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._design_drift_btn.setEnabled(False)
        self._design_drift_btn.setText("Checking…")
        self._design_drift_result.setPlainText("Comparing your design doc against Dev Docs…")

        worker = _DesignDocSyncWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_design_drift_done)
        worker.failed.connect(self._on_design_drift_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _scope_creep_message(self, project) -> str | None:
        """Scope-Creep Flagging: pure local computation over the Dev Docs
        snapshot history, optionally cross-referenced against the latest
        uploaded design doc text. No AI call."""
        snapshots = list(reversed(self._services.dev_docs.history(project.id, limit=20)))
        upload = self._services.design_doc_sync.latest_upload(project.id)
        finding = detect_scope_creep(
            snapshots, design_doc_text=upload.text if upload is not None else None
        )
        return finding.message

    def _on_design_drift_done(self, result: DesignDocSyncResult) -> None:
        self._design_drift_btn.setEnabled(True)
        self._design_drift_btn.setText("Check design drift")
        text = result.response_text
        project = self._services.active_project()
        if project is not None:
            scope_note = self._scope_creep_message(project)
            if scope_note:
                text += f"\n\n--- Scope-creep note ---\n{scope_note}"
        self._design_drift_result.setPlainText(text)
        self.usage_changed.emit()
        self._refresh_design_drift_history()

    def _on_design_drift_failed(self, message: str) -> None:
        self._design_drift_btn.setEnabled(True)
        self._design_drift_btn.setText("Check design drift")
        self._design_drift_result.setPlainText(message)

    def _refresh_design_drift_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._design_drift_history.setPlainText(
                "Checks are saved once you select an active project."
            )
            return
        reports = self._services.design_doc_sync.history(project.id, limit=5)
        if not reports:
            self._design_drift_history.setPlainText(
                "No design-drift checks saved for this project yet."
            )
            return
        lines = []
        for r in reports:
            summary = (r.ai_summary or "").strip().splitlines()
            first_line = next((line for line in summary if line.strip()), "")
            lines.append(f"[{r.created_at}] {first_line}")
        self._design_drift_history.setPlainText("\n".join(lines))

    def _refresh_design_drift(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        enabled = bool(project.design_doc_sync_enabled) if project else False
        active = has_project and enabled

        self._design_doc_input.setEnabled(active)
        self._design_doc_import_btn.setEnabled(active)
        self._design_doc_save_btn.setEnabled(active)
        self._design_drift_btn.setEnabled(active)

        if not has_project:
            self._design_drift_status.setText("Select a project to use Design Doc Sync.")
        elif not enabled:
            self._design_drift_status.setText(
                "Off for this project. Turn on \"Design Doc Sync\" on the Projects screen to "
                "use this section."
            )
        else:
            upload = self._services.design_doc_sync.latest_upload(project.id)
            if upload is None:
                self._design_drift_status.setText(
                    "No design doc saved yet for this project. Paste or import one above, "
                    "then Save design doc."
                )
            else:
                filename_note = f" ({upload.filename})" if upload.filename else ""
                self._design_drift_status.setText(
                    f"Design doc saved {upload.uploaded_at}{filename_note}."
                )
        self._refresh_design_drift_history()

    # --- Localization Readiness + Draft Translation Pass ----------------------
    #
    # Paired on this same card per spec: the spec calls for the Draft
    # Translation Pass to live on a "Localization panel," and since there is
    # no other dedicated Localization screen/section, this is the natural
    # home for both — a readiness check and a translation aid are clearly
    # meant to sit together.

    def _build_localization(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Localization")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Localization Readiness Check: a read-only scan of this project's .cs scripts for "
            "likely-hardcoded user-facing strings, plus prefab/scene text components that "
            "aren't obviously parameterized. Heuristic, not certainty — see the note below the "
            "results for exactly what it can and can't catch."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._localization_scan_btn = QPushButton("Scan localization readiness (local, free)")
        self._localization_scan_btn.clicked.connect(self._on_localization_scan)
        row.addWidget(self._localization_scan_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._localization_result = QTextEdit()
        self._localization_result.setReadOnly(True)
        self._localization_result.setPlaceholderText(
            "Hardcoded-string and prefab-text findings will appear here."
        )
        self._localization_result.setFixedHeight(200)
        layout.addWidget(self._localization_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._localization_history = QTextEdit()
        self._localization_history.setReadOnly(True)
        self._localization_history.setFixedHeight(70)
        layout.addWidget(self._localization_history)

        translation_title = QLabel("Draft Translation Pass")
        translation_title.setObjectName("SectionTitle")
        layout.addWidget(translation_title)

        translation_intro = QLabel(
            "Paste or import a dialogue file (plain text, one line per entry; or simple CSV/JSON "
            "with a \"text\" field — see the format examples as placeholder text below) and pick "
            "a target language. " + DRAFT_NOT_SHIP_READY_NOTICE
        )
        translation_intro.setObjectName("Muted")
        translation_intro.setWordWrap(True)
        layout.addWidget(translation_intro)

        self._translation_input = QPlainTextEdit()
        self._translation_input.setPlaceholderText(
            "One line per entry, e.g.:\nWelcome, traveler.\nYour journey begins now.\n\n"
            "...or JSON: [\"Welcome, traveler.\", \"Your journey begins now.\"]\n"
            "...or CSV: id,text\ngreeting,Welcome, traveler."
        )
        self._translation_input.setFixedHeight(120)
        layout.addWidget(self._translation_input)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Target language:"))
        self._translation_language_input = QLineEdit()
        self._translation_language_input.setPlaceholderText(
            "e.g. Japanese, French, Brazilian Portuguese"
        )
        lang_row.addWidget(self._translation_language_input, 1)
        layout.addLayout(lang_row)

        row2 = QHBoxLayout()
        self._translation_import_btn = QPushButton("Import file…")
        self._translation_import_btn.clicked.connect(self._on_translation_import)
        row2.addWidget(self._translation_import_btn)
        row2.addStretch(1)
        self._translation_run_btn = QPushButton("Draft translation")
        self._translation_run_btn.clicked.connect(self._on_translation_run)
        row2.addWidget(self._translation_run_btn)
        layout.addLayout(row2)

        self._translation_result = QTextEdit()
        self._translation_result.setReadOnly(True)
        self._translation_result.setPlaceholderText(
            "Your draft translation (for a human translator to review) will appear here."
        )
        self._translation_result.setFixedHeight(200)
        layout.addWidget(self._translation_result)

        translation_history_title = QLabel("Recent drafts")
        translation_history_title.setObjectName("SectionTitle")
        layout.addWidget(translation_history_title)
        self._translation_history = QTextEdit()
        self._translation_history.setReadOnly(True)
        self._translation_history.setFixedHeight(70)
        layout.addWidget(self._translation_history)

    def _on_localization_scan(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._localization_scan_btn.setEnabled(False)
        self._localization_result.setPlainText(
            "Scanning scripts and prefabs/scenes — this can take a moment on a large project…"
        )

        worker = _LocalizationScanWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_localization_scan_done)
        worker.failed.connect(self._on_localization_scan_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_localization_scan_done(self, scan: LocalizationReadinessScan) -> None:
        self._localization_scan_btn.setEnabled(True)
        lines = [
            f"Scripts scanned: {scan.scripts_scanned}  ·  Prefabs/scenes scanned: "
            f"{scan.prefabs_scanned}",
            "",
            "Likely-hardcoded strings in scripts:",
        ]
        if scan.hardcoded_strings:
            for f in scan.hardcoded_strings[:30]:
                lines.append(f"- [{f.confidence}] {f.file}:{f.line} — \"{f.text}\"")
            if len(scan.hardcoded_strings) > 30:
                lines.append(f"...and {len(scan.hardcoded_strings) - 30} more.")
        else:
            lines.append("None found.")
        lines.append("")
        lines.append("Prefab/scene text not obviously parameterized:")
        if scan.prefab_texts:
            for f in scan.prefab_texts[:30]:
                lines.append(f"- {f.file} — \"{f.text}\"")
            if len(scan.prefab_texts) > 30:
                lines.append(f"...and {len(scan.prefab_texts) - 30} more.")
        else:
            lines.append("None found.")
        lines.append("")
        lines.append(HEURISTIC_CAVEAT)
        self._localization_result.setPlainText("\n".join(lines))
        self._refresh_localization_history()

    def _on_localization_scan_failed(self, message: str) -> None:
        self._localization_scan_btn.setEnabled(True)
        self._localization_result.setPlainText(message)

    def _refresh_localization_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._localization_history.setPlainText(
                "Scans are saved once you select an active project."
            )
            return
        reports = self._services.localization_readiness.history(project.id, limit=5)
        if not reports:
            self._localization_history.setPlainText("No localization scans saved yet.")
            return
        lines = []
        for r in reports:
            f = r.findings
            hc = len(f.get("hardcoded_strings", []))
            pt = len(f.get("prefab_texts", []))
            lines.append(f"[{r.created_at}] {hc} hardcoded string(s), {pt} prefab text(s)")
        self._localization_history.setPlainText("\n".join(lines))

    def _on_translation_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import a dialogue file",
            "",
            "Dialogue files (*.txt *.csv *.json);;All files (*)",
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
        self._translation_input.setPlainText(text)
        self._translation_pending_filename = Path(path).name

    def _on_translation_run(self) -> None:
        text = self._translation_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to translate", "Paste or import a dialogue file first."
            )
            return
        target_language = self._translation_language_input.text().strip()
        if not target_language:
            QMessageBox.information(
                self, "Target language needed", "Enter the language to translate into."
            )
            return
        filename = self._translation_pending_filename
        self._translation_run_btn.setEnabled(False)
        self._translation_run_btn.setText("Translating…")
        self._translation_result.setPlainText("Drafting a translation…")

        worker = _DraftTranslationWorker(self._services, text, target_language, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_translation_done)
        worker.failed.connect(self._on_translation_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_translation_done(self, result: DraftTranslationResult) -> None:
        self._translation_run_btn.setEnabled(True)
        self._translation_run_btn.setText("Draft translation")
        self._translation_result.setPlainText(result.response_text)
        self._translation_pending_filename = None
        self.usage_changed.emit()
        self._refresh_translation_history()

    def _on_translation_failed(self, message: str) -> None:
        self._translation_run_btn.setEnabled(True)
        self._translation_run_btn.setText("Draft translation")
        self._translation_result.setPlainText(message)

    def _refresh_translation_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._translation_history.setPlainText(
                "Drafts are saved once you select an active project."
            )
            return
        drafts = self._services.draft_translation.history(project.id, limit=5)
        if not drafts:
            self._translation_history.setPlainText("No draft translations saved yet.")
            return
        lines = [
            f"[{d.created_at}] {d.entry_count} entry/entries -> {d.target_language}"
            for d in drafts
        ]
        self._translation_history.setPlainText("\n".join(lines))

    def _on_toggle_health(self) -> None:
        expanded = not self._health_body.isVisible()
        self._health_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        action = "collapse" if expanded else "expand"
        self._health_toggle.setText(f"{arrow} Code Health summary (click to {action})")

    # --- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project yet. You can still analyze a log, but pick a project on "
                "the Projects screen to save sessions and add Unity context."
            )
        else:
            if project.is_valid_unity:
                status = "valid Unity project"
            elif project.path:
                status = "folder not recognized as Unity"
            else:
                status = "no Unity folder connected"
            self._context_label.setText(f"Active project: {project.name} · {status}")
        self._refresh_history()
        self._refresh_version_history()
        self._refresh_health_history()
        self._refresh_changelog_status()
        self._refresh_changelog_history()
        self._refresh_asset_scan_history()
        self._refresh_dependency_check_history()
        self._refresh_dev_docs_history()
        self._refresh_design_drift()
        self._refresh_localization_history()
        self._refresh_translation_history()

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Sessions are saved once you select an active project.")
            return
        sessions = self._services.debugging.history(project.id, limit=10)
        if not sessions:
            self._history.setPlainText("No debugging sessions saved for this project yet.")
            return
        lines = []
        for s in sessions:
            error = s.detected_error_type or "Unknown error"
            where = f" in {s.detected_file}" if s.detected_file else ""
            summary = s.summary or ""
            lines.append(f"[{s.created_at}] {error}{where}\n    {summary}")
        self._history.setPlainText("\n".join(lines))

    def _refresh_version_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._version_history.setPlainText(
                "Checks are saved once you select an active project."
            )
            return
        reports = self._services.version_check.history(project.id, limit=10)
        if not reports:
            self._version_history.setPlainText(
                "No outdated-API checks saved for this project yet."
            )
            return
        lines = [
            f"[{r.created_at}] {len(r.hits)} hit(s)\n    {r.ai_summary or ''}" for r in reports
        ]
        self._version_history.setPlainText("\n".join(lines))

    def _refresh_health_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._health_history.setPlainText("Checks are saved once you select an active project.")
            return
        reports = self._services.code_health.history(project.id, limit=10)
        if not reports:
            self._health_history.setPlainText("No code-health checks saved for this project yet.")
            return
        lines = [f"[{r.created_at}]\n    {r.ai_summary or ''}" for r in reports]
        self._health_history.setPlainText("\n".join(lines))

    # --- Crash analysis handlers ---------------------------------------------

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a Unity log", "", "Log files (*.log *.txt);;All files (*)"
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
        self._log_input.setPlainText(text)
        self._pending_filename = Path(path).name

    def _on_analyze(self) -> None:
        log_text = self._log_input.toPlainText().strip()
        if not log_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste a log or import a file first."
            )
            return

        source_type = SOURCE_FILE if self._pending_filename else SOURCE_PASTE
        filename = self._pending_filename
        self._set_busy(True)
        self._result.setPlainText("Reading the log and thinking it through…")

        worker = _CrashWorker(self._services, log_text, source_type, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_done(self, analysis: DebugAnalysis) -> None:
        text = analysis.response_text
        if analysis.regression_match is not None:
            text = text + "\n\nKnown-issue match:\n- " + analysis.regression_match.note
        self._result.setPlainText(text)
        if analysis.regression_match is not None:
            description = analysis.regression_match.note
        elif analysis.session is not None and analysis.session.source_filename:
            description = f"From the imported log file \"{analysis.session.source_filename}\"."
        else:
            description = "From the pasted crash log excerpt below."
        self._source_link.set_source(description, analysis.parsed.excerpt)
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._source_link.set_source(None, None)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")

    # --- Version-check handlers -----------------------------------------------

    def _on_version_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a script", "", "C# files (*.cs);;All files (*)"
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
        self._version_input.setPlainText(text)
        self._version_pending_filename = Path(path).name

    def _on_version_scan(self) -> None:
        code_text = self._version_input.toPlainText().strip()
        if not code_text:
            QMessageBox.information(
                self, "Nothing to scan", "Paste a script or import a file first."
            )
            return
        parsed = self._services.version_check.scan(code_text)
        if not parsed.hits:
            self._version_result.setPlainText(
                "Local scan (no AI used): none of Spiced's known-deprecated APIs were found.\n\n"
                "Click Analyze with AI for a written review, or keep this scan for free."
            )
            return
        lines = ["Local scan (no AI used):"]
        for hit in parsed.hits:
            lines.append(
                f"- Line {hit.line_number}: {hit.api_name} -> {hit.replacement} "
                f"(deprecated in {hit.deprecated_in})\n    {hit.reason}"
            )
        lines.append("\nClick Analyze with AI for a written review.")
        self._version_result.setPlainText("\n".join(lines))

    def _on_version_analyze(self) -> None:
        code_text = self._version_input.toPlainText().strip()
        if not code_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste a script or import a file first."
            )
            return
        filename = self._version_pending_filename
        self._version_analyze_btn.setEnabled(False)
        self._version_analyze_btn.setText("Analyzing…")
        self._version_result.setPlainText("Reading the script and thinking it through…")

        worker = _VersionCheckWorker(self._services, code_text, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_version_done)
        worker.failed.connect(self._on_version_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_version_done(self, review: VersionCheckReview) -> None:
        self._version_result.setPlainText(review.response_text)
        hit_count = len(review.parsed.hits)
        description = (
            f"From {hit_count} deprecated-API hit(s) found by the local scan of the "
            "pasted/imported script below."
        )
        self._version_source_link.set_source(description, review.parsed.excerpt)
        self._version_pending_filename = None
        self._version_analyze_btn.setEnabled(True)
        self._version_analyze_btn.setText("Analyze with AI")
        self.usage_changed.emit()
        self._refresh_version_history()

    def _on_version_failed(self, message: str) -> None:
        self._version_result.setPlainText(message)
        self._version_source_link.set_source(None, None)
        self._version_analyze_btn.setEnabled(True)
        self._version_analyze_btn.setText("Analyze with AI")

    # --- Code health handlers --------------------------------------------------

    def _on_health_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a script", "", "C# files (*.cs);;All files (*)"
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
        self._health_input.setPlainText(text)
        self._health_pending_filename = Path(path).name

    def _on_health_analyze(self) -> None:
        code_text = self._health_input.toPlainText().strip()
        if not code_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste a script or import a file first."
            )
            return
        filename = self._health_pending_filename
        self._health_analyze_btn.setEnabled(False)
        self._health_analyze_btn.setText("Checking…")
        self._health_result.setPlainText("Reading the file and thinking it through…")

        worker = _CodeHealthWorker(self._services, code_text, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_health_done)
        worker.failed.connect(self._on_health_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_health_done(self, review: CodeHealthReview) -> None:
        self._health_result.setPlainText(review.response_text)
        excerpt = (
            review.report.raw_excerpt
            if review.report is not None
            else self._health_input.toPlainText().strip()[:CODE_HEALTH_MAX_EXCERPT_CHARS]
        )
        self._health_source_link.set_source(
            "From the pasted/imported script below (this excerpt, plus the local metrics "
            "shown above, is what was sent to the AI).",
            excerpt,
        )
        self._health_pending_filename = None
        self._health_analyze_btn.setEnabled(True)
        self._health_analyze_btn.setText("Check code health")
        self.usage_changed.emit()
        self._refresh_health_history()

    def _on_health_failed(self, message: str) -> None:
        self._health_result.setPlainText(message)
        self._health_source_link.set_source(None, None)
        self._health_analyze_btn.setEnabled(True)
        self._health_analyze_btn.setText("Check code health")

    # --- Changelog Generation handlers -----------------------------------------

    def _refresh_changelog_status(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._changelog_status.setText("Select a project to draft a changelog.")
            return
        stable = self._services.build_reports.latest_stable_for_project(project.id)
        if stable is not None:
            self._changelog_status.setText(
                f"Will draft from commits since the build marked stable on {stable.created_at} "
                "(mark a different build stable on Testing → Build & Release to change this)."
            )
        else:
            self._changelog_status.setText(
                "No build has been marked stable yet — will draft from the last "
                "40 commits. Mark a build stable on Testing → Build & Release for a tighter window."
            )

    def _on_draft_changelog(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        since_date = None
        stable = self._services.build_reports.latest_stable_for_project(project.id)
        if stable is not None:
            since_date = stable.created_at[:10]  # "YYYY-MM-DD" prefix

        self._changelog_draft_btn.setEnabled(False)
        self._current_changelog_draft_id = None
        self._changelog_text.setPlainText("Reading git log and thinking it through…")

        worker = _ChangelogWorker(self._services, project, since_date)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_changelog_done)
        worker.failed.connect(self._on_changelog_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_changelog_done(self, result: ChangelogResult) -> None:
        self._changelog_draft_btn.setEnabled(True)
        self._current_changelog_draft_id = result.draft.id
        self._changelog_text.setPlainText(result.response_text)
        self.usage_changed.emit()
        self._refresh_changelog_history()

    def _on_changelog_failed(self, message: str) -> None:
        self._changelog_draft_btn.setEnabled(True)
        self._changelog_text.setPlainText(message)

    def _on_save_changelog_edit(self) -> None:
        if self._current_changelog_draft_id is None:
            QMessageBox.information(
                self, "Nothing to save", "Draft a changelog first, then edit and save it."
            )
            return
        self._services.changelog.save_edit(
            self._current_changelog_draft_id, self._changelog_text.toPlainText()
        )
        self._refresh_changelog_history()

    def _on_post_changelog_to_discord(self) -> None:
        text = self._changelog_text.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to post", "Draft (or write) a changelog above first."
            )
            return
        if not self._services.discord_posting_enabled():
            QMessageBox.information(
                self,
                "Discord integration is off",
                "Turn on \"Allow Spiced to post to Discord\" on the Settings screen first.",
            )
            return
        poster = self._services.build_discord_poster()
        if not poster.is_available():
            QMessageBox.information(
                self,
                "Discord isn't configured",
                "Set DISCORD_BOT_TOKEN and a channel id (DISCORD_CHANNEL_ID or "
                "DISCORD_ANNOUNCE_CHANNEL_ID) in your environment or a local .env file first.",
            )
            return

        # Approval-required is the default path per spec: always show the
        # exact text and require a click, unless the developer has
        # separately opted into auto-post on the Settings screen.
        if not self._services.discord_auto_post_enabled():
            confirm = QMessageBox.question(
                self,
                "Post to Discord?",
                f"This will post the following to {poster.channel_label()}:\n\n{text}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self._discord_post_btn.setEnabled(False)
        self._discord_post_btn.setText("Posting…")

        worker = _DiscordPostWorker(self._services, text)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_discord_post_done)
        worker.failed.connect(self._on_discord_post_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_discord_post_done(self) -> None:
        self._discord_post_btn.setEnabled(True)
        self._discord_post_btn.setText("Post to Discord")
        QMessageBox.information(self, "Posted", "Your changelog was posted to Discord.")

    def _on_discord_post_failed(self, message: str) -> None:
        self._discord_post_btn.setEnabled(True)
        self._discord_post_btn.setText("Post to Discord")
        QMessageBox.warning(self, "Couldn't post to Discord", message)

    def _refresh_changelog_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._changelog_history.setPlainText(
                "Drafts are saved once you select an active project."
            )
            return
        drafts = self._services.changelog.history(project.id, limit=5)
        if not drafts:
            self._changelog_history.setPlainText("No changelog drafts saved for this project yet.")
            return
        lines = []
        for d in drafts:
            edited = " (edited)" if d.edited_text else ""
            lines.append(f"[{d.created_at}] {d.source_commit_range or ''}{edited}")
        self._changelog_history.setPlainText("\n".join(lines))

    # --- Asset Health handlers --------------------------------------------------

    def _on_asset_scan(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._asset_scan_btn.setEnabled(False)
        self._asset_scan_result.setPlainText(
            "Scanning Assets/ — this can take a moment on a large project…"
        )
        worker = _AssetScanWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_asset_scan_done)
        worker.failed.connect(self._on_asset_scan_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_asset_scan_done(self, findings: AssetScanFindings) -> None:
        self._asset_scan_btn.setEnabled(True)
        self._asset_scan_result.setPlainText(_format_asset_findings(findings))

    def _on_asset_scan_failed(self, message: str) -> None:
        self._asset_scan_btn.setEnabled(True)
        self._asset_scan_result.setPlainText(message)

    def _on_asset_scan_ai(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._asset_scan_ai_btn.setEnabled(False)
        self._asset_scan_ai_btn.setText("Thinking…")
        self._asset_scan_result.setPlainText("Scanning and thinking it through…")

        worker = _AssetScanAIWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_asset_scan_ai_done)
        worker.failed.connect(self._on_asset_scan_ai_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_asset_scan_ai_done(self, review: AssetScanReview) -> None:
        self._asset_scan_ai_btn.setEnabled(True)
        self._asset_scan_ai_btn.setText("Get AI summary")
        text = _format_asset_findings(review.findings)
        if review.response_text:
            text += f"\n\n--- AI summary ---\n{review.response_text}"
        self._asset_scan_result.setPlainText(text)
        self.usage_changed.emit()
        self._refresh_asset_scan_history()

    def _on_asset_scan_ai_failed(self, message: str) -> None:
        self._asset_scan_ai_btn.setEnabled(True)
        self._asset_scan_ai_btn.setText("Get AI summary")
        self._asset_scan_result.setPlainText(message)

    def _refresh_asset_scan_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._asset_scan_history.setPlainText(
                "AI-summarized scans are saved once you select an active project."
            )
            return
        reports = self._services.asset_scan.history(project.id, limit=5)
        if not reports:
            self._asset_scan_history.setPlainText(
                "No AI-summarized scans saved yet (a local-only \"Scan assets\" pass isn't saved)."
            )
            return
        lines = []
        for r in reports:
            f = r.findings
            oversized_count = len(f.get("oversized", []))
            orphan_count = len(f.get("orphaned_assets", []))
            lines.append(
                f"[{r.created_at}] {oversized_count} oversized/uncompressed · "
                f"{orphan_count} possibly orphaned"
            )
        self._asset_scan_history.setPlainText("\n".join(lines))

    # --- Dependency check handlers -------------------------------------------

    def _on_dependency_check(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._dependency_check_btn.setEnabled(False)
        self._dependency_check_result.setPlainText(
            "Reading manifest.json and querying the Unity Package Registry…"
        )
        worker = _DependencyCheckWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_dependency_check_done)
        worker.failed.connect(self._on_dependency_check_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_dependency_check_done(self, findings: DependencyCheckFindings) -> None:
        self._dependency_check_btn.setEnabled(True)
        self._dependency_check_result.setPlainText(_format_dependency_findings(findings))

    def _on_dependency_check_failed(self, message: str) -> None:
        self._dependency_check_btn.setEnabled(True)
        self._dependency_check_result.setPlainText(message)

    def _on_dependency_check_ai(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._dependency_check_ai_btn.setEnabled(False)
        self._dependency_check_ai_btn.setText("Thinking…")
        self._dependency_check_result.setPlainText("Checking dependencies and thinking it through…")

        worker = _DependencyCheckAIWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_dependency_check_ai_done)
        worker.failed.connect(self._on_dependency_check_ai_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_dependency_check_ai_done(self, review: DependencyCheckReview) -> None:
        self._dependency_check_ai_btn.setEnabled(True)
        self._dependency_check_ai_btn.setText("Get AI summary")
        text = _format_dependency_findings(review.findings)
        if review.response_text:
            text += f"\n\n--- AI summary ---\n{review.response_text}"
        self._dependency_check_result.setPlainText(text)
        self.usage_changed.emit()
        self._refresh_dependency_check_history()

    def _on_dependency_check_ai_failed(self, message: str) -> None:
        self._dependency_check_ai_btn.setEnabled(True)
        self._dependency_check_ai_btn.setText("Get AI summary")
        self._dependency_check_result.setPlainText(message)

    def _refresh_dependency_check_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._dependency_check_history.setPlainText(
                "AI-summarized checks are saved once you select an active project."
            )
            return
        reports = self._services.dependency_check.history(project.id, limit=5)
        if not reports:
            self._dependency_check_history.setPlainText(
                "No AI-summarized dependency checks saved yet (a local-only check isn't saved)."
            )
            return
        lines = []
        for r in reports:
            results = r.findings.get("results", [])
            outdated_count = sum(1 for x in results if x.get("outdated"))
            unchecked_count = sum(1 for x in results if not x.get("checked"))
            lines.append(
                f"[{r.created_at}] {outdated_count} outdated · {unchecked_count} not checked · "
                f"{len(results)} total"
            )
        self._dependency_check_history.setPlainText("\n".join(lines))
