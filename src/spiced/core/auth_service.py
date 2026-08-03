"""Small-Team Mode session management.

Wraps SupabaseAuthClient and persists the resulting session (access token,
refresh token, user id/email) in the local app_settings table via
SettingsRepository — the same key/value store every other setting already
uses. Solo-Dev Mode never touches this; it only runs once a developer opts
into Team Mode from the UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.backend_client.auth_client import AuthSession, SupabaseAuthClient
from spiced.storage.settings import SettingsRepository

ACCESS_TOKEN_KEY = "team_mode_access_token"
REFRESH_TOKEN_KEY = "team_mode_refresh_token"
USER_ID_KEY = "team_mode_user_id"
USER_EMAIL_KEY = "team_mode_user_email"


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str


class AuthService:
    def __init__(
        self, settings: SettingsRepository, auth_client: SupabaseAuthClient | None = None
    ) -> None:
        self._settings = settings
        self._client = auth_client or SupabaseAuthClient()

    def is_configured(self) -> bool:
        return self._client.is_configured()

    def sign_up(self, email: str, password: str) -> AuthUser:
        session = self._client.sign_up(email, password)
        self._store_session(session)
        return AuthUser(id=session.user_id, email=session.email)

    def log_in(self, email: str, password: str) -> AuthUser:
        session = self._client.log_in(email, password)
        self._store_session(session)
        return AuthUser(id=session.user_id, email=session.email)

    def log_out(self) -> None:
        self._settings.set(ACCESS_TOKEN_KEY, "")
        self._settings.set(REFRESH_TOKEN_KEY, "")
        self._settings.set(USER_ID_KEY, "")
        self._settings.set(USER_EMAIL_KEY, "")

    def is_logged_in(self) -> bool:
        return bool(self._settings.get(ACCESS_TOKEN_KEY))

    def current_user(self) -> AuthUser | None:
        user_id = self._settings.get(USER_ID_KEY)
        email = self._settings.get(USER_EMAIL_KEY)
        if not user_id or not email:
            return None
        return AuthUser(id=user_id, email=email)

    def access_token(self) -> str | None:
        return self._settings.get(ACCESS_TOKEN_KEY) or None

    def _store_session(self, session: AuthSession) -> None:
        self._settings.set(ACCESS_TOKEN_KEY, session.access_token)
        self._settings.set(REFRESH_TOKEN_KEY, session.refresh_token)
        self._settings.set(USER_ID_KEY, session.user_id)
        self._settings.set(USER_EMAIL_KEY, session.email)
