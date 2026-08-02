from spiced.core.regression import (
    MATCH_EXACT,
    MATCH_SIMILAR,
    RegressionService,
    debug_signature,
    failure_signature,
)
from spiced.storage.database import Database
from spiced.storage.known_issues import SOURCE_DEBUG, SOURCE_TEST, KnownIssueRepository
from spiced.storage.projects import ProjectRepository


def _service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths", engine="Unity")
    return RegressionService(KnownIssueRepository(db)), project, projects


def test_signatures_are_normalized():
    assert debug_signature("NullReferenceException", "HealthPickup.cs") == debug_signature(
        "  nullreferenceexception  ", "HealthPickup.CS"
    )
    assert failure_signature("Player takes damage!") == failure_signature("player takes damage")


def test_first_occurrence_has_no_match():
    service, project, _projects = _service()
    outcome = service.note_issue(
        project.id, SOURCE_DEBUG, debug_signature("NullReferenceException", "HealthPickup.cs"),
        "NullReferenceException in HealthPickup.cs",
    )
    assert outcome.match is None
    assert outcome.issue.occurrences == 1
    assert outcome.issue.status == "open"


_NULL_REF_TITLE = "NullReferenceException in HealthPickup.cs"


def test_exact_repeat_is_flagged_and_counted():
    service, project, _projects = _service()
    sig = debug_signature("NullReferenceException", "HealthPickup.cs")
    service.note_issue(project.id, SOURCE_DEBUG, sig, _NULL_REF_TITLE)
    outcome = service.note_issue(project.id, SOURCE_DEBUG, sig, _NULL_REF_TITLE)
    assert outcome.match is not None
    assert outcome.match.kind == MATCH_EXACT
    assert outcome.issue.occurrences == 2


def test_resolved_issue_recurring_notes_regression_in_message():
    service, project, _projects = _service()
    sig = debug_signature("NullReferenceException", "HealthPickup.cs")
    first = service.note_issue(project.id, SOURCE_DEBUG, sig, _NULL_REF_TITLE)
    service.mark_resolved(first.issue.id)
    outcome = service.note_issue(project.id, SOURCE_DEBUG, sig, _NULL_REF_TITLE)
    assert outcome.match is not None
    assert "resolved" in outcome.match.note.lower()
    assert "regression" in outcome.match.note.lower()
    # Marking resolved doesn't get silently overwritten by a later occurrence.
    assert outcome.issue.status == "resolved"


def test_fuzzy_match_on_similar_test_failure_names():
    service, project, _projects = _service()
    service.note_issue(
        project.id, SOURCE_TEST, failure_signature("Player takes damage from spikes"),
        "Player takes damage from spikes",
    )
    outcome = service.note_issue(
        project.id, SOURCE_TEST, failure_signature("Player takes damage from spikes near lava"),
        "Player takes damage from spikes near lava",
    )
    assert outcome.match is not None
    assert outcome.match.kind == MATCH_SIMILAR


def test_unrelated_failures_do_not_match():
    service, project, _projects = _service()
    service.note_issue(
        project.id,
        SOURCE_TEST,
        failure_signature("Save file fails to load"),
        "Save file fails to load",
    )
    outcome = service.note_issue(
        project.id, SOURCE_TEST, failure_signature("Jump feels floaty"), "Jump feels floaty"
    )
    assert outcome.match is None


def test_mark_resolved_and_reopen_round_trip():
    service, project, _projects = _service()
    outcome = service.note_issue(project.id, SOURCE_TEST, failure_signature("X"), "X")
    resolved = service.mark_resolved(outcome.issue.id)
    assert resolved.status == "resolved"
    reopened = service.mark_open(outcome.issue.id)
    assert reopened.status == "open"


def test_list_for_project_is_scoped():
    service, project, projects = _service()
    other_project = projects.create("Other", engine="Unity")
    service.note_issue(project.id, SOURCE_TEST, failure_signature("A"), "A")
    assert len(service.list_for_project(project.id)) == 1
    assert service.list_for_project(other_project.id) == []
