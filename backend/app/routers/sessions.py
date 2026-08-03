"""Team-visible session summaries for a team-linked project.

Posted by the desktop client when Team Mode is on and the active project is
linked to a team (see core/session_summary.py on the client). Only the
AI-produced digest text and start/end timestamps ever land here — see the
docstring on ``app.models.SessionSummary`` for why nothing else does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import SessionSummary, User
from app.routers.teams import _require_membership
from app.schemas import SessionSummaryCreate, SessionSummaryOut

router = APIRouter(prefix="/teams/{team_id}/projects/{project_uuid}/sessions", tags=["sessions"])


@router.post("", response_model=SessionSummaryOut, status_code=201)
def create_session_summary(
    team_id: str,
    project_uuid: str,
    body: SessionSummaryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionSummary:
    _require_membership(db, team_id, user)
    row = SessionSummary(
        team_id=team_id,
        project_uuid=project_uuid,
        user_id=user.id,
        started_at=body.started_at,
        ended_at=body.ended_at,
        summary_text=body.summary_text,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[SessionSummaryOut])
def list_session_summaries(
    team_id: str,
    project_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SessionSummary]:
    _require_membership(db, team_id, user)
    return (
        db.query(SessionSummary)
        .filter(SessionSummary.team_id == team_id, SessionSummary.project_uuid == project_uuid)
        .order_by(SessionSummary.created_at.desc())
        .all()
    )
