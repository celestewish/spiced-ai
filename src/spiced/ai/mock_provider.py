"""A deterministic, offline provider used for development and tests.

The voice is calm and professional: a helpful colleague, not a hype machine.
"""

from __future__ import annotations

from spiced.ai.base import AIProvider, AIResponse


class MockProvider(AIProvider):
    name = "mock"

    def is_available(self) -> bool:
        return True

    def generate(self, prompt: str) -> AIResponse:
        prompt = prompt.strip()
        if not prompt:
            text = "I'm here whenever you want to talk something through. What's on your mind?"
        else:
            text = (
                "Thanks for sharing that. I'm running in offline mock mode right now, "
                "so I can't reason about your build yet, but here's how I'd approach it:\n\n"
                f"1. Restate the goal: \"{prompt}\"\n"
                "2. Reproduce it reliably before changing anything.\n"
                "3. Narrow down the smallest failing case, then we look at it together.\n\n"
                "Connect a real provider in Settings when you're ready and I can go deeper."
            )
        return AIResponse(text=text, provider=self.name, model="mock-1")

    def display_name(self) -> str:
        return "Mock (offline)"
