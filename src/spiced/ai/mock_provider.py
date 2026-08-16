"""A deterministic, offline provider used for development and tests.

The voice is calm and professional: a helpful colleague, not a hype machine.
"""

from __future__ import annotations

from collections.abc import Callable

from spiced.ai.base import AIProvider, AIResponse

_STREAM_CHUNK_WORDS = 6


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

    def generate_stream(self, prompt: str, on_chunk: Callable[[str], None]) -> AIResponse:
        """Fake-chunks the canned reply (word groups, no artificial delay)
        instead of delivering it whole. This is the only provider path the
        offscreen test suite actually exercises, so it's also the only place
        multi-chunk accumulation gets real coverage -- emitting a single
        chunk here would mean the whole streaming pipeline ships untested."""
        response = self.generate(prompt)
        words = response.text.split(" ")
        for i in range(0, len(words), _STREAM_CHUNK_WORDS):
            piece = " ".join(words[i : i + _STREAM_CHUNK_WORDS])
            if i + _STREAM_CHUNK_WORDS < len(words):
                piece += " "
            on_chunk(piece)
        return response

    def display_name(self) -> str:
        return "Mock (offline)"
