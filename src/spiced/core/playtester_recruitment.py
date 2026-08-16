"""Playtester Recruitment Assistant use-case (Phase G, section 7, Phase 2 tier).

Drafts a recruitment post via the AI provider from a short description of
what testers are needed for, the target platform, and a timeframe. The spec
also calls for this to "manage a simple sign-up/build-distribution flow" —
scoped down here to a local sign-up list the developer tracks by hand
(name/contact/status): Spiced has no real build-distribution infrastructure
(no build hosting, no email sending) and never sends anything on the
developer's behalf. The drafted post itself is copy-paste scratch text, not
persisted — same philosophy as Changelog Generation's draft-then-copy flow,
except changelog drafts happen to be saved for edit-and-reuse while a
recruitment post is a one-off; the local sign-up list is what's actually
tracked over time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_playtester_recruitment_prompt
from spiced.storage.playtester_signups import (
    STATUS_CONFIRMED,
    STATUS_INVITED,
    STATUS_TESTED,
    STATUSES,
    PlaytesterSignup,
    PlaytesterSignupRepository,
)
from spiced.storage.projects import Project

__all__ = [
    "STATUS_CONFIRMED",
    "STATUS_INVITED",
    "STATUS_TESTED",
    "STATUSES",
    "PlaytesterSignup",
    "PlaytesterRecruitmentService",
    "ProviderNotReadyError",
    "RecruitmentDraftResult",
]


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


@dataclass(frozen=True)
class RecruitmentDraftResult:
    response_text: str
    provider: str


class PlaytesterRecruitmentService:
    def __init__(self, signups: PlaytesterSignupRepository) -> None:
        self._signups = signups

    # --- AI-drafted recruitment post (not persisted) ------------------------

    def draft_post(
        self,
        provider: AIProvider,
        *,
        needs_description: str,
        target_platform: str,
        timeframe: str,
        project: Project | None = None,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> RecruitmentDraftResult:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        prompt = build_playtester_recruitment_prompt(
            needs_description=needs_description,
            target_platform=target_platform,
            timeframe=timeframe,
            project_name=project.name if project else None,
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)
        return RecruitmentDraftResult(response_text=response.text, provider=response.provider)

    # --- Local sign-up list (no real distribution) ---------------------------

    def add_signup(
        self, project_id: int, name: str, contact: str | None, status: str = STATUS_INVITED
    ) -> PlaytesterSignup:
        name = name.strip()
        if not name:
            raise ValueError("A tester name is required.")
        return self._signups.create(project_id, name, (contact or "").strip() or None, status)

    def list_signups(self, project_id: int) -> list[PlaytesterSignup]:
        return self._signups.list_for_project(project_id)

    def set_status(self, signup_id: int, status: str) -> PlaytesterSignup:
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status}")
        return self._signups.set_status(signup_id, status)

    def delete_signup(self, signup_id: int) -> None:
        self._signups.delete(signup_id)
