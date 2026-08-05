"""Asset Review Queue (Phase I, section 8, Core tier).

Artists "upload" assets to a review queue -- paste a folder path or pick
files via a file dialog (UI concern, ``ui.screens.art``) -- and Spiced runs
local, deterministic technical checks per asset:

1. **Resolution power-of-two** (images only): a common Unity texture-import
   convention, not a hard rule -- framed as a heads-up, never a failure.
2. **File-size sanity**: reuses the same documented thresholds as the Asset
   Optimization Sweep (``connectors.unity_scan.OVERSIZED_TEXTURE_BYTES`` /
   ``OVERSIZED_AUDIO_BYTES``) rather than inventing new ones.
3. **Format check**: flags known *source-only* formats (``.psd``,
   ``.aseprite``, ``.clip``, ``.procreate``, ...) that are conventionally
   exported to a Unity-importable format before being dropped into
   ``Assets/`` -- Spiced cannot verify whether an exported copy exists
   elsewhere, so this is a reminder, not a confirmed problem.
4. **``.meta`` introspection**: Unity's ``.meta`` files are plain,
   regex-extractable text sitting next to each imported asset (the same
   structural fact ``connectors.unity_scan`` already relies on for GUIDs).
   A texture's mipmap setting is genuinely visible there, nested under
   ``TextureImporter: mipmaps: enableMipMap: 0/1`` -- **verified against a
   real Unity-generated ``.meta`` file** (a texture ``.meta`` fetched from a
   public GitHub repo, tangrams/unity-terrain-example's
   ``Assets/normals.png.meta``), not merely inferred from documentation; the
   original task brief's guessed field name (``mipmaps: enabled:``) turned
   out not to match Unity's real serialization and was corrected to
   ``enableMipMap`` after checking the sample. If no ``.meta`` file exists
   next to an asset at all, that's flagged too -- it means the asset was
   never imported through Unity, a real, checkable problem (not every
   picked file will be under a Unity project's ``Assets/`` folder, in which
   case a missing ``.meta`` is expected and not surfaced as a defect --
   see ``project_root``).

This is suggestions only -- nothing is ever modified, deleted, or
re-exported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from spiced.connectors.unity_scan import (
    OVERSIZED_AUDIO_BYTES,
    OVERSIZED_TEXTURE_BYTES,
    UNCOMPRESSED_AUDIO_EXTS,
    UNCOMPRESSED_TEXTURE_EXTS,
)
from spiced.storage.asset_review_reports import AssetReviewReport, AssetReviewReportRepository
from spiced.storage.projects import Project

REVIEW_QUEUE_CAVEAT = (
    "Automated technical checks only -- not an art-direction review. Power-of-two is a common "
    "Unity texture-import convention, not a hard rule; a non-power-of-two texture is completely "
    "fine for UI art, sprites, or anything not tiled/mip-mapped. Missing mipmaps or a missing "
    ".meta file only matter for assets actually placed under a Unity project's Assets/ folder -- "
    "a file reviewed from anywhere else on disk won't have a .meta yet and that's expected, not "
    "a defect."
)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff"}
_SOURCE_ONLY_EXTS = {".psd", ".aseprite", ".ase", ".clip", ".procreate", ".xcf", ".sketch"}

_META_GUID_RE = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
_TEXTURE_IMPORTER_RE = re.compile(r"^TextureImporter:\s*$", re.MULTILINE)
_ENABLE_MIPMAP_RE = re.compile(r"^\s*enableMipMap:\s*(\d)", re.MULTILINE)


class UnreadableAssetError(RuntimeError):
    """Raised when the file can't be read at all (not an image-format problem)."""


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


@dataclass(frozen=True)
class AssetReviewFinding:
    path: str
    kind: str  # "image" | "other"
    file_size_bytes: int
    width: int | None
    height: int | None
    is_power_of_two: bool | None
    oversized: bool
    format_warning: str | None
    meta_present: bool | None  # None when project_root wasn't supplied (not checked)
    meta_has_guid: bool | None
    mipmaps_enabled: bool | None  # None when unknown (no meta, not a texture importer, unparsed)
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": self.kind,
            "file_size_bytes": self.file_size_bytes,
            "width": self.width,
            "height": self.height,
            "is_power_of_two": self.is_power_of_two,
            "oversized": self.oversized,
            "format_warning": self.format_warning,
            "meta_present": self.meta_present,
            "meta_has_guid": self.meta_has_guid,
            "mipmaps_enabled": self.mipmaps_enabled,
            "issues": self.issues,
            "passed": self.passed,
        }


def review_asset(path: str | Path, *, project_root: str | Path | None = None) -> AssetReviewFinding:
    """Run every local, deterministic check on a single asset file.

    ``project_root`` is optional: when given and the asset sits under
    ``project_root/Assets``, ``.meta`` absence is treated as a real finding;
    otherwise ``.meta`` checks are skipped (not just "missing") since a
    freshly-picked file outside any Unity project has no reason to have one
    yet.
    """
    p = Path(path)
    if not p.is_file():
        raise UnreadableAssetError(f'"{p}" is not a readable file.')
    ext = p.suffix.lower()
    size = p.stat().st_size
    issues: list[str] = []

    width = height = None
    is_pow2 = None
    kind = "image" if ext in _IMAGE_EXTS else "other"
    if kind == "image":
        try:
            with Image.open(p) as img:
                width, height = img.size
        except (OSError, UnidentifiedImageError):
            kind = "other"
        else:
            is_pow2 = _is_power_of_two(width) and _is_power_of_two(height)
            if not is_pow2:
                issues.append(
                    f"{width}x{height} is not a power-of-two resolution -- a common Unity "
                    "texture-import convention, not a hard rule; only worth a look if this is a "
                    "tiled or mip-mapped texture."
                )

    oversized = False
    if ext in UNCOMPRESSED_TEXTURE_EXTS and size >= OVERSIZED_TEXTURE_BYTES:
        oversized = True
        issues.append(f"{size / (1024 * 1024):.1f} MB is large for an uncompressed-prone format.")
    elif ext in UNCOMPRESSED_AUDIO_EXTS and size >= OVERSIZED_AUDIO_BYTES:
        oversized = True
        issues.append(f"{size / (1024 * 1024):.1f} MB is large for an uncompressed-prone format.")

    format_warning = None
    if ext in _SOURCE_ONLY_EXTS:
        format_warning = (
            f"{ext} looks like a source-only working file -- double-check it's also been "
            "exported to a Unity-importable format (Spiced can't tell whether an exported copy "
            "exists elsewhere)."
        )
        issues.append(format_warning)

    meta_present: bool | None = None
    meta_has_guid: bool | None = None
    mipmaps_enabled: bool | None = None
    check_meta = False
    if project_root is not None:
        try:
            assets_dir = (Path(project_root) / "Assets").resolve()
            p.resolve().relative_to(assets_dir)
            check_meta = True
        except (OSError, ValueError):
            check_meta = False
    if check_meta:
        meta_path = p.with_name(p.name + ".meta")
        meta_present = meta_path.is_file()
        if not meta_present:
            issues.append(
                "No .meta file found next to this asset -- it was likely never imported "
                "through Unity."
            )
        else:
            try:
                meta_text = meta_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                meta_text = ""
            meta_has_guid = bool(_META_GUID_RE.search(meta_text))
            if not meta_has_guid:
                issues.append("The .meta file exists but no guid could be found in it.")
            if _TEXTURE_IMPORTER_RE.search(meta_text):
                mip_match = _ENABLE_MIPMAP_RE.search(meta_text)
                if mip_match:
                    mipmaps_enabled = mip_match.group(1) == "1"
                    if not mipmaps_enabled:
                        issues.append(
                            "Mipmaps are disabled (enableMipMap: 0) -- fine for UI/pixel-perfect "
                            "art, worth double-checking for a texture used in 3D space."
                        )

    return AssetReviewFinding(
        path=str(p),
        kind=kind,
        file_size_bytes=size,
        width=width,
        height=height,
        is_power_of_two=is_pow2,
        oversized=oversized,
        format_warning=format_warning,
        meta_present=meta_present,
        meta_has_guid=meta_has_guid,
        mipmaps_enabled=mipmaps_enabled,
        issues=issues,
    )


def iter_folder_files(folder_path: str | Path) -> list[Path]:
    """Every non-``.meta`` file under ``folder_path``, recursively. Shared by
    ``review_folder`` and by ``ui.screens.art`` so folder-walking logic
    exists in exactly one place."""
    root = Path(folder_path)
    if not root.is_dir():
        return []
    return [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() != ".meta"]


def review_folder(
    folder_path: str | Path, *, project_root: str | Path | None = None
) -> list[AssetReviewFinding]:
    return [review_asset(p, project_root=project_root) for p in iter_folder_files(folder_path)]


def review_paths(
    paths: list[str], *, project_root: str | Path | None = None
) -> list[AssetReviewFinding]:
    return [review_asset(p, project_root=project_root) for p in paths]


@dataclass(frozen=True)
class AssetReviewResult:
    findings: list[AssetReviewFinding]
    report: AssetReviewReport | None
    caveat: str = REVIEW_QUEUE_CAVEAT

    @property
    def flagged_count(self) -> int:
        return sum(1 for f in self.findings if not f.passed)


class AssetReviewQueueService:
    def __init__(self, reports: AssetReviewReportRepository) -> None:
        self._reports = reports

    def review(
        self, paths: list[str], *, project: Project | None = None
    ) -> AssetReviewResult:
        project_root = project.path if project is not None else None
        findings = review_paths(paths, project_root=project_root)
        report = None
        if project is not None:
            report = self._reports.create(project.id, [f.as_dict() for f in findings])
        return AssetReviewResult(findings=findings, report=report)

    def history(self, project_id: int, limit: int = 20) -> list[AssetReviewReport]:
        return self._reports.list_for_project(project_id, limit=limit)
