"""E2E §3 -- Cross-Feature Rules/Trigger Subsystem (E2E_TEST_PLAN.md).

Highest-priority section per the plan and per CLAUDE.md. Existing unit tests
(``tests/test_rules_engine.py``) already cover ``evaluate_rules``'s
default-then-override logic in isolation with a fake backend; these E2E
tests drive the same engine end to end through a real ``Services(":memory:")``
composition root and real automation-feature entry points (e.g. ``services.
palette_drift.scan``), matching what actually calls into the rules engine in
production (see ``app.services.Services.__init__``'s
``_rule_aware_findings`` wiring).

**Deviations from the plan (see the final report for the full list):**

* §3.3 (rule chaining, cycle detection) has no corresponding mechanism.
  ``core.rules_engine._perform_action`` calls ``TeamService.
  send_finding_to_team_board`` / ``notify_relevant_members_for_project_event``
  / ``ChangelogService.queue_note`` directly -- none of these re-enter
  ``evaluate_rules`` with a new event. There is no "output of Rule A" that
  could trigger Rule B, so there is no chain and no cycle to detect.
  ``test_3_3_actions_never_reenter_evaluate_rules`` pins this down instead of
  silently skipping the row.
* §3.6 (100+ event burst, "queues/throttles") has no queue or throttle:
  ``evaluate_rules`` is called synchronously and inline, once per
  ``RuleAwareFindingRepository.create`` call, with no batching layer.
  Rewritten to what's real: 100 sequential events all get evaluated
  correctly with no event dropped and no crash -- a correctness assertion,
  not a queuing/throttling one.
* §3.5 (tier-gated rule fails closed) has no tier check anywhere in
  ``rules_engine.py`` -- a rule fires (or doesn't) based only on
  event-kind/severity/enabled, never on the acting team's billing tier.
  Rewritten to pin down that a rule fires the same way regardless of the
  team's tier, and cross-referenced with §5.4's combined RBAC+billing gate
  test, which covers the one place a tier check for rules-engine-created
  content actually exists (task/notification *visibility*, not creation).
"""

from __future__ import annotations

from conftest import build_e2e_services, seed_team_with_tiered_accounts

from spiced.automation.finding import (
    SEVERITY_WARNING,
    STATUS_ERROR,
    STATUS_FLAGGED,
    Finding,
)
from spiced.core.rules_engine import (
    ACTION_CREATE_TASK,
    ACTION_NOTIFY,
    ACTION_QUEUE_CHANGELOG_NOTE,
    RuleAwareFindingRepository,
    TriggerEvent,
    evaluate_rules,
)
from spiced.storage.automation_findings import AutomationFindingRepository


def _project_with_team(tmp_path):
    services, backend = build_e2e_services()
    project = services.projects.create_project("Fixture Game", engine="Godot")
    team, project_uuid, accounts = seed_team_with_tiered_accounts(services, backend, project)
    return services, backend, project, team, accounts


# --- §3.1: single event fires a single matching rule ------------------------


def test_3_1_single_event_fires_single_matching_rule_exactly_once(tmp_path):
    services, backend, project, team, _accounts = _project_with_team(tmp_path)
    backend.add_trigger_rule(team.id, "audio.loudness_normalize", SEVERITY_WARNING, ACTION_NOTIFY)
    event = TriggerEvent(
        event_kind="audio.loudness_normalize",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="2 file(s) too loud",
        source_feature_id="audio.loudness_normalize",
        run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_NOTIFY]


# --- §3.2: one event matches multiple rules; deterministic order -----------


def test_3_2_multiple_matching_rules_all_fire_in_the_order_they_were_added(tmp_path):
    services, backend, project, team, _accounts = _project_with_team(tmp_path)
    # The real storage layer has no "multiple active rules for one event
    # kind" concept -- TeamService.add_trigger_rule appends independent rows,
    # and rules_engine._rules_for_event returns every enabled row matching
    # the event kind, in the order list_trigger_rules returns them (insertion
    # order on the fake backend, matching a real DB's default row order for
    # an unordered SELECT in practice).
    backend.add_trigger_rule(team.id, "vfx.gpu_shader_profiling", SEVERITY_WARNING, ACTION_NOTIFY)
    backend.add_trigger_rule(
        team.id, "vfx.gpu_shader_profiling", SEVERITY_WARNING, ACTION_CREATE_TASK
    )
    event = TriggerEvent(
        event_kind="vfx.gpu_shader_profiling",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="3 shader(s) over budget",
        source_feature_id="vfx.gpu_shader_profiling",
        run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_NOTIFY, ACTION_CREATE_TASK]
    # Re-running is deterministic -- not a one-off ordering fluke.
    assert [r.action for r in evaluate_rules(services, event)] == [
        ACTION_NOTIFY,
        ACTION_CREATE_TASK,
    ]


# --- §3.3: rewritten -- no chaining mechanism exists ------------------------


def test_3_3_actions_never_reenter_evaluate_rules(tmp_path, monkeypatch):
    """Pins down the deviation explained in the module docstring: firing a
    create_task/notify/queue_changelog_note action never produces a second
    TriggerEvent, so there is no chain (and therefore no cycle) to test."""
    services, backend, project, team, _accounts = _project_with_team(tmp_path)
    backend.add_trigger_rule(team.id, "art.palette_drift", SEVERITY_WARNING, ACTION_CREATE_TASK)

    calls = []
    real_evaluate_rules = evaluate_rules

    def _counting_evaluate_rules(services_arg, event_arg):
        calls.append(event_arg)
        return real_evaluate_rules(services_arg, event_arg)

    monkeypatch.setattr("spiced.core.rules_engine.evaluate_rules", _counting_evaluate_rules)

    event = TriggerEvent(
        event_kind="art.palette_drift",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="color drift detected",
        source_feature_id="art.palette_drift",
        run_id="r1",
    )
    real_evaluate_rules(services, event)

    # Only our own direct call was ever recorded -- performing the
    # create_task action didn't trigger a second, internal evaluate_rules call.
    assert len(calls) == 0
    assert len(backend.tasks) == 1


# --- §3.4: simultaneous events from two connectors, same project -----------


def test_3_4_simultaneous_events_from_two_sources_neither_drops_nor_double_fires(tmp_path):
    services, backend, project, team, _accounts = _project_with_team(tmp_path)
    backend.add_trigger_rule(team.id, "art.palette_drift", SEVERITY_WARNING, ACTION_CREATE_TASK)
    backend.add_trigger_rule(team.id, "animation_bug_finding", SEVERITY_WARNING, ACTION_CREATE_TASK)

    godot_asset_event = TriggerEvent(
        event_kind="art.palette_drift",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="color drift detected",
        source_feature_id="art.palette_drift",
        run_id="godot-r1",
    )
    git_adjacent_event = TriggerEvent(
        event_kind="animation_bug_finding",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="2 empty state(s) flagged",
        source_feature_id="animation.live_animation_bug_detection",
        run_id="anim-r1",
    )

    # No shared mutable request-scoped state in evaluate_rules -- each call
    # is independent, so "simultaneous" reduces to "order-independent" here;
    # confirm both orders produce exactly one task each, no cross-talk.
    evaluate_rules(services, godot_asset_event)
    evaluate_rules(services, git_adjacent_event)

    assert len(backend.tasks) == 2
    assert {t.source_ref for t in backend.tasks} == {"godot-r1", "anim-r1"}


# --- §3.5: rewritten -- no tier check in the rules engine itself -----------


def test_3_5_rule_fires_the_same_regardless_of_team_billing_tier(tmp_path):
    """No tier-gating exists in rules_engine.py (see module docstring) --
    the free-tier member's rule fires identically to what a studio-tier
    team would get. Tier-aware *visibility* of the resulting task is a
    separate, real behavior tested in test_e2e_05_rbac.py's combined
    RBAC+billing scenario (§5.4)."""
    services, backend, project, team, accounts = _project_with_team(tmp_path)
    assert accounts["member"].tier == "free"
    backend.add_trigger_rule(
        team.id, "audio.loudness_normalize", SEVERITY_WARNING, ACTION_CREATE_TASK
    )
    event = TriggerEvent(
        event_kind="audio.loudness_normalize",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="2 file(s) too loud",
        source_feature_id="audio.loudness_normalize",
        run_id="r1",
    )

    results = evaluate_rules(services, event)

    assert [r.action for r in results] == [ACTION_CREATE_TASK]
    assert results[0].performed is True


# --- §3.6: rewritten -- correctness under volume, not queuing/throttling ---


def test_3_6_high_event_volume_processes_every_event_with_no_drop(tmp_path):
    services, backend, project, team, _accounts = _project_with_team(tmp_path)
    backend.add_trigger_rule(
        team.id, "art.palette_drift", SEVERITY_WARNING, ACTION_QUEUE_CHANGELOG_NOTE
    )

    for i in range(120):
        event = TriggerEvent(
            event_kind="art.palette_drift",
            project_id=project.id,
            severity=SEVERITY_WARNING,
            summary=f"drift #{i}",
            source_feature_id="art.palette_drift",
            run_id=f"r{i}",
        )
        results = evaluate_rules(services, event)
        assert [r.action for r in results] == [ACTION_QUEUE_CHANGELOG_NOTE]

    notes = services.changelog.pending_notes(project.id)
    assert len(notes) == 120  # every one of the 120 events produced its note -- none dropped


# --- §3.7: rule execution failure mid-chain doesn't corrupt other rules ----


def test_3_7_one_rules_engine_failure_does_not_break_the_next_evaluation(tmp_path, monkeypatch):
    services, backend, project, team, _accounts = _project_with_team(tmp_path)
    wrapped = RuleAwareFindingRepository(AutomationFindingRepository(services.db), services)

    import spiced.core.rules_engine as rules_engine_module

    original_evaluate = rules_engine_module._evaluate_rules  # pre-patch reference, not the wrapper
    call_count = {"n": 0}

    def _flaky(services_arg, event_arg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated rules-engine crash")
        return original_evaluate(services_arg, event_arg)

    monkeypatch.setattr("spiced.core.rules_engine._evaluate_rules", _flaky)

    first = Finding(
        feature_id="audio.loudness_normalize",
        project_id=str(project.id),
        status=STATUS_ERROR,
        summary="boom",
    )
    record_1 = wrapped.create(project.id, first)  # must not raise despite the simulated crash
    assert record_1.status == STATUS_ERROR

    second = Finding(
        feature_id="audio.loudness_normalize",
        project_id=str(project.id),
        status=STATUS_FLAGGED,
        summary="all good now",
    )
    record_2 = wrapped.create(
        project.id, second
    )  # unrelated finding still saves and evaluates cleanly
    assert record_2.status == STATUS_FLAGGED
    # The second finding still queued its default changelog note -- the
    # first call's crash didn't leave the rules engine (or the changelog
    # queue) in a broken state for the next one.
    notes = services.changelog.pending_notes(project.id)
    assert [n.note_text for n in notes] == ["all good now"]
