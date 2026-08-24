"""Git connector: read + write (Market-Viability Roadmap, Phase 1).

Same shape as every other connector in this package -- thin, stateless free
functions plus frozen dataclass results, no instance state -- but backed by
GitPython instead of a hand-rolled ``subprocess.run(["git", ...])`` call
(see the ``GitPython`` dependency comment in ``pyproject.toml`` for why: the
three existing git touchpoints do simple single-command reads that
subprocess handles fine, but write operations have edge cases -- detached
HEAD, partial staging, line-ending normalization -- GitPython already
handles safely).

Like every connector, this module carries no opt-in gate of its own --
gating is the caller's responsibility (``core.git_integration``, checked
against ``Project.git_integration_enabled``), matching the established
convention.

Path safety: every function that takes a caller-suppliable relative path
resolves it against the repository root and refuses to proceed if the
result escapes that root (``_resolve_within`` below). This is a new,
explicit control -- no existing connector before this one has taken a
user-suppliable relative path into a write operation, so there's no prior
precedent to lean on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo


class GitConnectorError(RuntimeError):
    """Base class for every error this module raises."""


class NotAGitRepositoryError(GitConnectorError):
    """Raised when ``project_path`` isn't (inside) a git working tree."""


class PathEscapesRepositoryError(GitConnectorError):
    """Raised when a caller-supplied relative path resolves outside the repo."""


class NothingStagedError(GitConnectorError):
    """Raised by ``commit_staged`` when there is nothing staged to commit."""


class DiscardNotConfirmedError(GitConnectorError):
    """Raised by ``discard_unstaged_changes`` unless called with confirmed=True."""


def _open_repo(project_path: str | Path) -> Repo:
    try:
        return Repo(str(project_path), search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise NotAGitRepositoryError(
            f"{project_path} doesn't look like a git repository -- make sure this folder "
            "(or one of its parent folders) has been initialized with `git init`."
        ) from exc


def _resolve_within(repo: Repo, relative_path: str) -> Path:
    """Resolve ``relative_path`` against the repo's working tree root and
    refuse it if it would land outside that root -- closes off path
    traversal via a crafted ``"../../outside"``-style relative path."""
    root = Path(repo.working_tree_dir).resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise PathEscapesRepositoryError(
            f"'{relative_path}' resolves outside the project folder -- refusing."
        )
    return candidate


def is_git_repo(project_path: str | Path) -> bool:
    """True iff ``project_path`` is (inside) a git working tree. Never raises."""
    try:
        _open_repo(project_path)
    except NotAGitRepositoryError:
        return False
    return True


# --- Read surface -------------------------------------------------------


@dataclass(frozen=True)
class GitStatusResult:
    branch: str | None  # None when HEAD is detached
    is_detached: bool
    ahead: int
    behind: int
    staged: list[str] = field(default_factory=list)
    unstaged: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.staged or self.unstaged or self.untracked)

    @property
    def dirty_count(self) -> int:
        return len(set(self.staged) | set(self.unstaged) | set(self.untracked))


def repo_status(project_path: str | Path) -> GitStatusResult:
    """Current branch, ahead/behind vs. its upstream, and staged/unstaged/
    untracked file lists. Ahead/behind is 0/0 when there's no upstream
    (a local-only branch) rather than raising."""
    repo = _open_repo(project_path)

    is_detached = repo.head.is_detached
    branch = None if is_detached else repo.active_branch.name

    ahead = behind = 0
    if not is_detached:
        tracking = repo.active_branch.tracking_branch()
        if tracking is not None:
            try:
                ahead = sum(1 for _ in repo.iter_commits(f"{tracking.name}..{branch}"))
                behind = sum(1 for _ in repo.iter_commits(f"{branch}..{tracking.name}"))
            except GitCommandError:
                ahead = behind = 0

    staged = repo.index.diff("HEAD") if repo.head.is_valid() else []
    staged_paths = sorted({d.a_path or d.b_path for d in staged if (d.a_path or d.b_path)})
    unstaged = repo.index.diff(None)
    unstaged_paths = sorted({d.a_path or d.b_path for d in unstaged if (d.a_path or d.b_path)})
    untracked_paths = sorted(repo.untracked_files)

    return GitStatusResult(
        branch=branch,
        is_detached=is_detached,
        ahead=ahead,
        behind=behind,
        staged=staged_paths,
        unstaged=unstaged_paths,
        untracked=untracked_paths,
    )


@dataclass(frozen=True)
class GitCommitEntry:
    short_hash: str
    author_name: str
    date_iso: str
    message: str


def file_history(
    project_path: str | Path, relative_path: str, limit: int = 20
) -> list[GitCommitEntry]:
    """Commit history for one file, newest first. ``[]`` if the file has no
    history yet (untracked, or the repo has no commits) -- never raises for
    that case, matching the connector-wide "read paths don't raise" style."""
    repo = _open_repo(project_path)
    target = _resolve_within(repo, relative_path)
    root = Path(repo.working_tree_dir).resolve()
    rel = target.relative_to(root).as_posix()
    try:
        commits = list(repo.iter_commits(paths=rel, max_count=limit))
    except GitCommandError:
        return []
    return [
        GitCommitEntry(
            short_hash=c.hexsha[:7],
            author_name=c.author.name or "",
            date_iso=c.committed_datetime.isoformat(),
            message=c.message.strip().splitlines()[0] if c.message.strip() else "",
        )
        for c in commits
    ]


def diff_for_path(project_path: str | Path, relative_path: str, *, staged: bool = False) -> str:
    """Unified diff text for one file -- feeds ``ui.widgets.diff_viewer.
    DiffViewerDialog`` directly rather than a new diff UI. ``""`` if there's
    no difference to show (or the path is untracked and unstaged, which git
    diff doesn't cover)."""
    repo = _open_repo(project_path)
    target = _resolve_within(repo, relative_path)
    root = Path(repo.working_tree_dir).resolve()
    rel = target.relative_to(root).as_posix()
    args = ["--cached", "--", rel] if staged else ["--", rel]
    try:
        return repo.git.diff(*args)
    except GitCommandError:
        return ""


# --- Write surface -------------------------------------------------------


@dataclass(frozen=True)
class GitStageResult:
    staged: list[str]


def stage_paths(project_path: str | Path, relative_paths: list[str]) -> GitStageResult:
    """Stage one or more files (``git add``). Each path is validated to stay
    inside the repo before reaching GitPython."""
    repo = _open_repo(project_path)
    root = Path(repo.working_tree_dir).resolve()
    rels = []
    for relative_path in relative_paths:
        target = _resolve_within(repo, relative_path)
        rels.append(target.relative_to(root).as_posix())
    if rels:
        repo.index.add(rels)
    return GitStageResult(staged=rels)


@dataclass(frozen=True)
class GitCommitResult:
    short_hash: str
    message: str


def commit_staged(
    project_path: str | Path,
    message: str,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
) -> GitCommitResult:
    """Commit whatever is currently staged. Refuses an empty staged set with
    a typed ``NothingStagedError`` rather than letting GitPython raise a raw
    ``GitCommandError``, and refuses a blank commit message."""
    repo = _open_repo(project_path)
    if not message.strip():
        raise GitConnectorError("Commit message cannot be empty.")

    # An unborn HEAD (brand-new repo, no commits yet) has nothing to diff
    # against -- any index entry at all counts as staged in that case.
    has_staged = bool(repo.index.diff("HEAD")) if repo.head.is_valid() else bool(repo.index.entries)
    if not has_staged:
        raise NothingStagedError(
            "Nothing is staged to commit -- stage at least one file first."
        )

    actor_kwargs = {}
    if author_name or author_email:
        from git import Actor

        actor_kwargs["author"] = Actor(
            author_name or repo.config_reader().get_value("user", "name", "Spiced"),
            author_email or repo.config_reader().get_value("user", "email", "spiced@local"),
        )

    commit = repo.index.commit(message.strip(), **actor_kwargs)
    return GitCommitResult(short_hash=commit.hexsha[:7], message=message.strip())


@dataclass(frozen=True)
class GitDiscardResult:
    discarded: list[str]


def discard_unstaged_changes(
    project_path: str | Path,
    relative_paths: list[str],
    *,
    confirmed: bool = False,
) -> GitDiscardResult:
    """Discard unstaged (working-tree) changes to the given files -- the one
    genuinely destructive operation in this connector. Matches this app's
    existing confirm-before-send pattern (Discord posting): raises
    ``DiscardNotConfirmedError`` unless called with ``confirmed=True``, so a
    caller can never trigger this by accident. The UI gets its own dedicated
    confirmation dialog on top of this -- this check is the connector-level
    backstop, not a replacement for it."""
    if not confirmed:
        raise DiscardNotConfirmedError(
            "discard_unstaged_changes requires confirmed=True -- this permanently discards "
            "uncommitted work."
        )
    repo = _open_repo(project_path)
    root = Path(repo.working_tree_dir).resolve()
    rels = []
    for relative_path in relative_paths:
        target = _resolve_within(repo, relative_path)
        rels.append(target.relative_to(root).as_posix())
    if rels:
        repo.git.checkout("--", *rels)
    return GitDiscardResult(discarded=rels)
