"""Team CRUD, invites, and project linking."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Team, TeamMember, TeamProject, User
from app.schemas import (
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
        role="owner",
        joined_at=datetime.now(UTC),
    )
    db.add(owner)
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
    _require_membership(db, team_id, user)

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
        joined_at=datetime.now(UTC) if existing_user else None,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.get("/{team_id}/members", response_model=list[TeamMemberOut])
def list_members(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamMember]:
    _require_membership(db, team_id, user)
    return db.query(TeamMember).filter(TeamMember.team_id == team_id).all()


@router.post(
    "/{team_id}/projects", response_model=TeamProjectOut, status_code=status.HTTP_201_CREATED
)
def link_project(
    team_id: str,
    body: TeamProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamProject:
    _require_membership(db, team_id, user)
    existing = (
        db.query(TeamProject)
        .filter(TeamProject.team_id == team_id, TeamProject.project_uuid == body.project_uuid)
        .first()
    )
    if existing is not None:
        existing.name = body.name
        db.commit()
        db.refresh(existing)
        return existing
    link = TeamProject(team_id=team_id, project_uuid=body.project_uuid, name=body.name)
    db.add(link)
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
    db.delete(link)
    db.commit()
