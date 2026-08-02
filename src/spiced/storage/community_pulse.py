"""Community-pulse check-in persistence.

A compact record of one opt-in check-in: which source and channel were read,
how many messages, a trimmed excerpt, and the AI's high-level summary. Full
message history is never stored.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class CommunityPulseCheckin:
    id: int
    project_id: int
    source: str
    channel_label: str | None
    message_count: int
    raw_excerpt: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str


class CommunityPulseRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source: str,
        channel_label: str | None,
        message_count: int,
        raw_excerpt: str | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> CommunityPulseCheckin:
        new_id = self._db.execute(
            "INSERT INTO community_pulse_checkins ("
            "project_id, source, channel_label, message_count, raw_excerpt, ai_summary, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, source, channel_label, message_count, raw_excerpt, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, checkin_id: int) -> CommunityPulseCheckin:
        row = self._db.query_one(
            "SELECT * FROM community_pulse_checkins WHERE id = ?", (checkin_id,)
        )
        if row is None:
            raise KeyError(f"No community pulse check-in with id {checkin_id}")
        return self._to_checkin(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[CommunityPulseCheckin]:
        rows = self._db.query_all(
            "SELECT * FROM community_pulse_checkins WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_checkin(r) for r in rows]

    @staticmethod
    def _to_checkin(row) -> CommunityPulseCheckin:
        return CommunityPulseCheckin(
            id=row["id"],
            project_id=row["project_id"],
            source=row["source"],
            channel_label=row["channel_label"],
            message_count=row["message_count"],
            raw_excerpt=row["raw_excerpt"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
