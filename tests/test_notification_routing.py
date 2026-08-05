"""Relevance-Based Notifications routing logic (Phase J).

Scope reminder: this tests the routing *decision* only -- no notification is
ever delivered/displayed by this module, see its docstring for the Phase K
sequencing boundary.
"""

from __future__ import annotations

from spiced.backend_client.api_client import EventRoutingRule, NotificationPreference, TeamMember
from spiced.core.notification_routing import disciplines_for_event, relevant_members_for_event


def _member(user_id, discipline=None):
    return TeamMember(
        id=f"m-{user_id}",
        team_id="t1",
        user_id=user_id,
        invited_email=None,
        role="member",
        discipline=discipline,
        joined_at="2026-01-01T00:00:00Z",
        created_at="2026-01-01T00:00:00Z",
    )


def test_default_routing_for_audio_checklist_gap():
    members = [_member("u1", "audio"), _member("u2", "programmer"), _member("u3", None)]
    relevant = relevant_members_for_event(members, "audio_checklist_gap")
    assert [m.user_id for m in relevant] == ["u1"]


def test_default_routing_for_shader_performance_flag_covers_two_disciplines():
    members = [_member("u1", "programmer"), _member("u2", "artist"), _member("u3", "audio")]
    relevant = relevant_members_for_event(members, "shader_performance_flag")
    assert {m.user_id for m in relevant} == {"u1", "u2"}


def test_unknown_event_kind_routes_to_nobody_by_default():
    members = [_member("u1", "programmer")]
    assert relevant_members_for_event(members, "totally_unknown_kind") == []


def test_team_rules_replace_default_entirely():
    members = [_member("u1", "audio"), _member("u2", "design")]
    rules = [EventRoutingRule(id="r1", team_id="t1", event_kind="audio_checklist_gap",
                               discipline="design", created_at="now")]
    relevant = relevant_members_for_event(members, "audio_checklist_gap", team_rules=rules)
    assert [m.user_id for m in relevant] == ["u2"]
    assert disciplines_for_event("audio_checklist_gap", rules) == ["design"]


def test_preference_override_opts_a_member_out():
    members = [_member("u1", "audio")]
    prefs = [NotificationPreference(id="p1", team_id="t1", user_id="u1",
                                     event_kind="audio_checklist_gap", enabled=False,
                                     created_at="now")]
    relevant = relevant_members_for_event(members, "audio_checklist_gap", preferences=prefs)
    assert relevant == []


def test_preference_override_opts_a_member_in_despite_discipline_mismatch():
    members = [_member("u1", "programmer")]
    prefs = [NotificationPreference(id="p1", team_id="t1", user_id="u1",
                                     event_kind="audio_checklist_gap", enabled=True,
                                     created_at="now")]
    relevant = relevant_members_for_event(members, "audio_checklist_gap", preferences=prefs)
    assert [m.user_id for m in relevant] == ["u1"]


def test_team_task_assigned_uses_extra_discipline_dynamically():
    members = [_member("u1", "animation"), _member("u2", "audio")]
    relevant = relevant_members_for_event(
        members, "team_task_assigned", extra_discipline="animation"
    )
    assert [m.user_id for m in relevant] == ["u1"]


def test_members_with_no_discipline_are_never_matched_by_default():
    members = [_member("u1", None)]
    assert relevant_members_for_event(members, "known_issue_opened") == []
