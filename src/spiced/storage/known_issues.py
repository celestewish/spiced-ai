"""Known-issue persistence, backing Regression Tracking.

A known issue is a lightweight, deduplicated record of a bug signature Spiced
has seen before — from a debugging session or a test-result failure — plus
whether the developer has since marked it resolved. New failures are matched
against this history so repeats surface as "this resembles a bug from before"
instead of being re-diagnosed from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"

SOURCE_DEBUG = "debug"
SOURCE_TEST = "test"
# Player Crash & Error Reporting (Phase G, section 7): a crash a real player
# of the shipped game reported, ingested via core.player_crash_reports and
# surfaced in the Known Issues panel with a visible "from players" tag.
SOURCE_PLAYER = "player"


@dataclass(frozen=True)
class KnownIssue:
    id: int
    project_id: int
    signature: str
    source: str
    title: str
    category: str | None
    status: str
    occurrences: int
    first_seen_at: str
    last_seen_at: str
    resolved_at: str | None
    created_at: str


class KnownIssueRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def find(self, project_id: int, signature: str) -> KnownIssue | None:
        row = self._db.query_one(
            "SELECT * FROM known_issues WHERE project_id = ? AND signature = ?",
            (project_id, signature),
        )
        return self._to_issue(row) if row is not None else None

    def upsert(
        self,
        project_id: int,
        signature: str,
        source: str,
        title: str,
        category: str | None = None,
    ) -> KnownIssue:
        existing = self.find(project_id, signature)
        if existing is None:
            self._db.execute(
                "INSERT INTO known_issues (project_id, signature, source, title, category) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, signature, source, title, category),
            )
        else:
            self._db.execute(
                "UPDATE known_issues SET occurrences = occurrences + 1, "
                "last_seen_at = datetime('now'), title = ? WHERE id = ?",
                (title, existing.id),
            )
        return self.find(project_id, signature)  # type: ignore[return-value]

    def mark_resolved(self, issue_id: int) -> KnownIssue:
        self._db.execute(
            "UPDATE known_issues SET status = ?, resolved_at = datetime('now') WHERE id = ?",
            (STATUS_RESOLVED, issue_id),
        )
        return self.get(issue_id)

    def mark_open(self, issue_id: int) -> KnownIssue:
        self._db.execute(
            "UPDATE known_issues SET status = ?, resolved_at = NULL WHERE id = ?",
            (STATUS_OPEN, issue_id),
        )
        return self.get(issue_id)

    def get(self, issue_id: int) -> KnownIssue:
        row = self._db.query_one("SELECT * FROM known_issues WHERE id = ?", (issue_id,))
        if row is None:
            raise KeyError(f"No known issue with id {issue_id}")
        return self._to_issue(row)

    def list_for_project(self, project_id: int) -> list[KnownIssue]:
        rows = self._db.query_all(
            "SELECT * FROM known_issues WHERE project_id = ? "
            "ORDER BY last_seen_at DESC, id DESC",
            (project_id,),
        )
        return [self._to_issue(r) for r in rows]

    @staticmethod
    def _to_issue(row) -> KnownIssue:
        return KnownIssue(
            id=row["id"],
            project_id=row["project_id"],
            signature=row["signature"],
            source=row["source"],
            title=row["title"],
            category=row["category"],
            status=row["status"],
            occurrences=row["occurrences"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            resolved_at=row["resolved_at"],
            created_at=row["created_at"],
        )
