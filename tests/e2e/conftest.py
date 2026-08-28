"""Shared fixtures for the E2E suite (see ../../E2E_TEST_PLAN.md).

Every E2E test drives a real ``Services(":memory:")`` instance -- the same
composition root the desktop app itself uses (see ``app.services.Services``)
-- against real fixture repos/projects on disk. The one thing that can't be
real is the Spiced backend (``BackendClient`` talks to a remote HTTP API not
present in this repo): per E2E_TEST_PLAN.md's own instruction to avoid
hitting real network/payment endpoints, ``TeamService``/``BillingService``
here are wired to ``E2EFakeBackendClient`` below instead of a real
``BackendClient``, same technique ``tests/test_rules_engine.py``'s
``_services()`` helper already uses for the equivalent unit tests.

``E2EFakeBackendClient`` additionally simulates two things a real backend
does that this repo's code does not implement locally:

* Role-based 403s (``_require_role``) -- ``core.team_service.TeamService.
  my_role``'s own docstring says permission enforcement is the backend's
  ``require_role`` check, not anything client-side. This fake reproduces
  that boundary so RBAC scenarios (E2E_TEST_PLAN.md §5) can assert on it,
  without this repo containing (or this suite exercising) the real backend.
* Stripe subscriptions (``subscriptions``) -- ``core.billing_service.
  BillingService`` only ever forwards to the backend; the fake supplies
  scriptable ``Subscription`` rows so plan-gating scenarios (§4, rewritten
  to match the real flat-tier design -- see that section's module docstring
  for why) don't need a real Stripe account.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from spiced.app.services import Services
from spiced.backend_client.api_client import (
    BackendAPIError,
    Notification,
    NotificationPreference,
    Subscription,
    Team,
    TeamMember,
    TeamProject,
    TeamTask,
    TriggerRule,
)
from spiced.backend_client.auth_client import AuthSession
from spiced.core.auth_service import AuthService
from spiced.core.billing_service import BillingService
from spiced.core.team_service import TeamService
from spiced.core.usage_counter import UsageCounter
from spiced.storage.usage import UsageRepository

_NOW = "2026-08-27T00:00:00Z"

# --- Fake auth + backend --------------------------------------------------


class _FakeAuthClient:
    """User id is derived deterministically from the email's local part so
    E2E tests can predict it (and pre-seed a matching TeamMember/Subscription
    on the fake backend) without a round trip. Same shape as ``test_rules_
    engine.py``'s ``_FakeAuthClient``, just with a stable id instead of a
    fixed ``"u1"``."""

    def is_configured(self) -> bool:
        return True

    def log_in(self, email: str, password: str) -> AuthSession:
        user_id = f"user-{email.split('@')[0]}"
        return AuthSession(
            access_token=f"jwt-{user_id}",
            refresh_token=f"r-{user_id}",
            user_id=user_id,
            email=email,
        )

    def sign_up(self, email: str, password: str) -> AuthSession:
        return self.log_in(email, password)


class E2EFakeBackendClient:
    """In-memory double for ``BackendClient``, covering every call surface
    ``TeamService``/``BillingService`` touch. See module docstring for why
    this exists and what it deliberately simulates beyond a plain fake."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.teams: dict[str, Team] = {}
        self.members: dict[str, list[TeamMember]] = {}
        self.tasks: list[TeamTask] = []
        self.notifications: list[Notification] = []
        self.trigger_rules: list[TriggerRule] = []
        self.linked_projects: list[TeamProject] = []
        self.routing_rules: list = []
        self.notification_prefs: list[NotificationPreference] = []
        self.subscriptions: dict[str, Subscription] = {}
        self._seq = 0

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def set_token(self, token: str | None) -> None:
        self.token = token

    def _current_user_id(self) -> str | None:
        if not self.token or not self.token.startswith("jwt-"):
            return None
        return self.token[len("jwt-") :]

    def _require_role(self, team_id: str, allowed_roles: set[str]) -> None:
        """Stand-in for the real backend's ``require_role`` dependency (see
        ``app.routers.teams`` on the backend, referenced from ``TeamService.
        remove_member``'s docstring) -- raises the same
        ``BackendAPIError`` shape ``BackendClient._request`` raises for a
        real HTTP 403, so callers exercise the identical error path."""
        user_id = self._current_user_id()
        member = next((m for m in self.members.get(team_id, []) if m.user_id == user_id), None)
        if member is None or member.role not in allowed_roles:
            raise BackendAPIError("Spiced backend request failed (HTTP 403).")

    # --- teams / members ---------------------------------------------------

    def create_team(self, name: str) -> Team:
        team = Team(
            id=self._id("team"),
            name=name,
            created_by=self._current_user_id() or "u1",
            created_at=_NOW,
        )
        self.teams[team.id] = team
        self.members.setdefault(team.id, [])
        return team

    def list_teams(self) -> list[Team]:
        return list(self.teams.values())

    def invite_member(self, team_id: str, email: str, role: str = "member") -> TeamMember:
        self._require_role(team_id, {"owner", "admin"})
        member = TeamMember(
            id=self._id("m"),
            team_id=team_id,
            user_id=None,
            invited_email=email,
            role=role,
            discipline=None,
            joined_at=None,
            created_at=_NOW,
        )
        self.members.setdefault(team_id, []).append(member)
        return member

    def list_members(self, team_id: str) -> list[TeamMember]:
        return self.members.get(team_id, [])

    def remove_member(self, team_id: str, member_id: str) -> None:
        self._require_role(team_id, {"owner", "admin"})
        self.members[team_id] = [m for m in self.members.get(team_id, []) if m.id != member_id]

    def link_project(self, team_id: str, project_uuid: str, name: str) -> TeamProject:
        link = TeamProject(
            id=self._id("link"),
            team_id=team_id,
            project_uuid=project_uuid,
            name=name,
            created_at=_NOW,
        )
        self.linked_projects.append(link)
        return link

    def list_projects(self, team_id: str) -> list[TeamProject]:
        return [p for p in self.linked_projects if p.team_id == team_id]

    def unlink_project(self, team_id: str, project_uuid: str) -> None:
        self.linked_projects = [
            p
            for p in self.linked_projects
            if not (p.team_id == team_id and p.project_uuid == project_uuid)
        ]

    # --- billing (Phase 5) ---------------------------------------------------

    def get_subscription(self) -> Subscription | None:
        return self.subscriptions.get(self._current_user_id())

    def create_checkout_session(self, plan_key: str, *, team_id: str | None = None) -> str:
        return f"https://checkout.stripe.example/fake-session/{plan_key}"

    def create_portal_session(self) -> str:
        return "https://billing.stripe.example/fake-portal"

    # --- trigger rules / routing / notifications / tasks ---------------------

    def list_trigger_rules(self, team_id: str) -> list[TriggerRule]:
        return [r for r in self.trigger_rules if r.team_id == team_id]

    def add_trigger_rule(
        self, team_id, event_kind, min_severity, action, *, action_params_json="{}", enabled=True
    ) -> TriggerRule:
        rule = TriggerRule(
            id=self._id("tr"),
            team_id=team_id,
            event_kind=event_kind,
            min_severity=min_severity,
            action=action,
            action_params_json=action_params_json,
            enabled=enabled,
            created_at=_NOW,
        )
        self.trigger_rules.append(rule)
        return rule

    def delete_trigger_rule(self, team_id: str, rule_id: str) -> None:
        self.trigger_rules = [r for r in self.trigger_rules if r.id != rule_id]

    def list_routing_rules(self, team_id: str) -> list:
        return [r for r in self.routing_rules if r.team_id == team_id]

    def list_notification_preferences(self, team_id: str) -> list[NotificationPreference]:
        return [p for p in self.notification_prefs if p.team_id == team_id]

    def create_task(
        self,
        team_id,
        title,
        *,
        description=None,
        project_uuid=None,
        assigned_discipline=None,
        source_type="manual",
        source_ref=None,
    ) -> TeamTask:
        task = TeamTask(
            id=self._id("task"),
            team_id=team_id,
            project_uuid=project_uuid,
            title=title,
            description=description,
            status="open",
            assigned_discipline=assigned_discipline,
            source_type=source_type,
            source_ref=source_ref,
            created_by_user_id=self._current_user_id() or "u1",
            created_at=_NOW,
            updated_at=_NOW,
        )
        self.tasks.append(task)
        return task

    def list_tasks(self, team_id: str, project_uuid: str | None = None) -> list[TeamTask]:
        rows = [t for t in self.tasks if t.team_id == team_id]
        if project_uuid:
            rows = [t for t in rows if t.project_uuid == project_uuid]
        return rows

    def create_notification(
        self,
        team_id,
        recipient_user_id,
        event_kind,
        title,
        body,
        *,
        subject_type=None,
        subject_id=None,
    ) -> Notification:
        n = Notification(
            id=self._id("n"),
            team_id=team_id,
            recipient_user_id=recipient_user_id,
            event_kind=event_kind,
            title=title,
            body=body,
            subject_type=subject_type,
            subject_id=subject_id,
            created_at=_NOW,
            read_at=None,
        )
        self.notifications.append(n)
        return n

    def list_notifications(self, team_id: str) -> list[Notification]:
        return [n for n in self.notifications if n.team_id == team_id]


# --- Services wiring -------------------------------------------------------


def build_e2e_services() -> tuple[Services, E2EFakeBackendClient]:
    """A real ``Services(":memory:")`` with Team/Billing wired to the fake
    backend above. Everything else (projects, rules engine, changelog,
    findings storage, ...) is the genuine production wiring."""
    services = Services(db_path=":memory:")
    backend = E2EFakeBackendClient()
    services.auth = AuthService(services._settings, _FakeAuthClient())
    services.billing = BillingService(services.auth, backend)
    services.usage = UsageCounter(
        UsageRepository(services.db), services._settings, services.billing
    )
    services.teams = TeamService(services.auth, services.projects, backend)
    return services, backend


@dataclass(frozen=True)
class E2EAccount:
    email: str
    user_id: str
    token: str
    role: str
    tier: str


# Free has no Subscription row at all (UsageCounter falls back to the local
# mock plan) -- Small-Team/Studio map onto core.plans' real plan keys.
_TIER_PLAN_KEY = {"small-team": "indie", "studio": "studio"}


def seed_team_with_tiered_accounts(
    services: Services, backend: E2EFakeBackendClient, project
) -> tuple[Team, str, dict[str, E2EAccount]]:
    """Seed one team, linked to ``project``, with 3 members across both the
    RBAC role axis (owner/admin/member) and the billing tier axis
    (free/small-team/studio) -- E2E_TEST_PLAN.md §0's "at least 3 test
    accounts across tiers" requirement. Returns (team, project_uuid,
    {role: account})."""
    services.auth.log_in("owner@example.com", "hunter2")
    team = services.teams.create_team("Fixture Crew")
    services.teams.link_active_project(team.id, project.id, project.name)
    project_uuid = services.projects.get_project(project.id).project_uuid

    accounts: dict[str, E2EAccount] = {}
    for email, role, tier in (
        ("owner@example.com", "owner", "studio"),
        ("admin@example.com", "admin", "small-team"),
        ("member@example.com", "member", "free"),
    ):
        user_id = f"user-{email.split('@')[0]}"
        member = TeamMember(
            id=f"m-{user_id}",
            team_id=team.id,
            user_id=user_id,
            invited_email=None,
            role=role,
            discipline=None,
            joined_at=_NOW,
            created_at=_NOW,
        )
        backend.members.setdefault(team.id, []).append(member)
        if tier in _TIER_PLAN_KEY:
            backend.subscriptions[user_id] = Subscription(
                id=f"sub-{user_id}",
                user_id=user_id,
                team_id=team.id,
                plan_key=_TIER_PLAN_KEY[tier],
                stripe_customer_id=f"cus-{user_id}",
                stripe_subscription_id=f"sub-stripe-{user_id}",
                status="active",
                current_period_end=None,
                created_at=_NOW,
            )
        accounts[role] = E2EAccount(
            email=email, user_id=user_id, token=f"jwt-{user_id}", role=role, tier=tier
        )
    return team, project_uuid, accounts


def log_in_as(services: Services, account: E2EAccount) -> None:
    services.auth.log_in(account.email, "hunter2")


# --- Git fixture repo (E2E_TEST_PLAN.md §0) --------------------------------


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _write_png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (32, 32)) -> None:
    Image.new("RGB", size, color).save(path, format="PNG")


def make_git_fixture_repo(root: Path) -> Path:
    """A real, local (no remote) throwaway git repo with a realistic commit
    history, one binary asset, and one submodule -- E2E_TEST_PLAN.md §0."""
    sub = root / "fixture-submodule"
    sub.mkdir()
    _git("init", "-q", cwd=sub)
    _git("config", "user.email", "e2e@example.com", cwd=sub)
    _git("config", "user.name", "E2E Fixture", cwd=sub)
    (sub / "lib.gd").write_text("extends Node\n", encoding="utf-8")
    _git("add", "lib.gd", cwd=sub)
    _git("commit", "-q", "-m", "submodule: initial commit", cwd=sub)

    repo = root / "fixture-repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "e2e@example.com", cwd=repo)
    _git("config", "user.name", "E2E Fixture", cwd=repo)

    (repo / "README.md").write_text("# Fixture Game\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-q", "-m", "initial commit", cwd=repo)

    (repo / "src").mkdir()
    (repo / "src" / "main.gd").write_text("extends Node\n", encoding="utf-8")
    _git("add", "src/main.gd", cwd=repo)
    _git("commit", "-q", "-m", "add main script", cwd=repo)

    (repo / "art").mkdir()
    _write_png(repo / "art" / "icon.png", (200, 40, 40))
    _git("add", "art/icon.png", cwd=repo)
    _git("commit", "-q", "-m", "add icon asset", cwd=repo)

    # Local-file submodules are refused by default since git 2.38.1
    # (CVE-2022-39253) unless explicitly allowed -- safe here since both
    # repos are throwaway fixtures under the same tmp_path.
    _git("-c", "protocol.file.allow=always", "submodule", "add", str(sub), "vendor/lib", cwd=repo)
    _git("commit", "-q", "-m", "add vendored submodule", cwd=repo)

    return repo


def add_large_binary(repo: Path, relative_path: str, size_bytes: int) -> Path:
    """A sparse file of exactly ``size_bytes`` -- for the 50MB+ oversized-
    asset scenario (§1.3) without actually writing that many bytes."""
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(b"\0")
    return target


# --- Godot fixture project (E2E_TEST_PLAN.md §0) ---------------------------

_MINIMAL_PROJECT_GODOT = """config_version=5

[application]

config/name="Fixture Game"
config/features=PackedStringArray("4.7")
run/main_scene="res://main.tscn"
"""

_MINIMAL_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")
"""

_MINIMAL_GD_SCRIPT = "extends Node2D\n\n\nfunc _ready() -> None:\n\tpass\n"


def make_godot_fixture_project(root: Path, name: str = "fixture-godot") -> Path:
    """A minimal but real Godot 4 project: ``project.godot``, one ``.tscn``
    scene, one ``.gd`` script, one imported (image) asset -- E2E_TEST_PLAN.md
    §0."""
    proj = root / name
    proj.mkdir()
    (proj / "project.godot").write_text(_MINIMAL_PROJECT_GODOT, encoding="utf-8")
    (proj / "main.tscn").write_text(_MINIMAL_TSCN, encoding="utf-8")
    (proj / "main.gd").write_text(_MINIMAL_GD_SCRIPT, encoding="utf-8")
    assets = proj / "assets"
    assets.mkdir()
    _write_png(assets / "icon.png", (40, 200, 40))
    return proj


# --- Unreal fixture project (not in E2E_TEST_PLAN.md's scope -- added per
# the discovered-gap decision; see the final report) ------------------------

_MINIMAL_UPROJECT = json.dumps(
    {
        "FileVersion": 3,
        "EngineAssociation": "5.3",
        "Category": "",
        "Description": "",
        "Modules": [{"Name": "FixtureGame", "Type": "Runtime", "LoadingPhase": "Default"}],
    }
)


def make_unreal_fixture_project(root: Path, name: str = "fixture-unreal") -> Path:
    proj = root / name
    proj.mkdir()
    (proj / "FixtureGame.uproject").write_text(_MINIMAL_UPROJECT, encoding="utf-8")
    (proj / "Content").mkdir()
    source_dir = proj / "Source" / "FixtureGame"
    source_dir.mkdir(parents=True)
    (source_dir / "FixtureGame.Build.cs").write_text("// stub build rules\n", encoding="utf-8")
    return proj
