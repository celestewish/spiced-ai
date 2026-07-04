"""Abstract AI provider interface."""

from __future__ import annotations

import abc
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

    def display_name(self) -> str:
        return self.name.capitalize()
