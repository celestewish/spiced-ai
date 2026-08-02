"""A deterministic, offline community source used for free/offline try-outs."""

from __future__ import annotations

from spiced.core.community.base import CommunityMessage, CommunitySource

_CANNED_MESSAGES = (
    CommunityMessage("playtester_ari", "the new dash feels so much better, nice work"),
    CommunityMessage("mossy_dev", "still hitting that floaty jump people mentioned last week"),
    CommunityMessage("kel", "any word on when the next build drops? excited to try the boss"),
    CommunityMessage("playtester_ari", "loading into the forest level took a while just now"),
    CommunityMessage("nova", "loving the art direction honestly, the palette is great"),
)


class MockCommunitySource(CommunitySource):
    name = "mock"

    def is_available(self) -> bool:
        return True

    def fetch_recent(self, limit: int = 30) -> list[CommunityMessage]:
        return list(_CANNED_MESSAGES[:limit])

    def channel_label(self) -> str:
        return "#mock-community (offline sample data)"

    def display_name(self) -> str:
        return "Mock (offline)"
