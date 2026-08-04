"""Changelog Generation use-case.

Reads ``git log`` for the *user's game project* (never Spiced's own repo) —
read-only, ``cwd=project.path`` — combines it with locally-resolved
``known_issues`` in the same window, and drafts patch notes via the AI
provider. The developer reviews/edits the draft in the UI before copying it
anywhere; Spiced never publishes it. Distinct from the Roadmap's changelog
(Phase C), which is about Spiced's own release notes, not the developer's game.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_changelog_prompt
from spiced.core.regression import RegressionService
from spiced.storage.changelog_drafts import ChangelogDraft, ChangelogDraftRepository
from spiced.storage.known_issues import STATUS_RESOLVED
from spiced.storage.projects import Project

DEFAULT_COMMIT_COUNT = 40
GIT_TIMEOUT_S = 15
MAX_LOG_CHARS = 4000


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NotAGitRepoError(RuntimeError):
    """Raised when the project has no folder, or its folder isn't a git repo."""


@dataclass(frozen=True)
class ChangelogSource:
    commit_range: str
    git_log_excerpt: str
    resolved_issue_titles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChangelogResult:
    source: ChangelogSource
    response_text: str
    provider: str
    draft: ChangelogDraft


class ChangelogService:
    def __init__(
        self, drafts: ChangelogDraftRepository, regression: RegressionService | None = None
    ) -> None:
        self._drafts = drafts
        self._regression = regression

    def read_git_log(
        self,
        project: Project,
        commit_count: int = DEFAULT_COMMIT_COUNT,
        since_date: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(commit_range_label, log_excerpt)`` for ``project``'s own
        git history. Read-only (``git log``/``git rev-parse`` with
        ``cwd=project.path``) — never writes anything. Raises
        ``NotAGitRepoError`` if the project has no folder, git isn't
        available, or the folder isn't inside a git repository, so callers
        can show a clear, friendly message instead of crashing.
        """
        if not project.path:
            raise NotAGitRepoError(
                "This project has no connected folder yet — connect one on the Projects screen."
            )
        try:
            check = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=project.path,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise NotAGitRepoError(
                "Could not run git for this project's folder — make sure git is installed "
                "and on your PATH."
            ) from None
        if check.returncode != 0 or check.stdout.strip() != "true":
            raise NotAGitRepoError(
                f'"{project.path}" does not look like a git repository. Changelog drafting '
                "reads your game project's own git log, so it needs one."
            )

        command = ["git", "log", "--pretty=format:%h %ad %s", "--date=short"]
        if since_date:
            command.append(f"--since={since_date}")
            label = f"commits since {since_date}"
        else:
            command.append(f"-n{commit_count}")
            label = f"last {commit_count} commit(s)"
        try:
            result = subprocess.run(
                command, cwd=project.path, capture_output=True, text=True, timeout=GIT_TIMEOUT_S
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotAGitRepoError(f"Could not read git log: {exc}") from None

        log_text = (result.stdout or "").strip()
        return label, log_text[:MAX_LOG_CHARS]

    def resolved_issues_since(self, project_id: int, since_date: str | None) -> list[str]:
        """Titles of known issues resolved on/after ``since_date`` (or ever,
        if no date is given). Purely local — no AI, no network."""
        if self._regression is None:
            return []
        titles = []
        for issue in self._regression.list_for_project(project_id):
            if issue.status != STATUS_RESOLVED:
                continue
            if since_date and issue.resolved_at and issue.resolved_at < since_date:
                continue
            titles.append(issue.title)
        return titles

    def draft(
        self,
        provider: AIProvider,
        project: Project,
        *,
        commit_count: int = DEFAULT_COMMIT_COUNT,
        since_date: str | None = None,
        record_usage=None,
    ) -> ChangelogResult:
        """Read git history + resolved issues, ask the provider to draft
        patch notes, and save the draft. Raises ``NotAGitRepoError`` if the
        project's folder isn't a git repo, and ``ProviderNotReadyError`` if
        the provider has no usable credentials.
        """
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )

        commit_range, log_excerpt = self.read_git_log(
            project, commit_count=commit_count, since_date=since_date
        )
        resolved_titles = self.resolved_issues_since(project.id, since_date)

        prompt = build_changelog_prompt(
            git_log_excerpt=log_excerpt,
            commit_range=commit_range,
            resolved_issue_titles=resolved_titles,
            project_name=project.name,
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        draft = self._drafts.create(
            project_id=project.id,
            source_commit_range=commit_range,
            raw_git_log_excerpt=log_excerpt or None,
            ai_draft_text=response.text,
            provider=response.provider,
        )
        return ChangelogResult(
            source=ChangelogSource(
                commit_range=commit_range,
                git_log_excerpt=log_excerpt,
                resolved_issue_titles=resolved_titles,
            ),
            response_text=response.text,
            provider=response.provider,
            draft=draft,
        )

    def save_edit(self, draft_id: int, edited_text: str) -> ChangelogDraft:
        """Save the developer's edited version. Never sent anywhere by
        Spiced — just persisted so ``ChangelogDraft.display_text`` prefers
        it over the raw AI draft next time it's shown."""
        return self._drafts.set_edited_text(draft_id, edited_text)

    def history(self, project_id: int, limit: int = 20) -> list[ChangelogDraft]:
        return self._drafts.list_for_project(project_id, limit=limit)
