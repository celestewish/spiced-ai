"""Store Page / Build Checklist use-case.

A deterministic, per-platform "ready to ship" checklist — Steam and itch.io
for now, the two stores most indie Unity developers target first. Kept
intentionally small and general rather than citing specific numeric limits
Spiced can't verify stay current (e.g. exact store asset pixel dimensions):
each item below reflects a well-known, slow-changing platform convention, and
every checklist ends with an explicit reminder to verify against the
platform's current docs before shipping. This is a stateless, computed view
(no database table) — the checklist is cheap to recompute and there is no
history worth keeping; a fresh computation is always trustworthy without
needing a saved snapshot. An optional AI commentary pass can be layered on
top (see ``analyze_checklist``), but the checklist itself never depends on
a provider being configured.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from spiced.ai.base import AIProvider

STEAM = "steam"
ITCH = "itch"
PLATFORMS = (STEAM, ITCH)

PLATFORM_LABELS = {STEAM: "Steam", ITCH: "itch.io"}

# A generic "this is getting large" heads-up threshold, not a hard platform
# limit — Steam and itch.io both support very large games; this just flags a
# build worth a second look for patch/download-time impact.
LARGE_BUILD_HEADS_UP_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

_COMMON_ITEMS: tuple[str, ...] = (
    "Confirm the build actually launches from a clean folder (no leftover Editor-only files "
    "or absolute paths baked in from your dev machine).",
    "Double-check your game's version number/build number is visible somewhere you can "
    "reference in support requests (e.g. a small label in a menu, or in the changelog).",
)

_STEAM_ITEMS: tuple[str, ...] = (
    "Steamworks account, app registered, and depot/branch configuration ready in your "
    "SteamPipe build config.",
    "Store page has the required capsule images and at least a handful of screenshots — "
    "Steam won't let you publish a store page missing these.",
    "Keep file layout reasonably stable between builds; SteamPipe patches by content-"
    "addressed chunks, so wholesale repacking/renaming of unchanged files means bigger "
    "patches for players even when the actual content didn't change much.",
    "Push to a private beta branch first and install/verify via steamcmd before flipping "
    "the branch players see live.",
    "Decide upfront whether you want Steam achievements/cloud saves/trading cards — adding "
    "them later is fine, but removing ones players have unlocked is awkward.",
    "Set a content/age rating (Steam's own content survey) if your store page requires one.",
)

_ITCH_ITEMS: tuple[str, ...] = (
    "itch.io has no hard build-size limit, but very large uploads slow downloads for "
    "players on slower connections — worth keeping an eye on total upload size regardless.",
    "Use butler (itch's CLI) to push builds; it diffs against your last upload, so keeping "
    "file layout stable between versions keeps patches small the same way SteamPipe does.",
    "Set a price (or \"no payment\"/\"name your price\") and at least one screenshot — "
    "itch.io requires both before a project page can go live.",
    "Tag the project accurately (platform, genre, engine) — itch.io's discovery leans "
    "heavily on tags rather than a curated storefront.",
    "If you expect players to use the itch app for auto-updates, make sure your "
    "executable ends up at a predictable, stable path across builds.",
)

_VERIFY_NOTE = (
    "Platform requirements change over time — treat this as a general starting checklist "
    "and verify current specifics against {platform}'s own documentation before shipping."
)


@dataclass(frozen=True)
class ChecklistItem:
    text: str
    note: str | None = None


@dataclass(frozen=True)
class ReleaseChecklist:
    platform: str
    platform_label: str
    items: list[ChecklistItem] = field(default_factory=list)
    verify_note: str = ""


def build_checklist(platform: str, build_size_bytes: int | None = None) -> ReleaseChecklist:
    """Compute the deterministic checklist for ``platform``.

    ``build_size_bytes`` is optional — pass the size of a project's most
    recent build output (e.g. from a ``BuildReport.output_path``) to add one
    extra, size-aware heads-up item; omit it for a purely static checklist.
    """
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform: {platform!r}. Expected one of {PLATFORMS}.")

    platform_items = _STEAM_ITEMS if platform == STEAM else _ITCH_ITEMS
    items = [ChecklistItem(text=t) for t in platform_items]
    items.extend(ChecklistItem(text=t) for t in _COMMON_ITEMS)

    if build_size_bytes is not None and build_size_bytes >= LARGE_BUILD_HEADS_UP_BYTES:
        gb = build_size_bytes / (1024**3)
        items.insert(
            0,
            ChecklistItem(
                text=f"Your latest build is about {gb:.1f} GB.",
                note=(
                    "Not a platform limit being hit — just large enough that patch size and "
                    "player download time are worth thinking about."
                ),
            ),
        )

    label = PLATFORM_LABELS[platform]
    return ReleaseChecklist(
        platform=platform,
        platform_label=label,
        items=items,
        verify_note=_VERIFY_NOTE.format(platform=label),
    )


def analyze_checklist(
    provider: AIProvider,
    checklist: ReleaseChecklist,
    *,
    project_name: str | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """Optional brief AI commentary layered on the deterministic checklist.

    The checklist itself stays trustworthy with no provider at all — this is
    purely an optional narrative pass, never persisted (see module docstring
    on why this feature has no database table).
    """
    from spiced.ai.prompt_templates import build_release_checklist_prompt

    prompt = build_release_checklist_prompt(checklist, project_name=project_name)
    if on_chunk is not None:
        return provider.generate_stream(prompt, on_chunk).text
    return provider.generate(prompt).text
