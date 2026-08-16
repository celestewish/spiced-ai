"""Abstract AI provider interface."""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AIResponse:
    """A single reply from a provider."""

    text: str
    provider: str
    model: str | None = None


class AIProvider(abc.ABC):
    """The boundary between Spiced and any AI backend.

    Implementations must be side-effect free with respect to the user's
    project files: Spiced never sends project files to a provider without an
    explicit, separate confirmation step (not part of Phase 0).
    """

    #: Short, stable identifier used in settings and the usage log.
    name: str = "abstract"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is configured and usable right now."""

    @abc.abstractmethod
    def generate(self, prompt: str) -> AIResponse:
        """Return a reply for a single text prompt."""

    def generate_stream(self, prompt: str, on_chunk: Callable[[str], None]) -> AIResponse:
        """Like ``generate``, but calls ``on_chunk`` with each piece of text
        as it becomes available, so a caller can show partial output while
        the full reply is still being produced -- growing visible text
        doubles as the "still working" signal for AI calls that have no
        real progress fraction to report (unlike e.g. a build pipeline's
        named steps, or ``ui.widgets.pill_button``'s indeterminate
        water-fill, both of which stay as-is for genuinely different loading
        shapes).

        The default implementation has no real incremental output to offer:
        it just calls ``generate()`` once and delivers the whole response as
        a single chunk, so every provider is streaming-callable from day
        one. Providers whose backend actually supports token streaming
        (OpenAI, Gemini) override this for real incremental delivery.
        """
        response = self.generate(prompt)
        on_chunk(response.text)
        return response

    def display_name(self) -> str:
        return self.name.capitalize()
