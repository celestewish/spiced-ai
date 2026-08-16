"""Draft Translation Pass use-case (Phase H, section 7 part 2, Stretch tier).

The developer pastes/imports a dialogue file and picks a target language;
Spiced asks the AI for a draft machine translation. Always and clearly
labeled a draft for a human translator to refine, never presented as ship-
ready -- see ``build_draft_translation_prompt``'s rules and required
response format, both of which repeat that caveat, and the UI copy this
service's callers are expected to show alongside it.

Supported input formats, tried in this order (documented so the developer
knows what to paste/import):

1. **JSON** -- either a flat list of strings (``["Hello", "Goodbye"]``), a
   list of ``{"text": "..."}`` objects (any ``id``/``key`` field is kept as
   the entry's id), or a flat object mapping id -> text
   (``{"greeting": "Hello"}``).
2. **CSV** -- a header row containing a ``text`` column (an optional ``id``
   column is used as the entry id).
3. **Plain text** -- one dialogue line per line; blank lines are skipped.

Anything that fails JSON/CSV parsing falls back to plain text, so a plain
paste never hard-fails.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_draft_translation_prompt
from spiced.storage.draft_translations import DraftTranslation, DraftTranslationRepository
from spiced.storage.projects import Project

FORMAT_JSON = "json"
FORMAT_CSV = "csv"
FORMAT_PLAIN = "plain"

# Caps chosen to keep prompts (and what gets stored) bounded, the same
# philosophy as MAX_EXCERPT_CHARS elsewhere in the app.
MAX_ENTRIES = 200
MAX_RAW_EXCERPT_CHARS = 8000

DRAFT_NOT_SHIP_READY_NOTICE = (
    "Draft only -- for a human translator to review and refine. Never presented as ship-ready; "
    "machine translation can miss tone, idiom, and context a native speaker would catch."
)


@dataclass(frozen=True)
class DialogueEntry:
    entry_id: str | None
    text: str


@dataclass(frozen=True)
class ParsedDialogue:
    entries: list[DialogueEntry] = field(default_factory=list)
    source_format: str = FORMAT_PLAIN

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def lines(self) -> list[str]:
        return [e.text for e in self.entries]


def _parse_json(text: str) -> list[DialogueEntry] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    entries: list[DialogueEntry] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                if item.strip():
                    entries.append(DialogueEntry(entry_id=None, text=item.strip()))
            elif isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str) and value.strip():
                    entry_id = item.get("id") or item.get("key")
                    entries.append(
                        DialogueEntry(
                            entry_id=str(entry_id) if entry_id is not None else None,
                            text=value.strip(),
                        )
                    )
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and value.strip():
                entries.append(DialogueEntry(entry_id=str(key), text=value.strip()))
    else:
        return None
    return entries or None


def _parse_csv(text: str) -> list[DialogueEntry] | None:
    try:
        reader = csv.DictReader(io.StringIO(text.strip()))
        fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        if "text" not in fieldnames:
            return None
        rows = list(reader)
    except csv.Error:
        return None
    entries: list[DialogueEntry] = []
    for row in rows:
        entry_id = None
        line = None
        for key, val in row.items():
            if key is None:
                continue
            key_lower = key.strip().lower()
            if key_lower == "text":
                line = (val or "").strip()
            elif key_lower == "id":
                entry_id = (val or "").strip() or None
        if line:
            entries.append(DialogueEntry(entry_id=entry_id, text=line))
    return entries or None


def _parse_plain(text: str) -> list[DialogueEntry]:
    return [
        DialogueEntry(entry_id=None, text=line.strip())
        for line in text.splitlines()
        if line.strip()
    ]


def parse_dialogue(text: str) -> ParsedDialogue:
    """Parse a pasted/imported dialogue file, trying JSON, then CSV, then
    falling back to plain text (one line per entry) -- see module docstring.
    """
    cleaned = text.strip()
    if not cleaned:
        return ParsedDialogue(entries=[], source_format=FORMAT_PLAIN)

    json_entries = _parse_json(cleaned)
    if json_entries is not None:
        return ParsedDialogue(entries=json_entries[:MAX_ENTRIES], source_format=FORMAT_JSON)

    csv_entries = _parse_csv(cleaned)
    if csv_entries is not None:
        return ParsedDialogue(entries=csv_entries[:MAX_ENTRIES], source_format=FORMAT_CSV)

    return ParsedDialogue(
        entries=_parse_plain(cleaned)[:MAX_ENTRIES], source_format=FORMAT_PLAIN
    )


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NoDialogueError(RuntimeError):
    """Raised when nothing usable was parsed from the pasted/imported text."""


@dataclass(frozen=True)
class DraftTranslationResult:
    parsed: ParsedDialogue
    response_text: str
    provider: str
    translation: DraftTranslation | None


class DraftTranslationService:
    def __init__(self, translations: DraftTranslationRepository) -> None:
        self._translations = translations

    def parse(self, text: str) -> ParsedDialogue:
        return parse_dialogue(text)

    def translate(
        self,
        provider: AIProvider,
        text: str,
        target_language: str,
        *,
        project: Project | None = None,
        source_filename: str | None = None,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> DraftTranslationResult:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings "
                "for free offline analysis."
            )

        parsed = parse_dialogue(text)
        if not parsed.entries:
            raise NoDialogueError(
                "Nothing usable was found in that paste/import. See the documented plain-text/"
                "CSV/JSON formats above."
            )

        target = target_language.strip() or "(unspecified — ask for a target language)"
        prompt = build_draft_translation_prompt(
            parsed.lines, target_language=target, project_name=project.name if project else None
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        translation = None
        if project is not None:
            translation = self._translations.create(
                project.id,
                source_filename=source_filename,
                source_format=parsed.source_format,
                target_language=target,
                entry_count=parsed.entry_count,
                raw_excerpt=text.strip()[:MAX_RAW_EXCERPT_CHARS] or None,
                ai_draft_text=response.text,
                provider=response.provider,
            )

        return DraftTranslationResult(
            parsed=parsed,
            response_text=response.text,
            provider=response.provider,
            translation=translation,
        )

    def history(self, project_id: int, limit: int = 20) -> list[DraftTranslation]:
        return self._translations.list_for_project(project_id, limit=limit)
