"""Test fixtures: an in-memory SQLite DB and a stubbed get_current_user.

Tests never hit the live Supabase project. ``get_db`` is overridden to use a
shared in-memory SQLite engine (StaticPool keeps one connection alive across
the test), and ``get_current_user`` is overridden so tests can pick which
user is "logged in" via the ``login_as`` fixture instead of making a real
call to Supabase Auth.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from app.auth import get_current_user, get_current_user_optional, get_or_create_user
from app.db import Base, get_db
from app.main import app
from fastapi import Depends, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _CurrentUserState:
    user_id: str | None = None
    email: str | None = None


_state = _CurrentUserState()


def _override_get_current_user(db: Session = Depends(get_db)):
    if _state.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No test user logged in."
        )
    return get_or_create_user(db, _state.user_id, _state.email)


def _override_get_current_user_optional(db: Session = Depends(get_db)):
    if _state.user_id is None:
        return None
    return get_or_create_user(db, _state.user_id, _state.email)


app.dependency_overrides[get_db] = _override_get_db
app.dependency_overrides[get_current_user] = _override_get_current_user
app.dependency_overrides[get_current_user_optional] = _override_get_current_user_optional


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def login_as():
    known_ids: dict[str, str] = {}

    def _login(email: str | None = None, user_id: str | None = None) -> str:
        if user_id is None and email is not None:
            user_id = known_ids.get(email)
        resolved_id = user_id or str(uuid.uuid4())
        resolved_email = email or f"{resolved_id}@example.com"
        known_ids[resolved_email] = resolved_id
        _state.user_id = resolved_id
        _state.email = resolved_email
        return resolved_id

    yield _login
    _state.user_id = None
    _state.email = None


@pytest.fixture
def logout():
    """Drop back to "not signed in" mid-test, without ending the test.

    Used by tests that need to check anonymous behavior (e.g. the Roadmap's
    public GETs) after already calling ``login_as`` earlier in the same test.
    """

    def _logout() -> None:
        _state.user_id = None
        _state.email = None

    return _logout
