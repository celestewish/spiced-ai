"""Unified Task Board (Phase J, section 8 part 2, Core tier).

A single flat task list per team, optionally scoped to one team-linked
project. Auth + team membership is required throughout, mirroring
``routers.teams``'s patterns exactly (``_require_membership`` is imported,
not reimplemented). Feedback clusters / bug findings "route automatically to
the relevant role" per spec by way of the desktop client pre-filling
``assigned_discipline``/``source_type``/``source_ref`` when it calls
``POST`` from one of the "Send to Team Board" actions (see
``core.team_service.TeamService.send_finding_to_team_board`` and the
Animation/Audio/Testing screens) -- this router itself stays a plain CRUD
surface with no routing logic of its own.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import TeamTask, User
from app.routers.teams import _require_membership
from app.schemas import TeamTaskCreate, TeamTaskOut, TeamTaskUpdate

router = APIRouter(prefix="/teams/{team_id}/tasks", tags=["team-tasks"])


@router.post("", response_model=TeamTaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    team_id: str,
    body: TeamTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamTask:
    _require_membership(db, team_id, user)
    title = body.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Title can't be empty."
        )
    task = TeamTask(
        team_id=team_id,
        project_uuid=body.project_uuid,
        title=title,
        description=body.description,
        assigned_discipline=body.assigned_discipline,
        source_type=body.source_type,
        source_ref=body.source_ref,
        created_by_user_id=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[TeamTaskOut])
def list_tasks(
    team_id: str,
    project_uuid: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamTask]:
    _require_membership(db, team_id, user)
    query = db.query(TeamTask).filter(TeamTask.team_id == team_id)
    if project_uuid:
        query = query.filter(TeamTask.project_uuid == project_uuid)
    return query.order_by(TeamTask.created_at.desc()).all()


@router.patch("/{task_id}", response_model=TeamTaskOut)
def update_task(
    team_id: str,
    task_id: str,
    body: TeamTaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamTask:
    _require_membership(db, team_id, user)
    task = db.get(TeamTask, task_id)
    if task is None or task.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if body.title is not None:
        stripped = body.title.strip()
        if not stripped:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Title can't be empty."
            )
        task.title = stripped
    if body.description is not None:
        task.description = body.description
    if body.status is not None:
        task.status = body.status
    if body.assigned_discipline is not None:
        task.assigned_discipline = body.assigned_discipline
    task.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    team_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_membership(db, team_id, user)
    task = db.get(TeamTask, task_id)
    if task is None or task.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    db.delete(task)
    db.commit()
