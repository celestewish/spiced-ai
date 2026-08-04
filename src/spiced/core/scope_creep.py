"""Scope-Creep Flagging use-case (Phase F, section 6, Core tier).

Paired with Design Doc Sync on the same screen per spec — but built entirely
on Auto-Generated Dev Docs' own snapshot history (``dev_docs_snapshots``, via
``core.dev_docs``), not a separate tracking mechanism. Compares successive
snapshots' class/method counts over time and flags sustained, one-directional
growth, optionally cross-referencing new class names against the developer's
uploaded design doc text (from ``core.design_doc_sync``) to call out systems
that grew without ever being mentioned there.

Purely deterministic — no AI call. A single click-through "does the codebase
keep growing" trend either is or isn't there in the numbers Dev Docs already
saved; a narrative pass wouldn't add anything a provider could verify, same
reasoning as the Code Health Dashboard's naming/dead-reference checks.

Framing note: every message here is a gentle heads-up ("scope has grown in
these areas"), never a blocker and never phrased as a problem — per spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.storage.dev_docs_snapshots import DevDocsSnapshot

# Only flag a trend once at least this many snapshots exist — a single
# generation has nothing to compare against, and two isn't enough to call
# growth "sustained" rather than a one-off between two points.
MIN_SNAPSHOTS_FOR_TREND = 3

# Growth only counts as worth mentioning once the codebase has grown by at
# least this many classes since the earliest snapshot in view. Small
# fluctuations (a rename split across two generations, a class merged into
# another) shouldn't trigger a heads-up.
MIN_CLASS_GROWTH = 5


@dataclass(frozen=True)
class ScopeCreepFinding:
    growing: bool
    class_count_trend: list[int] = field(default_factory=list)
    method_count_trend: list[int] = field(default_factory=list)
    new_class_names: list[str] = field(default_factory=list)
    undocumented_new_classes: list[str] = field(default_factory=list)

    @property
    def message(self) -> str | None:
        """A short, gentle heads-up — or None if there's nothing to say.

        Never phrased as a blocker or a verdict, per spec.
        """
        if not self.growing:
            return None
        added = len(self.new_class_names)
        class_word = "class" if added == 1 else "classes"
        note = (
            f"Scope has grown by {added} {class_word} since your earliest tracked Dev Docs "
            "snapshot. Just a heads-up, worth a look — not a blocker."
        )
        if self.undocumented_new_classes:
            names = ", ".join(self.undocumented_new_classes[:8])
            note += f" Some of that growth doesn't show up in your design doc yet: {names}."
        return note


def detect_scope_creep(
    snapshots: list[DevDocsSnapshot], *, design_doc_text: str | None = None
) -> ScopeCreepFinding:
    """Pure, deterministic, local-only.

    ``snapshots`` must be given oldest-first — ``DevDocsSnapshotRepository.
    list_for_project`` returns newest-first, so callers should pass
    ``list(reversed(...))``. ``design_doc_text`` is optional: without it,
    growth is still flagged, just without the "not mentioned in your design
    doc" cross-reference (Design Doc Sync is opt-in and may have nothing
    uploaded yet).
    """
    if len(snapshots) < MIN_SNAPSHOTS_FOR_TREND:
        return ScopeCreepFinding(growing=False)

    class_trend = [len(s.source_summary.get("classes", [])) for s in snapshots]
    method_trend = [s.method_count for s in snapshots]

    # "Sustained/one-directional": the class count never drops between
    # consecutive snapshots, and the total growth clears the noise floor.
    non_decreasing = all(b >= a for a, b in zip(class_trend, class_trend[1:], strict=False))
    total_growth = class_trend[-1] - class_trend[0]
    growing = non_decreasing and total_growth >= MIN_CLASS_GROWTH

    first_names = {c.get("name") for c in snapshots[0].source_summary.get("classes", [])}
    last_classes = snapshots[-1].source_summary.get("classes", [])
    new_names = sorted(
        {c.get("name") for c in last_classes if c.get("name") and c.get("name") not in first_names}
    )

    undocumented: list[str] = []
    if growing and design_doc_text:
        # Plain case-insensitive substring match against the class name
        # itself — not a semantic check. A design doc describing a system
        # in different words ("enemy AI" vs. the class ``EnemyAI``) won't
        # match; that's an accepted false-positive trade-off for staying
        # deterministic and free rather than requiring another AI call here.
        doc_lower = design_doc_text.lower()
        undocumented = [name for name in new_names if name.lower() not in doc_lower]

    return ScopeCreepFinding(
        growing=growing,
        class_count_trend=class_trend,
        method_count_trend=method_trend,
        new_class_names=new_names,
        undocumented_new_classes=undocumented,
    )
