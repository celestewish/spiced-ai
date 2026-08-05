"""Playtester Recruitment Assistant's local sign-up list.

Scoped down deliberately to a list the developer tracks by hand (name/
contact/status) — Spiced has no real build-distribution infrastructure and
never sends anything (no emails, no build links) on the developer's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database

STATUS_INVITED = "invited"
STATUS_CONFIRMED = "confirmed"
STATUS_TESTED = "tested"
STATUSES = (STATUS_INVITED, STATUS_CONFIRMED, STATUS_TESTED)


@dataclass(frozen=True)
class PlaytesterSignup:
    id: int
    project_id: int
    name: str
    contact: str | None
    status: str
    created_at: str
    updated_at: str


class PlaytesterSignupRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, project_id: int, name: str, contact: str | None, status: str = STATUS_INVITED
    ) -> PlaytesterSignup:
        new_id = self._db.execute(
            "INSERT INTO playtester_signups (project_id, name, contact, status) "
            "VALUES (?, ?, ?, ?)",
            (project_id, name, contact, status),
        )
        return self.get(new_id)

    def set_status(self, signup_id: int, status: str) -> PlaytesterSignup:
        self._db.execute(
            "UPDATE playtester_signups SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, signup_id),
        )
        return self.get(signup_id)

    def delete(self, signup_id: int) -> None:
        self._db.execute("DELETE FROM playtester_signups WHERE id = ?", (signup_id,))

    def get(self, signup_id: int) -> PlaytesterSignup:
        row = self._db.query_one("SELECT * FROM playtester_signups WHERE id = ?", (signup_id,))
        if row is None:
            raise KeyError(f"No playtester signup with id {signup_id}")
        return self._to_signup(row)

    def list_for_project(self, project_id: int) -> list[PlaytesterSignup]:
        rows = self._db.query_all(
            "SELECT * FROM playtester_signups WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (project_id,),
        )
        return [self._to_signup(r) for r in rows]

    @staticmethod
    def _to_signup(row) -> PlaytesterSignup:
        return PlaytesterSignup(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            contact=row["contact"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
