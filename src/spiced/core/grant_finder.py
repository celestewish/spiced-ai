"""Grant/Funding Finder use-case (Phase H, section 7 part 2, Stretch tier).

Follows ``core.release_checklist``'s pattern exactly: a small, curated,
static dataset of well-known, long-established funding programs -- general,
slow-changing facts (who it's for, roughly what kind of project, the
official URL) rather than precise amounts/deadlines Spiced can't verify stay
current. Stateless (no database table needed -- it's cheap to recompute), and
every entry ends with an explicit "verify against the official page" caveat.
This is informational only, never a guarantee of eligibility or funding.

Dataset provenance: every entry below was verified via live web research
specifically so this feature ships accurate information rather than
hallucinated grant programs. This is a deliberately short, curated list --
a short accurate list beats a long uncertain one. A future contributor can
extend ``GRANTS`` with another ``GrantEntry`` without touching the filtering
logic below.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INFORMATIONAL_ONLY_NOTICE = (
    "Informational only, not a guarantee of eligibility or funding. Amounts, deadlines, and "
    "eligibility criteria change -- always verify current details on the official page before "
    "applying."
)

_VERIFY_NOTE = (
    "Amounts, deadlines, and eligibility change over time -- verify current details on the "
    "official page ({url}) before applying. This is informational only, never a guarantee of "
    "eligibility or funding."
)


@dataclass(frozen=True)
class GrantEntry:
    key: str
    name: str
    url: str
    description: str
    # Empty tuple means "not narrowed on this dimension" -- broadly applicable.
    project_types: tuple[str, ...] = field(default_factory=tuple)
    regions: tuple[str, ...] = field(default_factory=tuple)
    stages: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verify_note(self) -> str:
        return _VERIFY_NOTE.format(url=self.url)


# Verified entries only -- see module docstring. Do not add an entry here
# without being genuinely confident it's real and still described accurately;
# leave it out rather than guess.
GRANTS: tuple[GrantEntry, ...] = (
    GrantEntry(
        key="epic_megagrants",
        name="Epic MegaGrants",
        url="https://www.unrealengine.com/megagrants",
        description=(
            "Funds projects using Unreal Engine (or UEFN) or contributing to the open-source "
            "3D graphics ecosystem. Grants have historically ranged roughly $3,000 to "
            "$150,000+ depending on project scope. Submissions are rolling/window-based -- "
            "check the official page for current submission windows rather than assuming a "
            "fixed schedule."
        ),
        project_types=("unreal", "uefn", "open-source-3d"),
    ),
    GrantEntry(
        key="uk_games_fund",
        name="UK Games Fund",
        url="https://www.ukgamesfund.com",
        description=(
            "UK-government-backed seed-stage funding for UK-based indie studios/developers. "
            "Specific award amounts and application rounds change over time -- check the "
            "official page (or https://www.find-government-grants.service.gov.uk/grants/"
            "uk-games-fund-1 if the primary domain has changed) for the current figures and "
            "eligibility."
        ),
        regions=("uk", "united kingdom"),
        stages=("seed",),
    ),
    GrantEntry(
        key="igda_foundation",
        name="IGDA Foundation",
        url="https://igda.org",
        description=(
            "The International Game Developers Association Foundation funds and runs "
            "scholarship/funding programs supporting underrepresented and marginalized "
            "developers. Specific programs move around IGDA's site over time -- start at the "
            "main org site and look for the Foundation/funding section rather than a "
            "bookmarked sub-page that may no longer be current."
        ),
    ),
)


def _matches_dimension(filter_value: str, tags: tuple[str, ...]) -> bool:
    """Best-effort substring match: an entry with no tags on this dimension is
    broadly applicable and always matches (nothing to narrow against)."""
    if not tags:
        return True
    needle = filter_value.strip().lower()
    if not needle:
        return True
    return any(needle in tag or tag in needle for tag in tags)


def find_grants(
    *, project_type: str = "", region: str = "", stage: str = ""
) -> list[GrantEntry]:
    """Best-effort text filter over the static, curated dataset.

    Each filter is independently optional; an entry with no tags on a given
    dimension is treated as broadly applicable to that dimension (most of
    these three entries aren't narrowed by genre/project type at all, so
    region/stage tend to be the more meaningful filters -- see module
    docstring).
    """
    results = []
    for grant in GRANTS:
        if project_type and not _matches_dimension(project_type, grant.project_types):
            continue
        if region and not _matches_dimension(region, grant.regions):
            continue
        if stage and not _matches_dimension(stage, grant.stages):
            continue
        results.append(grant)
    return results
