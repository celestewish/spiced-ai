"""Safe, local demo-data seeding for portfolio demos.

Spiced can be hard to show off without a real Unity project on hand, so this
module builds one realistic, self-contained demo project — a debug session, a
handful of manual test cases with mixed statuses, one test run, and one player
feedback batch — entirely from bundled sample text.

Everything here is local and deterministic:

- No Unity is run and no real project files are touched.
- Nothing is sent to an AI provider; the "analysis" text is bundled sample copy,
  clearly labelled as a sample so it is never mistaken for a live AI review.
- Seeding is repeat-safe: it never creates a second demo project and never
  overwrites or deletes any project the developer created themselves. It only
  ever reads/writes the single project it owns (matched by its exact name).
"""

from __future__ import annotations

from spiced.core.feedback_classifier import classify
from spiced.core.feedback_parser import parse_feedback
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.projects import Project, ProjectRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository

# The demo project is identified solely by this exact name so seeding can be
# repeat-safe without ever matching a real project.
DEMO_PROJECT_NAME = "Starfall Prototype (Demo)"
DEMO_PROJECT_DESCRIPTION = "Bundled sample project for exploring Spiced. Safe to delete anytime."
DEMO_UNITY_VERSION = "2022.3.10f1"
# Not a real path — a readable label so the dashboard has Unity context to show
# without pointing at (or touching) anything on disk.
DEMO_UNITY_PATH = "Bundled demo — no real Unity folder on disk"

DEMO_SOURCE = "demo"
DEMO_PROVIDER_LABEL = "Sample data (no AI used)"

# Six-line playtest scenario used to build the feedback batch. Deliberately
# mixes a bug, confusion, performance, UI, and praise so the review is realistic.
DEMO_FEEDBACK_TEXT = "\n".join(
    [
        "Playtester 1: I got completely lost in the first room and wasn't sure where to go.",
        "Playtester 2: The game crashed when I grabbed a health pickup.",
        "Playtester 3: Movement feels really smooth and responsive — loved it.",
        "Playtester 4: The pause menu sometimes didn't resume the game.",
        "Playtester 5: Frame rate got choppy during the big fight.",
        "Playtester 6: Really fun overall, and the art style is gorgeous.",
    ]
)


class DemoDataService:
    """Seeds and resets the single bundled demo project (local, no AI, no Unity)."""

    def __init__(self, db: Database) -> None:
        self._projects = ProjectRepository(db)
        self._debug = DebugSessionRepository(db)
        self._cases = TestCaseRepository(db)
        self._runs = TestRunRepository(db)
        self._feedback = FeedbackBatchRepository(db)
        self._db = db

    # --- Queries -----------------------------------------------------------

    def find_demo_project(self) -> Project | None:
        """Return the bundled demo project if it exists, else None."""
        for project in self._projects.list_all():
            if project.name == DEMO_PROJECT_NAME:
                return project
        return None

    def is_seeded(self) -> bool:
        return self.find_demo_project() is not None

    # --- Seeding -----------------------------------------------------------

    def seed(self) -> Project:
        """Create the demo project and its sample data if it isn't there yet.

        Repeat-safe: if the demo project already exists it is returned as-is and
        nothing is duplicated. Real projects are never read from or modified.
        """
        existing = self.find_demo_project()
        if existing is not None:
            return existing
        return self._create_demo()

    def load_fresh_demo(self) -> Project:
        """Reset the demo to its original state, then return it.

        Deletes only the demo project's own rows (matched by its exact name and
        id) and reseeds them. Any project the developer created is untouched.
        """
        existing = self.find_demo_project()
        if existing is not None:
            self._delete_demo_project(existing.id)
        return self._create_demo()

    # --- Internals ---------------------------------------------------------

    def _create_demo(self) -> Project:
        project = self._projects.create(
            name=DEMO_PROJECT_NAME,
            engine="Unity",
            description=DEMO_PROJECT_DESCRIPTION,
        )
        # A Unity "validation-style" context without needing real files on disk.
        project = self._projects.set_unity_folder(
            project.id,
            path=DEMO_UNITY_PATH,
            validation_status="valid",
            metadata={"unity_version": DEMO_UNITY_VERSION, "demo": True},
        )
        self._seed_debug(project.id)
        self._seed_cases(project.id)
        self._seed_run(project.id)
        self._seed_feedback(project.id)
        return project

    def _seed_debug(self, project_id: int) -> None:
        self._debug.create(
            project_id=project_id,
            source_type=DEMO_SOURCE,
            summary=(
                "A health pickup tried to use an object that was never assigned, so the game "
                "hit a NullReferenceException the moment the player collected it."
            ),
            detected_error_type="NullReferenceException",
            detected_file="HealthPickup.cs",
            detected_line=24,
            raw_excerpt=(
                "NullReferenceException: Object reference not set to an instance of an object\n"
                "  at HealthPickup.OnTriggerEnter (UnityEngine.Collider other) "
                "[0x00000] in HealthPickup.cs:24"
            ),
            suggested_next_steps=[
                "Open HealthPickup.cs and check what is referenced on line 24.",
                "Confirm the player's health component is assigned in the Inspector.",
                "Add a null check before applying healing, then retest the pickup.",
            ],
            provider=DEMO_PROVIDER_LABEL,
        )

    def _seed_cases(self, project_id: int) -> None:
        # Mixed statuses so the dashboard and testing screen look realistic.
        specs = [
            ("Player can move and jump", "Controls", "High", "Pass", None),
            (
                "Health pickup restores HP",
                "Gameplay",
                "Critical",
                "Fail",
                "NullReferenceException when collecting a pickup (HealthPickup.cs:24).",
            ),
            (
                "Pause menu opens and resumes play",
                "UI",
                "High",
                "Fail",
                "Resume sometimes does nothing.",
            ),
            ("Level 1 loads from the main menu", "Progression", "Medium", "Pass", None),
            ("Save and load restores progress", "Save/Load", "High", "Blocked", None),
            ("Enemy takes damage from the sword", "Gameplay", "Medium", "Not Run", None),
        ]
        for title, category, priority, status, note in specs:
            case = self._cases.create(
                project_id=project_id,
                title=title,
                category=category,
                priority=priority,
            )
            if status != "Not Run":
                self._cases.set_status(case.id, status, note)

    def _seed_run(self, project_id: int) -> None:
        self._runs.create(
            project_id=project_id,
            source_type=DEMO_SOURCE,
            source_filename="playtest-build-results.txt",
            raw_excerpt=(
                "Ran 5 checks: 2 passed, 2 failed, 1 skipped.\n"
                "FAILED: Health pickup restores HP\n"
                "FAILED: Pause menu resumes correctly"
            ),
            parsed_summary={
                "source_format": DEMO_SOURCE,
                "total": 5,
                "passed": 2,
                "failed": 2,
                "skipped": 1,
                "failures": [
                    "Health pickup restores HP",
                    "Pause menu resumes correctly",
                ],
                "confidence": "high",
            },
            ai_summary=(
                "2 of 5 checks passed. The health-pickup crash and the pause-menu resume "
                "are the two failures worth investigating first."
            ),
            retest_checklist=[
                "Fix and retest the health-pickup crash.",
                "Confirm the pause menu reliably resumes play.",
                "Re-run the skipped save/load check once it is unblocked.",
            ],
            provider=DEMO_PROVIDER_LABEL,
        )

    def _seed_feedback(self, project_id: int) -> None:
        parsed = parse_feedback(DEMO_FEEDBACK_TEXT)
        classification = classify(parsed.entries)
        self._feedback.create(
            project_id=project_id,
            source_type=DEMO_SOURCE,
            entry_count=parsed.entry_count,
            source_label="Playtest 1 (sample)",
            raw_excerpt=parsed.excerpt or None,
            parsed_summary={
                **parsed.as_summary_dict(),
                **classification.as_summary_dict(),
            },
            ai_summary=(
                "Players enjoyed the movement and art, but a health-pickup crash, a pause-menu "
                "bug, first-room confusion, and a framerate dip in big fights need attention."
            ),
            themes=[
                "Smooth, satisfying movement",
                "First-room navigation confusion",
                "Stability and performance rough edges",
            ],
            issues=[
                "Crash when collecting a health pickup",
                "Pause menu occasionally fails to resume",
                "Framerate drops during large fights",
            ],
            action_items=[
                "Fix the health-pickup crash (see Debugging Buddy).",
                "Add a gentle first-room signpost or objective marker.",
                "Profile the big-fight scene for the framerate dip.",
            ],
            provider=DEMO_PROVIDER_LABEL,
        )

    def _delete_demo_project(self, project_id: int) -> None:
        """Delete only the demo project's rows, guarded by its exact name.

        The guard means that even if an id were somehow reused, we never delete a
        project the developer created themselves.
        """
        row = self._db.query_one(
            "SELECT id FROM projects WHERE id = ? AND name = ?",
            (project_id, DEMO_PROJECT_NAME),
        )
        if row is None:
            return
        self._db.execute("DELETE FROM debug_sessions WHERE project_id = ?", (project_id,))
        self._db.execute("DELETE FROM test_cases WHERE project_id = ?", (project_id,))
        self._db.execute("DELETE FROM test_runs WHERE project_id = ?", (project_id,))
        self._db.execute("DELETE FROM feedback_batches WHERE project_id = ?", (project_id,))
        self._db.execute(
            "DELETE FROM projects WHERE id = ? AND name = ?",
            (project_id, DEMO_PROJECT_NAME),
        )
