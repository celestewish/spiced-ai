"""E2E §5 -- Small-Team Mode RBAC (E2E_TEST_PLAN.md), local-boundary only.

Per the explicit direction on scope: real permission enforcement is the
Spiced backend's own ``require_role`` check (see ``core.team_service.
TeamService.my_role``'s docstring, quoted in the final report), on a backend
that does not exist in this repo. ``E2EFakeBackendClient._require_role``
(``tests/e2e/conftest.py``) reproduces that boundary's *shape* -- a 403-style
``BackendAPIError`` for an insufficient role -- so these tests can assert on
how ``TeamService`` and its callers react to that response. They do **not**
exercise the real server-side authorization logic itself, which lives
outside this repo and is out of scope here.
"""

from __future__ import annotations

import pytest
from conftest import _NOW, build_e2e_services, log_in_as, seed_team_with_tiered_accounts

from spiced.backend_client.api_client import BackendAPIError


def _team_and_accounts(tmp_path):
    services, backend = build_e2e_services()
    project = services.projects.create_project("Fixture Game", engine="Godot")
    team, project_uuid, accounts = seed_team_with_tiered_accounts(services, backend, project)
    return services, backend, project, team, project_uuid, accounts


# --- §5.1: admin role performs a restricted action -- succeeds -------------


def test_5_1_admin_role_can_remove_a_member(tmp_path):
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)
    log_in_as(services, accounts["admin"])
    target = backend.members[team.id][2]  # the "member" account
    assert target.role == "member"

    services.teams.remove_member(team.id, target.id)  # must not raise

    remaining_ids = {m.id for m in backend.list_members(team.id)}
    assert target.id not in remaining_ids


def test_5_1_owner_role_can_remove_a_member(tmp_path):
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)
    log_in_as(services, accounts["owner"])
    target = backend.members[team.id][1]  # the "admin" account

    services.teams.remove_member(team.id, target.id)  # must not raise

    remaining_ids = {m.id for m in backend.list_members(team.id)}
    assert target.id not in remaining_ids


# --- §5.2: non-admin attempts same action -- blocked with a clear error ----


def test_5_2_member_role_is_blocked_from_removing_a_member(tmp_path):
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)
    log_in_as(services, accounts["member"])
    target = backend.members[team.id][1]  # the "admin" account

    # A typed, catchable error -- not a bare Exception/500-shaped crash.
    with pytest.raises(BackendAPIError) as exc_info:
        services.teams.remove_member(team.id, target.id)
    assert "403" in str(exc_info.value)

    # Nothing was actually removed.
    remaining_ids = {m.id for m in backend.list_members(team.id)}
    assert target.id in remaining_ids


def test_5_2_member_role_is_blocked_from_inviting_a_new_member(tmp_path):
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)
    log_in_as(services, accounts["member"])

    with pytest.raises(BackendAPIError):
        services.teams.invite_member(team.id, "newperson@example.com")


# --- my_role(): UI-hiding read path (the one thing genuinely local here) ---


def test_my_role_reports_the_signed_in_users_real_role(tmp_path):
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)

    log_in_as(services, accounts["member"])
    assert services.teams.my_role(team.id) == "member"

    log_in_as(services, accounts["admin"])
    assert services.teams.my_role(team.id) == "admin"


def test_my_role_returns_none_when_signed_out(tmp_path):
    services, backend, project, team, _uuid, _accounts = _team_and_accounts(tmp_path)
    # seed_team_with_tiered_accounts leaves the "owner" session logged in
    # (it has to sign in to create/link the team) -- explicitly sign out to
    # exercise the actually-signed-out case this test is about.
    services.auth.log_out()
    assert services.teams.my_role(team.id) is None


def test_my_role_returns_none_rather_than_raising_on_backend_hiccup(tmp_path, monkeypatch):
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)
    log_in_as(services, accounts["member"])

    def _boom(team_id):
        raise BackendAPIError("simulated outage")

    monkeypatch.setattr(backend, "list_members", _boom)

    assert services.teams.my_role(team.id) is None  # never raises


# --- §5.3: role change mid-session ------------------------------------------


def test_5_3_role_change_takes_effect_on_next_check_without_relogin(tmp_path):
    """Confirmed expected behavior for this codebase: my_role() re-fetches
    members on every call (no caching), so a role change is visible on the
    very next check with no re-login required -- the alternative branch
    §5.3 allows for ("or, if it does require re-auth, that's the confirmed
    behavior") does not apply here."""
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)
    log_in_as(services, accounts["member"])
    assert services.teams.my_role(team.id) == "member"

    # Promote the member to admin directly on the backend (simulating an
    # owner's action elsewhere), same session, no re-login.
    members = backend.members[team.id]
    idx = next(i for i, m in enumerate(members) if m.user_id == accounts["member"].user_id)
    from spiced.backend_client.api_client import TeamMember

    members[idx] = TeamMember(
        id=members[idx].id,
        team_id=team.id,
        user_id=members[idx].user_id,
        invited_email=None,
        role="admin",
        discipline=None,
        joined_at=_NOW,
        created_at=_NOW,
    )

    assert services.teams.my_role(team.id) == "admin"


# --- §5.4: RBAC combined with billing tier ----------------------------------


def test_5_4_studio_only_action_requires_both_role_and_tier(tmp_path):
    """A concrete stand-in for 'a permission that's Studio-tier-only':
    real Stripe checkout/portal access (core.billing_service) is gated on
    being signed in at all, and a studio-only feature would additionally
    need the resolved plan to be 'studio' -- both checks are independent
    and both must pass. Demonstrated here since no single built-in action
    in this codebase currently combines a team role check with a plan
    check (see the final report's note on this gap)."""
    services, backend, project, team, _uuid, accounts = _team_and_accounts(tmp_path)

    # admin role, but free tier -- role gate passes, tier gate must not.
    log_in_as(services, accounts["admin"])
    assert services.teams.my_role(team.id) == "admin"
    assert services.usage.current_plan().key != "studio"

    # owner role AND studio tier (seeded that way in conftest) -- both pass.
    log_in_as(services, accounts["owner"])
    assert services.teams.my_role(team.id) == "owner"
    assert services.usage.current_plan().key == "studio"


# --- §5.5: rule created by a lower-permission user ---------------------------


def test_5_5_rule_aware_repository_has_no_creator_permission_scope_to_respect():
    """Rewritten: core.rules_engine has no concept of "the user who
    configured this TriggerRule" at evaluation time at all --
    ``_perform_action`` runs with the app's own local Services instance,
    never an impersonated per-member scope, and ``TriggerRule`` itself
    (backend_client.api_client) carries no creator/user_id field. So there
    is no elevated-vs-creator-scope distinction in the code to test; a rule
    a "member"-role user configures runs exactly the same way a rule an
    "owner" configures does. Flagged as a real gap, not silently skipped."""
    from spiced.backend_client.api_client import TriggerRule

    field_names = set(TriggerRule.__dataclass_fields__)
    assert "created_by_user_id" not in field_names
    assert "creator_role" not in field_names
