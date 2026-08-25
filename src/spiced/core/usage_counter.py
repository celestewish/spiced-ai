"""Local prompt-usage counter, with a real plan source once signed in
(Market-Viability Roadmap, Phase 5).

Prompt *counting* stays exactly as it always was -- a local, per-machine
tally (``UsageRepository``), never sent anywhere. What Phase 5 changes is
where the *plan* itself comes from: a solo/offline developer still picks
any plan for free from ``PLAN_SETTING_KEY`` (clearly a preview, per the
Settings screen's own copy) -- Spiced doesn't gate a local-only, no-account
workflow behind a purchase. Once signed in to Small-Team Mode, though, the
plan comes from the developer's real Stripe subscription
(``core.billing_service.BillingService``) instead of a self-selected
dropdown, which is the actual gap the roadmap's report named ("every
feature built on a mock counter needs retrofitting"). Usage-based *metered*
billing (per-prompt overage) stays explicitly deferred -- flat tiers only.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.core.billing_service import BillingService
from spiced.core.plans import Plan, get_plan
from spiced.storage.settings import SettingsRepository
from spiced.storage.usage import UsageRepository

PLAN_SETTING_KEY = "plan"


@dataclass(frozen=True)
class UsageStatus:
    plan: Plan
    used: int

    @property
    def remaining(self) -> int | None:
        """Prompts left this cycle, or None when the plan is unlimited."""
        if self.plan.is_unlimited:
            return None
        return max(self.plan.monthly_prompts - self.used, 0)

    def summary(self) -> str:
        if self.plan.is_unlimited:
            return f"{self.plan.label} plan  ·  {self.used} used  ·  Unlimited"
        return (
            f"{self.plan.label} plan  ·  {self.remaining} of "
            f"{self.plan.monthly_prompts} prompts remaining"
        )


class UsageCounter:
    """Bridges the usage log and the current plan for display in the UI."""

    def __init__(
        self,
        usage: UsageRepository,
        settings: SettingsRepository,
        billing: BillingService | None = None,
    ) -> None:
        self._usage = usage
        self._settings = settings
        self._billing = billing

    def current_plan(self) -> Plan:
        """The real plan from an active Stripe subscription once signed in
        (``BillingService.current_subscription``, itself already a safe
        no-op for a solo/offline user); falls back to the local mock
        setting whenever there's no billing service wired up, no
        subscription, or the subscription isn't currently usable (e.g.
        canceled) -- same "never block, always show something sensible"
        default this whole app follows."""
        if self._billing is not None:
            subscription = self._billing.current_subscription()
            if subscription is not None and subscription.is_usable:
                return get_plan(subscription.plan_key)
        return get_plan(self._settings.get(PLAN_SETTING_KEY))

    def set_plan(self, plan_key: str) -> None:
        """Sets the local *preview* plan only -- has no effect on a real
        Stripe subscription once signed in, since ``current_plan`` prefers
        that over this setting. Solo/offline users can still freely preview
        any plan's limits, per this feature's original mock design."""
        self._settings.set(PLAN_SETTING_KEY, plan_key)

    def record_prompt(self, provider: str, kind: str = "chat") -> None:
        self._usage.record(provider, kind)

    def status(self) -> UsageStatus:
        return UsageStatus(plan=self.current_plan(), used=self._usage.total())
