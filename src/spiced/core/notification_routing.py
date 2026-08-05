"""Relevance-Based Notifications: routing logic only (Phase J, section 8 part 2).

**Sequencing scope boundary** (see the phase plan): Section 9's Notification
Center (a bell icon + inbox UI) is Phase K, a later phase, and is NOT built
here. This module is the routing/filtering *mechanism* that future
Notification Center is expected to consume: given a team's members, an event
kind, and any team-level routing rules / per-member preference overrides
(fetched from the backend via ``TeamService`` -- see ``core.team_service.
TeamService.relevant_members_for_project_event``), decide which members are
relevant to one occurrence of that event. Nothing here delivers, stores, or
displays an actual notification -- there is no inbox, no bell icon, no
"seen"/"unread" state, and no push/email/toast of any kind. That is
explicitly Phase K's job; this phase only builds the decision layer plus a
Settings-page panel for editing the routing rules (see
``ui.screens.settings.SettingsScreen``'s notification routing section).
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
