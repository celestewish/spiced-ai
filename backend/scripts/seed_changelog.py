"""One-time seed: real changelog entries for Spiced's already-shipped phases.

Every entry below is a plain-language paraphrase of what actually shipped,
sourced strictly from this repo's own ``git log`` (the Phase 0-6 merge
commits) and the corresponding code, plus Phase A/B which are also already
merged into main — see ``.claude/plans/serene-imagining-karp.md`` for the
original phase descriptions. Nothing here is fabricated marketing copy, and
nothing describes a feature that isn't actually in the codebase. Phase C
(this phase) is intentionally NOT included yet — it hasn't merged, so it
hasn't "shipped" from a user's point of view.

Idempotent: skips any (version_or_phase_label, title) pair that's already
present, so running this more than once is safe.

Usage (from ``backend/``, with DATABASE_URL pointing at the target database):

    python -m scripts.seed_changelog
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models import ChangelogEntry

ENTRIES: list[dict[str, str]] = [
    {
        "version_or_phase_label": "Phase 0",
        "title": "Desktop app skeleton",
        "body": (
            "Laid the foundation for Spiced: a PySide6 desktop shell with sidebar "
            "navigation, local SQLite storage, and the first AI provider wiring."
        ),
    },
    {
        "version_or_phase_label": "Phase 1",
        "title": "Unity Debugging Buddy",
        "body": (
            "Paste or import a Unity error log and get a calm, structured diagnosis with "
            "safe next steps. A local, deterministic parser reads the log first; only a "
            "trimmed excerpt is ever sent to the AI provider, never the full log."
        ),
    },
    {
        "version_or_phase_label": "Phase 2",
        "title": "Automated Testing foundation",
        "body": (
            "Track manual test cases (title, steps, expected result, status) and get an "
            "AI-assisted review of pasted or imported test-run results, including a retest "
            "checklist. Editing and deleting test cases followed shortly after."
        ),
    },
    {
        "version_or_phase_label": "Phase 3",
        "title": "Feedback Review foundation",
        "body": (
            "Paste or import player feedback and see it parsed locally into theme cards by "
            "category, plus an AI-written review that separates bugs from design "
            "preferences without deciding your design for you."
        ),
    },
    {
        "version_or_phase_label": "Phase 4",
        "title": "Project Dashboard and build-readiness overview",
        "body": (
            "A new Dashboard screen rolls up recent debugging, testing, and feedback "
            "activity into a single build-readiness read — evidence and caveats, never a "
            "hidden score."
        ),
    },
    {
        "version_or_phase_label": "Phase 5A",
        "title": "Safe local demo-data seeding",
        "body": (
            "A one-click, repeat-safe way to load a bundled demo project so new users can "
            "see every screen populated with realistic sample data — fully local, nothing "
            "sent anywhere, and it never touches your own projects."
        ),
    },
    {
        "version_or_phase_label": "Phase 6",
        "title": "Testing/QA, Debugging, and Feedback expansion",
        "body": (
            "Added Performance & Profiling reports with an optional target-hardware "
            "simulation, an Accessibility Pass (real WCAG contrast math plus a "
            "colorblind-simulation check), Version-Aware Suggestions (local scanning for "
            "deprecated Unity APIs), a Code Health Dashboard, Known Issues / regression "
            "tracking so repeat bugs are recognized, Community Pulse check-ins (opt-in), "
            "and feedback-to-task drafting. Also added an opt-in \"Run Unity tests\" action "
            "that launches a project's own Unity Test Runner headlessly and feeds the "
            "results through the same review pipeline as a pasted result."
        ),
    },
    {
        "version_or_phase_label": "Phase A",
        "title": "Backend & Auth Foundation",
        "body": (
            "Introduced a hosted FastAPI + Postgres backend and Supabase-based sign-up/"
            "log-in, laying the groundwork for Small-Team Mode. Solo-Dev Mode is "
            "completely unaffected and remains fully local by default."
        ),
    },
    {
        "version_or_phase_label": "Phase B",
        "title": "Team & Workflow",
        "body": (
            "Added Solo-Dev Mode vs. Small-Team Mode as an explicit, off-by-default "
            "settings toggle; AI-generated session summaries that can post to a "
            "team-linked project so teammates see the same recap; and a non-gamified "
            "Build Health Score badge — evidence and caveats, not a score — as a "
            "persistent header on the Testing screen."
        ),
    },
]


def run() -> int:
    db = SessionLocal()
    inserted = 0
    try:
        existing = {
            (row.version_or_phase_label, row.title)
            for row in db.query(ChangelogEntry.version_or_phase_label, ChangelogEntry.title)
        }
        for entry in ENTRIES:
            key = (entry["version_or_phase_label"], entry["title"])
            if key in existing:
                continue
            db.add(ChangelogEntry(**entry))
            inserted += 1
        db.commit()
    finally:
        db.close()
    return inserted


if __name__ == "__main__":
    count = run()
    print(f"Inserted {count} changelog entr{'y' if count == 1 else 'ies'}.")
