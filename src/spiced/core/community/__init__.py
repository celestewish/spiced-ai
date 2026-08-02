"""Community-source boundary for Community Pulse Check-ins (mock + Discord)."""

from __future__ import annotations

from spiced.core.community.base import CommunityMessage, CommunitySource
from spiced.core.community.factory import DEFAULT_SOURCE, available_sources, build_source

__all__ = [
    "CommunityMessage",
    "CommunitySource",
    "DEFAULT_SOURCE",
    "available_sources",
    "build_source",
]
