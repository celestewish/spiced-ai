"""Recursive, read-only scans of a Godot project (Market-Viability Roadmap,
Phase 2) -- the Godot counterpart to ``connectors.unity_scan``.

Structural difference from Unity, worth being explicit about: Godot has no
separate ``Assets/`` subfolder -- the entire project root *is* ``res://``.
Every scan here walks the whole project root, excluding ``.godot/`` (Godot's
local editor cache -- the direct analogue of Unity's ``Library/``, never
worth scanning) and the usual VCS/build directories.

**Format verification.** The oversized-asset thresholds mirror
``unity_scan``'s unchanged -- nothing about what counts as a large PNG is
engine-specific. The ``.import`` sidecar format (``[remap]``/``[deps]``
sections, ``source_file=``) was verified against a real file fetched from
the same ``godotengine/godot-demo-projects`` sample used by
``connectors.godot`` (``icon.webp.import``) -- not assumed from memory.

Every function here only reads files; nothing is ever modified or deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Same conservative, documented-not-authoritative thresholds as
# unity_scan.py -- nothing about what counts as an oversized texture/audio
# source file differs by engine.
OVERSIZED_TEXTURE_BYTES = 4 * 1024 * 1024
OVERSIZED_AUDIO_BYTES = 5 * 1024 * 1024

UNCOMPRESSED_TEXTURE_EXTS = {".png", ".tga", ".bmp", ".tif", ".tiff", ".exr", ".webp"}
UNCOMPRESSED_AUDIO_EXTS = {".wav", ".aiff", ".aif"}
COMPRESSED_TEXTURE_EXTS = {".jpg", ".jpeg"}
COMPRESSED_AUDIO_EXTS = {".ogg", ".mp3"}

# Extensions Godot's editor imports (and therefore writes a "<file>.import"
# sidecar for) -- images and audio, the two kinds this scan cares about.
_IMPORTABLE_EXTS = (
    UNCOMPRESSED_TEXTURE_EXTS
    | UNCOMPRESSED_AUDIO_EXTS
    | COMPRESSED_TEXTURE_EXTS
    | COMPRESSED_AUDIO_EXTS
)

# Never worth walking into: Godot's own editor cache, VCS metadata, and
# addon/plugin code a developer doesn't own (broken-import noise there isn't
# actionable the way it is in the developer's own resources).
_EXCLUDED_DIR_NAMES = {".godot", ".git", ".import"}

_SOURCE_FILE_RE = re.compile(r'^source_file="((?:[^"\\]|\\.)*)"')


def iter_resources(project_path: str | Path) -> list[Path]:
    """Every file under the project root that isn't a ``.import`` sidecar
    and isn't inside an excluded directory. ``[]`` if the folder doesn't
    exist."""
    root = Path(project_path)
    if not root.is_dir():
        return []
    results: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() == ".import":
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in p.relative_to(root).parts[:-1]):
            continue
        results.append(p)
    return results


@dataclass(frozen=True)
class OversizedAssetFinding:
    path: str  # relative to the project root, forward-slashed
    size_bytes: int
    kind: str  # "texture" | "audio"
    reason: str


def find_oversized_and_uncompressed(
    project_path: str | Path,
    texture_threshold: int = OVERSIZED_TEXTURE_BYTES,
    audio_threshold: int = OVERSIZED_AUDIO_BYTES,
) -> list[OversizedAssetFinding]:
    """Flag large/uncompressed-format texture and audio files by extension +
    size -- same logic and thresholds as ``unity_scan.find_oversized_and_
    uncompressed``, over Godot's flat ``res://`` layout instead of ``Assets/``.
    A suggestion list only; nothing is resized, recompressed, or deleted."""
    root = Path(project_path)
    findings: list[OversizedAssetFinding] = []
    for asset in iter_resources(project_path):
        ext = asset.suffix.lower()
        try:
            size = asset.stat().st_size
        except OSError:
            continue
        rel = asset.relative_to(root).as_posix()
        if ext in UNCOMPRESSED_TEXTURE_EXTS and size >= texture_threshold:
            findings.append(
                OversizedAssetFinding(
                    path=rel,
                    size_bytes=size,
                    kind="texture",
                    reason=(
                        f"{_human_size(size)} {ext} file — an uncompressed-prone source "
                        "format at this size; worth checking its Import dock compression "
                        "settings."
                    ),
                )
            )
        elif ext in UNCOMPRESSED_AUDIO_EXTS and size >= audio_threshold:
            findings.append(
                OversizedAssetFinding(
                    path=rel,
                    size_bytes=size,
                    kind="audio",
                    reason=(
                        f"{_human_size(size)} {ext} file — consider compressing to .ogg or "
                        "setting its Import dock compression mode."
                    ),
                )
            )
    findings.sort(key=lambda f: f.size_bytes, reverse=True)
    return findings


def _human_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.1f} MB"


@dataclass(frozen=True)
class ImportScanResult:
    # Importable resources (image/audio) with no "<file>.import" sidecar yet
    # -- Godot re-imports these automatically next time the editor opens the
    # project, so this is a "not yet imported" heads-up, not a broken
    # reference the way a missing Unity .meta would be.
    not_yet_imported: list[str] = field(default_factory=list)
    # ".import" sidecars whose [deps] source_file no longer exists on disk --
    # left behind after the source was renamed or deleted outside the
    # editor. This *is* the direct Godot analogue of Unity's broken-.meta
    # case.
    orphaned_import_files: list[str] = field(default_factory=list)


def scan_imports(project_path: str | Path) -> ImportScanResult:
    """Cross-reference importable resources against their ``.import``
    sidecars, and every ``.import`` sidecar's declared ``source_file``
    against the resource it claims to describe."""
    root = Path(project_path)
    if not root.is_dir():
        return ImportScanResult()

    not_yet_imported: list[str] = []
    for asset in iter_resources(project_path):
        if asset.suffix.lower() not in _IMPORTABLE_EXTS:
            continue
        if not Path(str(asset) + ".import").is_file():
            not_yet_imported.append(asset.relative_to(root).as_posix())

    orphaned: list[str] = []
    for import_file in root.rglob("*.import"):
        if any(part in _EXCLUDED_DIR_NAMES for part in import_file.relative_to(root).parts[:-1]):
            continue
        source = _read_source_file(import_file)
        if source is None:
            continue
        source_path = _resolve_res_path(root, source)
        if source_path is not None and not source_path.is_file():
            orphaned.append(import_file.relative_to(root).as_posix())

    not_yet_imported.sort()
    orphaned.sort()
    return ImportScanResult(not_yet_imported=not_yet_imported, orphaned_import_files=orphaned)


def _read_source_file(import_file: Path) -> str | None:
    try:
        text = import_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        m = _SOURCE_FILE_RE.match(line)
        if m:
            return m.group(1)
    return None


def _resolve_res_path(root: Path, res_path: str) -> Path | None:
    """``"res://a/b.png"`` -> ``<root>/a/b.png``. ``None`` for anything not
    rooted at ``res://`` (e.g. an ``user://`` path, which isn't part of the
    project on disk)."""
    if not res_path.startswith("res://"):
        return None
    return root / res_path[len("res://") :]
