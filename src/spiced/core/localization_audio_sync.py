"""Localization Audio Sync (Phase I, section 8, Stretch tier).

Flags voice lines that may no longer match the current script/localization
text. Real speech-to-text content verification is deliberately out of scope
-- it would need a new ML dependency this phase doesn't add -- so this is a
**metadata/naming-convention + file-timestamp heuristic only**:

1. A voice-line audio file's last-modified timestamp *older* than its
   corresponding script line's last-edit timestamp is a real, checkable
   staleness signal (the recording predates a text edit -- it may well be
   reading an outdated line).
2. A script line with no matching audio file at all is a coverage gap.

Spiced **cannot verify that a recording's actual spoken content matches the
text** -- this is a staleness/coverage check, not a content check, and the
UI says so explicitly, every time.

This is deliberately self-contained rather than folded into Localization
Readiness Check (``core.localization_readiness``, Phase H): that module
scans ``.cs``/prefab files for hardcoded strings, a different question
entirely from "does this recording match the current text." The Audio
screen presents this feature next to a link/reference to that existing
check per spec ("paired with the Localization Readiness Check"), rather
than duplicating its scan here.

Line IDs are matched either from a dev-supplied mapping or inferred from
filenames using a common convention (e.g. ``VO_Line042_v2.wav`` ->
``line042``) -- inference is itself a heuristic and can miss non-conforming
filenames, which show up as "unmatched audio files" rather than silently
being dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

STALENESS_CAVEAT = (
    "Staleness/coverage check only -- Spiced cannot listen to or transcribe these recordings, "
    "so it cannot verify a voice line's actual spoken content matches the current script text. "
    "A recording is flagged 'possibly stale' only when its file was last modified before the "
    "matching script line's own last-edit time; a script line is flagged 'missing audio' only "
    "when no audio file's inferred or supplied line ID matches it. Both are heuristics, not "
    "confirmations -- always spot-check flagged lines yourself."
)

_LINE_ID_RE = re.compile(r"(line[_\s-]?\d+)", re.IGNORECASE)
_VOICE_FILE_EXTS = {".wav", ".mp3", ".ogg", ".aiff", ".aif"}


def _normalize_line_id(raw: str) -> str:
    return re.sub(r"[_\s-]", "", raw).lower()


def infer_line_id_from_filename(filename: str) -> str | None:
    """Best-effort line-ID inference from a filename convention like
    ``VO_Line042_v2.wav`` -> ``line042``. Returns ``None`` if the filename
    doesn't contain a recognizable ``line<number>`` token -- callers treat
    those files as "unmatched," not as an error."""
    match = _LINE_ID_RE.search(filename)
    if not match:
        return None
    return _normalize_line_id(match.group(1))


@dataclass(frozen=True)
class ScriptLine:
    line_id: str
    text: str
    last_modified: float  # epoch seconds


@dataclass(frozen=True)
class VoiceLineFile:
    path: str
    last_modified: float
    line_id: str | None = None  # dev-supplied override; inferred from filename if None


@dataclass(frozen=True)
class StaleVoiceLineFinding:
    line_id: str
    audio_path: str
    script_modified_at: float
    audio_modified_at: float


@dataclass(frozen=True)
class MissingAudioFinding:
    line_id: str
    script_text_excerpt: str


@dataclass(frozen=True)
class LocalizationAudioSyncResult:
    stale_recordings: list[StaleVoiceLineFinding] = field(default_factory=list)
    missing_audio: list[MissingAudioFinding] = field(default_factory=list)
    unmatched_audio_files: list[str] = field(default_factory=list)
    script_lines_checked: int = 0
    caveat: str = STALENESS_CAVEAT


def scan_localization_audio_sync(
    script_lines: list[ScriptLine], voice_files: list[VoiceLineFile]
) -> LocalizationAudioSyncResult:
    by_line_id: dict[str, list[VoiceLineFile]] = {}
    unmatched: list[str] = []
    for vf in voice_files:
        line_id = vf.line_id or infer_line_id_from_filename(Path(vf.path).name)
        if line_id is None:
            unmatched.append(vf.path)
            continue
        by_line_id.setdefault(_normalize_line_id(line_id), []).append(vf)

    stale: list[StaleVoiceLineFinding] = []
    missing: list[MissingAudioFinding] = []
    for line in script_lines:
        matches = by_line_id.get(_normalize_line_id(line.line_id))
        if not matches:
            missing.append(MissingAudioFinding(line.line_id, line.text[:80]))
            continue
        newest = max(matches, key=lambda v: v.last_modified)
        if newest.last_modified < line.last_modified:
            stale.append(
                StaleVoiceLineFinding(
                    line.line_id, newest.path, line.last_modified, newest.last_modified
                )
            )

    return LocalizationAudioSyncResult(
        stale_recordings=stale,
        missing_audio=missing,
        unmatched_audio_files=sorted(unmatched),
        script_lines_checked=len(script_lines),
    )


def scan_voice_folder(folder_path: str | Path) -> list[VoiceLineFile]:
    """Read-only scan of a folder for voice-line audio files, inferring each
    one's line ID from its filename and reading its filesystem mtime."""
    root = Path(folder_path)
    if not root.is_dir():
        return []
    files: list[VoiceLineFile] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _VOICE_FILE_EXTS:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        files.append(VoiceLineFile(path=str(p), last_modified=mtime, line_id=None))
    return files


def parse_script_lines(text: str, last_modified: float) -> list[ScriptLine]:
    """Parse a simple ``line_id,text`` paste format, one line per entry, all
    sharing ``last_modified`` (typically 'now', or an imported file's own
    mtime) -- Spiced has no access to a per-line edit history inside a
    pasted block of text, only to the paste/file's timestamp as a whole."""
    lines: list[ScriptLine] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or "," not in raw:
            continue
        line_id, _, remainder = raw.partition(",")
        line_id = line_id.strip()
        remainder = remainder.strip()
        if not line_id or not remainder:
            continue
        lines.append(ScriptLine(line_id=line_id, text=remainder, last_modified=last_modified))
    return lines
