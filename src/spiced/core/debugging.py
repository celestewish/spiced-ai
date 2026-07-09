"""Debugging use-case: turn a Unity log into calm, structured guidance.

Flow: parse the log locally (deterministic) -> build a Unity-specific prompt
from that evidence -> ask the selected provider -> persist a compact session.
The full log is never sent or stored; only a trimmed excerpt is used.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_unity_debug_prompt
from spiced.core.unity_log_parser import ParsedLog, parse_unity_log
from spiced.storage.debug_sessions import DebugSession, DebugSessionRepository
from spiced.storage.projects import Project

SOURCE_PASTE = "paste"
SOURCE_FILE = "file"


@dataclass(frozen=True)
class DebugAnalysis:
    parsed: ParsedLog
    response_text: str
    provider: str
    session: DebugSession | None


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class DebuggingService:
    """Coordinates parsing, prompting, the provider call, and persistence."""

    def __init__(self, sessions: DebugSessionRepository) -> None:
        self._sessions = sessions

    def parse(self, log_text: str) -> ParsedLog:
        return parse_unity_log(log_text)

    def analyze(
        self,
        provider: AIProvider,
        log_text: str,
        *,
        project: Project | None = None,
        source_type: str = SOURCE_PASTE,
        source_filename: str | None = None,
        record_usage=None,
    ) -> DebugAnalysis:
        """Parse the log, ask the provider, and save a session if we have a project.

        ``record_usage`` is an optional callback invoked with the provider name
        after a successful reply, so the usage counter can increment.
        """
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in "
                "Settings for free offline analysis."
            )

        parsed = self.parse(log_text)
        metadata = project.engine_metadata if project else {}
        prompt = build_unity_debug_prompt(
            parsed,
            project_name=project.name if project else None,
            unity_version=metadata.get("unity_version"),
        )

        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        session = None
        if project is not None:
            session = self._save_session(
                project_id=project.id,
                parsed=parsed,
                response_text=response.text,
                provider=response.provider,
                source_type=source_type,
                source_filename=source_filename,
            )

        return DebugAnalysis(
            parsed=parsed,
            response_text=response.text,
            provider=response.provider,
            session=session,
        )

    def history(self, project_id: int, limit: int = 20) -> list[DebugSession]:
        return self._sessions.list_for_project(project_id, limit=limit)

    def _save_session(
        self,
        *,
        project_id: int,
        parsed: ParsedLog,
        response_text: str,
        provider: str,
        source_type: str,
        source_filename: str | None,
    ) -> DebugSession:
        primary = parsed.primary
        summary = _summarize(response_text)
        return self._sessions.create(
            project_id=project_id,
            source_type=source_type,
            source_filename=source_filename,
            detected_error_type=primary.error_type if primary else None,
            detected_file=primary.script or primary.file if primary else None,
            detected_line=primary.line if primary else None,
            raw_excerpt=parsed.excerpt or None,
            summary=summary,
            suggested_next_steps=_extract_next_steps(response_text),
            provider=provider,
        )


def _summarize(response_text: str, limit: int = 240) -> str:
    """Take the first meaningful line of the response as a short summary."""
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's what"):
            return stripped[:limit]
    return response_text.strip()[:limit]


def _extract_next_steps(response_text: str) -> list[str]:
    """Pull the bullet list under the 'Safe next steps:' heading, if present."""
    steps: list[str] = []
    capturing = False
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("safe next steps"):
            capturing = True
            continue
        if capturing:
            if stripped.startswith(("-", "*")):
                steps.append(stripped.lstrip("-* ").strip())
            elif stripped and stripped.endswith(":"):
                break
    return steps
