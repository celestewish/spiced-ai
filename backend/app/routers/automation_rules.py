"""Cross-Feature Rules/Trigger Engine: a team's saved automation rules
(Market-Viability Roadmap, Phase 4).

Pure CRUD over ``TriggerRule`` rows, same shape as ``routers.notifications``'
routing-rules endpoints -- this router only persists rule configuration.
Evaluating a rule against an incoming event (``core.rules_engine.
evaluate_rules``) happens entirely on the desktop client; the backend has
no event bus and doesn't need one for this, matching ``EventRoutingRule``'s
own "routing decision data only, never delivers anything" scope boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import TriggerRule, User
from app.routers.teams import _require_membership
from app.schemas import TriggerRuleCreate, TriggerRuleOut

router = APIRouter(prefix="/teams/{team_id}", tags=["automation-rules"])


@router.get("/trigger-rules", response_model=list[TriggerRuleOut])
def list_trigger_rules(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TriggerRule]:
    _require_membership(db, team_id, user)
    return db.query(TriggerRule).filter(TriggerRule.team_id == team_id).all()


@router.post("/trigger-rules", response_model=TriggerRuleOut, status_code=status.HTTP_201_CREATED)
def add_trigger_rule(
    team_id: str,
    body: TriggerRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TriggerRule:
    _require_membership(db, team_id, user)
    existing = (
        db.query(TriggerRule)
        .filter(
            TriggerRule.team_id == team_id,
            TriggerRule.event_kind == body.event_kind,
            TriggerRule.action == body.action,
        )
        .first()
    )
    if existing is not None:
        return existing
    rule = TriggerRule(
        team_id=team_id,
        event_kind=body.event_kind,
        min_severity=body.min_severity,
        action=body.action,
        action_params_json=body.action_params_json,
        enabled=body.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/trigger-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trigger_rule(
    team_id: str,
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_membership(db, team_id, user)
    rule = db.get(TriggerRule, rule_id)
    if rule is None or rule.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    db.delete(rule)
    db.commit()
