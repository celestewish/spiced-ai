"""Community Pulse Check-ins use-case.

Off by default. When the developer opts in and a community source is
available (the free mock, or Discord via a bot token), Spiced reads recent
messages from exactly one channel and asks the selected AI provider for a
light, high-level sentiment summary — never a deep analysis, never a post
back to the community.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_community_pulse_prompt
from spiced.core.community.base import CommunitySource
from spiced.storage.community_pulse import CommunityPulseCheckin, CommunityPulseRepository
from spiced.storage.projects import Project

DEFAULT_MESSAGE_LIMIT = 30
MAX_EXCERPT_CHARS = 2000


@dataclass(frozen=True)
class CommunityPulseResult:
    channel_label: str
    message_count: int
    response_text: str
    provider: str
    checkin: CommunityPulseCheckin | None


class SourceNotReadyError(RuntimeError):
    """Raised when the selected community source isn't configured."""


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected AI provider has no usable credentials."""


class CommunityPulseService:
    def __init__(self, checkins: CommunityPulseRepository) -> None:
        self._checkins = checkins

    def check_in(
        self,
        provider: AIProvider,
        source: CommunitySource,
        *,
        project: Project | None = None,
        limit: int = DEFAULT_MESSAGE_LIMIT,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> CommunityPulseResult:
        if not source.is_available():
            raise SourceNotReadyError(
                f"The {source.display_name()} community source isn't configured. Switch to the "
                "mock source for a free offline preview, or set its credentials."
            )
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )

        messages = source.fetch_recent(limit=limit)
        channel_label = source.channel_label()
        prompt = build_community_pulse_prompt(
            messages, channel_label=channel_label, project_name=project.name if project else None
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        checkin = None
        if project is not None:
            excerpt = "\n".join(f"{m.author}: {m.text}" for m in messages)[:MAX_EXCERPT_CHARS]
            checkin = self._checkins.create(
                project_id=project.id,
                source=source.name,
                channel_label=channel_label,
                message_count=len(messages),
                raw_excerpt=excerpt or None,
                ai_summary=_summarize(response.text),
                provider=response.provider,
            )

        return CommunityPulseResult(
            channel_label=channel_label,
            message_count=len(messages),
            response_text=response.text,
            provider=response.provider,
            checkin=checkin,
        )

    def history(self, project_id: int, limit: int = 20) -> list[CommunityPulseCheckin]:
        return self._checkins.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's"):
            return stripped[:limit]
    return response_text.strip()[:limit]
