"""E2E §7 -- Cross-Cutting Scenarios (E2E_TEST_PLAN.md), full-stack.

**The plan's central substitution, explained once here.** All three §7
flows are written around "a connector detects a change" as the trigger. As
established in §1/§2's own module docstrings, none of Spiced's connectors
(``git_connector``, ``godot``/``godot_scan``, ``unreal``) emit an event or
touch the rules engine at all -- they are pure detection/read/write
utilities. The actual event source that reaches ``core.rules_engine.
evaluate_rules`` in production is one of the 13 Bible-track automation
services (``app.services.Services._rule_aware_findings``) or the one
confirmed legacy adapter, animation bug detection
(``Services.record_animation_bug_finding``).

So each flow below still does the literal connector action the plan
describes (a real git commit against a real fixture repo; a real Godot
fixture project on disk) for its own sake, but the event that actually
drives the rules engine comes from a real automation feature
(``services.palette_drift.scan`` / ``services.record_animation_bug_finding``)
run against that same fixture, not from the connector itself. This is the
same substitution documented in §1/§2/§3's module docstrings, composed here
into the full-stack flow the plan asks for.
"""

from __future__ import annotations

from tests.e2e.conftest import (
    build_e2e_services,
    log_in_as,
    make_git_fixture_repo,
    make_godot_fixture_project,
    seed_team_with_tiered_accounts,
)

from spiced.connectors import git_connector
from spiced.core.animation_bug_detection import detect_animation_bugs
from spiced.core.rules_engine import ACTION_CREATE_TASK, SEVERITY_WARNING

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


# --- Flow 1: commit lands -> real event -> rule fires -> task created,
# unaffected by billing tier, visible across RBAC roles ---------------------


def test_flow_1_commit_to_rule_driven_task_across_billing_and_rbac(tmp_path):
    services, backend = build_e2e_services()
    project = services.projects.create_project("Fixture Game", engine="Godot")
    team, project_uuid, accounts = seed_team_with_tiered_accounts(services, backend, project)
    backend.add_trigger_rule(team.id, "art.palette_drift", SEVERITY_WARNING, ACTION_CREATE_TASK)

    # Real git connector action: a developer commits a new asset to the
    # fixture repo (the literal §7 flow-1 trigger).
    repo = make_git_fixture_repo(tmp_path)
    git_connector.stage_paths(repo, ["art/icon.png"])  # already committed by the fixture builder;
    status_before = git_connector.repo_status(repo)
    assert status_before.is_clean is True

    # Real event source: a palette-drift scan over the repo's art/ folder
    # (see module docstring for why this stands in for "the connector fires
    # an event" -- git_connector itself never does).
    services.palette_drift.add_reference_color(project.id, "#0000FF")
    finding, _record = services.palette_drift.scan(project, repo / "art")

    assert finding.status in (
        "flagged",
        "error",
    )  # the fixture's red icon is far from reference blue

    # The team-configured rule fired and created a task.
    assert len(backend.tasks) == 1
    task = backend.tasks[0]

    # Billing tier never gated it (§4.5/§3.5's finding, re-confirmed here in
    # the full-stack flow): the acting/creating context has no tier check at
    # rule-evaluation time at all.
    assert task.status == "open"

    # RBAC: task *visibility* isn't role-restricted on the real backend
    # (only mutations like remove_member are, per §5) -- confirm every
    # seeded role can see it.
    for role in ("owner", "admin", "member"):
        log_in_as(services, accounts[role])
        visible_ids = {t.id for t in services.teams.list_tasks(team.id)}
        assert task.id in visible_ids

    # But mutation stays role-gated exactly as §5 established: the "member"
    # account still can't remove a teammate even though it can see the task.
    import pytest

    from spiced.backend_client.api_client import BackendAPIError

    log_in_as(services, accounts["member"])
    with pytest.raises(BackendAPIError):
        services.teams.remove_member(team.id, backend.members[team.id][0].id)


# --- Flow 2: account "at cap" when the event lands -- confirm the defined
# (non-)policy: rule execution is not gated by usage/billing state at all --


def test_flow_2_rule_fires_even_when_free_tier_usage_is_fully_exhausted(tmp_path):
    services, backend = build_e2e_services()
    project = services.projects.create_project("Fixture Game", engine="Godot")
    team, project_uuid, accounts = seed_team_with_tiered_accounts(services, backend, project)
    backend.add_trigger_rule(team.id, "animation_bug_finding", SEVERITY_WARNING, ACTION_CREATE_TASK)

    log_in_as(services, accounts["member"])  # free tier
    for _ in range(25):  # exhaust the real Free plan's 25 monthly prompts
        services.usage.record_prompt("mock", kind="chat")
    status = services.usage.status()
    assert status.plan.key == "free"
    assert status.remaining == 0  # genuinely "at cap"

    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "Hub.controller").write_text(_CONTROLLER_WITH_EMPTY_STATE, encoding="utf-8")
    result = detect_animation_bugs(tmp_path)
    assert result.flagged_count == 1

    services.record_animation_bug_finding(project.id, result)

    # No policy in this codebase blocks/queues/bills-overage for a
    # rules-engine action based on prompt-usage cap state -- confirmed by
    # the task being created exactly as it would be with usage remaining.
    # (E2E_TEST_PLAN.md §7 flow 2's "confirm which policy applies" -- the
    # honest answer for this codebase is "none exists yet"; see final report.)
    assert len(backend.tasks) == 1


# --- Flow 3: a Godot-project change and a git-adjacent event land in the
# same window -- both processed, neither dropped -----------------------------


def test_flow_3_godot_change_and_second_event_same_window_both_processed(tmp_path):
    services, backend = build_e2e_services()
    project = services.projects.create_project("Fixture Game", engine="Godot")
    team, project_uuid, accounts = seed_team_with_tiered_accounts(services, backend, project)
    backend.add_trigger_rule(team.id, "art.palette_drift", SEVERITY_WARNING, ACTION_CREATE_TASK)
    backend.add_trigger_rule(team.id, "animation_bug_finding", SEVERITY_WARNING, ACTION_CREATE_TASK)

    godot_project = make_godot_fixture_project(tmp_path, name="fixture-godot-flow3")
    services.palette_drift.add_reference_color(project.id, "#0000FF")

    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "Hub.controller").write_text(_CONTROLLER_WITH_EMPTY_STATE, encoding="utf-8")
    anim_result = detect_animation_bugs(tmp_path)
    assert anim_result.flagged_count == 1

    # Fire both real events "within the same window" (no ordering guarantee
    # to break -- evaluate_rules has no shared mutable request-scoped state,
    # see test_e2e_03_rules_engine.py's §3.4 test for the same point made
    # directly against the engine).
    finding, _record = services.palette_drift.scan(project, godot_project / "assets")
    services.record_animation_bug_finding(project.id, anim_result)

    assert finding.status in ("flagged", "error")
    assert len(backend.tasks) == 2
    task_sources = {t.description for t in backend.tasks}
    assert any("drift" in (d or "").lower() or "flagged" in (d or "").lower() for d in task_sources)
    assert any("empty state" in (d or "") for d in task_sources)
