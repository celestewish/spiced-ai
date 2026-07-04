"""AI provider boundary.

Everything the app needs from an AI backend goes through :class:`AIProvider`.
This keeps Spiced provider-agnostic and swappable (mock, Gemini, others later).
"""

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.factory import available_providers, build_provider
from spiced.ai.mock_provider import MockProvider

__all__ = [
    "AIProvider",
    "AIResponse",
    "MockProvider",
    "build_provider",
    "available_providers",
]
