"""Audio Implementation Checklist (Phase I, section 8, Core tier).

Fully static/heuristic, no engine execution: scans the project's ``.cs``
scripts (reusing the read-only file-walk from ``connectors.unity_scan.
iter_assets``, the same approach ``connectors.unity_docs_scan`` and
``core.localization_readiness`` already use) for code that looks like it's
triggering audio playback, and cross-references the variable/field names
involved against audio asset files present under ``Assets/``.

**Matching heuristic and its honest limits** (mirrors Dead Reference
Detection's "best-effort, could be loaded dynamically" caveat): a script
reference is matched to an audio file by *normalized name similarity* --
lowercase, strip non-alphanumerics, strip common tokens like "clip"/
"sound"/"sfx"/"audio"/"fx" -- and considered a match if one normalized name
contains the other. This is deliberately loose (no AST, no actual Unity
Inspector-assigned reference graph is visible to a static scan) and has a
real false-positive/false-negative shape:

- A script field named ``explosionClip`` won't match a file named
  ``boom_01.wav`` -- a real mismatch this scan cannot see (false negative).
- A field named ``clip`` alone (too generic) is excluded from matching
  entirely to avoid meaningless matches against every audio file in the
  project.
- Many real Unity audio clips are assigned purely via the Inspector (drag-
  and-drop onto a serialized field) with no ``.clip = someVariable`` or
  ``PlayOneShot(someVariable)`` call anywhere in code -- those references are
  invisible to this scan and will never show as "matched," even though the
  audio is genuinely wired up in the scene/prefab.
- Audio loaded dynamically (``Resources.Load``, Addressables, or by a
  string path built at runtime) won't be matched either.

Every finding here is "worth a look," never a confirmed defect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_scan import iter_assets
from spiced.storage.audio_checklist_reports import (
    AudioChecklistReport,
    AudioChecklistReportRepository,
)
from spiced.storage.projects import Project

AUDIO_IMPLEMENTATION_CAVEAT = (
    "Best-effort, name-similarity matching only -- not a real reference graph. Audio assigned "
    "purely via the Unity Inspector (no matching .clip=/PlayOneShot(...) call in code) won't be "
    "seen as 'matched' even when it's genuinely wired up. Audio loaded dynamically (Resources."
    "Load, Addressables, a runtime-built path) also won't be seen. Treat every flagged item as "
    "worth a manual check, never a confirmed missing/unused asset."
)

AUDIO_FILE_EXTS = {".wav", ".mp3", ".ogg", ".aiff", ".aif"}

_PLAY_ONE_SHOT_RE = re.compile(r"\.PlayOneShot\s*\(\s*(\w+)")
# ".Play(someClip)" -- requires "(" directly after "Play" (mod whitespace),
# so this naturally does not also match inside ".PlayOneShot(...)" (which
# has "OneShot(" right after "Play", not "(").
_PLAY_RE = re.compile(r"\.Play\s*\(\s*(\w*)")
_CLIP_ASSIGN_RE = re.compile(r"\.clip\s*=\s*(\w+)")
_PLAY_AT_POINT_RE = re.compile(r"AudioSource\.PlayClipAtPoint\s*\(\s*(\w+)")

# Tokens stripped during normalization -- generic audio-domain words that add
# no matching signal on their own (see module docstring).
_STRIP_TOKENS = ("clip", "sound", "sfx", "audio", "fx")
_MIN_NAME_LENGTH = 3


def _normalize(name: str) -> str:
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    for token in _STRIP_TOKENS:
        norm = norm.replace(token, "")
    return norm


@dataclass(frozen=True)
class ScriptAudioReference:
    file: str  # relative to the project root, forward-slashed
    line: int
    variable_name: str
    call_kind: str  # "PlayOneShot" | "Play" | "clip_assign" | "PlayClipAtPoint"


@dataclass(frozen=True)
class AudioImplementationScan:
    matched_references: list[ScriptAudioReference] = field(default_factory=list)
    unmatched_references: list[ScriptAudioReference] = field(default_factory=list)
    unreferenced_audio_files: list[str] = field(default_factory=list)
    scripts_scanned: int = 0
    audio_files_found: int = 0
    caveat: str = AUDIO_IMPLEMENTATION_CAVEAT

    def as_summary_dict(self) -> dict:
        def _ref_dict(r: ScriptAudioReference) -> dict:
            return {
                "file": r.file, "line": r.line, "variable_name": r.variable_name,
                "call_kind": r.call_kind,
            }

        return {
            "scripts_scanned": self.scripts_scanned,
            "audio_files_found": self.audio_files_found,
            "matched_references": [_ref_dict(r) for r in self.matched_references],
            "unmatched_references": [_ref_dict(r) for r in self.unmatched_references],
            "unreferenced_audio_files": self.unreferenced_audio_files,
        }


def _scan_script(text: str, rel_path: str) -> list[ScriptAudioReference]:
    refs: list[ScriptAudioReference] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("//"):
            continue
        for pattern, kind in (
            (_PLAY_ONE_SHOT_RE, "PlayOneShot"),
            (_PLAY_AT_POINT_RE, "PlayClipAtPoint"),
            (_CLIP_ASSIGN_RE, "clip_assign"),
        ):
            for match in pattern.finditer(raw_line):
                var = match.group(1)
                if var and len(var) >= _MIN_NAME_LENGTH:
                    refs.append(ScriptAudioReference(rel_path, line_number, var, kind))
        # .Play(someClip) -- but not the bare .Play() call some AudioSource
        # code uses with no argument (nothing to match against).
        for match in _PLAY_RE.finditer(raw_line):
            var = match.group(1)
            if var and len(var) >= _MIN_NAME_LENGTH:
                refs.append(ScriptAudioReference(rel_path, line_number, var, "Play"))
    return refs


def _find_match(norm_ref: str, audio_stems: dict[str, str]) -> str | None:
    if len(norm_ref) < _MIN_NAME_LENGTH:
        return None
    for norm_stem, original_path in audio_stems.items():
        if not norm_stem:
            continue
        if norm_ref in norm_stem or norm_stem in norm_ref:
            return original_path
    return None


def scan_audio_implementation(project_path: str | Path) -> AudioImplementationScan:
    """Read-only scan of a Unity project's scripts and audio assets.

    Returns an empty result (never raises) if the project has no ``Assets/``
    folder. Nothing is ever written back to the project.
    """
    root = Path(project_path)
    references: list[ScriptAudioReference] = []
    audio_files: list[str] = []
    scripts_scanned = 0

    for asset in iter_assets(root):
        suffix = asset.suffix.lower()
        if suffix == ".cs":
            try:
                text = asset.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scripts_scanned += 1
            rel = asset.relative_to(root).as_posix()
            references.extend(_scan_script(text, rel))
        elif suffix in AUDIO_FILE_EXTS:
            audio_files.append(asset.relative_to(root).as_posix())

    audio_stems = {_normalize(Path(f).stem): f for f in audio_files}

    matched: list[ScriptAudioReference] = []
    unmatched: list[ScriptAudioReference] = []
    matched_files: set[str] = set()
    for ref in references:
        norm_ref = _normalize(ref.variable_name)
        match = _find_match(norm_ref, audio_stems)
        if match:
            matched.append(ref)
            matched_files.add(match)
        else:
            unmatched.append(ref)

    unreferenced = [f for f in audio_files if f not in matched_files]

    return AudioImplementationScan(
        matched_references=matched,
        unmatched_references=unmatched,
        unreferenced_audio_files=sorted(unreferenced),
        scripts_scanned=scripts_scanned,
        audio_files_found=len(audio_files),
    )


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


class AudioImplementationChecklistService:
    def __init__(self, reports: AudioChecklistReportRepository) -> None:
        self._reports = reports

    def scan(self, project: Project) -> tuple[AudioImplementationScan, AudioChecklistReport]:
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        scan = scan_audio_implementation(project.path)
        report = self._reports.create(project.id, scan.as_summary_dict())
        return scan, report

    def history(self, project_id: int, limit: int = 20) -> list[AudioChecklistReport]:
        return self._reports.list_for_project(project_id, limit=limit)
