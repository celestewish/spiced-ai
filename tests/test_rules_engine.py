"""Tests for core.rules_engine: TriggerEvent adapters, evaluate_rules'
default-then-override logic per action type, and RuleAwareFindingRepository's
transparent wrapping of the 13 automation services' finding-persistence path.

Uses a real Services(":memory:") instance (so project/changelog storage is
real, not mocked) with its TeamService's backend swapped for a fake client
(same style as tests/test_team_service_task_board.py) for the team-scoped
create_task/notify actions.
"""

from __future__ import annotations

from spiced.app.services import Services
from spiced.automation.finding import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_ERROR,
    STATUS_FLAGGED,
    STATUS_PASS,
    Finding,
    FindingItem,
)
from spiced.backend_client.api_client import (
    EventRoutingRule,
    Notification,
    NotificationPreference,
    Team,
    TeamMember,
    TeamProject,
    TeamTask,
    TriggerRule,
)
from spiced.backend_client.auth_client import AuthSession
from spiced.core.animation_bug_detection import (
    AnimationBugScanResult,
    EmptyStateFinding,
    detect_animation_bugs,
)
from spiced.core.auth_service import AuthService
from spiced.core.rules_engine import (
    ACTION_CREATE_TASK,
    ACTION_NOTIFY,
    ACTION_QUEUE_CHANGELOG_NOTE,
    ANIMATION_BUG_EVENT_KIND,
    RuleAwareFindingRepository,
    TriggerEvent,
    animation_bug_event,
    evaluate_rules,
    finding_to_event,
)
from spiced.core.team_service import TeamService
from spiced.storage.automation_findings import AutomationFindingRepository


class _FakeAuthClient:
    def is_configured(self) -> bool:
        return True

    def log_in(self, email: str, password: str) -> AuthSession:
        return AuthSession(access_token="jwt-1", refresh_token="r1", user_id="u1", email=email)

    def sign_up(self, email: str, password: str) -> AuthSession:
        return self.log_in(email, password)


class _FakeBackendClient:
    """Minimal fake covering exactly what evaluate_rules' create_task/notify
    actions touch -- same style/shape as test_team_service_task_board.py's
    fake, trimmed to this module's needs plus TriggerRule support."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.tasks: list[TeamTask] = []
        self.notifications: list[Notification] = []
        self.trigger_rules: list[TriggerRule] = []
        self.linked_projects: list[TeamProject] = []
        self.members: list[TeamMember] = [
            TeamMember(
                id="m1", team_id="team-1", user_id="u1", invited_email=None, role="owner",
                discipline="animation", joined_at="2026-08-24T00:00:00Z",
                created_at="2026-08-24T00:00:00Z",
            )
        ]

    def set_token(self, token: str | None) -> None:
        self.token = token

    def list_teams(self) -> list[Team]:
        return [Team(id="team-1", name="Crew", created_by="u1", created_at="2026-08-24T00:00:00Z")]

    def link_project(self, team_id: str, project_uuid: str, name: str) -> TeamProject:
        link = TeamProject(
            id=f"link-{len(self.linked_projects) + 1}", team_id=team_id,
            project_uuid=project_uuid, name=name, created_at="2026-08-24T00:00:00Z",
        )
        self.linked_projects.append(link)
        return link

    def list_projects(self, team_id: str) -> list[TeamProject]:
        return [p for p in self.linked_projects if p.team_id == team_id]

    def list_members(self, team_id: str) -> list[TeamMember]:
        return self.members

    def create_task(self, team_id, title, *, description=None, project_uuid=None,
                     assigned_discipline=None, source_type="manual", source_ref=None):
        task = TeamTask(
            id=f"task-{len(self.tasks) + 1}", team_id=team_id, project_uuid=project_uuid,
            title=title, description=description, status="open",
            assigned_discipline=assigned_discipline, source_type=source_type,
            source_ref=source_ref, created_by_user_id="u1",
            created_at="2026-08-24T00:00:00Z", updated_at="2026-08-24T00:00:00Z",
        )
        self.tasks.append(task)
        return task

    def list_routing_rules(self, team_id) -> list[EventRoutingRule]:
        return []

    def list_notification_preferences(self, team_id) -> list[NotificationPreference]:
        return []

    def create_notification(self, team_id, recipient_user_id, event_kind, title, body,
                             *, subject_type=None, subject_id=None):
        notification = Notification(
            id=f"n{len(self.notifications) + 1}", team_id=team_id,
            recipient_user_id=recipient_user_id, event_kind=event_kind, title=title,
            body=body, subject_type=subject_type, subject_id=subject_id,
            created_at="2026-08-24T00:00:00Z", read_at=None,
        )
        self.notifications.append(notification)
        return notification

    def list_trigger_rules(self, team_id: str) -> list[TriggerRule]:
        return [r for r in self.trigger_rules if r.team_id == team_id]

    def add_trigger_rule(self, team_id, event_kind, min_severity, action, *,
                          action_params_json="{}", enabled=True):
        rule = TriggerRule(
            id=f"tr{len(self.trigger_rules) + 1}", team_id=team_id, event_kind=event_kind,
            min_severity=min_severity, action=action, action_params_json=action_params_json,
            enabled=enabled, created_at="2026-08-24T00:00:00Z",
        )
        self.trigger_rules.append(rule)
        return rule


def _services(*, team_linked: bool) -> tuple[Services, _FakeBackendClient, int]:
    services = Services(db_path=":memory:")
    project = services.projects.create_project("Test Game", engine="Unity")
    if not team_linked:
        return services, _FakeBackendClient(), project.id

    backend = _FakeBackendClient()
    services.auth = AuthService(services._settings, _FakeAuthClient())
    services.teams = TeamService(services.auth, services.projects, backend)
    services.auth.log_in("dev@example.com", "hunter2")
    services.teams.link_active_project("team-1", project.id, project.name)
    return services, backend, project.id


# --- finding_to_event / animation_bug_event adapters -----------------------


def test_finding_to_event_maps_flagged_status_to_warning_severity():
    finding = Finding(
        feature_id="audio.loudness_normalize",
        project_id="1",
        status=STATUS_FLAGGED,
        summary="2 file(s) too loud",
        items=[FindingItem(asset_path="a.wav", severity=SEVERITY_WARNING, message="too loud")],
    )
    event = finding_to_event(finding, project_id=1)
    assert event.event_kind == "audio.loudness_normalize"
    assert event.project_id == 1
    assert event.severity == SEVERITY_WARNING
    assert event.run_id == finding.run_id


def test_finding_to_event_maps_error_status_to_error_severity():
    finding = Finding(
        feature_id="vfx.shader_variant_analysis", project_id="1", status=STATUS_ERROR,
        summary="scan failed",
    )
    assert finding_to_event(finding, project_id=1).severity == SEVERITY_ERROR


def test_finding_to_event_maps_pass_status_to_info_severity():
    finding = Finding(
        feature_id="art.palette_drift", project_id="1", status=STATUS_PASS, summary="all clear"
    )
    assert finding_to_event(finding, project_id=1).severity == SEVERITY_INFO


def test_animation_bug_event_none_when_nothing_flagged():
    result = AnimationBugScanResult(controllers_scanned=3)
    assert animation_bug_event(result, project_id=1, run_id="run-1") is None


def test_animation_bug_event_warning_severity_when_flagged():
    result = AnimationBugScanResult(
        empty_states=[EmptyStateFinding("Hub.controller", "Idle", "123")],
        controllers_scanned=1,
    )
    event = animation_bug_event(result, project_id=1, run_id="run-1")
    assert event is not None
    assert event.event_kind == ANIMATION_BUG_EVENT_KIND
    assert event.severity == SEVERITY_WARNING
    assert event.run_id == "run-1"


# --- evaluate_rules: default behavior (no team, or team with no matching
# rule) ----------------------------------------------------------------


def test_default_rule_queues_changelog_note_for_solo_project():
    services, _backend, project_id = _services(team_linked=False)
    event = TriggerEvent(
        event_kind="audio.loudness_normalize", project_id=project_id, severity=SEVERITY_WARNING,
        summary="2 file(s) too loud", source_feature_id="audio.loudness_normalize", run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_QUEUE_CHANGELOG_NOTE]
    assert results[0].performed is True
    notes = services.changelog.pending_notes(project_id)
    assert [n.note_text for n in notes] == ["2 file(s) too loud"]


def test_default_rule_below_min_severity_does_nothing():
    services, _backend, project_id = _services(team_linked=False)
    event = TriggerEvent(
        event_kind="audio.loudness_normalize", project_id=project_id, severity=SEVERITY_INFO,
        summary="all clear", source_feature_id="audio.loudness_normalize", run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert results == []
    assert services.changelog.pending_notes(project_id) == []


def test_solo_project_never_makes_a_network_call():
    """No team linked -- create_task/notify never fire (they require a
    team), and evaluate_rules never touches the backend client at all."""
    services, backend, project_id = _services(team_linked=False)
    event = TriggerEvent(
        event_kind="animation.mocap_cleanup_assist", project_id=project_id,
        severity=SEVERITY_ERROR, summary="bad mocap data",
        source_feature_id="animation.mocap_cleanup_assist", run_id="r1",
    )

    evaluate_rules(services, event)

    assert backend.tasks == []
    assert backend.notifications == []


def test_team_linked_project_with_no_matching_rule_still_uses_default():
    services, _backend, project_id = _services(team_linked=True)
    event = TriggerEvent(
        event_kind="art.palette_drift", project_id=project_id, severity=SEVERITY_WARNING,
        summary="color drift detected", source_feature_id="art.palette_drift", run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_QUEUE_CHANGELOG_NOTE]


# --- evaluate_rules: team-configured rules replace the default -------------


def test_team_rule_create_task_replaces_default():
    services, backend, project_id = _services(team_linked=True)
    backend.add_trigger_rule(
        "team-1", "animation_bug_finding", SEVERITY_WARNING, ACTION_CREATE_TASK
    )
    event = TriggerEvent(
        event_kind="animation_bug_finding", project_id=project_id, severity=SEVERITY_WARNING,
        summary="2 empty state(s) flagged",
        source_feature_id="animation.live_animation_bug_detection",
        run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_CREATE_TASK]
    assert len(backend.tasks) == 1
    assert backend.tasks[0].description == "2 empty state(s) flagged"
    # The default queue_changelog_note must NOT also fire -- team rules
    # replace the default entirely, they don't merge with it.
    assert services.changelog.pending_notes(project_id) == []


def test_team_rule_notify_creates_notifications_for_relevant_members():
    services, backend, project_id = _services(team_linked=True)
    backend.add_trigger_rule("team-1", "art.palette_drift", SEVERITY_WARNING, ACTION_NOTIFY)
    event = TriggerEvent(
        event_kind="art.palette_drift", project_id=project_id, severity=SEVERITY_WARNING,
        summary="color drift detected", source_feature_id="art.palette_drift", run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_NOTIFY]
    # backend.members[0] has discipline "animation", not "artist" (art.
    # palette_drift's default routed discipline) -- no member matches, so
    # zero notifications is the correct outcome, not a failure.
    assert results[0].performed is False


def test_team_rule_notify_reaches_member_whose_discipline_matches():
    services, backend, project_id = _services(team_linked=True)
    backend.members[0] = TeamMember(
        id="m1", team_id="team-1", user_id="u1", invited_email=None, role="owner",
        discipline="artist", joined_at="2026-08-24T00:00:00Z", created_at="2026-08-24T00:00:00Z",
    )
    backend.add_trigger_rule("team-1", "art.palette_drift", SEVERITY_WARNING, ACTION_NOTIFY)
    event = TriggerEvent(
        event_kind="art.palette_drift", project_id=project_id, severity=SEVERITY_WARNING,
        summary="color drift detected", source_feature_id="art.palette_drift", run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert results[0].performed is True
    assert len(backend.notifications) == 1


def test_team_rule_respects_its_own_min_severity_threshold():
    services, backend, project_id = _services(team_linked=True)
    backend.add_trigger_rule("team-1", "art.palette_drift", SEVERITY_ERROR, ACTION_CREATE_TASK)
    event = TriggerEvent(
        event_kind="art.palette_drift", project_id=project_id, severity=SEVERITY_WARNING,
        summary="color drift detected", source_feature_id="art.palette_drift", run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert results == []
    assert backend.tasks == []


def test_disabled_team_rule_is_ignored():
    services, backend, project_id = _services(team_linked=True)
    backend.add_trigger_rule(
        "team-1", "art.palette_drift", SEVERITY_WARNING, ACTION_CREATE_TASK, enabled=False
    )
    event = TriggerEvent(
        event_kind="art.palette_drift", project_id=project_id, severity=SEVERITY_WARNING,
        summary="color drift detected", source_feature_id="art.palette_drift", run_id="r1",
    )

    results = evaluate_rules(services, event)

    # A disabled rule doesn't count as "matching" -- falls back to default.
    assert [r.action for r in results] == [ACTION_QUEUE_CHANGELOG_NOTE]
    assert backend.tasks == []


def test_evaluate_rules_never_raises_for_unknown_project():
    services, _backend, project_id = _services(team_linked=False)
    event = TriggerEvent(
        event_kind="art.palette_drift", project_id=99999, severity=SEVERITY_WARNING,
        summary="x", source_feature_id="art.palette_drift", run_id="r1",
    )
    assert evaluate_rules(services, event) == []


# --- RuleAwareFindingRepository ---------------------------------------------


def test_rule_aware_repository_persists_identically_to_raw_repository():
    services, _backend, project_id = _services(team_linked=False)
    raw_repo = AutomationFindingRepository(services.db)
    wrapped = RuleAwareFindingRepository(raw_repo, services)
    finding = Finding(
        feature_id="audio.loudness_normalize", project_id=str(project_id), status=STATUS_FLAGGED,
        summary="2 file(s) too loud",
        items=[FindingItem(asset_path="a.wav", severity=SEVERITY_WARNING, message="too loud")],
    )

    record = wrapped.create(project_id, finding)

    raw_record = raw_repo.get(record.id)
    assert record.id == raw_record.id
    assert record.run_id == finding.run_id
    assert record.status == STATUS_FLAGGED
    assert wrapped.get(record.id) == raw_record
    assert wrapped.get_by_run_id(finding.run_id) == raw_record
    assert wrapped.list_for_project(project_id) == raw_repo.list_for_project(project_id)


def test_rule_aware_repository_also_evaluates_rules():
    services, _backend, project_id = _services(team_linked=False)
    wrapped = RuleAwareFindingRepository(AutomationFindingRepository(services.db), services)
    finding = Finding(
        feature_id="vfx.gpu_shader_profiling", project_id=str(project_id), status=STATUS_FLAGGED,
        summary="3 shader(s) over budget",
    )

    wrapped.create(project_id, finding)

    notes = services.changelog.pending_notes(project_id)
    assert [n.note_text for n in notes] == ["3 shader(s) over budget"]


def test_rule_aware_repository_swallows_a_broken_evaluation(monkeypatch):
    """A rules-engine bug must never break the underlying finding save."""
    services, _backend, project_id = _services(team_linked=False)
    wrapped = RuleAwareFindingRepository(AutomationFindingRepository(services.db), services)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("spiced.core.rules_engine._evaluate_rules", _boom)
    finding = Finding(
        feature_id="audio.loudness_normalize", project_id=str(project_id), status=STATUS_FLAGGED,
        summary="x",
    )

    record = wrapped.create(project_id, finding)  # must not raise

    assert record.status == STATUS_FLAGGED


# --- Services.record_animation_bug_finding: the one confirmed legacy
# adapter, end to end against a real .controller fixture (not mocks) -------

_CONTROLLER_WITH_EMPTY_STATE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions: []
  m_Motion: {fileID: 0}
--- !u!1107 &400
AnimatorStateMachine:
  m_Name: Base Layer
  m_ChildStates:
  - m_State: {fileID: 200}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_DefaultState: {fileID: 200}
"""


def test_record_animation_bug_finding_queues_changelog_note_by_default(tmp_path):
    services, _backend, project_id = _services(team_linked=False)
    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "Hub.controller").write_text(_CONTROLLER_WITH_EMPTY_STATE, encoding="utf-8")

    result = detect_animation_bugs(tmp_path)
    assert result.flagged_count == 1  # sanity check on the real scan itself

    services.record_animation_bug_finding(project_id, result)

    notes = services.changelog.pending_notes(project_id)
    assert len(notes) == 1
    assert notes[0].source_event_kind == ANIMATION_BUG_EVENT_KIND


def test_record_animation_bug_finding_creates_task_via_team_rule(tmp_path):
    services, backend, project_id = _services(team_linked=True)
    backend.add_trigger_rule(
        "team-1", ANIMATION_BUG_EVENT_KIND, SEVERITY_WARNING, ACTION_CREATE_TASK
    )
    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "Hub.controller").write_text(_CONTROLLER_WITH_EMPTY_STATE, encoding="utf-8")

    result = detect_animation_bugs(tmp_path)

    services.record_animation_bug_finding(project_id, result)

    assert len(backend.tasks) == 1
    assert "empty state" in backend.tasks[0].description


def test_record_animation_bug_finding_no_event_when_nothing_flagged(tmp_path):
    services, _backend, project_id = _services(team_linked=False)
    assets = tmp_path / "Assets"
    assets.mkdir()  # no .controller files at all -- nothing to flag

    result = detect_animation_bugs(tmp_path)
    assert result.flagged_count == 0

    services.record_animation_bug_finding(project_id, result)  # must not raise

    assert services.changelog.pending_notes(project_id) == []
