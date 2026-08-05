"""Comment Threads on Assets/Builds (Phase J, section 8 part 2, Phase 2 tier).

Create/list-by-subject, auth + team membership required throughout, mirroring
``routers.teams``'s patterns. ``subject_type``/``subject_id`` together
identify the thing being commented on (a ``TeamTask``, a local Known Issue,
etc.) -- see ``app.models.Comment``'s docstring for why ``subject_id`` is a
plain string rather than a foreign key.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Comment, User
from app.routers.teams import _require_membership
from app.schemas import CommentCreate, CommentOut

router = APIRouter(prefix="/teams/{team_id}/comments", tags=["comments"])


@router.post("", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def create_comment(
    team_id: str,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Comment:
    _require_membership(db, team_id, user)
    text = body.body.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Comment body can't be empty."
        )
    comment = Comment(
        team_id=team_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        author_user_id=user.id,
        body=text,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("", response_model=list[CommentOut])
def list_comments(
    team_id: str,
    subject_type: str,
    subject_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Comment]:
    _require_membership(db, team_id, user)
    return (
        db.query(Comment)
        .filter(
            Comment.team_id == team_id,
            Comment.subject_type == subject_type,
            Comment.subject_id == subject_id,
        )
        .order_by(Comment.created_at.asc())
        .all()
    )
