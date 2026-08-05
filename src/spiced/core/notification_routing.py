"""Relevance-Based Notifications: routing logic (Phase J, section 8 part 2),
now consumed by the actual Notification Center (Phase K, section 9 part 1).

This module stays the routing/filtering *mechanism* only: given a team's
members, an event kind, and any team-level routing rules / per-member
preference overrides, decide which members are relevant to one occurrence of
that event. It still never delivers, stores, or displays anything itself --
that's ``core.team_service.TeamService._notify_event`` (Phase K), which calls
``relevant_members_for_event`` below and then creates one
``backend_client.api_client.Notification`` row per relevant, already-joined
member via the backend's ``/teams/{team_id}/notifications`` endpoints.
"""

from __future__ import annotations

from spiced.backend_client.api_client import EventRoutingRule, NotificationPreference, TeamMember

# Default event-kind -> relevant discipline(s) mapping, used whenever a team
# hasn't saved its own routing rules for a given event kind (see
# ``disciplines_for_event``). Reuses the discipline concept from Role-Based
# Dashboards (#4) as the default routing key, per spec. Editable per team via
# the Settings routing panel, which persists overrides as ``EventRoutingRule``
# rows on the backend -- this dict is only the fallback, not the source of
# truth once a team has customized a kind.
DEFAULT_EVENT_KIND_DISCIPLINES: dict[str, list[str]] = {
    "audio_checklist_gap": ["audio"],
    "animation_bug_finding": ["animation"],
    "art_review_finding": ["artist"],
    "known_issue_opened": ["programmer"],
    "known_issue_regression": ["programmer"],
    "shader_performance_flag": ["programmer", "artist"],
    # Routed dynamically off the specific task's own assigned_discipline
    # (see relevant_members_for_event's extra_discipline parameter) rather
    # than a fixed default -- an empty default list here is intentional.
    "team_task_assigned": [],
    # A quiet Context Panel note either way (see ui.build_scheduler), but
    # also now a real notification for whoever's on point for builds.
    "build_failed": ["programmer"],
    # Routed dynamically, same as team_task_assigned: a comment on a task
    # routes to that task's assigned_discipline, a comment on a known issue
    # routes to "programmer" (see TeamService._notify_comment) -- an empty
    # default here is intentional.
    "comment_posted": [],
}

KNOWN_EVENT_KINDS: list[str] = sorted(DEFAULT_EVENT_KIND_DISCIPLINES)


def disciplines_for_event(
    event_kind: str, team_rules: list[EventRoutingRule] | None = None
) -> list[str]:
    """Which discipline(s) an event kind routes to, for one team.

    If the team has at least one saved rule for ``event_kind``, those rules
    *replace* the hardcoded default entirely (rather than merging with it),
    so a team can narrow or widen the default set without fighting it.
    Falls back to ``DEFAULT_EVENT_KIND_DISCIPLINES`` otherwise.
    """
    if team_rules:
        team_specific = sorted({r.discipline for r in team_rules if r.event_kind == event_kind})
        if team_specific:
            return team_specific
    return list(DEFAULT_EVENT_KIND_DISCIPLINES.get(event_kind, []))


def relevant_members_for_event(
    members: list[TeamMember],
    event_kind: str,
    *,
    team_rules: list[EventRoutingRule] | None = None,
    preferences: list[NotificationPreference] | None = None,
    extra_discipline: str | None = None,
) -> list[TeamMember]:
    """Which of ``members`` should be notified about one occurrence of
    ``event_kind`` -- the routing decision Phase K's future Notification
    Center is expected to call.

    ``extra_discipline`` lets a caller pass a *dynamic* discipline for event
    kinds with no fixed default (e.g. "team_task_assigned" routes to
    whichever discipline that specific task was assigned to, not a fixed
    list) -- it's unioned into the routed discipline set for this call only.

    ``preferences`` are per-member explicit overrides (``NotificationPreference``
    rows): a member with an explicit row for this event kind uses that row's
    ``enabled`` value instead of the discipline-based default, letting
    anyone opt in or out regardless of their own discipline.
    """
    disciplines = set(disciplines_for_event(event_kind, team_rules))
    if extra_discipline:
        disciplines.add(extra_discipline)

    overrides: dict[str, bool] = {}
    for pref in preferences or []:
        if pref.event_kind == event_kind and pref.user_id:
            overrides[pref.user_id] = pref.enabled

    relevant: list[TeamMember] = []
    for member in members:
        if member.user_id and member.user_id in overrides:
            if overrides[member.user_id]:
                relevant.append(member)
            continue
        if member.discipline and member.discipline in disciplines:
            relevant.append(member)
    return relevant
