"""Open Roadmap & Feedback Loop use-cases (Phase C, section 5, stretch).

Backend-hosted so every developer sees the same list. Viewing the changelog
and suggestion board needs no login at all. Submitting a suggestion or voting
requires being signed in — reusing ``AuthService``/``AuthDialog`` from Phase A
exactly as-is, the same way Phase B's Team Mode toggle does, rather than
building a separate roadmap-specific account system.
"""

from __future__ import annotations

from spiced.backend_client.api_client import BackendClient, ChangelogEntry, RoadmapSuggestion
from spiced.core.auth_service import AuthService


class RoadmapService:
    def __init__(self, auth: AuthService, api_client: BackendClient | None = None) -> None:
        self._auth = auth
        self._client = api_client or BackendClient()

    def _synced_client(self) -> BackendClient:
        # Attach whatever token (if any) is currently available. Public
        # roadmap endpoints work fine with no token at all; this only makes
        # sure a signed-in developer's requests are recognized as "theirs"
        # where that matters (e.g. voted_by_me, submitting a suggestion).
        self._client.set_token(self._auth.access_token())
        return self._client

    def list_changelog(self) -> list[ChangelogEntry]:
        return self._synced_client().list_changelog()

    def list_suggestions(self) -> list[RoadmapSuggestion]:
        return self._synced_client().list_suggestions()

    def submit_suggestion(self, title: str, body: str) -> RoadmapSuggestion:
        """Requires the caller to already be signed in (see AuthService)."""
        return self._synced_client().create_suggestion(title, body)

    def vote(self, suggestion_id: str) -> None:
        self._synced_client().vote_suggestion(suggestion_id)

    def unvote(self, suggestion_id: str) -> None:
        self._synced_client().unvote_suggestion(suggestion_id)
