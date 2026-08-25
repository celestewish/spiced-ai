"""Tests for Changelog Generation (core.changelog_draft).

``git`` is always mocked via subprocess — these tests never require an
actual git repository on disk or a real AI provider.
"""

from __future__ import annotations

import subprocess

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import CHANGELOG_RULES, build_changelog_prompt
from spiced.core.changelog_draft import (
    ChangelogService,
    NotAGitRepoError,
    ProviderNotReadyError,
)
from spiced.core.regression import RegressionService
from spiced.storage.changelog_drafts import ChangelogDraftRepository
from spiced.storage.database import Database
from spiced.storage.known_issues import SOURCE_TEST, KnownIssueRepository
from spiced.storage.pending_changelog_notes import PendingChangelogNoteRepository
from spiced.storage.projects import ProjectRepository

CANNED = "Here's a draft changelog from your recent history.\n\nHighlights:\n- Added dash."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


class _FakeCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def _service():
    db = Database(":memory:")
    projects_repo = ProjectRepository(db)
    project = projects_repo.create("Moonlit Depths", engine="Unity")
    regression = RegressionService(KnownIssueRepository(db))
    service = ChangelogService(ChangelogDraftRepository(db), regression)
    return service, project, regression, projects_repo


def _service_with_notes():
    """Same as _service(), plus a real PendingChangelogNoteRepository --
    Market-Viability Roadmap, Phase 4's queue_changelog_note action.
    _service() above deliberately omits it, proving queue_note/
    pending_notes stay safe no-ops for a ChangelogService built the older
    way (backward compatible for any existing caller)."""
    db = Database(":memory:")
    projects_repo = ProjectRepository(db)
    project = projects_repo.create("Moonlit Depths", engine="Unity")
    regression = RegressionService(KnownIssueRepository(db))
    notes = PendingChangelogNoteRepository(db)
    service = ChangelogService(ChangelogDraftRepository(db), regression, notes)
    return service, project, notes, projects_repo


def _with_path(projects_repo: ProjectRepository, project, path):
    """Attach a folder path without requiring it to look like a Unity
    project — ChangelogService only cares about ``project.path``."""
    return projects_repo.set_unity_folder(project.id, str(path), "unknown")


def _mock_git(monkeypatch, log_output: str, is_repo: bool = True):
    def fake_run(command, cwd, capture_output, text, timeout):
        if "rev-parse" in command:
            return _FakeCompletedProcess(stdout="true\n" if is_repo else "false\n", returncode=0)
        return _FakeCompletedProcess(stdout=log_output, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)


# --- read_git_log ------------------------------------------------------------


def test_read_git_log_raises_when_project_has_no_path():
    service, project, _regression, _repo = _service()
    with pytest.raises(NotAGitRepoError):
        service.read_git_log(project)


def test_read_git_log_raises_when_not_a_git_repo(monkeypatch, tmp_path):
    service, project, _regression, repo = _service()
    project = _with_path(repo, project, tmp_path)
    _mock_git(monkeypatch, "", is_repo=False)
    with pytest.raises(NotAGitRepoError):
        service.read_git_log(project)


def test_read_git_log_returns_excerpt_and_label(monkeypatch, tmp_path):
    service, project, _regression, repo = _service()
    project = _with_path(repo, project, tmp_path)
    _mock_git(monkeypatch, "abc123 2026-01-01 Fix jump bug\ndef456 2026-01-02 Add dash\n")
    label, excerpt = service.read_git_log(project, commit_count=10)
    assert "10" in label
    assert "Fix jump bug" in excerpt
    assert "Add dash" in excerpt


def test_read_git_log_uses_since_date_when_given(monkeypatch, tmp_path):
    service, project, _regression, repo = _service()
    project = _with_path(repo, project, tmp_path)
    captured = {}

    def fake_run(command, cwd, capture_output, text, timeout):
        if "rev-parse" in command:
            return _FakeCompletedProcess(stdout="true\n")
        captured["command"] = command
        return _FakeCompletedProcess(stdout="abc123 2026-01-05 Fix crash\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    label, excerpt = service.read_git_log(project, since_date="2026-01-01")
    assert "2026-01-01" in label
    assert any("--since=2026-01-01" in part for part in captured["command"])


# --- resolved_issues_since -----------------------------------------------------


def test_resolved_issues_since_filters_by_date():
    service, project, regression, _repo = _service()
    regression.note_issue(project.id, SOURCE_TEST, "sig-old", "Old bug")
    old_issue = regression.list_for_project(project.id)[0]
    regression.mark_resolved(old_issue.id)

    regression.note_issue(project.id, SOURCE_TEST, "sig-new", "New bug")
    new_issue = [i for i in regression.list_for_project(project.id) if i.title == "New bug"][0]
    regression.mark_resolved(new_issue.id)

    # Both got resolved "now" in this in-memory test, so no filter includes
    # both, and a far-future date excludes both.
    assert set(service.resolved_issues_since(project.id, None)) == {"Old bug", "New bug"}
    assert service.resolved_issues_since(project.id, "2099-01-01") == []


def test_resolved_issues_since_returns_empty_without_regression_service():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths")
    service = ChangelogService(ChangelogDraftRepository(db), regression=None)
    assert service.resolved_issues_since(project.id, None) == []


# --- draft ---------------------------------------------------------------------


def test_draft_raises_when_provider_unavailable(tmp_path):
    service, project, _regression, repo = _service()
    project = _with_path(repo, project, tmp_path)
    with pytest.raises(ProviderNotReadyError):
        service.draft(FakeProvider(available=False), project)


def test_draft_saves_a_changelog_draft(monkeypatch, tmp_path):
    service, project, _regression, repo = _service()
    project = _with_path(repo, project, tmp_path)
    _mock_git(monkeypatch, "abc123 2026-01-01 Fix jump bug\n")

    usage = []
    result = service.draft(FakeProvider(), project, record_usage=usage.append)

    assert result.response_text == CANNED
    assert result.draft.ai_draft_text == CANNED
    assert result.draft.project_id == project.id
    assert usage == ["fake"]
    assert service.history(project.id)[0].id == result.draft.id


def test_draft_raises_not_a_git_repo_error_and_does_not_call_provider():
    service, project, _regression, _repo = _service()

    class ExplodingProvider(AIProvider):
        name = "boom"

        def is_available(self):
            return True

        def generate(self, prompt):
            raise AssertionError("should not be called when the project isn't a git repo")

    with pytest.raises(NotAGitRepoError):
        service.draft(ExplodingProvider(), project)


def test_save_edit_updates_display_text():
    service, project, _regression, _repo = _service()
    draft = service._drafts.create(project_id=project.id, ai_draft_text="original")
    assert draft.display_text == "original"
    updated = service.save_edit(draft.id, "edited version")
    assert updated.display_text == "edited version"


# --- prompt content -------------------------------------------------------------


# --- pending notes (Market-Viability Roadmap, Phase 4's
# queue_changelog_note rules-engine action) ---------------------------------


def test_queue_note_and_pending_notes_without_repository_is_a_safe_no_op():
    service, _project, _regression, _repo = _service()
    assert service.queue_note(1, "some note") is None
    assert service.pending_notes(1) == []


def test_queue_note_and_pending_notes_round_trip():
    service, project, notes, _repo = _service_with_notes()
    service.queue_note(project.id, "flagged by Palette Drift Detection", "art.palette_drift")

    pending = service.pending_notes(project.id)

    assert [n.note_text for n in pending] == ["flagged by Palette Drift Detection"]
    assert notes.list_pending(project.id) == pending


def test_draft_incorporates_and_consumes_pending_notes(monkeypatch, tmp_path):
    service, project, notes, projects_repo = _service_with_notes()
    project = _with_path(projects_repo, project, tmp_path)
    _mock_git(monkeypatch, "abc123 2026-01-01 Fix jump bug\n")
    note = service.queue_note(
        project.id, "flagged by Palette Drift Detection", "art.palette_drift"
    )

    captured_prompts = []
    real_build = build_changelog_prompt

    def _spy_build(**kwargs):
        prompt = real_build(**kwargs)
        captured_prompts.append(prompt)
        return prompt

    monkeypatch.setattr("spiced.core.changelog_draft.build_changelog_prompt", _spy_build)

    service.draft(FakeProvider(), project)

    assert "flagged by Palette Drift Detection" in captured_prompts[0]
    # The note is consumed once a draft incorporates it -- not still pending.
    assert service.pending_notes(project.id) == []
    assert notes.get(note.id).consumed_at is not None


def test_draft_with_no_pending_notes_omits_the_notes_section(monkeypatch, tmp_path):
    service, project, _notes, projects_repo = _service_with_notes()
    project = _with_path(projects_repo, project, tmp_path)
    _mock_git(monkeypatch, "abc123 2026-01-01 Fix jump bug\n")

    captured_prompts = []
    real_build = build_changelog_prompt

    def _spy_build(**kwargs):
        prompt = real_build(**kwargs)
        captured_prompts.append(prompt)
        return prompt

    monkeypatch.setattr("spiced.core.changelog_draft.build_changelog_prompt", _spy_build)
    service.draft(FakeProvider(), project)

    assert "Other things Spiced flagged" not in captured_prompts[0]


def test_changelog_prompt_includes_rules_and_evidence():
    prompt = build_changelog_prompt(
        git_log_excerpt="abc123 2026-01-01 Fix jump bug",
        commit_range="last 40 commit(s)",
        resolved_issue_titles=["Crash on level load"],
        project_name="Moonlit Depths",
    )
    for rule in CHANGELOG_RULES:
        assert rule in prompt
    assert "Fix jump bug" in prompt
    assert "Crash on level load" in prompt
    assert "Moonlit Depths" in prompt
