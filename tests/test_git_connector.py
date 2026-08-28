"""Tests for connectors.git_connector: read + write git operations.

Uses a real throwaway git repo per test (via ``_git``/``_make_repo``), same
convention as test_precommit_hook.py -- no mocked filesystem or faked
``.git`` directory.
"""

from __future__ import annotations

import subprocess

import pytest

from spiced.connectors.git_connector import (
    DiscardNotConfirmedError,
    GitConnectorError,
    NotAGitRepositoryError,
    NothingStagedError,
    PathEscapesRepositoryError,
    commit_staged,
    diff_for_path,
    discard_unstaged_changes,
    file_history,
    is_git_repo,
    repo_status,
    stage_paths,
)


def _git(*args: str, cwd) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _make_repo(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    return tmp_path


def _commit_file(repo_path, name: str, content: str, message: str) -> None:
    (repo_path / name).write_text(content, encoding="utf-8")
    _git("add", name, cwd=repo_path)
    _git("commit", "-q", "-m", message, cwd=repo_path)


# --- is_git_repo / not-a-repo errors -----------------------------------------


def test_is_git_repo_false_for_plain_folder(tmp_path):
    assert is_git_repo(tmp_path) is False


def test_is_git_repo_true_for_real_repo(tmp_path):
    _make_repo(tmp_path)
    assert is_git_repo(tmp_path) is True


def test_repo_status_raises_not_a_git_repository_error(tmp_path):
    with pytest.raises(NotAGitRepositoryError):
        repo_status(tmp_path)


# --- repo_status --------------------------------------------------------


def test_repo_status_on_fresh_repo_with_one_commit(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")

    status = repo_status(repo)

    assert status.is_detached is False
    assert status.branch in ("main", "master")  # depends on the host's git default
    assert status.is_clean is True
    assert status.staged == []
    assert status.unstaged == []
    assert status.untracked == []


def test_repo_status_reports_untracked_files(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")
    (repo / "new.txt").write_text("new", encoding="utf-8")

    status = repo_status(repo)

    assert status.untracked == ["new.txt"]
    assert status.is_clean is False
    assert status.dirty_count == 1


def test_repo_status_reports_unstaged_modification(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")
    (repo / "a.txt").write_text("changed", encoding="utf-8")

    status = repo_status(repo)

    assert status.unstaged == ["a.txt"]
    assert status.staged == []


def test_repo_status_reports_staged_change(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    _git("add", "a.txt", cwd=repo)

    status = repo_status(repo)

    assert status.staged == ["a.txt"]
    assert status.unstaged == []


def test_repo_status_reports_multiple_staged_changes(tmp_path):
    """Regression test: repo_status must not try to sort GitPython Diff
    objects directly (they don't support ordering) -- it needs at least two
    staged files to exercise that path at all."""
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    (repo / "b.txt").write_text("new", encoding="utf-8")
    _git("add", "a.txt", "b.txt", cwd=repo)

    status = repo_status(repo)

    assert status.staged == ["a.txt", "b.txt"]


# --- file_history / diff_for_path ----------------------------------------


def test_file_history_returns_commits_newest_first(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")
    _commit_file(repo, "a.txt", "v2", "second")

    entries = file_history(repo, "a.txt")

    assert [e.message for e in entries] == ["second", "first"]
    assert all(len(e.short_hash) == 7 for e in entries)


def test_file_history_empty_for_untracked_file(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")
    (repo / "new.txt").write_text("new", encoding="utf-8")

    assert file_history(repo, "new.txt") == []


def test_file_history_rejects_path_escaping_repo(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")

    with pytest.raises(PathEscapesRepositoryError):
        file_history(repo, "../../outside.txt")


def test_diff_for_path_shows_unstaged_change(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello\n", "init")
    (repo / "a.txt").write_text("goodbye\n", encoding="utf-8")

    diff = diff_for_path(repo, "a.txt")

    assert "hello" in diff
    assert "goodbye" in diff


def test_diff_for_path_staged_only_shows_staged_diff(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello\n", "init")
    (repo / "a.txt").write_text("goodbye\n", encoding="utf-8")

    assert diff_for_path(repo, "a.txt", staged=True) == ""
    _git("add", "a.txt", cwd=repo)
    assert "goodbye" in diff_for_path(repo, "a.txt", staged=True)


def test_diff_for_path_rejects_path_escaping_repo(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")

    with pytest.raises(PathEscapesRepositoryError):
        diff_for_path(repo, "../../outside.txt")


# --- stage_paths / commit_staged -----------------------------------------


def test_stage_paths_stages_untracked_file(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")
    (repo / "new.txt").write_text("new", encoding="utf-8")

    result = stage_paths(repo, ["new.txt"])

    assert result.staged == ["new.txt"]
    assert repo_status(repo).staged == ["new.txt"]
    assert repo_status(repo).untracked == []


def test_stage_paths_rejects_path_escaping_repo(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")

    with pytest.raises(PathEscapesRepositoryError):
        stage_paths(repo, ["../../outside.txt"])


def test_commit_staged_round_trip(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")
    (repo / "new.txt").write_text("new", encoding="utf-8")
    stage_paths(repo, ["new.txt"])

    result = commit_staged(repo, "add new.txt")

    assert result.message == "add new.txt"
    assert len(result.short_hash) == 7
    assert repo_status(repo).is_clean is True

    entries = file_history(repo, "new.txt")
    assert entries[0].message == "add new.txt"


def test_commit_staged_raises_when_nothing_staged(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")

    with pytest.raises(NothingStagedError):
        commit_staged(repo, "nothing to commit")


def test_commit_staged_raises_on_blank_message(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")
    (repo / "new.txt").write_text("new", encoding="utf-8")
    stage_paths(repo, ["new.txt"])

    with pytest.raises(GitConnectorError):
        commit_staged(repo, "   ")


def test_commit_staged_works_on_brand_new_repo_with_no_prior_commits(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "a.txt").write_text("hello", encoding="utf-8")
    stage_paths(repo, ["a.txt"])

    result = commit_staged(repo, "first commit")

    assert result.message == "first commit"


# --- discard_unstaged_changes ---------------------------------------------


def test_discard_unstaged_changes_raises_without_confirmation(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")
    (repo / "a.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(DiscardNotConfirmedError):
        discard_unstaged_changes(repo, ["a.txt"])

    # Must be left untouched -- the raise happens before anything runs.
    assert (repo / "a.txt").read_text(encoding="utf-8") == "changed"


def test_discard_unstaged_changes_reverts_file_when_confirmed(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "hello", "init")
    (repo / "a.txt").write_text("changed", encoding="utf-8")

    result = discard_unstaged_changes(repo, ["a.txt"], confirmed=True)

    assert result.discarded == ["a.txt"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "hello"


def test_discard_unstaged_changes_rejects_path_escaping_repo_even_when_confirmed(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_file(repo, "a.txt", "v1", "first")

    with pytest.raises(PathEscapesRepositoryError):
        discard_unstaged_changes(repo, ["../../outside.txt"], confirmed=True)
