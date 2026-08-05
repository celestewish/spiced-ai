"""Relevance-Based Notifications: routing rules + preferences (Phase J).

**Scope boundary (see the phase plan's sequencing note, repeated here
because it matters for how thin this router is on purpose): this is the
routing *decision* layer only. There is no inbox, no "unread" state, and
nothing here ever delivers or displays a notification to anyone -- that is
Section 9's Notification Center (Phase K), a later phase. This router only
persists (a) a team's own event-kind -> discipline routing rules, layered
over the desktop's hardcoded defaults (see ``core.notification_routing``),
and (b) each member's explicit per-event-kind opt-in/opt-out. Phase K's
future Notification Center is expected to call
``core.notification_routing.relevant_members_for_event`` (fed by this
router's data) to decide who to actually notify.**
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import EventRoutingRule, NotificationPreference, User
from app.routers.teams import _require_membership
from app.schemas import (
    EventRoutingRuleCreate,
    EventRoutingRuleOut,
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
        db.commit()
        db.refresh(existing)
        return existing
    pref = NotificationPreference(
        team_id=team_id, user_id=user.id, event_kind=body.event_kind, enabled=body.enabled
    )
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref
