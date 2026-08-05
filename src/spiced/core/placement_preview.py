"""In-Engine Placement Preview -- scoped down (Phase I, section 8, Stretch tier).

**Scope decision, stated plainly**: the literal spec ("renders a quick
in-context preview of how a new asset looks placed in-scene, without
requiring the artist to open or know the engine") describes actual 3D/2D
engine rendering. Spiced deliberately never renders a scene or runs the
engine beyond the few narrow, already-established opt-in exceptions (Run
Unity Tests, the headless Build Pipeline) -- neither of which renders
anything visual. Building a true in-engine preview would mean embedding or
driving Unity's own renderer, which is out of scope and would violate that
principle.

**What this builds instead**: a simple 2D image composite using Pillow (the
same dependency already used by the Trailer & Screenshot Checklist and
Asset Review Queue -- no new library). The developer picks a background
reference image (e.g. an existing screenshot of the scene/area) and the new
asset image; Spiced pastes the asset onto the background at a
developer-specified position and scale, producing a rough visual mockup.

This is **not a real in-engine render** -- no lighting, shading, camera
perspective, physics, or gameplay collision is represented, and every result
and the Art screen's copy say so explicitly and repeatedly, never just once
in a docstring.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

PLACEMENT_PREVIEW_DISCLAIMER = (
    "This is a rough 2D compositing mockup ONLY -- NOT a real in-engine render. Lighting, "
    "shading, camera perspective, physics, and gameplay collision are not represented. Use it "
    "purely as a rough 'does this roughly fit here' sanity check, never as a preview of how the "
    "asset will actually look or behave in Unity."
)


class UnreadableImageError(RuntimeError):
    """Raised when Pillow can't open the background or asset image."""


@dataclass(frozen=True)
class PlacementPreviewResult:
    output_path: str
    background_size: tuple[int, int]
    asset_size_placed: tuple[int, int]
    position: tuple[int, int]
    scale: float
    disclaimer: str = PLACEMENT_PREVIEW_DISCLAIMER


def create_placement_preview(
    background_path: str | Path,
    asset_path: str | Path,
    output_path: str | Path,
    *,
    x: int | None = None,
    y: int | None = None,
    scale: float = 1.0,
) -> PlacementPreviewResult:
    """Composite ``asset_path`` onto ``background_path`` and save to
    ``output_path``. ``x``/``y`` default to centering the asset on the
    background. ``scale`` defaults to 1.0 (no resizing)."""
    try:
        with Image.open(background_path) as bg_src:
            background = bg_src.convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise UnreadableImageError(f'Could not read the background image: {exc}') from exc

    try:
        with Image.open(asset_path) as asset_src:
            asset = asset_src.convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise UnreadableImageError(f'Could not read the asset image: {exc}') from exc

    if scale != 1.0 and scale > 0:
        new_size = (max(1, round(asset.width * scale)), max(1, round(asset.height * scale)))
        asset = asset.resize(new_size)

    placed_x = x if x is not None else (background.width - asset.width) // 2
    placed_y = y if y is not None else (background.height - asset.height) // 2

    composite = background.copy()
    composite.paste(asset, (placed_x, placed_y), asset)
    composite.convert("RGB").save(output_path)

    return PlacementPreviewResult(
        output_path=str(output_path),
        background_size=background.size,
        asset_size_placed=asset.size,
        position=(placed_x, placed_y),
        scale=scale,
    )
