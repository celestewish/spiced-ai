"""Tests for core.git_integration: the opt-in gate in front of
connectors.git_connector.

Uses a real Project (via ProjectRepository against an in-memory Database)
and a real throwaway git repo, same convention as the rest of this app's
tests -- no mocks.
"""

from __future__ import annotations

import subprocess

import pytest

from spiced.core.git_integration import (
    GitIntegrationNotEnabledError,
    commit_staged,
    discard_unstaged_changes,
    repo_status,
    stage_paths,
)
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _git(*args: str, cwd) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _make_repo(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    _git("add", "a.txt", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    return _make_repo(tmp_path)


@pytest.fixture
def repository():
    return ProjectRepository(Database(":memory:"))


def _project_with_path(repository, path, *, git_enabled: bool):
    project = repository.create("Test Project", engine="Unity", path=str(path))
    return repository.set_git_integration_settings(project.id, git_enabled)


def test_repo_status_raises_when_not_enabled(repository, repo):
    project = _project_with_path(repository, repo, git_enabled=False)
    with pytest.raises(GitIntegrationNotEnabledError):
        repo_status(project)


def test_repo_status_raises_when_enabled_but_no_folder(repository):
    project = repository.create("No Folder", engine="Unity", path=None)
    project = repository.set_git_integration_settings(project.id, True)
    with pytest.raises(GitIntegrationNotEnabledError):
        repo_status(project)


def test_repo_status_works_when_enabled(repository, repo):
    project = _project_with_path(repository, repo, git_enabled=True)
    status = repo_status(project)
    assert status.is_clean is True


def test_stage_and_commit_via_gate(repository, repo):
    project = _project_with_path(repository, repo, git_enabled=True)
    (repo / "new.txt").write_text("new", encoding="utf-8")

    stage_paths(project, ["new.txt"])
    result = commit_staged(project, "add new.txt")

    assert result.message == "add new.txt"
    assert repo_status(project).is_clean is True


def test_discard_via_gate_requires_confirmation(repository, repo):
    project = _project_with_path(repository, repo, git_enabled=True)
    (repo / "a.txt").write_text("changed", encoding="utf-8")

    from spiced.connectors.git_connector import DiscardNotConfirmedError

    with pytest.raises(DiscardNotConfirmedError):
        discard_unstaged_changes(project, ["a.txt"])

    result = discard_unstaged_changes(project, ["a.txt"], confirmed=True)
    assert result.discarded == ["a.txt"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "hello"


def test_disabled_gate_prevents_writes_even_with_confirmation(repository, repo):
    """The opt-in gate must be checked before the write happens -- an
    unconfirmed write attempt on a disabled project must not touch the repo
    at all, regardless of ``confirmed``."""
    project = _project_with_path(repository, repo, git_enabled=False)
    (repo / "a.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(GitIntegrationNotEnabledError):
        discard_unstaged_changes(project, ["a.txt"], confirmed=True)

    assert (repo / "a.txt").read_text(encoding="utf-8") == "changed"
