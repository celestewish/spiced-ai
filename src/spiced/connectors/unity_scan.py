"""Recursive, read-only scans of a Unity project's ``Assets/`` folder.

``connectors.unity`` (``detect_unity_project``) is deliberately shallow —
its own docstring says so, and it stays that way. This module is the new,
separate territory Phase D needs: real recursive folder walks that back the
Asset Optimization Sweep and the Code Health Dashboard's Dead Reference
Detection / Naming Consistency checks. Every function here only reads files;
nothing is ever modified or deleted.

GUID cross-referencing note: Unity's ``.unity``/``.prefab``/``.asset``/
``.mat``/``.controller``/``.anim`` files are YAML-ish text, and a full parser
isn't needed to find references — Unity's own ``.meta`` files are just
``guid: <32 hex chars>`` plus importer settings, and every reference to
another asset inside a scene/prefab/etc. is serialized the same way. A
regex extraction of ``guid: <hex>`` occurrences is sufficient and is exactly
what Unity's own tooling relies on structurally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --- Thresholds (Asset Optimization Sweep) ----------------------------------
#
# These are deliberately simple, documented size thresholds rather than a
# claim about "correct" import settings — Unity's actual on-disk/in-memory
# footprint depends on texture compression format, mip maps, and platform,
# none of which a read-only file-size scan can see. The thresholds exist to
# flag files worth a second look, not to declare them wrong.
#
# 4 MB for a single *source* texture file (.png/.tga/.psd/...) is already
# large for anything but a big background/atlas — a good trigger to check the
# texture's Import Settings compression rather than assume it's fine.
OVERSIZED_TEXTURE_BYTES = 4 * 1024 * 1024
# 5 MB for a single *uncompressed* .wav is roughly a minute of 16-bit/44.1kHz
# stereo audio — long enough that most projects would rather compress it
# (.ogg/.mp3) or set its Unity import "Load Type"/compression explicitly.
OVERSIZED_AUDIO_BYTES = 5 * 1024 * 1024

# Extensions that are typically *uncompressed* source formats in a Unity
# project (as opposed to already-compressed .jpg/.ogg/.mp3). Flagged as
# "worth checking your import compression settings," not "wrong."
UNCOMPRESSED_TEXTURE_EXTS = {".png", ".tga", ".bmp", ".psd", ".tif", ".tiff", ".exr"}
UNCOMPRESSED_AUDIO_EXTS = {".wav", ".aiff", ".aif"}
COMPRESSED_TEXTURE_EXTS = {".jpg", ".jpeg"}
COMPRESSED_AUDIO_EXTS = {".ogg", ".mp3"}

# Folders whose contents are conventionally loaded dynamically (Resources.
# Load, StreamingAssets file access) rather than referenced by GUID from a
# scene/prefab — excluding them from "orphaned asset" flags avoids the most
# common false positives that scan can't otherwise account for.
_DYNAMIC_LOAD_DIR_NAMES = {"Resources", "StreamingAssets"}

# Files that reference other assets by GUID. Not exhaustive of every Unity
# YAML asset type, but covers the common referencing surfaces.
_REFERENCING_EXTENSIONS = {".unity", ".prefab", ".asset", ".mat", ".controller", ".anim"}

_GUID_RE = re.compile(r"guid:\s*([0-9a-fA-F]{32})")
_META_GUID_RE = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)


def _looks_builtin(guid: str) -> bool:
    """Heuristic for Unity's own built-in resource GUIDs (default materials,
    default fonts, etc.), which never have a ``.meta`` file under ``Assets/``
    since they ship inside the Editor itself. Unity's built-in GUIDs are long
    runs of the same hex digit with only one or two digits varying, so a low
    count of distinct hex characters is a reasonable, documented signal —
    not a lookup table Spiced can't verify. Also covers guids belonging to
    installed Packages (outside Assets/, so no local .meta is expected) is
    NOT handled by this check; see ``ReferenceScanResult`` caveat.
    """
    return len(set(guid.lower())) <= 3


def iter_assets(project_path: str | Path) -> list[Path]:
    """All non-``.meta`` files under ``Assets/``, or ``[]`` if it's missing."""
    assets_dir = Path(project_path) / "Assets"
    if not assets_dir.is_dir():
        return []
    return [p for p in assets_dir.rglob("*") if p.is_file() and p.suffix.lower() != ".meta"]


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
    """Flag large/uncompressed-format texture and audio files by extension + size.

    A suggestion list only — nothing is resized, recompressed, or deleted.
    """
    root = Path(project_path)
    findings: list[OversizedAssetFinding] = []
    for asset in iter_assets(project_path):
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
                        "format at this size; worth checking its Texture Import "
                        "compression settings."
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
                        f"{_human_size(size)} {ext} file — consider compressing to "
                        ".ogg or setting its Audio Import compression format."
                    ),
                )
            )
    findings.sort(key=lambda f: f.size_bytes, reverse=True)
    return findings


def _human_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.1f} MB"


@dataclass(frozen=True)
class BrokenReference:
    referencing_file: str
    missing_guid: str


@dataclass(frozen=True)
class ReferenceScanResult:
    broken_references: list[BrokenReference] = field(default_factory=list)
    orphaned_assets: list[str] = field(default_factory=list)
    total_meta_files: int = 0
    total_referencing_files: int = 0

    @property
    def caveat(self) -> str:
        return (
            "Best-effort only: an asset can be loaded dynamically (Resources.Load, "
            "Addressables) or come from an installed package, and this scan cannot see "
            "either — treat both lists as things worth a manual look, not certainties."
        )


def scan_references(project_path: str | Path) -> ReferenceScanResult:
    """Cross-reference GUIDs used in scenes/prefabs/etc. against ``.meta`` files.

    Flags (a) referenced GUIDs with no matching ``.meta`` under ``Assets/``
    (broken reference) and (b) ``.meta``-backed assets never referenced by
    anything else scanned (orphaned candidate). See ``ReferenceScanResult.
    caveat`` — this is a best-effort signal, not certainty.
    """
    root = Path(project_path)
    assets_dir = root / "Assets"
    if not assets_dir.is_dir():
        return ReferenceScanResult()

    guid_to_asset: dict[str, Path] = {}
    for meta_path in assets_dir.rglob("*.meta"):
        try:
            text = meta_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _META_GUID_RE.search(text)
        if not match:
            continue
        # meta_path is "<asset>.<ext>.meta" — strip only the trailing ".meta".
        asset_path = Path(str(meta_path)[: -len(".meta")])
        guid_to_asset[match.group(1).lower()] = asset_path

    referenced_guids: set[str] = set()
    broken: list[BrokenReference] = []
    referencing_count = 0
    for asset in iter_assets(project_path):
        if asset.suffix.lower() not in _REFERENCING_EXTENSIONS:
            continue
        try:
            text = asset.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        referencing_count += 1
        rel = asset.relative_to(root).as_posix()
        for guid in {g.lower() for g in _GUID_RE.findall(text)}:
            referenced_guids.add(guid)
            if guid not in guid_to_asset and not _looks_builtin(guid):
                broken.append(BrokenReference(referencing_file=rel, missing_guid=guid))

    orphaned: list[str] = []
    for guid, asset_path in guid_to_asset.items():
        if guid in referenced_guids:
            continue
        try:
            rel_parts = asset_path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in _DYNAMIC_LOAD_DIR_NAMES for part in rel_parts):
            continue
        orphaned.append(Path(*rel_parts).as_posix())

    broken.sort(key=lambda b: (b.referencing_file, b.missing_guid))
    orphaned.sort()
    return ReferenceScanResult(
        broken_references=broken,
        orphaned_assets=orphaned,
        total_meta_files=len(guid_to_asset),
        total_referencing_files=referencing_count,
    )


# --- Naming/Organization Consistency (folded into Code Health Dashboard) ----

_SNAKE_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)+$")
_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
_ALL_LOWER_RE = re.compile(r"^[a-z0-9]+$")
_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")

SNAKE_CASE = "snake_case"
KEBAB_CASE = "kebab-case"
PASCAL_CASE = "PascalCase"
CAMEL_CASE = "camelCase"
_MAX_OUTLIERS = 25


def _classify_name(stem: str) -> str | None:
    if _SNAKE_RE.match(stem):
        return SNAKE_CASE
    if _KEBAB_RE.match(stem):
        return KEBAB_CASE
    if _ALL_LOWER_RE.match(stem):
        return SNAKE_CASE  # single lowercase word — bucketed with snake_case
    if _PASCAL_RE.match(stem):
        return PASCAL_CASE
    if _CAMEL_RE.match(stem) and any(c.isupper() for c in stem):
        return CAMEL_CASE
    return None  # mixed separators, spaces, digits-first, etc. — not classifiable


@dataclass(frozen=True)
class NamingConventionResult:
    dominant_convention: str | None
    convention_counts: dict[str, int] = field(default_factory=dict)
    outliers: list[str] = field(default_factory=list)
    total_classified: int = 0
    total_files: int = 0


def infer_naming_convention(project_path: str | Path) -> NamingConventionResult:
    """Infer the project's dominant filename convention under ``Assets/`` and
    flag outliers — a suggestion, never an enforced rule."""
    files = iter_assets(project_path)
    root = Path(project_path)
    counts: dict[str, int] = {}
    classified: list[tuple[str, str]] = []  # (relative_path, convention)
    for f in files:
        convention = _classify_name(f.stem)
        if convention is None:
            continue
        counts[convention] = counts.get(convention, 0) + 1
        classified.append((f.relative_to(root).as_posix(), convention))

    if not counts:
        return NamingConventionResult(dominant_convention=None, total_files=len(files))

    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    outliers = [path for path, conv in classified if conv != dominant][:_MAX_OUTLIERS]
    return NamingConventionResult(
        dominant_convention=dominant,
        convention_counts=counts,
        outliers=outliers,
        total_classified=len(classified),
        total_files=len(files),
    )
