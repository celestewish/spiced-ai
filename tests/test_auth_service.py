"""AuthService tests: session persistence in app_settings via a fake auth client."""

from __future__ import annotations

from spiced.backend_client.auth_client import AuthSession
from spiced.core.auth_service import AuthService
from spiced.storage.database import Database
from spiced.storage.settings import SettingsRepository


class _FakeAuthClient:
    def __init__(self, session: AuthSession | None = None, configured: bool = True) -> None:
        self._session = session
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def sign_up(self, email: str, password: str) -> AuthSession:
        return self._session

    def log_in(self, email: str, password: str) -> AuthSession:
        return self._session


def _service(session: AuthSession | None = None, configured: bool = True) -> AuthService:
    db = Database(":memory:")
    return AuthService(SettingsRepository(db), _FakeAuthClient(session, configured))


def test_not_logged_in_by_default():
    service = _service()
    assert not service.is_logged_in()
    assert service.current_user() is None
    assert service.access_token() is None


def test_log_in_persists_session_and_marks_logged_in():
    session = AuthSession(
        access_token="jwt-1", refresh_token="refresh-1", user_id="u1", email="dev@example.com"
    )
    service = _service(session)
    user = service.log_in("dev@example.com", "hunter2")
    assert user.email == "dev@example.com"
    assert service.is_logged_in()
    assert service.access_token() == "jwt-1"
    assert service.current_user().id == "u1"


def test_sign_up_persists_session_like_log_in():
    session = AuthSession(
        access_token="jwt-2", refresh_token="refresh-2", user_id="u2", email="new@example.com"
    )
    service = _service(session)
    service.sign_up("new@example.com", "hunter2")
    assert service.is_logged_in()
    assert service.current_user().email == "new@example.com"


def test_log_out_clears_session():
    session = AuthSession(
        access_token="jwt-1", refresh_token="refresh-1", user_id="u1", email="dev@example.com"
    )
    service = _service(session)
    service.log_in("dev@example.com", "hunter2")
    service.log_out()
    assert not service.is_logged_in()
    assert service.current_user() is None
    assert service.access_token() is None


def test_is_configured_reflects_client():
    assert _service(configured=True).is_configured()
    assert not _service(configured=False).is_configured()
