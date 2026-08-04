import pytest

from spiced.storage.build_reports import TRIGGER_MANUAL, TRIGGER_SCHEDULED, BuildReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _repo_and_project():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return BuildReportRepository(db), project


def test_create_and_get():
    repo, project = _repo_and_project()
    report = repo.create(
        project_id=project.id,
        trigger=TRIGGER_MANUAL,
        started_at="2026-01-01 00:00:00",
        finished_at="2026-01-01 00:05:00",
        target_platform="StandaloneWindows64",
        succeeded=True,
        log_tail="all good",
        output_path=r"C:\proj\Builds\SpicedBuild.exe",
    )
    fetched = repo.get(report.id)
    assert fetched.succeeded is True
    assert fetched.trigger == TRIGGER_MANUAL
    assert fetched.marked_stable is False


def test_get_missing_raises():
    repo, _ = _repo_and_project()
    with pytest.raises(KeyError):
        repo.get(999)


def test_list_for_project_newest_first():
    repo, project = _repo_and_project()
    repo.create(project_id=project.id, trigger=TRIGGER_MANUAL, started_at="2026-01-01 00:00:00")
    repo.create(
        project_id=project.id, trigger=TRIGGER_SCHEDULED, started_at="2026-01-02 00:00:00"
    )
    reports = repo.list_for_project(project.id)
    assert [r.trigger for r in reports] == [TRIGGER_SCHEDULED, TRIGGER_MANUAL]


def test_latest_for_project_returns_none_when_empty():
    repo, project = _repo_and_project()
    assert repo.latest_for_project(project.id) is None


def test_latest_for_project_returns_most_recent():
    repo, project = _repo_and_project()
    repo.create(project_id=project.id, trigger=TRIGGER_MANUAL, started_at="2026-01-01 00:00:00")
    second = repo.create(
        project_id=project.id, trigger=TRIGGER_SCHEDULED, started_at="2026-01-02 00:00:00"
    )
    assert repo.latest_for_project(project.id).id == second.id


def test_mark_stable_sets_flag_and_clears_previous():
    repo, project = _repo_and_project()
    first = repo.create(
        project_id=project.id,
        trigger=TRIGGER_MANUAL,
        started_at="2026-01-01 00:00:00",
        succeeded=True,
    )
    second = repo.create(
        project_id=project.id,
        trigger=TRIGGER_MANUAL,
        started_at="2026-01-02 00:00:00",
        succeeded=True,
    )
    repo.mark_stable(first.id)
    assert repo.get(first.id).marked_stable is True
    assert repo.latest_stable_for_project(project.id).id == first.id

    repo.mark_stable(second.id)
    assert repo.get(first.id).marked_stable is False
    assert repo.get(second.id).marked_stable is True
    assert repo.latest_stable_for_project(project.id).id == second.id


def test_latest_stable_for_project_returns_none_when_nothing_marked():
    repo, project = _repo_and_project()
    repo.create(project_id=project.id, trigger=TRIGGER_MANUAL, started_at="2026-01-01 00:00:00")
    assert repo.latest_stable_for_project(project.id) is None


def test_succeeded_none_when_build_still_in_progress():
    repo, project = _repo_and_project()
    report = repo.create(
        project_id=project.id, trigger=TRIGGER_MANUAL, started_at="2026-01-01 00:00:00"
    )
    assert report.succeeded is None
