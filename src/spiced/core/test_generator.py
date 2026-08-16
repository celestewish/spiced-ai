"""Auto-Generated Unit Tests use-case (Phase 2 tier).

AI drafts NUnit C# test code for a system the developer points to (pasted
code, or a script file they picked). The draft is always shown for review
and editing first; Spiced only writes it to disk after an explicit per-file
"Approve" click on that specific draft (``approve_and_write``) — never
automatically, and never gated behind a project-level toggle the way Build
Pipeline/Pre-Commit Review are, since the "no changes without approval"
principle is enforced by the *action* itself here rather than a settings
flag. This is the one place in Phase E that writes into the developer's own
project unconditionally by design, per the plan's confirmed decision.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_test_case_script_prompt, build_test_generation_prompt
from spiced.storage.generated_test_drafts import GeneratedTestDraft, GeneratedTestDraftRepository
from spiced.storage.projects import Project
from spiced.storage.test_cases import TestCase

MAX_SOURCE_EXCERPT_CHARS = 6000

# Where a generated test file goes: reuse an existing conventional test
# folder if the project already has one, otherwise fall back to a clearly-
# named new folder under the standard EditMode location.
DEFAULT_TEST_SUBFOLDER = Path("Assets") / "Tests" / "EditMode"
_TEST_FOLDER_CANDIDATES = (
    Path("Assets") / "Tests" / "EditMode",
    Path("Assets") / "Tests" / "PlayMode",
    Path("Assets") / "Tests",
)

_CLASS_NAME_RE = re.compile(r"\bclass\s+(\w+)")
_NON_WORD_RE = re.compile(r"[^A-Za-z0-9_]")
_CODE_BLOCK_RE = re.compile(r"```(?:csharp|cs)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code_block(response_text: str) -> str:
    """Pull the fenced ```csharp code block out of a full AI reply.

    Falls back to the whole response (stripped) if no fenced block is found
    — a defensive fallback for a provider that doesn't follow the requested
    format exactly, not the expected path.
    """
    match = _CODE_BLOCK_RE.search(response_text)
    if match:
        return match.group(1).strip()
    return response_text.strip()


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to write into."""


def find_test_folder(project_path: str | Path) -> Path:
    """Return an existing conventional test folder, or the documented default.

    Checks ``Assets/Tests/EditMode``, ``Assets/Tests/PlayMode``, and a bare
    ``Assets/Tests`` (in that order) for an existing folder; falls back to
    ``Assets/Tests/EditMode`` (created on write) if none exist yet.
    """
    root = Path(project_path)
    for candidate in _TEST_FOLDER_CANDIDATES:
        if (root / candidate).is_dir():
            return root / candidate
    return root / DEFAULT_TEST_SUBFOLDER


def suggested_class_name(draft_text: str, system_label: str | None) -> str:
    """Best-effort NUnit test-class name for the output filename.

    Looks for ``class XyzTests`` in the draft text; falls back to a
    sanitized system label, then a generic name. Only affects the suggested
    filename, never the draft's own content.
    """
    match = _CLASS_NAME_RE.search(draft_text)
    if match:
        return match.group(1)
    if system_label:
        cleaned = _NON_WORD_RE.sub("", system_label)
        if cleaned:
            return f"{cleaned}Tests"
    return "GeneratedTests"


def next_available_path(path: Path) -> Path:
    """Never silently overwrite: append _2, _3, ... until a free name is found."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 2
    candidate = path.with_name(f"{stem}_{counter}{suffix}")
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
    return candidate


@dataclass(frozen=True)
class TestGenerationResult:
    draft: GeneratedTestDraft
    response_text: str
    provider: str


class TestGeneratorService:
    def __init__(self, drafts: GeneratedTestDraftRepository) -> None:
        self._drafts = drafts

    def generate_draft(
        self,
        provider: AIProvider,
        project: Project,
        source_code: str,
        *,
        system_label: str | None = None,
        record_usage=None,
    ) -> TestGenerationResult:
        """Ask the provider for a draft and save it — never writes any file."""
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        excerpt = source_code.strip()[:MAX_SOURCE_EXCERPT_CHARS]
        prompt = build_test_generation_prompt(
            excerpt, system_label=system_label, project_name=project.name
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)
        draft = self._drafts.create(
            project_id=project.id,
            system_label=system_label,
            source_excerpt=excerpt,
            draft_text=extract_code_block(response.text),
            provider=response.provider,
        )
        return TestGenerationResult(
            draft=draft, response_text=response.text, provider=response.provider
        )

    def generate_draft_from_test_case(
        self,
        provider: AIProvider,
        project: Project,
        test_case: TestCase,
        *,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> TestGenerationResult:
        """Draft a Unity test script implementing one of the developer's own,
        already-created QA test cases — never writes any file. Same review/
        approve flow as generate_draft, just a different prompt (and a
        different source_excerpt saved for the draft's history/audit trail:
        the test case's own title/steps/expected, not pasted code) since
        there's no source code to hand the AI here.
        """
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        prompt = build_test_case_script_prompt(
            test_case.title,
            test_case.steps,
            test_case.expected_result,
            project_name=project.name,
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)
        excerpt_parts = [f"Title: {test_case.title}"]
        if test_case.steps:
            excerpt_parts.append(f"Steps:\n{test_case.steps}")
        if test_case.expected_result:
            excerpt_parts.append(f"Expected result:\n{test_case.expected_result}")
        draft = self._drafts.create(
            project_id=project.id,
            system_label=test_case.title,
            source_excerpt="\n\n".join(excerpt_parts),
            draft_text=extract_code_block(response.text),
            provider=response.provider,
        )
        return TestGenerationResult(
            draft=draft, response_text=response.text, provider=response.provider
        )

    def approve_and_write(
        self,
        project: Project,
        draft_id: int,
        *,
        edited_text: str | None = None,
        overwrite: bool = False,
    ) -> GeneratedTestDraft:
        """Write one approved draft to disk. Only ever called from an explicit
        per-file "Approve" click — never automatically.

        ``edited_text`` lets whatever the developer edited on screen (not
        just the original AI draft) be what actually gets written. If a file
        of the suggested name already exists, a numeric suffix is appended
        instead (``FooTests_2.cs``, ...) unless the caller passes
        ``overwrite=True`` after getting a distinct confirmation from the
        developer — Spiced never silently replaces an existing file.
        """
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        draft = self._drafts.get(draft_id)
        text = edited_text if edited_text is not None else (draft.draft_text or "")
        class_name = suggested_class_name(text, draft.system_label)
        folder = find_test_folder(project.path)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{class_name}.cs"
        if not overwrite:
            target = next_available_path(target)
        target.write_text(text, encoding="utf-8")
        return self._drafts.mark_approved_and_written(draft.id, str(target))

    def history(self, project_id: int, limit: int = 20) -> list[GeneratedTestDraft]:
        return self._drafts.list_for_project(project_id, limit=limit)
