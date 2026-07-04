"""Provider selection.

Keeping construction in one place makes the boundary swappable and keeps the
UI from importing concrete providers directly.
"""

from __future__ import annotations

from spiced.ai.base import AIProvider
from spiced.ai.gemini_provider import GeminiProvider
from spiced.ai.mock_provider import MockProvider


def available_providers() -> list[str]:
    return ["mock", "gemini"]


def build_provider(name: str) -> AIProvider:
    key = (name or "mock").strip().lower()
    if key == "gemini":
        return GeminiProvider()
    if key == "mock":
        return MockProvider()
    raise ValueError(f"Unknown AI provider: {name!r}")
