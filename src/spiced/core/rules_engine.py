"""Cross-Feature Rules/Trigger Engine (Market-Viability Roadmap, Phase 4).

**Verified starting state** (see the roadmap document for the full writeup):
13 ``automation/*.py`` features already share one real schema
(``automation.finding.Finding``/``FindingItem``), persisted through one
choke point (``AutomationFindingRepository.create``). ``core.
notification_routing`` is already a small, working rules engine for *who*
gets notified about an event kind; this module is the sibling that decides
*what happens* -- evaluated against the same event-kind vocabulary,
reusing ``relevant_members_for_event`` directly for its own ``notify``
action rather than inventing a second routing mechanism.

**Deliberately a fixed, small action enum -- not a scripting DSL.** Three
actions only: ``create_task`` (reuses ``TeamService.send_finding_to_team_
board``), ``notify`` (reuses ``TeamService.notify_relevant_members_for_
project_event``), ``queue_changelog_note`` (reuses ``ChangelogService.
queue_note`` -- queues a draft, never auto-publishes, preserving this
app's existing "AI-drafted, developer-reviewed, Spiced never publishes"
convention). A condition is a minimum-severity threshold only, not a
general expression language. Cross-team rule sharing and a real DSL are
both explicitly out of scope -- see the roadmap's Recommendation 6
(extensibility) for where that ambition, if ever pursued, belongs.

**Event-kind vocabulary.** Each of the 13 automation features' own
``feature_id`` (e.g. ``"audio.loudness_normalize"``) IS its event kind --
lets a team target a rule at exactly one feature rather than only a
coarser category. ``core.notification_routing.DEFAULT_EVENT_KIND_
DISCIPLINES`` has been extended with a default discipline for all 13, so
the ``notify`` action has something sensible to route to even before a
team configures anything. Separately, ``ANIMATION_BUG_EVENT_KIND`` covers
the one confirmed legacy (pre-``Finding``-schema) analyzer this phase
wires: ``core.animation_bug_detection``, whose event kind
(``"animation_bug_finding"``) was already a *reserved-but-dormant* name in
``notification_routing`` before this phase existed. **Scope-honest note**:
only that one legacy module was confirmed cleanly mappable during this
phase's research -- a full audit of every other pre-``Finding``-schema
analyzer module is real, un-started follow-up work, not silently done here.

**Rule storage and default-then-override.** Team-scoped ``TriggerRule``
rows (backend, same shape as ``EventRoutingRule``) are loaded per event
kind; if a team has any *enabled* rows for that exact event kind, those
rows entirely replace the built-in default for that team (mirroring
``notification_routing.disciplines_for_event``'s own "replace, don't
merge" precedent) -- otherwise ``_DEFAULT_RULES`` applies. The only
built-in default is ``queue_changelog_note`` at ``SEVERITY_WARNING`` --
``create_task``/``notify`` require a team by definition (a task or
notification has to go somewhere), so they only ever fire from an
explicit, team-configured ``TriggerRule``. This naturally means a
solo/unlinked project's only meaningful rules-engine behavior is the
local, always-available changelog-note queue -- not a special-cased
solo/team branch, just what falls out of the same default-then-override
logic every project goes through.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spiced.automation.finding import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_ERROR,
    STATUS_FLAGGED,
    Finding,
)
from spiced.backend_client.api_client import BackendAPIError, NotAuthenticatedError
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository

if TYPE_CHECKING:
    from spiced.app.services import Services
    from spiced.core.animation_bug_detection import AnimationBugScanResult
    from spiced.storage.projects import Project

ACTION_CREATE_TASK = "create_task"
ACTION_NOTIFY = "notify"
ACTION_QUEUE_CHANGELOG_NOTE = "queue_changelog_note"
VALID_ACTIONS = frozenset({ACTION_CREATE_TASK, ACTION_NOTIFY, ACTION_QUEUE_CHANGELOG_NOTE})

# The one confirmed legacy (pre-Finding-schema) analyzer this phase wires --
# already a reserved-but-dormant event kind in notification_routing before
# this module existed.
ANIMATION_BUG_EVENT_KIND = "animation_bug_finding"

_SEVERITY_RANK = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_ERROR: 2}

# The only built-in default action -- see module docstring for why
# create_task/notify are never part of it.
_DEFAULT_RULES: tuple[tuple[str, str, dict], ...] = (
    (ACTION_QUEUE_CHANGELOG_NOTE, SEVERITY_WARNING, {}),
)


@dataclass(frozen=True)
class TriggerEvent:
    event_kind: str
    project_id: int
    severity: str
    summary: str
    source_feature_id: str
    run_id: str
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def finding_to_event(finding: Finding, project_id: int) -> TriggerEvent:
    """Trivial adapter for the 13 ``automation.Finding``-shaped features --
    the shapes already match almost exactly (see module docstring)."""
    return TriggerEvent(
        event_kind=finding.feature_id,
        project_id=project_id,
        severity=_severity_from_status(finding.status),
        summary=finding.summary,
        source_feature_id=finding.feature_id,
        run_id=finding.run_id,
        metadata={"item_count": len(finding.items), **finding.severity_counts},
        timestamp=finding.timestamp,
    )


def _severity_from_status(status: str) -> str:
    if status == STATUS_ERROR:
        return SEVERITY_ERROR
    if status == STATUS_FLAGGED:
        return SEVERITY_WARNING
    return SEVERITY_INFO


def animation_bug_event(
    result: AnimationBugScanResult, project_id: int, run_id: str
) -> TriggerEvent | None:
    """Adapter for ``core.animation_bug_detection.AnimationBugScanResult``
    -- the one confirmed legacy mapping (see module docstring). Returns
    ``None`` (no event to evaluate) when the scan found nothing; an empty
    run isn't an occurrence worth running rules against."""
    if result.flagged_count == 0:
        return None
    return TriggerEvent(
        event_kind=ANIMATION_BUG_EVENT_KIND,
        project_id=project_id,
        severity=SEVERITY_WARNING,  # risk indicators only, never a confirmed error (see module)
        summary=(
            f"{len(result.empty_states)} empty state(s), "
            f"{len(result.zero_duration_transitions)} zero-duration transition(s) flagged"
        ),
        source_feature_id="animation.live_animation_bug_detection",
        run_id=run_id,
        metadata={
            "empty_state_count": len(result.empty_states),
            "zero_duration_transition_count": len(result.zero_duration_transitions),
            "controllers_scanned": result.controllers_scanned,
        },
    )


@dataclass(frozen=True)
class TriggerActionResult:
    action: str
    performed: bool
    detail: str


def evaluate_rules(services: Services, event: TriggerEvent) -> list[TriggerActionResult]:
    """Evaluate every applicable rule for ``event`` and perform its action.

    Never raises -- a rules-engine failure (a missing project, a backend
    hiccup, a malformed ``action_params_json``) must never break the
    finding-save or scan operation that produced the event; see
    ``RuleAwareFindingRepository`` below, the one place this actually gets
    called from a live feature.
    """
    try:
        return _evaluate_rules(services, event)
    except Exception:
        return []


def _evaluate_rules(services: Services, event: TriggerEvent) -> list[TriggerActionResult]:
    project = services.projects.get_project(event.project_id)
    rules = _rules_for_event(services, project.project_uuid, event.event_kind)

    results: list[TriggerActionResult] = []
    event_rank = _SEVERITY_RANK.get(event.severity, 0)
    for action, min_severity, params in rules:
        if event_rank < _SEVERITY_RANK.get(min_severity, 0):
            continue
        results.append(_perform_action(services, event, project, action, params))
    return results


def _rules_for_event(
    services: Services, project_uuid: str | None, event_kind: str
) -> list[tuple[str, str, dict]]:
    if project_uuid:
        try:
            team = services.teams.find_team_for_project(project_uuid)
        except (BackendAPIError, NotAuthenticatedError):
            team = None
        if team is not None:
            try:
                team_rules = services.teams.list_trigger_rules(team.id)
            except (BackendAPIError, NotAuthenticatedError):
                team_rules = []
            matching = [
                (r.action, r.min_severity, _parse_params(r.action_params_json))
                for r in team_rules
                if r.event_kind == event_kind and r.enabled and r.action in VALID_ACTIONS
            ]
            if matching:
                return matching
    return list(_DEFAULT_RULES)


def _parse_params(action_params_json: str | None) -> dict:
    if not action_params_json:
        return {}
    try:
        data = json.loads(action_params_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _perform_action(
    services: Services, event: TriggerEvent, project: Project, action: str, params: dict
) -> TriggerActionResult:
    title = f"{event.event_kind}: {event.summary}"[:300]
    if action == ACTION_CREATE_TASK:
        if not project.project_uuid:
            return TriggerActionResult(action, False, "No team linked — nothing to create in.")
        task = services.teams.send_finding_to_team_board(
            project.project_uuid,
            title,
            description=event.summary,
            assigned_discipline=params.get("assigned_discipline"),
            source_type="rules_engine",
            source_ref=event.run_id,
        )
        detail = f"Created task {task.id}." if task is not None else "No team linked."
        return TriggerActionResult(action, task is not None, detail)

    if action == ACTION_NOTIFY:
        if not project.project_uuid:
            return TriggerActionResult(action, False, "No team linked — no one to notify.")
        notifications = services.teams.notify_relevant_members_for_project_event(
            project.project_uuid,
            event.event_kind,
            title,
            event.summary,
            subject_type="automation_finding",
            subject_id=event.run_id,
            extra_discipline=params.get("extra_discipline"),
        )
        return TriggerActionResult(
            action, bool(notifications), f"Notified {len(notifications)} member(s)."
        )

    if action == ACTION_QUEUE_CHANGELOG_NOTE:
        services.changelog.queue_note(project.id, event.summary, event.event_kind)
        return TriggerActionResult(action, True, "Queued a changelog note.")

    return TriggerActionResult(action, False, f"Unknown action: {action!r}")


class RuleAwareFindingRepository:
    """Drop-in wrapper for ``storage.automation_findings.
    AutomationFindingRepository`` that evaluates rules on every successful
    ``create`` -- the one choke point every one of the 13 automation
    ``XxxService`` classes already goes through
    (``self._findings.create(project.id, finding)``), so wiring rule
    evaluation here means **none of those 13 files need to change**: they
    call the exact same interface (``create``/``get``/``get_by_run_id``/
    ``list_for_project``) whether they were handed the raw repository or
    this wrapper, and don't know or care which.
    """

    def __init__(self, repo: AutomationFindingRepository, services: Services) -> None:
        self._repo = repo
        self._services = services

    def create(self, project_id: int, finding: Finding) -> AutomationFindingRecord:
        record = self._repo.create(project_id, finding)
        event = finding_to_event(finding, project_id)
        evaluate_rules(self._services, event)
        return record

    def get(self, record_id: int) -> AutomationFindingRecord:
        return self._repo.get(record_id)

    def get_by_run_id(self, run_id: str) -> AutomationFindingRecord | None:
        return self._repo.get_by_run_id(run_id)

    def list_for_project(
        self, project_id: int, *, feature_id: str | None = None, limit: int = 20
    ) -> list[AutomationFindingRecord]:
        return self._repo.list_for_project(project_id, feature_id=feature_id, limit=limit)
