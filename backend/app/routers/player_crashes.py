"""Player Crash & Error Reporting (Phase G, section 7, Core tier).

Ingestion needs no auth at all — players of a shipped game don't have Spiced
accounts — but only accepts reports for a ``project_uuid`` that's linked to
a team (see ``TeamProject``). Crash reporting only works for projects that
have opted into Small-Team Mode and linked a team, because that's the only
way Spiced has a ``project_uuid`` it can recognize at all: solo/local-only
projects never mint one, so there is nothing reachable to report against.
This is consistent with Spiced's local-first design, not an arbitrary
restriction — see ``docs/player_crash_reporting.md``.

Payload sizes are capped regardless of auth (Pydantic ``Field(max_length=…)``
rejects grossly oversized bodies outright; this router further truncates to
the tighter documented storage caps) — this is never an open, unbounded
write endpoint. Reading reports back requires auth and team membership, same
as every other team-visible resource.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import PlayerCrashReport, TeamProject, User
from app.routers.teams import _require_membership
from app.schemas import PlayerCrashReportCreate, PlayerCrashReportOut

router = APIRouter(prefix="/projects/{project_uuid}/player-crashes", tags=["player-crashes"])

# The tighter, documented storage caps — see docs/player_crash_reporting.md.
# Pydantic's Field(max_length=...) on PlayerCrashReportCreate is a looser
# outer bound that rejects wildly oversized requests before they're even
# processed; these are what's actually persisted.
MAX_ERROR_TYPE_CHARS = 200
MAX_MESSAGE_CHARS = 2000
MAX_STACK_EXCERPT_CHARS = 4000
MAX_APP_VERSION_CHARS = 100


def _require_team_linked_project(db: Session, project_uuid: str) -> TeamProject:
    link = db.query(TeamProject).filter(TeamProject.project_uuid == project_uuid).first()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "This project isn't linked to a Small-Team Mode team. Player crash reporting "
                "only works for team-linked projects — see docs/player_crash_reporting.md."
            ),
        )
    return link


@router.post("", response_model=PlayerCrashReportOut, status_code=status.HTTP_201_CREATED)
def create_player_crash_report(
    project_uuid: str,
    body: PlayerCrashReportCreate,
    db: Session = Depends(get_db),
) -> PlayerCrashReport:
    _require_team_linked_project(db, project_uuid)
    error_type = body.error_type.strip()[:MAX_ERROR_TYPE_CHARS] or "UnknownError"
    stack_excerpt = (body.stack_excerpt or "").strip()[:MAX_STACK_EXCERPT_CHARS] or None
    app_version = (body.app_version or "").strip()[:MAX_APP_VERSION_CHARS] or None
    report = PlayerCrashReport(
        project_uuid=project_uuid,
        error_type=error_type,
        message=body.message.strip()[:MAX_MESSAGE_CHARS],
        stack_excerpt=stack_excerpt,
        app_version=app_version,
        occurred_at=body.occurred_at,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("", response_model=list[PlayerCrashReportOut])
def list_player_crash_reports(
    project_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PlayerCrashReport]:
    link = _require_team_linked_project(db, project_uuid)
    _require_membership(db, link.team_id, user)
    return (
        db.query(PlayerCrashReport)
        .filter(PlayerCrashReport.project_uuid == project_uuid)
        .order_by(PlayerCrashReport.reported_at.desc())
        .all()
    )
