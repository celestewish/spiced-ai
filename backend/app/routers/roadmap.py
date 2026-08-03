"""Open Roadmap & Feedback Loop (Phase C, section 5, stretch).

Viewing the changelog and suggestion board needs no login. Submitting a
suggestion or voting requires the same Supabase-authenticated account system
as Small-Team Mode (Phase A) — there is no separate roadmap-specific account.

``POST /roadmap/changelog`` is intentionally left open/unauthenticated for
now: there is no admin-role concept anywhere in this backend yet (Phase A
only distinguishes team owner/member, which is team-scoped and unrelated to
who may publish Spiced's own release notes). Gating "who can publish
changelog entries" would mean building a first admin system just for this
one write path, which is out of scope for this phase. This is a known,
explicitly-flagged gap rather than an oversight — see the Phase C plan.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_optional
from app.db import get_db
from app.models import ChangelogEntry, RoadmapSuggestion, RoadmapVote, User
from app.schemas import (
    ChangelogEntryCreate,
    ChangelogEntryOut,
    RoadmapSuggestionCreate,
    RoadmapSuggestionOut,
)

router = APIRouter(prefix="/roadmap", tags=["roadmap"])


@router.get("/changelog", response_model=list[ChangelogEntryOut])
def list_changelog(db: Session = Depends(get_db)) -> list[ChangelogEntry]:
    return db.query(ChangelogEntry).order_by(ChangelogEntry.published_at.desc()).all()


@router.post("/changelog", response_model=ChangelogEntryOut, status_code=status.HTTP_201_CREATED)
def create_changelog_entry(
    body: ChangelogEntryCreate, db: Session = Depends(get_db)
) -> ChangelogEntry:
    entry = ChangelogEntry(
        version_or_phase_label=body.version_or_phase_label.strip(),
        title=body.title.strip(),
        body=body.body.strip(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _serialize_suggestion(row: RoadmapSuggestion, vote_count: int, voted_by_me: bool) -> dict:
    return {
        "id": row.id,
        "author_user_id": row.author_user_id,
        "title": row.title,
        "body": row.body,
        "created_at": row.created_at,
        "vote_count": vote_count,
        "voted_by_me": voted_by_me,
    }


@router.get("/suggestions", response_model=list[RoadmapSuggestionOut])
def list_suggestions(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[dict]:
    counts = dict(
        db.query(RoadmapVote.suggestion_id, func.count(RoadmapVote.id))
        .group_by(RoadmapVote.suggestion_id)
        .all()
    )
    my_votes: set[str] = set()
    if user is not None:
        my_votes = {
            v.suggestion_id
            for v in db.query(RoadmapVote).filter(RoadmapVote.user_id == user.id).all()
        }
    rows = db.query(RoadmapSuggestion).order_by(RoadmapSuggestion.created_at.desc()).all()
    return [_serialize_suggestion(row, counts.get(row.id, 0), row.id in my_votes) for row in rows]


@router.post(
    "/suggestions", response_model=RoadmapSuggestionOut, status_code=status.HTTP_201_CREATED
)
def create_suggestion(
    body: RoadmapSuggestionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    suggestion = RoadmapSuggestion(
        author_user_id=user.id, title=body.title.strip(), body=body.body.strip()
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return _serialize_suggestion(suggestion, 0, False)


@router.post("/suggestions/{suggestion_id}/vote", status_code=status.HTTP_204_NO_CONTENT)
def vote_suggestion(
    suggestion_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    suggestion = db.get(RoadmapSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found.")
    existing = (
        db.query(RoadmapVote)
        .filter(RoadmapVote.suggestion_id == suggestion_id, RoadmapVote.user_id == user.id)
        .first()
    )
    if existing is None:
        db.add(RoadmapVote(suggestion_id=suggestion_id, user_id=user.id))
        db.commit()


@router.delete("/suggestions/{suggestion_id}/vote", status_code=status.HTTP_204_NO_CONTENT)
def unvote_suggestion(
    suggestion_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    existing = (
        db.query(RoadmapVote)
        .filter(RoadmapVote.suggestion_id == suggestion_id, RoadmapVote.user_id == user.id)
        .first()
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
