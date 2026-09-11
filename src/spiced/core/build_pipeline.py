"""Automated Build Pipeline use-case.

Ties together the opt-in gate, the engine-appropriate build/export trigger
(``connectors.unity_build``/``godot_build``/``unreal_build``), and saved
``build_reports`` history. Three entry points share the one
``run_build_pipeline`` function so the opt-in gate can never be bypassed by
any of them:

1. a "Run build now" button (trigger=manual),
2. the in-app QTimer scheduler (trigger=scheduled, see ``ui/build_scheduler.py``),
3. ``trigger_build_from_hook``, a hook-callable extension point for Phase E's
   Pre-Commit Review feature (trigger=commit) — Phase E installs the actual
   ``.git/hooks/pre-commit`` script; this phase only makes sure the function it
   would call already exists and behaves correctly.

Per spec, only build *failures* are meant to interrupt the developer — a
successful scheduled/commit build stays quiet. This module doesn't decide how
that's surfaced (that's a UI concern, e.g. the Context Panel), but every
``BuildReport`` records ``succeeded`` so a caller can decide whether to notify.

**Engine dispatch (Godot/Unreal UI follow-up).** All three engines' own
result dataclasses (``UnityBuildResult``/``GodotExportResult``/
``UnrealBuildResult``) already share the same ``succeeded/output_path/
log_tail/error`` shape and map onto ``BuildReportRepository.create`` the same
way, so only the *how to trigger a build* step differs per engine -- factored
into the three private ``_run_*_build`` helpers below, each returning a
``_BuildOutcome`` the shared save step doesn't need to know the engine of.
Neither Godot nor Unreal has a Unity-Hub-equivalent to auto-discover an
installed engine from (see ``core.engine_executable_resolve``'s module
docstring) -- both require a manual, mandatory executable/install-root
override this phase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from spiced.connectors import godot_build, unity_build, unreal_build
from spiced.connectors.unreal import find_uproject_file
from spiced.core.engine_dispatch import ENGINE_GODOT, ENGINE_UNREAL
from spiced.core.engine_executable_resolve import (
    resolve_godot_executable,
    resolve_unreal_uat,
)
from spiced.core.unity_test_runner import resolve_unity_editor
from spiced.storage.build_reports import (
    TRIGGER_COMMIT,
    BuildReport,
    BuildReportRepository,
)
from spiced.storage.projects import Project, ProjectRepository

__all__ = [
    "BuildNotEnabledError",
    "BuildUnavailableError",
    "list_build_targets_for_project",
    "run_build_pipeline",
    "trigger_build_from_hook",
    "now_sqlite",
]


class BuildNotEnabledError(RuntimeError):
    """Raised when a build is triggered for a project that hasn't opted in."""


class BuildUnavailableError(RuntimeError):
    """Raised when a build can't be started (no folder, no resolvable Editor)."""


def now_sqlite() -> str:
    """A timestamp string matching SQLite's ``datetime('now')`` format, so it
    sorts correctly next to ``created_at``-style columns elsewhere."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class _BuildOutcome:
    target_platform: str
    succeeded: bool
    output_path: str | None
    log_tail: str | None


def list_build_targets_for_project(project: Project) -> list[str]:
    """Target-platform/export-preset names to offer in a build-target combo
    box, for whichever engine ``project`` is. Shared by the Projects and
    Testing screens so they don't each duplicate this branch.

    Godot's list is read live from the project's own ``export_presets.cfg``
    (there's no fixed vocabulary the way Unity/Unreal have -- see
    ``connectors.godot_build``'s module docstring) and is empty until a
    folder is connected and Export has been configured in the Godot Editor;
    callers should show an explanatory empty-state for that case rather than
    a silently-empty dropdown.
    """
    if project.engine == ENGINE_GODOT:
        if not project.path:
            return []
        return [p.name for p in godot_build.list_export_presets(project.path)]
    if project.engine == ENGINE_UNREAL:
        return list(unreal_build.PLATFORMS)
    return list(unity_build.BUILD_TARGETS)


def run_build_pipeline(
    project: Project,
    reports: BuildReportRepository,
    *,
    trigger: str,
    target_platform: str | None = None,
    editor_override: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> BuildReport:
    """Run one headless build/export for ``project`` and save its report.

    Always checks ``project.build_pipeline_enabled`` itself — unlike the
    Unity Test Runner (whose opt-in gate lives only in the UI callback), this
    function is the single choke point for three different trigger sources,
    so the check belongs here rather than being repeated (and potentially
    forgotten) at each call site.

    ``on_progress`` (Live Task Progress Transparency, Phase L), if given, is
    called with a plain-language description before each real step below --
    resolving the Editor, preparing the build script, running the (often
    multi-minute) headless build itself, then saving the report. Entirely
    optional and backward-compatible: every existing caller that doesn't
    pass it behaves exactly as before.
    """

    def _progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    if not project.build_pipeline_enabled:
        raise BuildNotEnabledError(
            f'Automated Build Pipeline is not enabled for "{project.name}". Turn it on for '
            "this project (Projects screen) first."
        )
    if not project.path:
        raise BuildUnavailableError(f"Connect a {project.engine} folder for this project first.")

    started_at = now_sqlite()
    if project.engine == ENGINE_GODOT:
        outcome = _run_godot_build(project, target_platform, editor_override, _progress)
    elif project.engine == ENGINE_UNREAL:
        outcome = _run_unreal_build(project, target_platform, editor_override, _progress)
    else:
        outcome = _run_unity_build(project, target_platform, editor_override, _progress)
    finished_at = now_sqlite()
    _progress("Saving the build report…")

    return reports.create(
        project_id=project.id,
        trigger=trigger,
        target_platform=outcome.target_platform,
        started_at=started_at,
        finished_at=finished_at,
        succeeded=outcome.succeeded,
        log_tail=outcome.log_tail,
        output_path=outcome.output_path,
    )


def _run_unity_build(
    project: Project,
    target_platform: str | None,
    editor_override: str | None,
    progress: Callable[[str], None],
) -> _BuildOutcome:
    progress("Resolving the Unity Editor to build with…")
    required_version = project.engine_metadata.get("unity_version")
    editor = resolve_unity_editor(required_version, editor_override)
    if editor is None:
        raise BuildUnavailableError(
            f"Unity {required_version or '(unknown version)'} isn't available. Install it via "
            "Unity Hub, or set a manual Editor path on the Projects screen."
        )
    platform = target_platform or project.build_target_platform or unity_build.DEFAULT_BUILD_TARGET
    progress("Preparing the build script…")
    script_info = unity_build.ensure_build_script(project.path)
    output_dir = str(_builds_dir(project.path))
    progress(f"Running the headless {platform} build (this can take a while)…")
    result = unity_build.run_build(
        editor.path, project.path, platform, output_dir, script_info.execute_method
    )
    return _BuildOutcome(
        target_platform=platform,
        succeeded=result.succeeded,
        output_path=result.output_path,
        log_tail=_report_log(result.error, result.log_tail),
    )


def _run_godot_build(
    project: Project,
    target_platform: str | None,
    editor_override: str | None,
    progress: Callable[[str], None],
) -> _BuildOutcome:
    progress("Checking the Godot executable…")
    godot_path = resolve_godot_executable(editor_override or project.unity_editor_path_override)
    if godot_path is None:
        raise BuildUnavailableError(
            "No valid Godot executable is configured for this project. Set the Godot executable "
            "path on the Projects screen — Spiced can't auto-detect it."
        )
    progress("Reading this project's export presets…")
    presets = godot_build.list_export_presets(project.path)
    if not presets:
        raise BuildUnavailableError(
            "This project has no export presets configured yet. Set up Export in the Godot "
            "Editor first (Project > Export…), then try again."
        )
    preset = next((p for p in presets if p.name == target_platform), None) or presets[0]
    output_dir = _builds_dir(project.path) / _sanitize_path_component(preset.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Godot's CLI writes exactly the file at this path -- it does not append
    # an extension of its own. The real extension needed depends on the
    # preset's target platform (.exe/.x86_64/.zip/...), which isn't derived
    # here; this is a best-effort default, flagged for validation against a
    # real Godot install (see this phase's plan notes on that gap).
    output_path = str(output_dir / _sanitize_path_component(preset.name))
    progress(f"Running the headless \"{preset.name}\" export (this can take a while)…")
    result = godot_build.run_export(godot_path, project.path, preset.name, output_path)
    return _BuildOutcome(
        target_platform=preset.name,
        succeeded=result.succeeded,
        output_path=result.output_path,
        log_tail=_report_log(result.error, result.log_tail),
    )


def _run_unreal_build(
    project: Project,
    target_platform: str | None,
    editor_override: str | None,
    progress: Callable[[str], None],
) -> _BuildOutcome:
    progress("Resolving the Unreal Engine install…")
    engine_root = editor_override or project.unity_editor_path_override
    uat_path = resolve_unreal_uat(engine_root)
    if uat_path is None:
        raise BuildUnavailableError(
            "No valid Unreal Engine install is configured for this project. Set the Engine "
            "install folder on the Projects screen — Spiced can't auto-detect it."
        )
    uproject_path = find_uproject_file(project.path)
    if uproject_path is None:
        raise BuildUnavailableError("No .uproject file found in this project's folder.")
    platform = target_platform or project.build_target_platform or unreal_build.DEFAULT_PLATFORM
    output_dir = str(_builds_dir(project.path) / platform)
    progress(f"Running the headless {platform} build (this can take a while)…")
    result = unreal_build.run_build(uat_path, str(uproject_path), platform, output_dir)
    return _BuildOutcome(
        target_platform=platform,
        succeeded=result.succeeded,
        output_path=result.output_path,
        log_tail=_report_log(result.error, result.log_tail),
    )


def trigger_build_from_hook(
    project_id: int, projects: ProjectRepository, reports: BuildReportRepository
) -> BuildReport:
    """Extension point Phase E's pre-commit hook mechanism can call.

    Phase E (not yet built) installs the actual ``.git/hooks/pre-commit``
    script; this phase only guarantees a stable, hook-callable function
    exists and reuses the exact same gated pipeline as every other trigger.
    """
    project = projects.get(project_id)
    return run_build_pipeline(project, reports, trigger=TRIGGER_COMMIT)


def _builds_dir(project_path: str) -> Path:
    return Path(project_path) / "Builds"


def _sanitize_path_component(name: str) -> str:
    """A preset/platform name (e.g. "Windows Desktop") turned into a safe
    single path segment."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("_") or "export"


def _report_log(error: str | None, log_tail: str | None) -> str | None:
    if error and log_tail:
        return f"{error}\n\n{log_tail}"
    return error or log_tail
