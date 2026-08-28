"""Recursive, read-only scan of an Unreal project's ``Content/`` folder
(Market-Viability Roadmap, Phase 3) -- the Unreal counterpart to
``connectors.unity_scan``/``connectors.godot_scan``.

**The Blueprint/binary limitation, named plainly.** Unity's ``.meta``/
``.controller`` files and Godot's ``project.godot``/``.tscn``/``.import``
files are all plain YAML-ish or JSON-ish text -- every scan this codebase
has for those engines reads real structure out of them. Unreal's
``.uasset``/``.umap`` files (which is what every Blueprint, material, mesh,
and level actually is on disk) are Unreal's own binary/serialized format,
undocumented and versioned per-engine-release, and cannot be meaningfully
parsed without the Unreal Editor itself running (its Python API or a
commandlet). This module does not attempt to -- it only scans what's true
of any binary file regardless of contents: its size and its extension.
"Full parity with Unity" for Unreal therefore means full parity for the
C++-scripted surface (``connectors.unreal_docs_scan``); Blueprint-heavy
projects get exactly the file-level scan below, nothing deeper. This is a
real limitation of the target platform, not a shortcut -- see the roadmap
document and each Unreal connector module for the same disclosure.

Every function here only reads files; nothing is ever modified or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Godot/Unity's texture/audio thresholds don't map onto opaque .uasset/.umap
# binaries (a texture, a mesh, and a level all share the same extension) --
# a flat, larger threshold is used instead, since a single .uasset can
# legitimately bundle many sub-objects that a raw source texture never would.
OVERSIZED_UASSET_BYTES = 20 * 1024 * 1024
OVERSIZED_UMAP_BYTES = 50 * 1024 * 1024

# Same conservative thresholds as unity_scan/godot_scan for any raw source
# image/audio file that ended up loose in Content/ instead of going through
# the editor's import pipeline -- this check doesn't touch .uasset/.umap
# binaries at all, only ordinary readable file formats.
OVERSIZED_TEXTURE_BYTES = 4 * 1024 * 1024
OVERSIZED_AUDIO_BYTES = 5 * 1024 * 1024
UNCOMPRESSED_TEXTURE_EXTS = {".png", ".tga", ".bmp", ".tif", ".tiff", ".exr"}
UNCOMPRESSED_AUDIO_EXTS = {".wav", ".aiff", ".aif"}


def iter_content_files(project_path: str | Path) -> list[Path]:
    """Every file under the project's ``Content/`` folder. ``[]`` if the
    project has no ``Content/`` folder."""
    content_dir = Path(project_path) / "Content"
    if not content_dir.is_dir():
        return []
    return [p for p in content_dir.rglob("*") if p.is_file()]


@dataclass(frozen=True)
class OversizedBinaryAssetFinding:
    path: str  # relative to the project root, forward-slashed
    size_bytes: int
    kind: str  # "uasset" | "umap"


def find_oversized_binary_assets(
    project_path: str | Path,
    uasset_threshold: int = OVERSIZED_UASSET_BYTES,
    umap_threshold: int = OVERSIZED_UMAP_BYTES,
) -> list[OversizedBinaryAssetFinding]:
    """Flag large ``.uasset``/``.umap`` files by size alone -- the only
    signal available without the Unreal Editor running (see module
    docstring). A suggestion list only; nothing is opened, converted, or
    deleted."""
    root = Path(project_path)
    findings: list[OversizedBinaryAssetFinding] = []
    for asset in iter_content_files(project_path):
        ext = asset.suffix.lower()
        try:
            size = asset.stat().st_size
        except OSError:
            continue
        threshold = None
        if ext == ".uasset":
            threshold = uasset_threshold
        elif ext == ".umap":
            threshold = umap_threshold
        if threshold is not None and size >= threshold:
            findings.append(
                OversizedBinaryAssetFinding(
                    path=asset.relative_to(root).as_posix(),
                    size_bytes=size,
                    kind=ext.lstrip("."),
                )
            )
    findings.sort(key=lambda f: f.size_bytes, reverse=True)
    return findings


@dataclass(frozen=True)
class LooseSourceAssetFinding:
    path: str  # relative to the project root, forward-slashed
    size_bytes: int
    kind: str  # "texture" | "audio"
    reason: str


def find_loose_uncompressed_source_assets(
    project_path: str | Path,
    texture_threshold: int = OVERSIZED_TEXTURE_BYTES,
    audio_threshold: int = OVERSIZED_AUDIO_BYTES,
) -> list[LooseSourceAssetFinding]:
    """Flag large, uncompressed-format image/audio files sitting directly in
    ``Content/`` rather than as an imported ``.uasset`` -- the one part of
    Unreal's ``Content/`` folder this scan *can* meaningfully inspect,
    since these are ordinary readable formats, not opaque binaries."""
    root = Path(project_path)
    findings: list[LooseSourceAssetFinding] = []
    for asset in iter_content_files(project_path):
        ext = asset.suffix.lower()
        try:
            size = asset.stat().st_size
        except OSError:
            continue
        rel = asset.relative_to(root).as_posix()
        if ext in UNCOMPRESSED_TEXTURE_EXTS and size >= texture_threshold:
            findings.append(
                LooseSourceAssetFinding(
                    path=rel,
                    size_bytes=size,
                    kind="texture",
                    reason=(
                        f"{_human_size(size)} {ext} file sitting loose in Content/ — usually "
                        "means it hasn't been imported through the Editor yet."
                    ),
                )
            )
        elif ext in UNCOMPRESSED_AUDIO_EXTS and size >= audio_threshold:
            findings.append(
                LooseSourceAssetFinding(
                    path=rel,
                    size_bytes=size,
                    kind="audio",
                    reason=(
                        f"{_human_size(size)} {ext} file sitting loose in Content/ — usually "
                        "means it hasn't been imported through the Editor yet."
                    ),
                )
            )
    findings.sort(key=lambda f: f.size_bytes, reverse=True)
    return findings


def _human_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.1f} MB"
