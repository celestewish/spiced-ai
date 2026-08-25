"""BillingService tests: orchestration over a fake BackendClient (same
style as test_team_service.py)."""

from __future__ import annotations

import pytest

from spiced.backend_client.api_client import (
    BackendAPIError,
    NotAuthenticatedError,
    Subscription,
)
from spiced.backend_client.auth_client import AuthSession
from spiced.core.auth_service import AuthService
from spiced.core.billing_service import BillingService
from spiced.storage.database import Database
from spiced.storage.settings import SettingsRepository


class _FakeAuthClient:
    def is_configured(self) -> bool:
        return True

    def log_in(self, email: str, password: str) -> AuthSession:
        return AuthSession(access_token="jwt-1", refresh_token="r1", user_id="u1", email=email)

    def sign_up(self, email: str, password: str) -> AuthSession:
        return self.log_in(email, password)


class _FakeBackendClient:
    def __init__(self) -> None:
        self.token: str | None = None
        self.subscription: Subscription | None = None
        self.checkout_calls: list[tuple[str, str | None]] = []
        self.portal_calls = 0
        self.raise_on_get: Exception | None = None

    def set_token(self, token: str | None) -> None:
        self.token = token

    def get_subscription(self) -> Subscription | None:
        if self.raise_on_get is not None:
            raise self.raise_on_get
        return self.subscription

    def create_checkout_session(self, plan_key: str, *, team_id: str | None = None) -> str:
        if not self.token:
            raise NotAuthenticatedError("Sign in to Spiced Team Mode first.")
        self.checkout_calls.append((plan_key, team_id))
        return "https://checkout.stripe.com/test-session"

    def create_portal_session(self) -> str:
        if not self.token:
            raise NotAuthenticatedError("Sign in to Spiced Team Mode first.")
        self.portal_calls += 1
        return "https://billing.stripe.com/test-portal"


def _setup():
    db = Database(":memory:")
    settings = SettingsRepository(db)
    auth = AuthService(settings, _FakeAuthClient())
    backend = _FakeBackendClient()
    billing = BillingService(auth, backend)
    return auth, billing, backend


def test_current_subscription_none_when_not_logged_in():
    _auth, billing, backend = _setup()
    backend.subscription = Subscription(
        id="s1", user_id="u1", team_id=None, plan_key="studio", stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1", status="active", current_period_end=None,
        created_at="2026-08-24T00:00:00Z",
    )
    assert billing.current_subscription() is None
    # Never even touches the backend client when not signed in.
    assert backend.token is None


def test_current_subscription_returns_it_when_logged_in():
    auth, billing, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    backend.subscription = Subscription(
        id="s1", user_id="u1", team_id=None, plan_key="studio", stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1", status="active", current_period_end=None,
        created_at="2026-08-24T00:00:00Z",
    )

    subscription = billing.current_subscription()

    assert subscription is not None
    assert subscription.plan_key == "studio"
    assert backend.token == "jwt-1"


def test_current_subscription_swallows_backend_errors():
    auth, billing, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    backend.raise_on_get = BackendAPIError("network hiccup")

    assert billing.current_subscription() is None


def test_current_subscription_swallows_auth_errors():
    auth, billing, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    backend.raise_on_get = NotAuthenticatedError("session expired")

    assert billing.current_subscription() is None


def test_start_checkout_returns_url_and_passes_plan_key():
    auth, billing, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")

    url = billing.start_checkout("indie")

    assert url == "https://checkout.stripe.com/test-session"
    assert backend.checkout_calls == [("indie", None)]


def test_start_checkout_passes_team_id_through():
    auth, billing, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")

    billing.start_checkout("studio", team_id="team-1")

    assert backend.checkout_calls == [("studio", "team-1")]


def test_start_checkout_raises_when_not_logged_in():
    _auth, billing, _backend = _setup()
    with pytest.raises(NotAuthenticatedError):
        billing.start_checkout("indie")


def test_open_billing_portal_returns_url():
    auth, billing, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")

    url = billing.open_billing_portal()

    assert url == "https://billing.stripe.com/test-portal"
    assert backend.portal_calls == 1
