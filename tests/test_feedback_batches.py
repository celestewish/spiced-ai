from spiced.storage.database import Database
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.projects import ProjectRepository


def _repo():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return FeedbackBatchRepository(db), project


def test_create_and_round_trip_json_properties():
    repo, project = _repo()
    batch = repo.create(
        project_id=project.id,
        source_type="paste",
        entry_count=3,
        source_label="Playtest 1",
        raw_excerpt="some excerpt",
        parsed_summary={"entry_count": 3, "confidence": "medium"},
        ai_summary="Players enjoyed movement but got lost.",
        themes=["movement", "navigation"],
        issues=["pause menu bug"],
        action_items=["add signposting"],
        provider="mock",
    )
    assert batch.entry_count == 3
    assert batch.themes == ["movement", "navigation"]
    assert batch.issues == ["pause menu bug"]
    assert batch.action_items == ["add signposting"]
    assert batch.parsed_summary["confidence"] == "medium"


def test_empty_lists_and_none_survive():
    repo, project = _repo()
    batch = repo.create(project_id=project.id, source_type="file", entry_count=0)
    assert batch.themes == []
    assert batch.issues == []
    assert batch.parsed_summary == {}


def test_list_for_project_is_scoped_and_ordered():
    repo, project = _repo()
    repo.create(project_id=project.id, source_type="paste", entry_count=1, source_label="first")
    repo.create(project_id=project.id, source_type="paste", entry_count=1, source_label="second")
    other = ProjectRepository(repo._db).create("Other", engine="Unity")
    repo.create(project_id=other.id, source_type="paste", entry_count=1, source_label="other")

    batches = repo.list_for_project(project.id)
    assert len(batches) == 2
    # Most recent first (created_at DESC, id DESC).
    assert batches[0].source_label == "second"
