"""Economy/Balance Simulation use-case (Phase E, section 6, Stretch tier).

Dev-supplied economy data (a small, documented JSON schema — see
``ECONOMY_SCHEMA_DOC``) is run through a local, deterministic Monte-Carlo-
style simulation: N simulated playthroughs, each a greedy chooser that
spends accumulated currency on the best value-per-cost unlocked item
available at each level, with a little per-playthrough income noise so the
simulation reflects *some* variance rather than being a single fixed
calculation dressed up as N runs. Flags items that turn out to be the
greedy choice in effectively every playthrough — a "dominant strategy"
signal, not a claim about play *feel* or fun.

Deliberately modest, per the plan: a single greedy heuristic over one
declared value axis and one currency, not a general game-theory or
RPG-balance engine. ``ECONOMY_SCHEMA_DOC`` says so explicitly so the UI can
show the same honest scope note the developer sees before they paste data.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.storage.economy_simulation_reports import (
    EconomySimulationReport,
    EconomySimulationReportRepository,
)
from spiced.storage.projects import Project

DEFAULT_PLAYTHROUGHS = 200
DEFAULT_INCOME_NOISE = 0.15  # +/- 15% per-playthrough income variance
DEFAULT_DOMINANT_THRESHOLD = 0.9  # picked first in >=90% of playthroughs => "dominant"
DEFAULT_SEED = 0  # fixed by default so the same input always yields the same report

ECONOMY_SCHEMA_DOC = """Economy data format (JSON):
{
  "items": [
    {"name": "Sword", "cost": 100, "value": 15, "unlock_level": 1}
  ],
  "currency_sources": [
    {"name": "Quest Reward", "amount_per_level": 50}
  ],
  "levels": 20
}

- items[].value is your own single benefit number for that item (damage, DPS, whatever one \
metric you want the simulation to greedily optimize for) — this tool only understands one axis \
of "better," not a whole build or stat sheet.
- items[].unlock_level is optional (defaults to 1).
- currency_sources[].amount_per_level values are added together for income earned per level; \
"currency_sources" itself is optional (defaults to a flat 10/level).
- "levels" is how many levels/stages to simulate.

This only models a single-currency, single-value-axis economy where a simulated player buys \
the best value-per-cost thing they can afford each level. It cannot model multiple currencies, \
diminishing returns, crafting chains, or player skill — treat findings as "worth a look," not \
a verdict. Only useful for projects that actually have this kind of buy-with-currency \
progression system."""


class InvalidEconomyDataError(ValueError):
    """Raised when supplied JSON doesn't match the documented schema closely
    enough to simulate (missing/invalid required fields)."""


@dataclass(frozen=True)
class EconomyItem:
    name: str
    cost: float
    value: float
    unlock_level: int = 1

    @property
    def value_per_cost(self) -> float:
        return self.value / self.cost if self.cost > 0 else float("inf")


@dataclass(frozen=True)
class CurrencySource:
    name: str
    amount_per_level: float


@dataclass(frozen=True)
class EconomyInput:
    items: list[EconomyItem]
    currency_sources: list[CurrencySource]
    levels: int


def parse_economy_input(data: dict) -> EconomyInput:
    """Parse+validate the documented JSON schema. Raises InvalidEconomyDataError
    with a plain-language reason on anything that doesn't fit it."""
    if not isinstance(data, dict):
        raise InvalidEconomyDataError("Top-level economy data must be a JSON object.")

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidEconomyDataError('Missing or empty "items" list.')
    items: list[EconomyItem] = []
    for i, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise InvalidEconomyDataError(f"items[{i}] must be an object.")
        try:
            name = str(raw["name"])
            cost = float(raw["cost"])
            value = float(raw["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidEconomyDataError(
                f'items[{i}] needs a string "name" and numeric "cost"/"value": {exc}'
            ) from exc
        if cost < 0 or value < 0:
            raise InvalidEconomyDataError(f"items[{i}] cost/value must not be negative.")
        raw_unlock = raw.get("unlock_level", 1)
        try:
            unlock_level = int(raw_unlock)
        except (TypeError, ValueError) as exc:
            raise InvalidEconomyDataError(f"items[{i}] unlock_level must be an integer.") from exc
        items.append(EconomyItem(name=name, cost=cost, value=value, unlock_level=unlock_level))

    raw_sources = data.get("currency_sources", [])
    if not isinstance(raw_sources, list):
        raise InvalidEconomyDataError('"currency_sources" must be a list.')
    sources: list[CurrencySource] = []
    for i, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            raise InvalidEconomyDataError(f"currency_sources[{i}] must be an object.")
        try:
            name = str(raw["name"])
            amount = float(raw["amount_per_level"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidEconomyDataError(
                f'currency_sources[{i}] needs a string "name" and numeric '
                f'"amount_per_level": {exc}'
            ) from exc
        sources.append(CurrencySource(name=name, amount_per_level=amount))
    if not sources:
        sources = [CurrencySource(name="(default)", amount_per_level=10.0)]

    raw_levels = data.get("levels", 20)
    try:
        levels = int(raw_levels)
    except (TypeError, ValueError) as exc:
        raise InvalidEconomyDataError('"levels" must be an integer.') from exc
    if levels < 1:
        raise InvalidEconomyDataError('"levels" must be at least 1.')

    return EconomyInput(items=items, currency_sources=sources, levels=levels)


def _income_per_level(economy: EconomyInput) -> float:
    return sum(s.amount_per_level for s in economy.currency_sources)


def _simulate_one_playthrough(
    economy: EconomyInput, rng: random.Random, noise: float
) -> dict[int, str]:
    """Return {level: item_name_bought} for one greedy playthrough.

    At most one purchase per level, and each item bought at most once —
    deliberately simple (see module docstring): the affordable, unlocked,
    not-yet-owned item with the best value-per-cost is bought whenever
    accumulated currency allows.
    """
    base_income = _income_per_level(economy)
    balance = 0.0
    owned: set[str] = set()
    purchases: dict[int, str] = {}
    for level in range(1, economy.levels + 1):
        income = base_income * (1 + rng.uniform(-noise, noise))
        balance += max(income, 0.0)
        candidates = [
            item
            for item in economy.items
            if item.unlock_level <= level and item.name not in owned and item.cost <= balance
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda item: item.value_per_cost)
        balance -= best.cost
        owned.add(best.name)
        purchases[level] = best.name
    return purchases


@dataclass(frozen=True)
class DominantStrategyFinding:
    item_name: str
    from_level: int
    pick_rate: float  # fraction of playthroughs where this was the first item bought


@dataclass(frozen=True)
class EconomySimulationFindings:
    playthroughs: int
    dominant_strategies: list[DominantStrategyFinding] = field(default_factory=list)
    never_purchased: list[str] = field(default_factory=list)
    pick_rate_by_item: dict[str, float] = field(default_factory=dict)

    def as_summary_dict(self) -> dict:
        return {
            "playthroughs": self.playthroughs,
            "dominant_strategies": [
                {"item_name": d.item_name, "from_level": d.from_level, "pick_rate": d.pick_rate}
                for d in self.dominant_strategies
            ],
            "never_purchased": self.never_purchased,
            "pick_rate_by_item": self.pick_rate_by_item,
        }


def simulate_economy(
    economy: EconomyInput,
    *,
    playthroughs: int = DEFAULT_PLAYTHROUGHS,
    income_noise: float = DEFAULT_INCOME_NOISE,
    dominant_threshold: float = DEFAULT_DOMINANT_THRESHOLD,
    seed: int | None = DEFAULT_SEED,
) -> EconomySimulationFindings:
    """Run N greedy playthroughs and flag dominant/never-purchased items.

    Deterministic for a fixed ``seed`` (default 0) — the same economy data
    always produces the same report, which matters for reproducible history
    and for tests.
    """
    rng = random.Random(seed)
    first_purchase_counts: dict[str, int] = {item.name: 0 for item in economy.items}
    any_purchase_counts: dict[str, int] = {item.name: 0 for item in economy.items}

    for _ in range(playthroughs):
        purchases = _simulate_one_playthrough(economy, rng, income_noise)
        if purchases:
            first_level = min(purchases)
            first_purchase_counts[purchases[first_level]] += 1
        for name in set(purchases.values()):
            any_purchase_counts[name] += 1

    pick_rate_by_item = {
        name: (any_purchase_counts[name] / playthroughs if playthroughs else 0.0)
        for name in any_purchase_counts
    }
    never_purchased = sorted(name for name, rate in pick_rate_by_item.items() if rate == 0.0)

    dominant: list[DominantStrategyFinding] = []
    for item in economy.items:
        rate = first_purchase_counts[item.name] / playthroughs if playthroughs else 0.0
        if rate >= dominant_threshold:
            dominant.append(
                DominantStrategyFinding(
                    item_name=item.name, from_level=item.unlock_level, pick_rate=rate
                )
            )
    dominant.sort(key=lambda d: d.pick_rate, reverse=True)

    return EconomySimulationFindings(
        playthroughs=playthroughs,
        dominant_strategies=dominant,
        never_purchased=never_purchased,
        pick_rate_by_item=pick_rate_by_item,
    )


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


@dataclass(frozen=True)
class EconomySimulationReview:
    findings: EconomySimulationFindings
    response_text: str | None
    provider: str | None
    report: EconomySimulationReport | None


class EconomySimulationService:
    def __init__(self, reports: EconomySimulationReportRepository) -> None:
        self._reports = reports

    def simulate(self, data: dict) -> EconomySimulationFindings:
        """Deterministic, local-only. Works with no AI provider."""
        economy = parse_economy_input(data)
        return simulate_economy(economy)

    def analyze(
        self,
        provider: AIProvider,
        project: Project,
        data: dict,
        *,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> EconomySimulationReview:
        """Simulate, then ask the provider for a plain-language summary, and save it."""
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still see the "
                "local simulation findings without it. For a written summary, add its API key "
                "to a local .env file (see .env.example), or switch to the Mock provider in "
                "Settings."
            )
        findings = self.simulate(data)

        # Lazy import to avoid a module-level cycle: ai.prompt_templates imports
        # the dataclasses above, so this module can't import prompt_templates
        # at module load time (same pattern as core.precommit_check.run_ai_pass).
        from spiced.ai.prompt_templates import build_economy_simulation_prompt

        prompt = build_economy_simulation_prompt(findings, project_name=project.name)
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = self._reports.create(
            project_id=project.id,
            input_data=data,
            findings=findings.as_summary_dict(),
            ai_summary=response.text,
            provider=response.provider,
        )
        return EconomySimulationReview(
            findings=findings,
            response_text=response.text,
            provider=response.provider,
            report=report,
        )

    def history(self, project_id: int, limit: int = 20) -> list[EconomySimulationReport]:
        return self._reports.list_for_project(project_id, limit=limit)
