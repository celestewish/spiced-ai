"""Community-source selection, mirroring ai/factory.py's provider boundary."""

from __future__ import annotations

from spiced.core.community.base import CommunitySource
from spiced.core.community.discord_source import DiscordCommunitySource
from spiced.core.community.mock_source import MockCommunitySource

DEFAULT_SOURCE = "mock"


def available_sources() -> list[str]:
    return ["mock", "discord"]


def build_source(name: str) -> CommunitySource:
    key = (name or DEFAULT_SOURCE).strip().lower()
    if key == "mock":
        return MockCommunitySource()
    if key == "discord":
        return DiscordCommunitySource()
    raise ValueError(f"Unknown community source: {name!r}")
