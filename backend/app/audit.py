"""Audit logging helper (Market-Viability Roadmap, Phase 6).

``record_audit_event`` only ever calls ``db.add(...)`` -- never its own
``db.commit()``. Call it from a mutating endpoint *before* that endpoint's
existing commit, so the audit row and the change it describes land in the
same database transaction: either both persist, or (on any error before
that commit) neither does. A separately-committed audit call would let the
two fall out of sync, which defeats the point of an audit trail.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import AuditLogEntry


def record_audit_event(
    db: Session,
    team_id: str,
    actor_user_id: str,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(
        team_id=team_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_json=json.dumps(metadata) if metadata else "{}",
    )
    db.add(entry)
    return entry
