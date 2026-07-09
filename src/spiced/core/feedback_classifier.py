"""Local heuristic feedback classification.

Runs before the AI step to give the model structured, deterministic evidence and
to make the feature testable. It is intentionally simple keyword scoring — not a
sentiment model — and never decides anything on the developer's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.core.feedback_parser import FeedbackEntry

BUG = "Bug or technical issue"
CONFUSION = "Confusion or onboarding issue"
FEATURE = "Feature request"
BALANCE = "Balance or difficulty concern"
PERFORMANCE = "Performance concern"
UIUX = "UI/UX concern"
PRAISE = "Praise"
PREFERENCE = "Subjective design preference"
UNKNOWN = "Unknown or mixed"

CATEGORIES = (
    BUG,
    CONFUSION,
    FEATURE,
    BALANCE,
    PERFORMANCE,
    UIUX,
    PRAISE,
    PREFERENCE,
    UNKNOWN,
)

# Ordered by scoring priority when scores tie: earlier wins. Technical/actionable
# signals outrank subjective ones so a mixed line surfaces the concrete issue.
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (BUG, (
        "crash", "crashed", "bug", "glitch", "broke", "broken", "error", "freeze",
        "froze", "fell through", "clip", "clipped", "not respond", "didn't respond",
        "did not respond", "unresponsive", "does not work", "doesn't work",
        "softlock", "soft lock", "exception", "null", "black screen",
    )),
    (PERFORMANCE, (
        "lag", "laggy", "fps", "framerate", "frame rate", "stutter", "stuttter",
        "slow", "performance", "loading time", "load time", "memory leak",
        "overheat", "choppy",
    )),
    (CONFUSION, (
        "confus", "did not understand", "didn't understand", "don't understand",
        "unclear", "where to go", "got lost", "i was lost", "how do i", "how to",
        "couldn't figure", "could not figure", "no idea", "not sure what",
        "tutorial", "onboarding", "didn't know", "did not know",
    )),
    (BALANCE, (
        "too hard", "too easy", "too tanky", "tanky", "difficulty", "difficult",
        "balance", "grindy", "overpowered", "unfair", "bullet sponge", "spongy",
        "hit it forever", "takes forever", "too many", "too few", "nerf", "buff",
    )),
    (UIUX, (
        "ui", "hud", "menu", "button", "layout", "font", "readability", "readable",
        "icon", "interface", "resolution", "text too small", "hard to read",
        "cluttered", "hard to navigate",
    )),
    (FEATURE, (
        "wish", "would like", "please add", "it would be nice", "would be nice",
        "add more", "want more", "i want", "hope you add", "could you add",
        "suggestion", "feature request", "should add", "more checkpoints",
    )),
    (PRAISE, (
        "love", "loved", "great", "awesome", "amazing", "fun", "enjoyed", "enjoy",
        "smooth", "satisfying", "fantastic", "feels good", "really good",
        "so good", "beautiful", "polished", "addictive", "best part",
    )),
    (PREFERENCE, (
        "personally", "in my opinion", "i think", "i'd rather", "i would rather",
        "prefer", "for my taste", "aesthetic", "too cartoony", "art style",
        "vibe", "feels like it should", "i don't like", "not a fan",
    )),
)


@dataclass
class FeedbackClassification:
    counts: dict = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)  # per-entry primary category

    def as_summary_dict(self) -> dict:
        return {"category_counts": self.counts}


def classify_entry(text: str) -> str:
    """Return the single best-matching category for one feedback string."""
    lowered = text.lower()
    best_category = UNKNOWN
    best_score = 0
    for category, keywords in _KEYWORDS:
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


def classify(entries: list[FeedbackEntry]) -> FeedbackClassification:
    """Classify each entry and tally category counts across the batch."""
    counts: dict[str, int] = {}
    labels: list[str] = []
    for entry in entries:
        label = classify_entry(entry.text)
        labels.append(label)
        counts[label] = counts.get(label, 0) + 1
    return FeedbackClassification(counts=counts, labels=labels)
