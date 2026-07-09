"""Recommended-next-action and missing-data guidance tests.

``build_next_actions`` turns stored evidence into a human-approved review queue.
It never executes anything — it only suggests, ordered by priority. These tests
use lightweight fakes for the stored records so behavior is pinned precisely.
"""

from dataclasses import dataclass

from spiced.core.dashboard import (
    MODULE_DEBUGGING,
    MODULE_FEEDBACK,
    MODULE_TESTING,
    PRIORITY_HIGH,
    PRIORITY_MEDIUM,
    _missing_data,
    build_next_actions,
)


@dataclass
class _FakeSession:
    id: int = 1
    detected_error_type: str | None = None
    detected_file: str | None = None
    detected_line: int | None = None


@dataclass
class _FakeCase:
    id: int
    title: str
    status: str
    failure_note: str | None = None


@dataclass
class _FakeRun:
    id: int
    parsed_summary: dict


@dataclass
class _FakeBatch:
    id: int = 1


@dataclass
class _FakeProject:
    path: str | None = None
    is_valid_unity: bool = False


def test_failed_run_creates_high_priority_testing_actions():
    run = _FakeRun(7, {"failures": ["Player takes damage", "Door opens", "Score saves"]})
    actions = build_next_actions([], [], run, [], {})
    assert len(actions) == 3
    assert all(a.source_module == MODULE_TESTING for a in actions)
    assert all(a.priority == PRIORITY_HIGH for a in actions)
    assert all(a.related_id == 7 for a in actions)
    assert "Player takes damage" in actions[0].title


def test_only_first_three_failures_become_actions():
    run = _FakeRun(1, {"failures": [f"t{i}" for i in range(10)]})
    actions = build_next_actions([], [], run, [], {})
    assert len(actions) == 3


def test_failing_and_blocked_cases_create_actions():
    cases = [
        _FakeCase(1, "Jump works", "Fail", failure_note="Jump does nothing"),
        _FakeCase(2, "Load save", "Blocked"),
        _FakeCase(3, "Menu opens", "Pass"),
    ]
    actions = build_next_actions([], cases, None, [], {})
    fail_action = next(a for a in actions if "Jump works" in a.title)
    blocked_action = next(a for a in actions if "Load save" in a.title)
    assert fail_action.priority == PRIORITY_HIGH
    assert fail_action.reason == "Jump does nothing"
    assert blocked_action.priority == PRIORITY_MEDIUM
    # A passing case does not generate an action.
    assert not any("Menu opens" in a.title for a in actions)


def test_debug_error_creates_single_high_priority_action():
    sessions = [
        _FakeSession(1, "NullReferenceException", "HealthPickup.cs", 24),
        _FakeSession(2, "IndexOutOfRangeException", "Inventory.cs", 8),
    ]
    actions = build_next_actions(sessions, [], None, [], {})
    debug_actions = [a for a in actions if a.source_module == MODULE_DEBUGGING]
    # Only one debugging action to avoid noise.
    assert len(debug_actions) == 1
    assert "HealthPickup.cs:24" in debug_actions[0].title
    assert debug_actions[0].priority == PRIORITY_HIGH
    assert debug_actions[0].related_id == 1


def test_bug_feedback_creates_high_priority_feedback_action():
    actions = build_next_actions(
        [], [], None, [_FakeBatch(5)], {"Bug or technical issue": 2, "Performance concern": 1}
    )
    feedback_actions = [a for a in actions if a.source_module == MODULE_FEEDBACK]
    assert len(feedback_actions) == 1
    assert feedback_actions[0].priority == PRIORITY_HIGH
    assert feedback_actions[0].related_id == 5


def test_confusion_feedback_creates_medium_priority_action():
    actions = build_next_actions(
        [], [], None, [_FakeBatch(9)], {"Confusion or onboarding issue": 3}
    )
    feedback_actions = [a for a in actions if a.source_module == MODULE_FEEDBACK]
    assert len(feedback_actions) == 1
    assert feedback_actions[0].priority == PRIORITY_MEDIUM


def test_actions_are_sorted_by_priority_and_capped():
    run = _FakeRun(1, {"failures": [f"t{i}" for i in range(3)]})  # 3 High
    cases = [_FakeCase(i, f"case{i}", "Blocked") for i in range(10)]  # many Medium
    actions = build_next_actions([], cases, run, [], {})
    assert len(actions) <= 8
    priorities = [a.priority for a in actions]
    # High-priority actions come first.
    assert priorities[0] == PRIORITY_HIGH
    high_index = [i for i, p in enumerate(priorities) if p == PRIORITY_HIGH]
    med_index = [i for i, p in enumerate(priorities) if p == PRIORITY_MEDIUM]
    if high_index and med_index:
        assert max(high_index) < min(med_index)


def test_no_data_means_no_actions():
    assert build_next_actions([], [], None, [], {}) == []


def test_missing_data_prompts_for_every_empty_module():
    project = _FakeProject(path=None, is_valid_unity=False)
    reminders = _missing_data(project, [], [], [], [])
    joined = " ".join(reminders)
    assert "Unity folder" in joined
    assert "Debugging Buddy" in joined
    assert "Automated Testing" in joined
    assert "Feedback Review" in joined


def test_missing_data_flags_invalid_unity_path():
    project = _FakeProject(path="/some/folder", is_valid_unity=False)
    reminders = _missing_data(project, [], [], [], [])
    assert any("isn't recognized as a Unity project" in r for r in reminders)


def test_missing_data_empty_when_all_present():
    project = _FakeProject(path="/game", is_valid_unity=True)
    reminders = _missing_data(
        project,
        [_FakeSession(1)],
        [_FakeCase(1, "c", "Pass")],
        [_FakeRun(1, {})],
        [_FakeBatch(1)],
    )
    assert reminders == []
