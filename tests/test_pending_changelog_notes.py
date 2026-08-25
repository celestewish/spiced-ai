"""Tests for storage.pending_changelog_notes.PendingChangelogNoteRepository."""

from __future__ import annotations

import pytest

from spiced.storage.database import Database
from spiced.storage.pending_changelog_notes import PendingChangelogNoteRepository


def _repo() -> PendingChangelogNoteRepository:
    return PendingChangelogNoteRepository(Database(":memory:"))


def test_queue_and_get():
    repo = _repo()
    note = repo.queue(1, "flagged by Palette Drift Detection", "art.palette_drift")
    assert note.project_id == 1
    assert note.note_text == "flagged by Palette Drift Detection"
    assert note.source_event_kind == "art.palette_drift"
    assert note.consumed_at is None
    assert repo.get(note.id) == note


def test_queue_without_source_event_kind():
    repo = _repo()
    note = repo.queue(1, "manual note")
    assert note.source_event_kind is None


def test_list_pending_only_returns_unconsumed_for_the_right_project():
    repo = _repo()
    a = repo.queue(1, "note a")
    repo.queue(2, "note for a different project")
    b = repo.queue(1, "note b")

    pending = repo.list_pending(1)

    assert [n.id for n in pending] == [a.id, b.id]  # oldest first


def test_mark_consumed_removes_from_pending_list():
    repo = _repo()
    a = repo.queue(1, "note a")
    b = repo.queue(1, "note b")

    repo.mark_consumed([a.id])

    pending = repo.list_pending(1)
    assert [n.id for n in pending] == [b.id]
    assert repo.get(a.id).consumed_at is not None


def test_mark_consumed_with_empty_list_is_a_no_op():
    repo = _repo()
    repo.queue(1, "note a")
    repo.mark_consumed([])
    assert len(repo.list_pending(1)) == 1


def test_get_raises_for_missing_id():
    repo = _repo()
    with pytest.raises(KeyError):
        repo.get(9999)
