"""Anonymous, opt-in feature-usage telemetry (Phase C, section 5).

No auth dependency anywhere in this router — telemetry is anonymous by
design, not tied to a team or account. See ``app.models.TelemetryEvent`` for
why the schema itself can't carry anything beyond a client id and an event
name.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TelemetryEvent
from app.schemas import TelemetryEventCreate, TelemetryEventOut

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("", response_model=TelemetryEventOut, status_code=status.HTTP_201_CREATED)
def create_telemetry_event(
    body: TelemetryEventCreate, db: Session = Depends(get_db)
) -> TelemetryEvent:
    event = TelemetryEvent(
        anonymous_client_id=body.anonymous_client_id.strip()[:36],
        event_name=body.event_name.strip()[:200],
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
