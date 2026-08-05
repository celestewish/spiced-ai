"""Visual Regression Testing (Phase J, section 8 part 2, Phase 2 tier).

Scope decision, matching every other visual feature already in this codebase
(``core.trailer_screenshot_checklist``, ``core.asset_review_queue``): paste/
import only. Spiced never captures a live engine screenshot -- the developer
picks a "before" folder and an "after" folder (screenshots from two builds of
the same key scenes), and Spiced diffs pairs that share a filename, entirely
locally, with Pillow. No new image-hashing dependency is added: this uses
``ImageChops.difference`` (already available via the existing Pillow
dependency) plus a documented pixel-difference-ratio threshold, the same
"simple, dependency-free, deterministic" spirit as
``trailer_screenshot_checklist``'s blank-shot variance heuristic.

For each matched pair this produces both a numeric "how much changed"
signal (the fraction of pixels whose grayscale absolute difference crosses
a threshold) and a saved highlighted-difference image (the "before" image
with changed regions tinted), so the developer can see *where* as well as
*how much*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, UnidentifiedImageError

from spiced.storage.database import default_db_path
from spiced.storage.projects import Project
from spiced.storage.visual_regression_reports import (
    VisualRegressionReport,
    VisualRegressionReportRepository,
)

VISUAL_REGRESSION_CAVEAT = (
    "Local pixel-difference comparison only -- Spiced never captures a live engine screenshot. "
    "Pairs are matched by filename between the 'before' and 'after' folders you pick; anything "
    "unmatched is listed separately, not silently skipped. This has no understanding of *why* a "
    "pair differs -- a deliberate art change reads exactly like an unintended regression. Treat "
    "every flagged pair as 'worth a look side by side,' never a confirmed bug."
)

# Fraction of pixels (0-255 grayscale difference, thresholded at
# _PIXEL_DIFF_THRESHOLD) that must differ before a pair is flagged as
# "changed" -- a documented, deterministic threshold, not a claim about
# visual significance to a player.
CHANGE_RATIO_THRESHOLD = 0.02
_PIXEL_DIFF_THRESHOLD = 24
_DIFF_HIGHLIGHT_COLOR = (255, 0, 255)


class UnreadableImageError(RuntimeError):
    """Raised when Pillow can't open a supplied file as an image."""


@dataclass(frozen=True)
class ImagePairDiff:
    name: str
    before_path: str
    after_path: str
    width: int
    height: int
    size_mismatch: bool
    changed_pixel_ratio: float
    changed: bool
    diff_image_path: str | None = None


@dataclass(frozen=True)
class VisualRegressionResult:
    pairs: list[ImagePairDiff] = field(default_factory=list)
    unmatched_before: list[str] = field(default_factory=list)
    unmatched_after: list[str] = field(default_factory=list)
    caveat: str = VISUAL_REGRESSION_CAVEAT

    @property
    def changed_count(self) -> int:
        return sum(1 for p in self.pairs if p.changed)

    def as_summary_dict(self) -> dict:
        return {
            "pairs": [
                {
                    "name": p.name,
                    "before_path": p.before_path,
                    "after_path": p.after_path,
                    "width": p.width,
                    "height": p.height,
                    "size_mismatch": p.size_mismatch,
                    "changed_pixel_ratio": p.changed_pixel_ratio,
                    "changed": p.changed,
                    "diff_image_path": p.diff_image_path,
                }
                for p in self.pairs
            ],
            "unmatched_before": self.unmatched_before,
            "unmatched_after": self.unmatched_after,
            "changed_count": self.changed_count,
        }


def diff_ratio_and_highlight(before: Image.Image, after: Image.Image) -> tuple[float, Image.Image]:
    """Public entry point (also used by ``ui.widgets.diff_viewer.DiffViewer``,
    Phase L's reusable image-diff widget) for the same changed-pixel-ratio +
    highlighted-diff-image computation ``diff_pair`` uses internally, but
    operating on already-open ``PIL.Image`` objects rather than file paths --
    the widget needs the highlight in memory to render it, not written to
    disk."""
    b = before.convert("RGB")
    a = after.convert("RGB")
    if b.size != a.size:
        a = a.resize(b.size)
    diff_gray = ImageChops.difference(b, a).convert("L")
    pixels = list(diff_gray.getdata())
    changed = sum(1 for p in pixels if p >= _PIXEL_DIFF_THRESHOLD)
    ratio = changed / len(pixels) if pixels else 0.0

    highlight = b.copy()
    mask = diff_gray.point(lambda p: 255 if p >= _PIXEL_DIFF_THRESHOLD else 0)
    color_layer = Image.new("RGB", b.size, _DIFF_HIGHLIGHT_COLOR)
    highlight.paste(color_layer, mask=mask)
    return ratio, highlight


# Backward-compatible private alias -- this module's own diff_pair() below
# used the underscored name before it was made public for reuse.
_diff_ratio_and_highlight = diff_ratio_and_highlight


def diff_pair(
    before_path: str | Path, after_path: str | Path, *, save_diff_to: Path | None = None
) -> ImagePairDiff:
    """Diff one before/after image pair. Raises ``UnreadableImageError``
    (naming the offending file) if either can't be opened by Pillow."""
    try:
        with Image.open(before_path) as before_img, Image.open(after_path) as after_img:
            before_img.load()
            after_img.load()
            size_mismatch = before_img.size != after_img.size
            width, height = before_img.size
            ratio, highlight = _diff_ratio_and_highlight(before_img, after_img)
    except (OSError, UnidentifiedImageError) as exc:
        raise UnreadableImageError(
            f"Could not read \"{Path(before_path).name}\" / \"{Path(after_path).name}\" as "
            f"images: {exc}"
        ) from exc

    diff_image_path = None
    if save_diff_to is not None:
        save_diff_to.parent.mkdir(parents=True, exist_ok=True)
        highlight.save(save_diff_to)
        diff_image_path = str(save_diff_to)

    return ImagePairDiff(
        name=Path(before_path).name,
        before_path=str(before_path),
        after_path=str(after_path),
        width=width,
        height=height,
        size_mismatch=size_mismatch,
        changed_pixel_ratio=round(ratio, 4),
        changed=ratio >= CHANGE_RATIO_THRESHOLD,
        diff_image_path=diff_image_path,
    )


def diff_folders(
    before_dir: str | Path, after_dir: str | Path, *, diff_output_dir: Path | None = None
) -> VisualRegressionResult:
    """Diff every filename common to both folders (non-recursive -- the
    developer picks a flat folder of screenshots for each build, matching
    the paste/import pattern the rest of this codebase's visual features use).
    Raises ``UnreadableImageError`` on the first pair Pillow can't open."""
    before_files = {p.name: p for p in Path(before_dir).iterdir() if p.is_file()}
    after_files = {p.name: p for p in Path(after_dir).iterdir() if p.is_file()}
    common = sorted(set(before_files) & set(after_files))

    pairs: list[ImagePairDiff] = []
    for name in common:
        save_to = Path(diff_output_dir) / f"diff_{name}" if diff_output_dir is not None else None
        pairs.append(diff_pair(before_files[name], after_files[name], save_diff_to=save_to))

    return VisualRegressionResult(
        pairs=pairs,
        unmatched_before=sorted(set(before_files) - set(after_files)),
        unmatched_after=sorted(set(after_files) - set(before_files)),
    )


def _diff_output_dir(project: Project) -> Path:
    """Where highlighted diff images for one project's runs are saved --
    alongside the local database, same "hidden app folder in the user's
    home directory" convention as ``storage.database.default_db_path``."""
    return default_db_path().parent / "visual_regression_diffs" / str(project.id)


class VisualRegressionService:
    def __init__(self, reports: VisualRegressionReportRepository) -> None:
        self._reports = reports

    def diff(
        self, project: Project | None, before_dir: str | Path, after_dir: str | Path
    ) -> tuple[VisualRegressionResult, VisualRegressionReport | None]:
        diff_output_dir = _diff_output_dir(project) if project is not None else None
        result = diff_folders(before_dir, after_dir, diff_output_dir=diff_output_dir)
        report = None
        if project is not None:
            report = self._reports.create(project.id, result.as_summary_dict())
        return result, report

    def history(self, project_id: int, limit: int = 20) -> list[VisualRegressionReport]:
        return self._reports.list_for_project(project_id, limit=limit)
