"""Team CRUD, invites, and project linking.

Role-Based Permissions (Market-Viability Roadmap, Phase 6): ``require_role``
below is what makes ``TeamMember.role`` load-bearing rather than the
vestigial field it was before this phase -- see ``app.models``' ``ROLE_*``
constants and ``TeamMember``'s docstring. Every mutating endpoint that
changes team membership, roles, or project links now also records an
``AuditLogEntry`` (``app.audit.record_audit_event``) in the same commit as
the change itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit import record_audit_event
from app.auth import get_current_user
from app.db import get_db
from app.models import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_RANK,
    AuditLogEntry,
    Team,
    TeamMember,
    TeamProject,
    User,
)
from app.schemas import (
    AuditLogEntryOut,
    MemberDisciplineUpdate,
    TeamCreate,
    TeamInviteRequest,
    TeamMemberOut,
    TeamOut,
    TeamProjectCreate,
    TeamProjectOut,
)

router = APIRouter(prefix="/teams", tags=["teams"])


def _require_membership(db: Session, team_id: str, user: User) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
        .first()
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this team."
        )
    return team


def require_role(db: Session, team_id: str, user: User, min_role: str) -> TeamMember:
    """Like ``_require_membership``, but also requires the caller's own
    role to rank at or above ``min_role`` (``ROLE_RANK``: member < admin <
    owner). Raises 404 for an unknown team (same as ``_require_membership``
    -- don't leak team existence to a non-member), 403 for "you're a member
    but not senior enough."

    Returns the caller's own ``TeamMember`` row (not the ``Team``) since
    every current caller needs to know who they are for an audit-log
    entry's ``actor_user_id`` or a self-protection check (e.g. "can't
    remove yourself"), not just that the team exists.
    """
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
        .first()
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this team."
        )
    if ROLE_RANK.get(member.role, 0) < ROLE_RANK.get(min_role, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This action requires the '{min_role}' role or higher.",
        )
    return member


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    body: TeamCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Team:
    team = Team(name=body.name.strip(), created_by=user.id)
    db.add(team)
    db.flush()
    owner = TeamMember(
        team_id=team.id,
        user_id=user.id,
        role=ROLE_OWNER,
        joined_at=datetime.now(UTC),
    )
    db.add(owner)
    record_audit_event(db, team.id, user.id, "team.created", target_type="team", target_id=team.id)
    db.commit()
    db.refresh(team)
    return team


@router.get("", response_model=list[TeamOut])
def list_teams(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Team]:
    return (
        db.query(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user.id)
        .all()
    )


@router.post("/{team_id}/invite", response_model=TeamMemberOut, status_code=status.HTTP_201_CREATED)
def invite_member(
    team_id: str,
    body: TeamInviteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamMember:
    require_role(db, team_id, user, ROLE_ADMIN)

    if body.role == ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Can't invite someone directly as owner -- a team has exactly one, "
            "set at creation.",
        )
    if body.role not in (ROLE_ADMIN, ROLE_MEMBER):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown role: {body.role!r}.",
        )

    # There is no email-sending infrastructure yet, so an invite is recorded
    # as a pending TeamMember row keyed by email. If the invited address
    # already belongs to a known user it is attached immediately; otherwise
    # it stays pending (user_id is null, invited_email is set) until someone
    # authenticates with that email — see
    # app.auth._attach_pending_invites, which runs on every request.
    existing_user = db.query(User).filter(User.email == body.email).first()

    duplicate_filter = [TeamMember.team_id == team_id]
    if existing_user is not None:
        duplicate = (
            db.query(TeamMember)
            .filter(*duplicate_filter, TeamMember.user_id == existing_user.id)
            .first()
        )
    else:
        duplicate = (
            db.query(TeamMember)
            .filter(*duplicate_filter, TeamMember.invited_email == body.email)
            .first()
        )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person is already a member or already invited.",
        )

    member = TeamMember(
        team_id=team_id,
        user_id=existing_user.id if existing_user else None,
        invited_email=None if existing_user else body.email,
        role=body.role,
        discipline=body.discipline,
        joined_at=datetime.now(UTC) if existing_user else None,
    )
    db.add(member)
    db.flush()
    record_audit_event(
        db,
        team_id,
        user.id,
        "member.invited",
        target_type="team_member",
        target_id=member.id,
        metadata={"email": body.email, "role": body.role},
    )
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    team_id: str,
    member_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Admin+ only. A member can't remove themselves through this endpoint
    (leaving a team, if ever added, would be its own self-service action
    with different semantics), and the team's owner can never be removed --
    only left by deleting the team itself, which this API doesn't expose."""
    actor = require_role(db, team_id, user, ROLE_ADMIN)
    member = db.get(TeamMember, member_id)
    if member is None or member.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    if member.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="You can't remove yourself.",
        )
    if member.role == ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The team owner can't be removed.",
        )
    record_audit_event(
        db,
        team_id,
        user.id,
        "member.removed",
        target_type="team_member",
        target_id=member.id,
        metadata={"email": member.email, "role": member.role},
    )
    db.delete(member)
    db.commit()


@router.get("/{team_id}/members", response_model=list[TeamMemberOut])
def list_members(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamMember]:
    _require_membership(db, team_id, user)
    return db.query(TeamMember).filter(TeamMember.team_id == team_id).all()


@router.patch("/{team_id}/members/me", response_model=TeamMemberOut)
def set_my_discipline(
    team_id: str,
    body: MemberDisciplineUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamMember:
    """Self-service discipline update (Phase J, Role-Based Dashboards) --
    any signed-in member of the team can set their own discipline, no
    approval needed. Deliberately left outside Phase 6's require_role gate
    below: discipline is a skill tag, not a privilege, and self-service
    changes to your own tag were never the risk that phase is about."""
    _require_membership(db, team_id, user)
    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found.")
    member.discipline = body.discipline
    record_audit_event(
        db, team_id, user.id, "member.discipline_set",
        target_type="team_member", target_id=member.id,
        metadata={"discipline": body.discipline},
    )
    db.commit()
    db.refresh(member)
    return member


@router.patch("/{team_id}/members/{member_id}", response_model=TeamMemberOut)
def set_member_discipline(
    team_id: str,
    member_id: str,
    body: MemberDisciplineUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamMember:
    """Teammate-set discipline path (Phase J) -- kept as permissive as it
    always was even after Phase 6 introduced require_role for invite_member/
    remove_member/project linking below: discipline is a skill tag, not a
    privilege, so it was never the kind of mutation that phase's threat
    model is about."""
    _require_membership(db, team_id, user)
    member = db.get(TeamMember, member_id)
    if member is None or member.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    member.discipline = body.discipline
    record_audit_event(
        db, team_id, user.id, "member.discipline_set",
        target_type="team_member", target_id=member.id,
        metadata={"discipline": body.discipline, "set_by": "teammate"},
    )
    db.commit()
    db.refresh(member)
    return member


@router.post(
    "/{team_id}/projects", response_model=TeamProjectOut, status_code=status.HTTP_201_CREATED
)
def link_project(
    team_id: str,
    body: TeamProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamProject:
    # Deliberately still any-member, not require_role: linking your own
    # project so teammates can see it is exactly the kind of everyday
    # action Phase 6's role gate isn't meant to block -- see this file's
    # module docstring on what did/didn't get a role requirement and why.
    _require_membership(db, team_id, user)
    existing = (
        db.query(TeamProject)
        .filter(TeamProject.team_id == team_id, TeamProject.project_uuid == body.project_uuid)
        .first()
    )
    if existing is not None:
        existing.name = body.name
        record_audit_event(
            db, team_id, user.id, "project.link_updated",
            target_type="team_project", target_id=existing.id,
            metadata={"project_uuid": body.project_uuid, "name": body.name},
        )
        db.commit()
        db.refresh(existing)
        return existing
    link = TeamProject(team_id=team_id, project_uuid=body.project_uuid, name=body.name)
    db.add(link)
    db.flush()
    record_audit_event(
        db, team_id, user.id, "project.linked",
        target_type="team_project", target_id=link.id,
        metadata={"project_uuid": body.project_uuid, "name": body.name},
    )
    db.commit()
    db.refresh(link)
    return link


@router.get("/{team_id}/projects", response_model=list[TeamProjectOut])
def list_projects(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamProject]:
    _require_membership(db, team_id, user)
    return db.query(TeamProject).filter(TeamProject.team_id == team_id).all()


@router.delete("/{team_id}/projects/{project_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project(
    team_id: str,
    project_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_membership(db, team_id, user)
    link = (
        db.query(TeamProject)
        .filter(TeamProject.team_id == team_id, TeamProject.project_uuid == project_uuid)
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found.")
    record_audit_event(
        db, team_id, user.id, "project.unlinked",
        target_type="team_project", target_id=link.id,
        metadata={"project_uuid": project_uuid},
    )
    db.delete(link)
    db.commit()


@router.get("/{team_id}/audit-log", response_model=list[AuditLogEntryOut])
def list_audit_log(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AuditLogEntry]:
    """Admin+ only -- the audit trail itself is exactly the kind of thing a
    regular member shouldn't need or get to browse, same reasoning as
    invite/remove being admin+ gated above."""
    require_role(db, team_id, user, ROLE_ADMIN)
    return (
        db.query(AuditLogEntry)
        .filter(AuditLogEntry.team_id == team_id)
        .order_by(AuditLogEntry.created_at.desc())
        .all()
    )
