"""Local prompt-usage counter with mock plan awareness."""

from __future__ import annotations

from dataclasses import dataclass

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
    """Bridges the usage log and the mock plan for display in the UI."""

    def __init__(self, usage: UsageRepository, settings: SettingsRepository) -> None:
        self._usage = usage
        self._settings = settings

    def current_plan(self) -> Plan:
        return get_plan(self._settings.get(PLAN_SETTING_KEY))

    def set_plan(self, plan_key: str) -> None:
        self._settings.set(PLAN_SETTING_KEY, plan_key)

    def record_prompt(self, provider: str, kind: str = "chat") -> None:
        self._usage.record(provider, kind)

    def status(self) -> UsageStatus:
        return UsageStatus(plan=self.current_plan(), used=self._usage.total())
