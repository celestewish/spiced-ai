"""Relevance-Based Notifications: routing rules + preferences (Phase J),
plus the Notification Center's actual delivery/storage layer (Phase K,
section 9 part 1, Core tier).

The routing-rules and notification-preferences endpoints below are Phase
J's original routing *decision* layer -- unchanged, still just "which
discipline(s) does this event kind route to" plus each member's own
opt-in/opt-out (now also carrying a ``delivery`` cadence, see
``NotificationPreferenceUpdate``). What's new in this phase is everything
under ``/notifications``: an actual inbox. Creation is called by the
desktop client itself (there is no server-side event bus yet -- see
``core.team_service.TeamService._notify_event`` and its callers) once it has
already used ``core.notification_routing.relevant_members_for_event`` (fed
by this router's routing data) to decide who's relevant to one occurrence of
an event; this endpoint just persists one row per relevant recipient.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import EventRoutingRule, Notification, NotificationPreference, TeamMember, User
from app.routers.teams import _require_membership
from app.schemas import (
    EventRoutingRuleCreate,
    EventRoutingRuleOut,
    NotificationCreate,
    NotificationOut,
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
)

router = APIRouter(prefix="/teams/{team_id}", tags=["notifications"])


@router.get("/routing-rules", response_model=list[EventRoutingRuleOut])
def list_routing_rules(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[EventRoutingRule]:
    _require_membership(db, team_id, user)
    return db.query(EventRoutingRule).filter(EventRoutingRule.team_id == team_id).all()


@router.post(
    "/routing-rules", response_model=EventRoutingRuleOut, status_code=status.HTTP_201_CREATED
)
def add_routing_rule(
    team_id: str,
    body: EventRoutingRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EventRoutingRule:
    _require_membership(db, team_id, user)
    existing = (
        db.query(EventRoutingRule)
        .filter(
            EventRoutingRule.team_id == team_id,
            EventRoutingRule.event_kind == body.event_kind,
            EventRoutingRule.discipline == body.discipline,
        )
        .first()
    )
    if existing is not None:
        return existing
    rule = EventRoutingRule(
        team_id=team_id, event_kind=body.event_kind, discipline=body.discipline
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/routing-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routing_rule(
    team_id: str,
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_membership(db, team_id, user)
    rule = db.get(EventRoutingRule, rule_id)
    if rule is None or rule.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    db.delete(rule)
    db.commit()


@router.get("/notification-preferences", response_model=list[NotificationPreferenceOut])
def list_notification_preferences(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NotificationPreference]:
    """Every member's saved override for this team -- readable by any
    member, since computing "who is relevant to this event" needs
    everyone's overrides, not just the caller's own."""
    _require_membership(db, team_id, user)
    return (
        db.query(NotificationPreference).filter(NotificationPreference.team_id == team_id).all()
    )


@router.put("/notification-preferences/me", response_model=NotificationPreferenceOut)
def set_my_notification_preference(
    team_id: str,
    body: NotificationPreferenceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationPreference:
    """Self-service only -- a member can set their own override, never
    someone else's."""
    _require_membership(db, team_id, user)
    existing = (
        db.query(NotificationPreference)
        .filter(
            NotificationPreference.team_id == team_id,
            NotificationPreference.user_id == user.id,
            NotificationPreference.event_kind == body.event_kind,
        )
        .first()
    )
    if existing is not None:
        existing.enabled = body.enabled
        existing.delivery = body.delivery
        db.commit()
        db.refresh(existing)
        return existing
    pref = NotificationPreference(
        team_id=team_id,
        user_id=user.id,
        event_kind=body.event_kind,
        enabled=body.enabled,
        delivery=body.delivery,
    )
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


# --- Notification Center: the actual inbox (Phase K, section 9 part 1) -----


@router.post("/notifications", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
def create_notification(
    team_id: str,
    body: NotificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Notification:
    """Create one notification for one recipient.

    The caller must themselves be a team member (same auth+membership gate
    as every other team-scoped write in this app), and the recipient must
    also be a member of this team -- this is deliberately not an open
    "notify anyone" endpoint. There's no requirement that the caller *is*
    the recipient: this is meant to be called once per relevant member after
    ``core.notification_routing.relevant_members_for_event`` has already
    decided who's relevant, so the caller and recipient are usually
    different people.
    """
    _require_membership(db, team_id, user)
    recipient_is_member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == body.recipient_user_id)
        .first()
    )
    if recipient_is_member is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The recipient must be a member of this team.",
        )
    title = body.title.strip()[:300]
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Title can't be empty."
        )
    notification = Notification(
        team_id=team_id,
        recipient_user_id=body.recipient_user_id,
        event_kind=body.event_kind,
        title=title,
        body=body.body.strip()[:4000],
        subject_type=body.subject_type,
        subject_id=body.subject_id,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Notification]:
    """Only the signed-in user's own notifications for this team, most
    recent first -- never another member's inbox."""
    _require_membership(db, team_id, user)
    return (
        db.query(Notification)
        .filter(Notification.team_id == team_id, Notification.recipient_user_id == user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    team_id: str,
    notification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Notification:
    _require_membership(db, team_id, user)
    notification = db.get(Notification, notification_id)
    if (
        notification is None
        or notification.team_id != team_id
        or notification.recipient_user_id != user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
        )
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return notification
