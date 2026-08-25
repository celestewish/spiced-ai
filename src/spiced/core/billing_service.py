"""Billing Foundation use-cases (Market-Viability Roadmap, Phase 5).

Thin orchestration over ``BackendClient``, same shape as ``TeamService``'s
``_synced_client()`` pattern -- keeps the caller's JWT in sync with
``AuthService`` before every call. Only meaningful when signed in to Small-
Team Mode; every method here is a no-op-returning-None/[] for a solo/
offline user rather than raising, so nothing in the desktop app needs a
special-cased "am I signed in" check before calling into this service --
see ``core.usage_counter.UsageCounter.current_plan`` for the one caller
that actually depends on that behavior.
"""

from __future__ import annotations

from spiced.backend_client.api_client import (
    BackendAPIError,
    BackendClient,
    NotAuthenticatedError,
    Subscription,
)
from spiced.core.auth_service import AuthService


class BillingService:
    def __init__(self, auth: AuthService, api_client: BackendClient | None = None) -> None:
        self._auth = auth
        self._client = api_client or BackendClient()

    def _synced_client(self) -> BackendClient:
        self._client.set_token(self._auth.access_token())
        return self._client

    def current_subscription(self) -> Subscription | None:
        """The signed-in user's most recent subscription, or ``None`` for a
        solo/offline user, one who's never subscribed, or on any backend/
        auth hiccup -- never raises, matching every other best-effort
        network read in this app (e.g. ``TeamService.find_team_for_
        project``)."""
        if not self._auth.is_logged_in():
            return None
        try:
            return self._synced_client().get_subscription()
        except (BackendAPIError, NotAuthenticatedError):
            return None

    def start_checkout(self, plan_key: str, *, team_id: str | None = None) -> str:
        """Returns a Stripe-hosted Checkout URL to open in the user's own
        browser -- the desktop app never touches a card number. Raises
        ``NotAuthenticatedError``/``BackendAPIError`` (unlike
        ``current_subscription``) since a caller explicitly starting a
        purchase flow needs to know if it failed, not silently see nothing
        happen."""
        return self._synced_client().create_checkout_session(plan_key, team_id=team_id)

    def open_billing_portal(self) -> str:
        """Returns a Stripe-hosted Billing Portal URL (manage/cancel an
        existing subscription, update the payment method, view invoices).
        Raises the same way ``start_checkout`` does."""
        return self._synced_client().create_portal_session()
