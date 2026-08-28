from spiced.backend_client.api_client import Subscription
from spiced.core.usage_counter import UsageCounter
from spiced.storage.database import Database
from spiced.storage.settings import SettingsRepository
from spiced.storage.usage import UsageRepository


def _counter() -> UsageCounter:
    db = Database(":memory:")
    return UsageCounter(UsageRepository(db), SettingsRepository(db))


def _subscription(plan_key: str = "studio", status: str = "active") -> Subscription:
    return Subscription(
        id="sub-1", user_id="u1", team_id=None, plan_key=plan_key,
        stripe_customer_id="cus_1", stripe_subscription_id="sub_stripe_1", status=status,
        current_period_end=None, created_at="2026-08-24T00:00:00Z",
    )


class _FakeBillingService:
    def __init__(self, subscription: Subscription | None) -> None:
        self._subscription = subscription

    def current_subscription(self) -> Subscription | None:
        return self._subscription


def _counter_with_billing(subscription: Subscription | None) -> UsageCounter:
    db = Database(":memory:")
    return UsageCounter(
        UsageRepository(db), SettingsRepository(db), _FakeBillingService(subscription)
    )


def test_default_plan_is_free():
    counter = _counter()
    assert counter.current_plan().key == "free"


def test_records_increment_usage_and_reduce_remaining():
    counter = _counter()
    start = counter.status()
    assert start.used == 0
    assert start.remaining == start.plan.monthly_prompts

    counter.record_prompt("mock")
    counter.record_prompt("mock")
    status = counter.status()
    assert status.used == 2
    assert status.remaining == status.plan.monthly_prompts - 2


def test_studio_plan_is_unlimited():
    counter = _counter()
    counter.set_plan("studio")
    counter.record_prompt("mock")
    status = counter.status()
    assert status.plan.is_unlimited
    assert status.remaining is None
    assert "Unlimited" in status.summary()


def test_remaining_never_negative():
    counter = _counter()
    counter.set_plan("free")
    for _ in range(counter.current_plan().monthly_prompts + 5):
        counter.record_prompt("mock")
    assert counter.status().remaining == 0


# --- Billing Foundation: real plan from a Stripe subscription once signed
# in (Market-Viability Roadmap, Phase 5) -------------------------------------


def test_active_subscription_plan_overrides_local_mock_setting():
    counter = _counter_with_billing(_subscription(plan_key="studio", status="active"))
    counter.set_plan("free")  # the local mock setting, deliberately ignored below

    assert counter.current_plan().key == "studio"


def test_trialing_and_past_due_subscriptions_still_grant_their_plan():
    for status in ("trialing", "past_due"):
        counter = _counter_with_billing(_subscription(plan_key="indie", status=status))
        assert counter.current_plan().key == "indie"


def test_canceled_subscription_falls_back_to_local_mock_setting():
    counter = _counter_with_billing(_subscription(plan_key="studio", status="canceled"))
    counter.set_plan("indie")

    assert counter.current_plan().key == "indie"


def test_no_subscription_falls_back_to_local_mock_setting():
    """A signed-in user who's never subscribed (billing service returns
    None) behaves exactly like a solo user for plan purposes."""
    counter = _counter_with_billing(None)
    counter.set_plan("indie")

    assert counter.current_plan().key == "indie"


def test_solo_user_never_touches_billing_service():
    """No billing service wired up at all -- the constructor default --
    must behave identically to before Phase 5, with zero new dependency."""
    counter = _counter()
    counter.set_plan("indie")
    assert counter.current_plan().key == "indie"
