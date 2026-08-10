"""Localization Readiness Check use-case (Phase H, section 7 part 2, Phase 2 tier).

A read-only recursive scan of the project's ``Assets/`` folder, reusing
``connectors.unity_scan.iter_assets`` the same way ``connectors.
unity_docs_scan`` does. Two independent heuristics, both deliberately
documented as heuristics rather than presented as ground truth:

1. **Hardcoded strings in ``.cs`` scripts.** A string literal is flagged when
   it looks user-facing: either the source line nearby contains a UI-ish
   keyword (text/label/message/dialogue/title/tooltip/caption/prompt/button/
   notification/subtitle) -- flagged "high" confidence -- or the literal is
   merely long enough and sentence-like (contains a space, isn't a bare
   identifier or path) -- flagged "low" confidence. This is a heuristic, not
   a real C# parser: it will miss user-facing strings that don't match the
   keyword list or read like plain identifiers, and it will flag some
   genuinely non-UI strings (log messages, exception text) that happen to
   read like sentences. It cannot know whether a string is actually shown to
   a player.

2. **Prefab/scene text components.** Unity's ``.prefab``/``.unity`` files are
   YAML-ish text (the same structural fact ``unity_scan``'s GUID
   cross-referencing already relies on) -- a ``Text``/``TextMeshPro``
   component serializes its content as an ``m_Text: <value>`` field. A
   non-empty value that contains no obvious placeholder token (``{0}``,
   ``{}``, ``%s``, ``%d``) is flagged as hardcoded, unparameterized text.
   This will miss text driven entirely from code (``.text = ...`` in a
   script, already covered by heuristic 1) and can't tell whether a flagged
   string is actually reachable by a player at runtime.

Both heuristics are surfaced with their false-positive/false-negative shape
spelled out in the UI, per spec ("document your heuristic clearly"). No AI
call is involved -- this is purely local and deterministic, the same
philosophy as Code Health's Naming Consistency / Dead Reference Detection
checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_scan import iter_assets
from spiced.storage.localization_readiness_reports import (
    LocalizationReadinessReport,
    LocalizationReadinessReportRepository,
)
from spiced.storage.projects import Project

HEURISTIC_CAVEAT = (
    "How this works: hardcoded-string detection flags string literals that read as "
    "user-facing text (a nearby UI-ish keyword, or just length + sentence shape) — it can miss "
    "strings that don't match those patterns and can flag some non-UI text (log/exception "
    "messages) that happens to read like a sentence. Prefab/scene text detection flags "
    "m_Text values with no placeholder token — it can't tell whether that text is actually "
    "reachable by a player. Give each finding a quick look before treating it as a real issue."
)

MIN_STRING_LENGTH = 12
_MAX_FINDINGS = 200

_UI_HINT_RE = re.compile(
    r"\b(text|label|message|dialogue|dialog|title|tooltip|caption|prompt|button|"
    r"notification|subtitle)\b",
    re.IGNORECASE,
)
_STRING_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_PATH_LIKE_RE = re.compile(r"[\\/]")
_IDENTIFIER_LIKE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_M_TEXT_RE = re.compile(r"^\s*m_Text:\s*(.*)$")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}|%[sd]")


def _looks_like_ui_text(literal: str) -> bool:
    """Excludes obvious non-UI literals: paths, bare identifiers/keys, URLs,
    and anything too short or without a space (see module docstring).

    The bare-identifier check only matters for literals with no space at
    all (e.g. "PlayerPrefsKey") -- it must run *before* the space
    requirement below, not after, since stripping spaces from a legitimate
    multi-word sentence ("Hello World" -> "HelloWorld") would otherwise
    make it look identifier-like too and wrongly exclude it.
    """
    if len(literal) < MIN_STRING_LENGTH:
        return False
    if _IDENTIFIER_LIKE_RE.match(literal):
        return False
    if " " not in literal:
        return False
    if _PATH_LIKE_RE.search(literal):
        return False
    if _URL_RE.match(literal):
        return False
    return True


@dataclass(frozen=True)
class HardcodedStringFinding:
    file: str  # relative to the project root, forward-slashed
    line: int
    text: str
    confidence: str  # "high" | "low"


@dataclass(frozen=True)
class PrefabTextFinding:
    file: str  # relative to the project root, forward-slashed
    text: str


@dataclass(frozen=True)
class LocalizationReadinessScan:
    hardcoded_strings: list[HardcodedStringFinding] = field(default_factory=list)
    prefab_texts: list[PrefabTextFinding] = field(default_factory=list)
    scripts_scanned: int = 0
    prefabs_scanned: int = 0

    def as_summary_dict(self) -> dict:
        return {
            "scripts_scanned": self.scripts_scanned,
            "prefabs_scanned": self.prefabs_scanned,
            "hardcoded_strings": [
                {"file": f.file, "line": f.line, "text": f.text, "confidence": f.confidence}
                for f in self.hardcoded_strings
            ],
            "prefab_texts": [{"file": f.file, "text": f.text} for f in self.prefab_texts],
        }


def _scan_script(text: str, rel_path: str) -> list[HardcodedStringFinding]:
    findings = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("//"):
            continue
        hint = bool(_UI_HINT_RE.search(raw_line))
        for match in _STRING_LITERAL_RE.finditer(raw_line):
            literal = match.group(1)
            if not _looks_like_ui_text(literal):
                continue
            findings.append(
                HardcodedStringFinding(
                    file=rel_path,
                    line=line_number,
                    text=literal,
                    confidence="high" if hint else "low",
                )
            )
    return findings


def _scan_prefab(text: str, rel_path: str) -> list[PrefabTextFinding]:
    findings = []
    for raw_line in text.splitlines():
        match = _M_TEXT_RE.match(raw_line)
        if not match:
            continue
        value = match.group(1).strip()
        if not value:
            continue
        if _PLACEHOLDER_RE.search(value):
            continue  # already parameterized -- not a hardcoded-text concern
        findings.append(PrefabTextFinding(file=rel_path, text=value))
    return findings


def scan_localization_readiness(project_path: str | Path) -> LocalizationReadinessScan:
    """Read-only scan of a Unity project's scripts and prefabs/scenes.

    Returns an empty result (never raises) if the project has no ``Assets/``
    folder — callers are expected to have already validated the project has
    a connected folder. Nothing is ever written back to the project.
    """
    root = Path(project_path)
    hardcoded: list[HardcodedStringFinding] = []
    prefab_texts: list[PrefabTextFinding] = []
    scripts_scanned = 0
    prefabs_scanned = 0

    for asset in iter_assets(root):
        suffix = asset.suffix.lower()
        if suffix == ".cs":
            try:
                text = asset.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scripts_scanned += 1
            rel = asset.relative_to(root).as_posix()
            hardcoded.extend(_scan_script(text, rel))
        elif suffix in (".prefab", ".unity"):
            try:
                text = asset.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            prefabs_scanned += 1
            rel = asset.relative_to(root).as_posix()
            prefab_texts.extend(_scan_prefab(text, rel))

    return LocalizationReadinessScan(
        hardcoded_strings=hardcoded[:_MAX_FINDINGS],
        prefab_texts=prefab_texts[:_MAX_FINDINGS],
        scripts_scanned=scripts_scanned,
        prefabs_scanned=prefabs_scanned,
    )


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


class LocalizationReadinessService:
    def __init__(self, reports: LocalizationReadinessReportRepository) -> None:
        self._reports = reports

    def scan(
        self, project: Project
    ) -> tuple[LocalizationReadinessScan, LocalizationReadinessReport]:
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        scan = scan_localization_readiness(project.path)
        report = self._reports.create(project.id, scan.as_summary_dict())
        return scan, report

    def history(self, project_id: int, limit: int = 20) -> list[LocalizationReadinessReport]:
        return self._reports.list_for_project(project_id, limit=limit)
