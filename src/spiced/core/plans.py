"""Mock subscription plans.

These are UI labels only. Spiced does not implement real billing, accounts,
or payment in this phase, and the limits below are not enforced against any
external service. They exist so the interface can show a plan and a remaining
prompt count.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    monthly_prompts: int  # -1 means "unlimited" for display purposes.

    @property
    def is_unlimited(self) -> bool:
        return self.monthly_prompts < 0


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 25),
    "indie": Plan("indie", "Indie", 500),
    "studio": Plan("studio", "Studio", -1),
}

DEFAULT_PLAN_KEY = "free"


def get_plan(key: str | None) -> Plan:
    return PLANS.get((key or DEFAULT_PLAN_KEY).lower(), PLANS[DEFAULT_PLAN_KEY])
