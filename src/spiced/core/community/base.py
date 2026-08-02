"""Abstract community-source interface for Community Pulse Check-ins.

Mirrors the AI provider boundary: a free, offline mock is always available,
and a real connection (Discord) is opt-in and gated behind credentials the
developer supplies. Implementations must be read-only — Spiced never posts,
reacts, or writes to any connected community platform.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class CommunityMessage:
    author: str
    text: str
    timestamp: str | None = None


class CommunitySource(abc.ABC):
    #: Short, stable identifier used in settings and saved check-ins.
    name: str = "abstract"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if this source is configured and usable right now."""

    @abc.abstractmethod
    def fetch_recent(self, limit: int = 30) -> list[CommunityMessage]:
        """Return up to ``limit`` recent public messages, oldest concerns first."""

    @abc.abstractmethod
    def channel_label(self) -> str:
        """A human-readable description of exactly what was read."""

    def display_name(self) -> str:
        return self.name.capitalize()
