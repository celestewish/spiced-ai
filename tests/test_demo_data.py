"""Demo-data seeding tests.

These exercise the real Services composition root against an in-memory database
so the DemoDataService, repositories, and dashboard are covered end to end. The
key promises: seeding populates every module, it is repeat-safe, it never
touches projects the developer created, and resetting only refreshes the demo.
"""

from spiced.app.services import Services
from spiced.core.dashboard import NEEDS_REVIEW
from spiced.core.demo_data import DEMO_PROJECT_NAME


def _services() -> Services:
    return Services(":memory:")


def test_seed_populates_every_module() -> None:
    svc = _services()
    project = svc.load_demo_project()

    assert project.name == DEMO_PROJECT_NAME
    assert project.is_valid_unity
    assert svc.active_project().id == project.id

    sessions = svc.debugging.history(project.id)
    assert len(sessions) == 1
    assert sessions[0].detected_error_type == "NullReferenceException"
    assert sessions[0].detected_file == "HealthPickup.cs"
    assert sessions[0].detected_line == 24

    cases = svc.testing.list_cases(project.id)
    assert len(cases) == 6
    statuses = {c.status for c in cases}
    assert {"Pass", "Fail", "Blocked", "Not Run"} <= statuses

    runs = svc.testing.history(project.id)
    assert len(runs) == 1
    summary = runs[0].parsed_summary
    assert (summary["total"], summary["passed"], summary["failed"], summary["skipped"]) == (
        5,
        2,
        2,
        1,
    )

    batches = svc.feedback.history(project.id)
    assert len(batches) == 1
    assert batches[0].entry_count == 6
    assert batches[0].parsed_summary.get("category_counts")

    svc.close()


def test_seed_is_repeat_safe() -> None:
    svc = _services()
    first = svc.load_demo_project()
    second = svc.load_demo_project()

    assert first.id == second.id
    assert len(svc.projects.list_projects()) == 1
    # No duplicated child rows.
    assert len(svc.debugging.history(first.id)) == 1
    assert len(svc.testing.list_cases(first.id)) == 6
    assert len(svc.testing.history(first.id)) == 1
    assert len(svc.feedback.history(first.id)) == 1

    svc.close()


def test_seed_never_touches_real_projects() -> None:
    svc = _services()
    real = svc.projects.create_project(name="My Real Game", engine="Unity")
    svc.testing.create_case(
        project_id=real.id, title="Real case", category="General", priority="Medium"
    )

    svc.load_demo_project(fresh=True)

    still_there = svc.projects.get_project(real.id)
    assert still_there.name == "My Real Game"
    assert len(svc.testing.list_cases(real.id)) == 1
    # Exactly two projects: the developer's and the demo.
    assert len(svc.projects.list_projects()) == 2

    svc.close()


def test_load_fresh_demo_resets_only_the_demo() -> None:
    svc = _services()
    project = svc.load_demo_project()
    # Add an extra case to the demo; a fresh load should discard it.
    svc.testing.create_case(
        project_id=project.id, title="Extra", category="General", priority="Low"
    )
    assert len(svc.testing.list_cases(project.id)) == 7

    refreshed = svc.load_demo_project(fresh=True)
    assert len(svc.projects.list_projects()) == 1
    assert len(svc.testing.list_cases(refreshed.id)) == 6

    svc.close()


def test_dashboard_reads_demo_as_needs_review() -> None:
    svc = _services()
    project = svc.load_demo_project()
    summary = svc.dashboard.summarize(project)

    assert summary is not None
    assert summary.readiness.label == NEEDS_REVIEW

    svc.close()


def test_onboarding_seen_flag_defaults_false_then_persists() -> None:
    svc = _services()
    assert svc.has_seen_onboarding() is False
    svc.mark_onboarding_seen()
    assert svc.has_seen_onboarding() is True

    svc.close()
