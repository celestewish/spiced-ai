"""Billing Foundation: Stripe Checkout/Portal + webhook mirroring
(Market-Viability Roadmap, Phase 5).

Scope, stated plainly: this makes the plan a real, paid thing instead of a
free self-selected dropdown (``core.plans``/``core.usage_counter`` on the
desktop side) -- it does not add usage-based *metered* billing (per-prompt
overage charges are explicitly deferred, per the roadmap's price-sensitivity
note). Flat tiers only.

The desktop app never touches a card number: ``create_checkout_session``
returns a Stripe-hosted Checkout URL, and ``create_portal_session`` returns
a Stripe-hosted Billing Portal URL -- both opened in the user's own browser
(see ``core.billing_service`` on the desktop side). This keeps Spiced
itself outside any PCI-DSS scope beyond "redirect to Stripe's own page."

**Webhook signature verification is the one security-critical piece of
this router** (Stripe's own docs, and this codebase's plan document, both
flag failing to verify ``Stripe-Signature`` as the single most common
real-world Stripe integration mistake): ``handle_webhook`` always calls
``stripe.Webhook.construct_event`` against the raw request body before
trusting anything in the payload, and a failed verification is rejected
with 400 before any database write -- see ``test_billing.py``'s dedicated
tests for this specifically.
"""

from __future__ import annotations

from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models import ROLE_ADMIN, Subscription, User
from app.routers.teams import require_role
from app.schemas import (
    CheckoutSessionCreate,
    CheckoutSessionOut,
    PortalSessionOut,
    SubscriptionOut,
)

router = APIRouter(prefix="/billing", tags=["billing"])

_PRICE_ID_ENV_ATTR = {
    "indie": "stripe_price_id_indie",
    "studio": "stripe_price_id_studio",
}


def _latest_subscription(db: Session, user_id: str) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )


def _plan_key_for_price_id(price_id: str | None) -> str | None:
    settings = get_settings()
    if price_id == settings.stripe_price_id_indie:
        return "indie"
    if price_id == settings.stripe_price_id_studio:
        return "studio"
    return None


@router.post(
    "/checkout-session", response_model=CheckoutSessionOut, status_code=status.HTTP_201_CREATED
)
def create_checkout_session(
    body: CheckoutSessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckoutSessionOut:
    # Role-Based Permissions (Market-Viability Roadmap, Phase 6): checking
    # out your *own* subscription needs no team role at all -- it's your
    # own money. Tagging a team_id (this plan is meant to cover that team)
    # is the part that needs a gate, since it's a team-wide commitment any
    # member shouldn't be able to make unilaterally.
    if body.team_id:
        require_role(db, body.team_id, user, ROLE_ADMIN)

    settings = get_settings()
    price_id = getattr(settings, _PRICE_ID_ENV_ATTR[body.plan_key])
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Billing isn't configured for the {body.plan_key} plan yet.",
        )
    stripe.api_key = settings.stripe_secret_key

    # Reuse an existing Stripe customer for this user if one already exists
    # (from a prior subscription, even a cancelled one) rather than minting
    # a new customer record every time they check out.
    existing = _latest_subscription(db, user.id)
    customer_id = existing.stripe_customer_id if existing else None

    base_url = str(request.base_url).rstrip("/")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        customer_email=None if customer_id else user.email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/billing/success",
        cancel_url=f"{base_url}/billing/cancel",
        metadata={
            "user_id": user.id,
            "plan_key": body.plan_key,
            "team_id": body.team_id or "",
        },
    )
    return CheckoutSessionOut(checkout_url=session.url)


@router.post("/portal-session", response_model=PortalSessionOut)
def create_portal_session(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PortalSessionOut:
    subscription = _latest_subscription(db, user.id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No billing account yet -- subscribe to a plan first.",
        )
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    base_url = str(request.base_url).rstrip("/")
    portal = stripe.billing_portal.Session.create(
        customer=subscription.stripe_customer_id,
        return_url=base_url,
    )
    return PortalSessionOut(portal_url=portal.url)


@router.get("/subscription", response_model=SubscriptionOut | None)
def get_my_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subscription | None:
    return _latest_subscription(db, user.id)


@router.get("/success", response_class=HTMLResponse, include_in_schema=False)
def checkout_success() -> str:
    """Where Stripe Checkout redirects the browser after a successful
    subscription. The desktop app itself never sees this page -- it finds
    out about the new subscription by re-fetching ``GET /billing/subscription``
    (see core.billing_service) once the developer switches back to Spiced,
    and independently via the webhook above updating the mirrored row."""
    return (
        "<html><body style='font-family: sans-serif; text-align: center; padding: 4rem;'>"
        "<h1>You're all set</h1><p>Your subscription is active. You can close this tab and "
        "return to Spiced.</p></body></html>"
    )


@router.get("/cancel", response_class=HTMLResponse, include_in_schema=False)
def checkout_cancel() -> str:
    return (
        "<html><body style='font-family: sans-serif; text-align: center; padding: 4rem;'>"
        "<h1>Checkout cancelled</h1><p>No changes were made. You can close this tab and return "
        "to Spiced.</p></body></html>"
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def handle_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid webhook payload: {exc}"
        ) from exc

    event_type = event["type"]
    # StripeObject deliberately doesn't support dict methods like .get()
    # (raises AttributeError pointing at .to_dict() instead) -- the handler
    # functions below all use .get() for defensive, malformed-event-safe
    # field access, so convert to a plain (recursively-plain) dict once here.
    data = event["data"]["object"].to_dict()

    if event_type == "checkout.session.completed":
        _upsert_from_checkout_session(db, data)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        _upsert_from_stripe_subscription(db, data)
    elif event_type == "customer.subscription.deleted":
        _mark_canceled(db, data)
    # Any other event type is acknowledged (200) but otherwise ignored --
    # Stripe retries on non-2xx, and this router only cares about the
    # subscription lifecycle events above.

    return {"received": True}


def _upsert_from_checkout_session(db: Session, session: dict) -> None:
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id")
    plan_key = metadata.get("plan_key")
    team_id = metadata.get("team_id") or None
    stripe_subscription_id = session.get("subscription")
    customer_id = session.get("customer")
    if not user_id or not plan_key or not customer_id:
        return  # Not one of our checkout sessions (or malformed) -- ignore.

    existing = None
    if stripe_subscription_id:
        existing = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
            .first()
        )
    if existing is not None:
        existing.status = "active"
        existing.plan_key = plan_key
        db.commit()
        return

    db.add(
        Subscription(
            user_id=user_id,
            team_id=team_id,
            plan_key=plan_key,
            stripe_customer_id=customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status="active",
        )
    )
    db.commit()


def _upsert_from_stripe_subscription(db: Session, subscription: dict) -> None:
    stripe_subscription_id = subscription.get("id")
    if not stripe_subscription_id:
        return
    existing = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
        .first()
    )
    if existing is None:
        # An update/creation event for a subscription Spiced never recorded
        # via checkout.session.completed (e.g. created directly in the
        # Stripe Dashboard) -- nothing to update against, and there's no
        # user_id in this event shape to create a fresh row from. Ignored.
        return

    items = subscription.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else None
    plan_key = _plan_key_for_price_id(price_id)
    if plan_key:
        existing.plan_key = plan_key
    existing.status = subscription.get("status", existing.status)
    period_end = subscription.get("current_period_end")
    if period_end:
        existing.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)
    db.commit()


def _mark_canceled(db: Session, subscription: dict) -> None:
    stripe_subscription_id = subscription.get("id")
    existing = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
        .first()
    )
    if existing is not None:
        existing.status = "canceled"
        db.commit()
