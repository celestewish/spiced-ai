"""JWT verification via Supabase Auth, plus lazy local user upsert.

Rather than verifying JWT signatures ourselves, every request's bearer token
is forwarded to Supabase Auth's ``GET /auth/v1/user`` endpoint. A 200 response
confirms the token is valid and tells us who it belongs to; anything else is
treated as unauthenticated. This keeps the backend from needing to manage or
rotate a JWT secret itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import TeamMember, User

_bearer_scheme = HTTPBearer(auto_error=False)


async def _fetch_supabase_user(token: str, settings: Settings) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            settings.supabase_user_endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key,
            },
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )
    return response.json()


def _attach_pending_invites(db: Session, user: User) -> None:
    pending = (
        db.query(TeamMember)
        .filter(TeamMember.user_id.is_(None), TeamMember.invited_email == user.email)
        .all()
    )
    if not pending:
        return
    now = datetime.now(UTC)
    for membership in pending:
        membership.user_id = user.id
        membership.joined_at = now
    db.commit()


def get_or_create_user(db: Session, user_id: str, email: str) -> User:
    """Upsert the local user row for a verified (user_id, email) pair.

    Also resolves any pending team invites addressed to this email. Runs on
    every authenticated request (not just first sight) so an invite sent
    after someone's first login still gets attached the next time they're
    seen — the filter in ``_attach_pending_invites`` is a no-op once there is
    nothing pending, so this stays cheap.
    """
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.email != email:
        user.email = email
        db.commit()

    _attach_pending_invites(db, user)
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    payload = await _fetch_supabase_user(credentials.credentials, settings)
    user_id = payload.get("id")
    email = payload.get("email")
    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase user response missing id/email.",
        )

    return get_or_create_user(db, user_id, email)
