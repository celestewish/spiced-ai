"""Billing Foundation endpoint tests (Market-Viability Roadmap, Phase 5).

Stripe's own network calls (Checkout Session / Billing Portal Session
creation) are monkeypatched -- these tests never hit the real Stripe API,
even in test mode. Webhook signature verification, by contrast, is
deliberately exercised for real: ``_sign_payload`` replicates Stripe's own
publicly documented signing scheme (``t=<timestamp>,v1=<hmac-sha256>``) so
``stripe.Webhook.construct_event`` itself does the verifying, not a stub --
this is the one piece of this router explicitly named (in this repo's
Market-Viability Roadmap) as the single most common real-world Stripe
integration mistake, so it gets tested against the real verification path,
not a mocked one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import app.routers.billing as billing_module

WEBHOOK_SECRET = "whsec_test_secret"
PRICE_ID_INDIE = "price_indie_test"
PRICE_ID_STUDIO = "price_studio_test"


@dataclass
class _FakeSettings:
    stripe_secret_key: str = "sk_test_fake"
    stripe_webhook_secret: str = WEBHOOK_SECRET
    stripe_price_id_indie: str = PRICE_ID_INDIE
    stripe_price_id_studio: str = PRICE_ID_STUDIO


def _patch_settings(monkeypatch, **overrides):
    settings = _FakeSettings(**overrides)
    monkeypatch.setattr(billing_module, "get_settings", lambda: settings)
    return settings


def _sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Stripe's own documented webhook signature scheme -- see
    https://docs.stripe.com/webhooks#verify-manually. Deliberately
    hand-rolled with stdlib hmac/hashlib rather than any stripe test helper,
    so this test is checking the *real* verification path
    (stripe.Webhook.construct_event) rather than a mocked stand-in for it.
    """
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


class _FakeCheckoutSession:
    def __init__(self, url="https://checkout.stripe.com/test-session", **kwargs):
        self.url = url
        self.kwargs = kwargs


class _FakePortalSession:
    def __init__(self, url="https://billing.stripe.com/test-portal", **kwargs):
        self.url = url
        self.kwargs = kwargs


def test_create_checkout_session_returns_stripe_url(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeCheckoutSession()

    monkeypatch.setattr(billing_module.stripe.checkout.Session, "create", fake_create)

    response = client.post("/billing/checkout-session", json={"plan_key": "indie"})

    assert response.status_code == 201
    assert response.json()["checkout_url"] == "https://checkout.stripe.com/test-session"
    assert captured["line_items"] == [{"price": PRICE_ID_INDIE, "quantity": 1}]
    assert captured["metadata"]["plan_key"] == "indie"
    assert captured["customer_email"] == "dev@example.com"
    assert captured["customer"] is None


def test_create_checkout_session_missing_price_id_returns_503(client, login_as, monkeypatch):
    _patch_settings(monkeypatch, stripe_price_id_studio="")
    login_as(email="dev@example.com")

    response = client.post("/billing/checkout-session", json={"plan_key": "studio"})

    assert response.status_code == 503


def test_create_checkout_session_requires_auth(client, monkeypatch):
    _patch_settings(monkeypatch)
    response = client.post("/billing/checkout-session", json={"plan_key": "indie"})
    assert response.status_code == 401


def test_create_checkout_session_with_team_id_requires_admin_role(client, login_as, monkeypatch):
    """Role-Based Permissions (Phase 6): checking out your own plan needs no
    team role, but tagging a team_id (a team-wide billing commitment) does."""
    _patch_settings(monkeypatch)
    member_id = login_as(email="member@example.com")
    client.get("/teams")
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    client.post(f"/teams/{team['id']}/invite", json={"email": "member@example.com"})

    login_as(user_id=member_id, email="member@example.com")
    response = client.post(
        "/billing/checkout-session", json={"plan_key": "indie", "team_id": team["id"]}
    )

    assert response.status_code == 403


def test_create_checkout_session_with_team_id_allowed_for_admin(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()

    def fake_create(**kwargs):
        return _FakeCheckoutSession()

    monkeypatch.setattr(billing_module.stripe.checkout.Session, "create", fake_create)

    response = client.post(
        "/billing/checkout-session", json={"plan_key": "indie", "team_id": team["id"]}
    )

    assert response.status_code == 201


def test_get_my_subscription_none_when_no_subscription(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    response = client.get("/billing/subscription")
    assert response.status_code == 200
    assert response.json() is None


def test_create_portal_session_requires_existing_subscription(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    response = client.post("/billing/portal-session")
    assert response.status_code == 404


def _complete_checkout(client, login_as, monkeypatch, *, plan_key="indie"):
    """Drive checkout-session creation through to a webhook-recorded
    Subscription row -- the same two-step flow a real Stripe integration
    goes through (create session, then Stripe calls the webhook once the
    customer pays)."""
    _patch_settings(monkeypatch)
    user_id = login_as(email="dev@example.com")

    payload = json.dumps(
        {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_test123",
                    "subscription": "sub_test123",
                    "metadata": {"user_id": user_id, "plan_key": plan_key, "team_id": ""},
                }
            },
        }
    ).encode()
    signature = _sign_payload(payload, WEBHOOK_SECRET)

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 200
    return user_id


def test_webhook_valid_signature_creates_subscription(client, login_as, monkeypatch):
    _complete_checkout(client, login_as, monkeypatch)

    sub = client.get("/billing/subscription").json()
    assert sub is not None
    assert sub["plan_key"] == "indie"
    assert sub["stripe_customer_id"] == "cus_test123"
    assert sub["stripe_subscription_id"] == "sub_test123"
    assert sub["status"] == "active"


def test_webhook_rejects_invalid_signature(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    payload = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": "t=123,v1=deadbeef", "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert client.get("/billing/subscription").json() is None


def test_webhook_rejects_missing_signature_header(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    payload = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()

    response = client.post(
        "/billing/webhook", content=payload, headers={"content-type": "application/json"}
    )

    assert response.status_code == 400


def test_webhook_rejects_signature_for_a_tampered_payload(client, login_as, monkeypatch):
    """The signature must be computed over the exact bytes received --
    signing one payload and sending a different one must fail, proving this
    isn't just checking "is there a signature header" but actually verifying
    payload integrity."""
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    original = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()
    signature = _sign_payload(original, WEBHOOK_SECRET)
    tampered = json.dumps({"id": "evt_1_tampered", "type": "checkout.session.completed"}).encode()

    response = client.post(
        "/billing/webhook",
        content=tampered,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )

    assert response.status_code == 400


def test_webhook_rejects_signature_from_the_wrong_secret(client, login_as, monkeypatch):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    payload = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()
    signature = _sign_payload(payload, "whsec_a_completely_different_secret")

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )

    assert response.status_code == 400


def test_webhook_customer_subscription_updated_updates_status_and_plan(
    client, login_as, monkeypatch
):
    _complete_checkout(client, login_as, monkeypatch, plan_key="indie")

    payload = json.dumps(
        {
            "id": "evt_2",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test123",
                    "status": "past_due",
                    "current_period_end": 1735689600,
                    "items": {"data": [{"price": {"id": PRICE_ID_STUDIO}}]},
                }
            },
        }
    ).encode()
    signature = _sign_payload(payload, WEBHOOK_SECRET)

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 200

    sub = client.get("/billing/subscription").json()
    assert sub["status"] == "past_due"
    assert sub["plan_key"] == "studio"  # upgraded price id maps back to the studio plan
    assert sub["current_period_end"] is not None


def test_webhook_customer_subscription_deleted_marks_canceled(client, login_as, monkeypatch):
    _complete_checkout(client, login_as, monkeypatch)

    payload = json.dumps(
        {
            "id": "evt_3",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_test123"}},
        }
    ).encode()
    signature = _sign_payload(payload, WEBHOOK_SECRET)

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 200

    sub = client.get("/billing/subscription").json()
    assert sub["status"] == "canceled"


def test_webhook_ignores_unhandled_event_types_but_still_returns_200(
    client, login_as, monkeypatch
):
    _patch_settings(monkeypatch)
    login_as(email="dev@example.com")
    payload = json.dumps(
        {"id": "evt_4", "type": "invoice.paid", "data": {"object": {}}}
    ).encode()
    signature = _sign_payload(payload, WEBHOOK_SECRET)

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )

    assert response.status_code == 200


def test_create_portal_session_returns_url_once_subscribed(client, login_as, monkeypatch):
    _complete_checkout(client, login_as, monkeypatch)

    def fake_create(**kwargs):
        assert kwargs["customer"] == "cus_test123"
        return _FakePortalSession()

    monkeypatch.setattr(billing_module.stripe.billing_portal.Session, "create", fake_create)

    response = client.post("/billing/portal-session")

    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://billing.stripe.com/test-portal"


def test_create_checkout_session_reuses_existing_stripe_customer(client, login_as, monkeypatch):
    user_id = _complete_checkout(client, login_as, monkeypatch)
    login_as(user_id=user_id, email="dev@example.com")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeCheckoutSession()

    monkeypatch.setattr(billing_module.stripe.checkout.Session, "create", fake_create)

    client.post("/billing/checkout-session", json={"plan_key": "studio"})

    assert captured["customer"] == "cus_test123"
    assert captured["customer_email"] is None
