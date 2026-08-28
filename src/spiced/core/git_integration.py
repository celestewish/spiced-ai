"""Version Control (Git) opt-in gate (Market-Viability Roadmap, Phase 1).

``connectors.git_connector`` carries no opt-in gate of its own, per this
app's established connector convention (see that module's docstring) --
gating is this module's job, checked against
``Project.git_integration_enabled``, the same shape as
``core.build_pipeline``'s ``build_pipeline_enabled`` gate.

Every public function here re-checks the gate itself rather than trusting
the caller to have already checked it, matching ``run_build_pipeline``'s
reasoning: this is the one choke point every UI call site (and, later, any
other trigger source) goes through, so the gate can't be forgotten at an
individual call site.
"""

from __future__ import annotations

from spiced.connectors import git_connector
from spiced.storage.projects import Project

__all__ = [
    "GitIntegrationNotEnabledError",
    "repo_status",
    "file_history",
    "diff_for_path",
    "stage_paths",
    "commit_staged",
    "discard_unstaged_changes",
]


class GitIntegrationNotEnabledError(RuntimeError):
    """Raised when a git operation is attempted for a project that hasn't opted in."""


def _require_enabled(project: Project) -> None:
    if not project.git_integration_enabled:
        raise GitIntegrationNotEnabledError(
            f'Version Control is not enabled for "{project.name}". Turn it on for this '
            "project (Projects screen) first."
        )
    if not project.path:
        raise GitIntegrationNotEnabledError(
            f'"{project.name}" has no folder connected yet -- connect one first.'
        )


def repo_status(project: Project) -> git_connector.GitStatusResult:
    _require_enabled(project)
    return git_connector.repo_status(project.path)


def file_history(
    project: Project, relative_path: str, limit: int = 20
) -> list[git_connector.GitCommitEntry]:
    _require_enabled(project)
    return git_connector.file_history(project.path, relative_path, limit)


def diff_for_path(project: Project, relative_path: str, *, staged: bool = False) -> str:
    _require_enabled(project)
    return git_connector.diff_for_path(project.path, relative_path, staged=staged)


def stage_paths(project: Project, relative_paths: list[str]) -> git_connector.GitStageResult:
    _require_enabled(project)
    return git_connector.stage_paths(project.path, relative_paths)


def commit_staged(
    project: Project,
    message: str,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
) -> git_connector.GitCommitResult:
    _require_enabled(project)
    return git_connector.commit_staged(
        project.path, message, author_name=author_name, author_email=author_email
    )


def discard_unstaged_changes(
    project: Project, relative_paths: list[str], *, confirmed: bool = False
) -> git_connector.GitDiscardResult:
    _require_enabled(project)
    return git_connector.discard_unstaged_changes(
        project.path, relative_paths, confirmed=confirmed
    )
