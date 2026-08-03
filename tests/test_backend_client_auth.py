"""SupabaseAuthClient tests. All HTTP is faked via httpx.MockTransport — no
real network call is ever made in tests.
"""

from __future__ import annotations

import httpx
import pytest

from spiced.backend_client.auth_client import AuthError, SupabaseAuthClient


def _client(handler) -> SupabaseAuthClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return SupabaseAuthClient(
        base_url="https://project.supabase.co",
        anon_key="anon-key",
        http_client=http_client,
    )


def test_log_in_success_returns_session():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/v1/token"
        assert request.headers["apikey"] == "anon-key"
        return httpx.Response(
            200,
            json={
                "access_token": "jwt-abc",
                "refresh_token": "refresh-abc",
                "expires_at": 1234567890,
                "user": {"id": "user-1", "email": "dev@example.com"},
            },
        )

    session = _client(handler).log_in("dev@example.com", "hunter2")
    assert session.access_token == "jwt-abc"
    assert session.user_id == "user-1"
    assert session.email == "dev@example.com"


def test_sign_up_success_returns_session():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/v1/signup"
        return httpx.Response(
            200,
            json={
                "access_token": "jwt-new",
                "refresh_token": "refresh-new",
                "user": {"id": "user-2", "email": "new@example.com"},
            },
        )

    session = _client(handler).sign_up("new@example.com", "hunter2")
    assert session.access_token == "jwt-new"
    assert session.user_id == "user-2"


def test_sign_up_without_confirmed_session_raises_friendly_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "user-3", "email": "pending@example.com"},
        )

    with pytest.raises(AuthError, match="confirm your email"):
        _client(handler).sign_up("pending@example.com", "hunter2")


def test_log_in_wrong_password_raises_with_supabase_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"}
        )

    with pytest.raises(AuthError, match="Invalid login credentials"):
        _client(handler).log_in("dev@example.com", "wrong")


def test_network_error_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AuthError, match="Could not reach Supabase Auth"):
        _client(handler).log_in("dev@example.com", "hunter2")


def test_not_configured_raises_before_making_a_request():
    client = SupabaseAuthClient(base_url="", anon_key="", http_client=httpx.Client())
    with pytest.raises(AuthError, match="isn't configured"):
        client.log_in("dev@example.com", "hunter2")


def test_is_configured_reflects_url_and_key():
    assert SupabaseAuthClient(base_url="https://x.supabase.co", anon_key="k").is_configured()
    assert not SupabaseAuthClient(base_url="", anon_key="").is_configured()
