"""Texture & Palette Drift Detection (Implementation Bible, Feature 4).

Flags when a new asset's color palette drifts from the project's
established style reference. Runs over the same image-asset batch pattern
as Asset Technical QA Scan (Feature 3), via the shared ``BatchRunner``
(Feature 0) directly -- unlike Features 1-3, this needs no external tool or
engine connection at all, so it's a clean, direct BatchRunner consumer.

No ML model: "dominant colors" come from a small hand-rolled k-means loop
over a downsampled pixel array (numpy only -- see pyproject.toml for why
scipy isn't added just for this), and "how different" is the average
nearest-color Delta-E (CIE76) between the asset's palette and the
reference's, in CIE Lab space -- both are well-documented, standard
formulas implemented directly here rather than via the unmaintained
``colormath`` package, per the Bible's own "hand-rolled Lab conversion"
fallback.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from spiced.automation.batch_runner import BatchRunner
from spiced.automation.finding import Finding, FindingItem
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.palette_reference_colors import (
    PaletteReferenceColor,
    PaletteReferenceColorRepository,
)
from spiced.storage.projects import Project

FEATURE_ID = "art.palette_drift"

DEFAULT_K = 8
# CIE76 Delta-E: ~2.3 is "just noticeable" to a trained eye, ~10 is
# "noticeable at a glance" for most people. 15 flags a palette that's
# clearly drifted, not one that's merely not pixel-identical.
DEFAULT_DELTA_E_THRESHOLD = 15.0
THUMBNAIL_SIZE = 100  # downsample before clustering -- plenty for a palette

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff")

_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")


class UnreadableImageError(RuntimeError):
    """Raised when Pillow can't open a supplied file as an image."""


class NoReferencePaletteError(RuntimeError):
    """Raised when a project has no reference palette colors configured."""


def normalize_hex_color(value: str) -> str:
    match = _HEX_RE.match(value.strip())
    if not match:
        raise ValueError(f'"{value}" is not a 6-digit hex color, e.g. "#3366CC".')
    return f"#{match.group(1).lower()}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = normalize_hex_color(hex_color)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _kmeans(pixels: np.ndarray, k: int, *, iterations: int = 10, seed: int = 0) -> np.ndarray:
    """Minimal k-means over an (N, 3) array, returning (k, 3) cluster centers."""
    if len(pixels) == 0:
        return np.zeros((0, 3))
    k = min(k, len(pixels))
    rng = np.random.default_rng(seed)
    centers = pixels[rng.choice(len(pixels), size=k, replace=False)].astype(float)
    for _ in range(iterations):
        distances = np.linalg.norm(pixels[:, None, :] - centers[None, :, :], axis=2)
        labels = distances.argmin(axis=1)
        new_centers = np.array(
            [
                pixels[labels == i].mean(axis=0) if np.any(labels == i) else centers[i]
                for i in range(k)
            ]
        )
        converged = np.allclose(new_centers, centers)
        centers = new_centers
        if converged:
            break
    return centers


def extract_dominant_colors(
    path: str | Path, k: int = DEFAULT_K, thumbnail_size: int = THUMBNAIL_SIZE
) -> list[str]:
    """The ``k`` dominant colors in ``path``, as ``#rrggbb`` hex strings."""
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((thumbnail_size, thumbnail_size))
            pixels = np.asarray(img).reshape(-1, 3)
    except (OSError, UnidentifiedImageError) as exc:
        raise UnreadableImageError(
            f'Could not read "{Path(path).name}" as an image: {exc}'
        ) from exc

    centers = _kmeans(pixels, k)
    return [_rgb_to_hex(tuple(c)) for c in centers]


def _srgb_channel_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lab_f(t: float) -> float:
    delta = 6 / 29
    return t ** (1 / 3) if t > delta**3 else t / (3 * delta**2) + 4 / 29


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB (D65) -> CIE Lab. Standard, well-documented conversion."""
    r, g, b = (_srgb_channel_to_linear(v) for v in rgb)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883
    fx, fy, fz = _lab_f(x / xn), _lab_f(y / yn), _lab_f(z / zn)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e_cie76(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    return math.sqrt(sum((c1 - c2) ** 2 for c1, c2 in zip(lab1, lab2, strict=True)))


def average_nearest_delta_e(colors_a: list[str], colors_b: list[str]) -> float:
    """For each color in ``colors_a``, the Delta-E to its nearest color in
    ``colors_b``, averaged -- "how far has this palette drifted from that
    one," not a strict one-to-one pairing."""
    if not colors_a or not colors_b:
        return 0.0
    labs_a = [rgb_to_lab(_hex_to_rgb(c)) for c in colors_a]
    labs_b = [rgb_to_lab(_hex_to_rgb(c)) for c in colors_b]
    nearest = [min(delta_e_cie76(a, b) for b in labs_b) for a in labs_a]
    return sum(nearest) / len(nearest)


def check_palette_drift(
    path: str | Path,
    reference_colors: list[str],
    *,
    k: int = DEFAULT_K,
    threshold: float = DEFAULT_DELTA_E_THRESHOLD,
) -> FindingItem:
    dominant = extract_dominant_colors(path, k=k)
    delta_e_avg = average_nearest_delta_e(dominant, reference_colors)
    drifted = delta_e_avg > threshold
    name = Path(path).name
    return FindingItem(
        asset_path=str(path),
        severity="warning" if drifted else "info",
        message=(
            f"{name}: palette drift {delta_e_avg:.1f} dE "
            + ("(flagged)" if drifted else "(within tolerance)")
        ),
        detail={
            "dominant_colors": dominant,
            "reference_colors": reference_colors,
            "delta_e_avg": round(delta_e_avg, 2),
            "threshold": threshold,
        },
    )


def _summarize(items: list[FindingItem], file_count: int) -> str:
    if file_count == 0:
        return "No image files found to check."
    errors = sum(1 for i in items if i.severity == "error")
    flagged = sum(1 for i in items if i.severity == "warning")
    if errors:
        return (
            f"Checked {file_count} image(s); {errors} failed, {flagged} flagged for "
            "palette drift."
        )
    if flagged:
        return f"Checked {file_count} image(s); {flagged} flagged for palette drift."
    return f"Checked {file_count} image(s); no palette drift found."


def scan_folder_for_drift(
    folder_path: str | Path,
    reference_colors: list[str],
    project_id: str,
    *,
    k: int = DEFAULT_K,
    threshold: float = DEFAULT_DELTA_E_THRESHOLD,
) -> Finding:
    if not reference_colors:
        raise NoReferencePaletteError("No reference palette colors were given.")

    runner = BatchRunner(FEATURE_ID, extensions=IMAGE_EXTENSIONS, summary_fn=_summarize)

    def callback(path: Path) -> FindingItem:
        return check_palette_drift(path, reference_colors, k=k, threshold=threshold)

    return runner.run(folder_path, project_id, callback)


def combined_reference_palette(folder_path: str | Path, k: int = DEFAULT_K) -> list[str]:
    """Extract each image's dominant colors under ``folder_path`` (top level
    only -- a curated reference folder, not a recursive project scan), then
    re-cluster the combined set down to ``k`` representative colors."""
    root = Path(folder_path)
    if not root.is_dir():
        raise NoReferencePaletteError(f'"{folder_path}" is not a folder.')
    image_paths = sorted(
        p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not image_paths:
        raise NoReferencePaletteError(f'No image files found in "{folder_path}".')

    all_colors: list[str] = []
    for p in image_paths:
        all_colors.extend(extract_dominant_colors(p, k=k))

    pixels = np.array([_hex_to_rgb(c) for c in all_colors], dtype=float)
    centers = _kmeans(pixels, k)
    return [_rgb_to_hex(tuple(c)) for c in centers]


class PaletteDriftService:
    def __init__(
        self, reference: PaletteReferenceColorRepository, findings: AutomationFindingRepository
    ) -> None:
        self._reference = reference
        self._findings = findings

    # --- Reference palette config --------------------------------------------

    def add_reference_color(self, project_id: int, hex_color: str) -> PaletteReferenceColor:
        return self._reference.add(project_id, hex_color)

    def list_reference_colors(self, project_id: int) -> list[PaletteReferenceColor]:
        return self._reference.list_for_project(project_id)

    def remove_reference_color(self, color_id: int) -> None:
        self._reference.delete(color_id)

    def set_reference_from_folder(
        self, project_id: int, folder_path: str | Path, *, k: int = DEFAULT_K
    ) -> list[PaletteReferenceColor]:
        """Replace this project's reference palette with the combined
        dominant colors extracted from every image in ``folder_path``."""
        colors = combined_reference_palette(folder_path, k=k)
        self._reference.clear(project_id)
        return [self._reference.add(project_id, c) for c in colors]

    # --- Scan -----------------------------------------------------------

    def scan(
        self, project: Project, folder_path: str | Path
    ) -> tuple[Finding, AutomationFindingRecord]:
        reference = [r.hex_color for r in self._reference.list_for_project(project.id)]
        if not reference:
            raise NoReferencePaletteError(
                f'No reference palette is configured for "{project.name}". Add reference colors, '
                "or set a reference folder, first."
            )
        threshold = (
            project.palette_drift_threshold
            if project.palette_drift_threshold is not None
            else DEFAULT_DELTA_E_THRESHOLD
        )
        finding = scan_folder_for_drift(
            folder_path, reference, str(project.id), threshold=threshold
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-palette-drift",
        description=(
            "Check a folder of images against a reference color palette, flagging any whose "
            "dominant colors have drifted more than a Delta-E threshold from the reference."
        ),
    )
    parser.add_argument("folder", help="Folder of images to check (scanned recursively).")
    parser.add_argument(
        "--reference-colors",
        nargs="+",
        required=True,
        help="Reference hex colors, e.g. --reference-colors #336699 #ffcc00",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_DELTA_E_THRESHOLD,
        help=f"Delta-E flag threshold (default: {DEFAULT_DELTA_E_THRESHOLD}).",
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="Dominant colors per image.")
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    try:
        finding = scan_folder_for_drift(
            args.folder,
            args.reference_colors,
            args.project_id,
            k=args.k,
            threshold=args.threshold,
        )
    except NoReferencePaletteError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(finding.as_dict(), indent=2))
    else:
        print(finding.summary)
        for item in finding.items:
            print(f"  [{item.severity}] {item.message}")

    return 1 if finding.status == "error" else 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
