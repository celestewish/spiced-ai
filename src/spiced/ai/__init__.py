"""AI provider boundary.

Everything the app needs from an AI backend goes through :class:`AIProvider`.
This keeps Spiced provider-agnostic and swappable. OpenAI is the default; the
mock provider is always available for free offline testing, and Gemini is
optional.
"""

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.factory import DEFAULT_PROVIDER, available_providers, build_provider
from spiced.ai.mock_provider import MockProvider
from spiced.ai.openai_provider import OpenAIProvider

__all__ = [
    "AIProvider",
    "AIResponse",
    "MockProvider",
    "OpenAIProvider",
    "DEFAULT_PROVIDER",
    "build_provider",
    "available_providers",
]
