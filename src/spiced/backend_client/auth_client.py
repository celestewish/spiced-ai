"""Supabase Auth REST client: sign up, log in.

Talks directly to Supabase Auth (not the Spiced backend) using the public
anon key, exactly like a browser-based client would. The desktop app never
verifies the JWT itself — it just stores it and sends it as a Bearer token to
the Spiced backend, which verifies it against Supabase on each request.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from spiced.backend_client import config


class AuthError(RuntimeError):
    """Raised when Supabase Auth rejects a signup/login attempt."""


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str
    user_id: str
    email: str
    expires_at: int | None = None


class SupabaseAuthClient:
    def __init__(
        self,
        base_url: str | None = None,
        anon_key: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or config.supabase_url()).rstrip("/")
        self._anon_key = anon_key or config.supabase_anon_key()
        self._http = http_client or httpx.Client(timeout=15.0)
        self._owns_http = http_client is None

    def is_configured(self) -> bool:
        return bool(self._base_url and self._anon_key)

    def sign_up(self, email: str, password: str) -> AuthSession:
        return self._token_request(f"{self._base_url}/auth/v1/signup", email, password)

    def log_in(self, email: str, password: str) -> AuthSession:
        return self._token_request(
            f"{self._base_url}/auth/v1/token?grant_type=password", email, password
        )

    def _token_request(self, url: str, email: str, password: str) -> AuthSession:
        if not self.is_configured():
            raise AuthError(
                "Team Mode isn't configured. Set SUPABASE_URL and SUPABASE_ANON_KEY "
                "in your environment or local .env file."
            )
        try:
            response = self._http.post(
                url,
                headers={
                    "apikey": self._anon_key,
                    "Content-Type": "application/json",
                },
                json={"email": email, "password": password},
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"Could not reach Supabase Auth: {exc}") from exc

        payload = _safe_json(response)
        if response.status_code >= 400:
            raise AuthError(_error_message(payload, response.status_code))
        return self._parse_session(payload)

    @staticmethod
    def _parse_session(payload: dict) -> AuthSession:
        access_token = payload.get("access_token")
        user = payload.get("user") or {}
        user_id = user.get("id")
        email = user.get("email")
        if not access_token or not user_id or not email:
            # Signup with email confirmation enabled returns a user but no
            # session until the address is confirmed.
            raise AuthError(
                "Signed up, but no active session was returned — check your inbox to "
                "confirm your email, then log in."
            )
        return AuthSession(
            access_token=access_token,
            refresh_token=payload.get("refresh_token", ""),
            user_id=user_id,
            email=email,
            expires_at=payload.get("expires_at"),
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {}


def _error_message(payload: dict, status_code: int) -> str:
    message = payload.get("msg") or payload.get("error_description") or payload.get("error")
    if message:
        return str(message)
    return f"Supabase Auth request failed (HTTP {status_code})."
