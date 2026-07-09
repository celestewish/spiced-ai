"""Provider selection.

Keeping construction in one place makes the boundary swappable and keeps the
UI from importing concrete providers directly. OpenAI is the default; the mock
provider stays available for free, offline testing, and Gemini is optional.
"""

from __future__ import annotations

from spiced.ai.base import AIProvider
from spiced.ai.gemini_provider import GeminiProvider
from spiced.ai.mock_provider import MockProvider
from spiced.ai.openai_provider import OpenAIProvider

DEFAULT_PROVIDER = "openai"


def available_providers() -> list[str]:
    return ["openai", "mock", "gemini"]


def build_provider(name: str) -> AIProvider:
    key = (name or DEFAULT_PROVIDER).strip().lower()
    if key == "openai":
        return OpenAIProvider()
    if key == "gemini":
        return GeminiProvider()
    if key == "mock":
        return MockProvider()
    raise ValueError(f"Unknown AI provider: {name!r}")
