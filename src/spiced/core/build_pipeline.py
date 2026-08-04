"""Automated Build Pipeline use-case.

Ties together the opt-in gate, the build-script write/find step, the headless
Unity build trigger (``connectors.unity_build``), and saved ``build_reports``
history. Three entry points share the one ``run_build_pipeline`` function so
the opt-in gate can never be bypassed by any of them:

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
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from spiced.connectors import unity_build
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


def run_build_pipeline(
    project: Project,
    reports: BuildReportRepository,
    *,
    trigger: str,
    target_platform: str | None = None,
    editor_override: str | None = None,
) -> BuildReport:
    """Run one headless build for ``project`` and save its report.

    Always checks ``project.build_pipeline_enabled`` itself — unlike the
    Unity Test Runner (whose opt-in gate lives only in the UI callback), this
    function is the single choke point for three different trigger sources,
    so the check belongs here rather than being repeated (and potentially
    forgotten) at each call site.
    """
    if not project.build_pipeline_enabled:
        raise BuildNotEnabledError(
            f'Automated Build Pipeline is not enabled for "{project.name}". Turn it on for '
            "this project (Projects screen) first."
        )
    if not project.path:
        raise BuildUnavailableError("Connect a Unity folder for this project first.")

    required_version = project.engine_metadata.get("unity_version")
    editor = resolve_unity_editor(required_version, editor_override)
    if editor is None:
        raise BuildUnavailableError(
            f"Unity {required_version or '(unknown version)'} isn't available. Install it via "
            "Unity Hub, or set a manual Editor path on the Projects screen."
        )

    platform = target_platform or project.build_target_platform or unity_build.DEFAULT_BUILD_TARGET
    started_at = now_sqlite()
    script_info = unity_build.ensure_build_script(project.path)
    output_dir = str(_builds_dir(project.path))
    result = unity_build.run_build(
        editor.path, project.path, platform, output_dir, script_info.execute_method
    )
    finished_at = now_sqlite()

    return reports.create(
        project_id=project.id,
        trigger=trigger,
        target_platform=platform,
        started_at=started_at,
        finished_at=finished_at,
        succeeded=result.succeeded,
        log_tail=_report_log(result),
        output_path=result.output_path,
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


def _report_log(result: unity_build.UnityBuildResult) -> str | None:
    if result.error and result.log_tail:
        return f"{result.error}\n\n{result.log_tail}"
    return result.error or result.log_tail
