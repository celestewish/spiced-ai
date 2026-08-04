"""SQLite connection management and schema initialization.

Spiced runs provider/chat work on a background thread, so database access can
come from more than one thread. sqlite3 forbids sharing a connection across
threads unless you opt in *and* serialize access yourself. We do exactly that:
the connection is opened with ``check_same_thread=False`` and every read/write
goes through a re-entrant lock, so calls are serialized and never overlap.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    engine      TEXT NOT NULL DEFAULT 'Unity',
    path        TEXT,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS prompt_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    provider   TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'chat',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS debug_sessions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id                INTEGER NOT NULL,
    source_type               TEXT NOT NULL,
    source_filename           TEXT,
    detected_error_type       TEXT,
    detected_file             TEXT,
    detected_line             INTEGER,
    raw_excerpt               TEXT,
    summary                   TEXT,
    suggested_next_steps_json TEXT,
    provider                  TEXT,
    created_at                TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'General',
    priority        TEXT NOT NULL DEFAULT 'Medium',
    steps           TEXT,
    expected_result TEXT,
    status          TEXT NOT NULL DEFAULT 'Not Run',
    failure_note    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            INTEGER NOT NULL,
    source_type           TEXT NOT NULL,
    source_filename       TEXT,
    raw_excerpt           TEXT,
    parsed_summary_json   TEXT,
    ai_summary            TEXT,
    retest_checklist_json TEXT,
    provider              TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback_batches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_type         TEXT NOT NULL,
    source_label        TEXT,
    source_filename     TEXT,
    entry_count         INTEGER NOT NULL DEFAULT 0,
    raw_excerpt         TEXT,
    parsed_summary_json TEXT,
    ai_summary          TEXT,
    themes_json         TEXT,
    issues_json         TEXT,
    action_items_json   TEXT,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS known_issues (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    signature     TEXT NOT NULL,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    category      TEXT,
    status        TEXT NOT NULL DEFAULT 'open',
    occurrences   INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, signature)
);

CREATE TABLE IF NOT EXISTS performance_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_type         TEXT NOT NULL,
    source_filename     TEXT,
    target_hardware     TEXT,
    raw_excerpt         TEXT,
    parsed_summary_json TEXT,
    ai_summary          TEXT,
    spikes_json         TEXT,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accessibility_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_type         TEXT NOT NULL,
    source_filename     TEXT,
    raw_excerpt         TEXT,
    parsed_summary_json TEXT,
    ai_summary          TEXT,
    findings_json       TEXT,
    score               INTEGER,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS version_check_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_filename     TEXT,
    raw_excerpt         TEXT,
    hits_json           TEXT,
    ai_summary          TEXT,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS code_health_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_filename     TEXT,
    raw_excerpt         TEXT,
    metrics_json        TEXT,
    ai_summary          TEXT,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    batch_id        INTEGER,
    category        TEXT NOT NULL,
    text            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS community_pulse_checkins (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL,
    source             TEXT NOT NULL,
    channel_label      TEXT,
    message_count      INTEGER NOT NULL DEFAULT 0,
    raw_excerpt        TEXT,
    ai_summary         TEXT,
    provider           TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Session Summaries (Phase B, Team & Workflow). A compact recap of what was
-- tested/fixed/still-open since the previous summary (or app start). Always
-- stored locally; additionally posted to the team backend's session-summary
-- endpoint when Team Mode is on and the project is team-linked — but only the
-- ai_summary text and started_at/ended_at ever leave this machine, never raw
-- session timing framed as a wellbeing signal (that stays local-only, for the
-- later Crunch-Pattern Awareness feature).
CREATE TABLE IF NOT EXISTS session_summaries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL,
    started_at     TEXT NOT NULL,
    ended_at       TEXT NOT NULL,
    tested_summary TEXT,
    fixed_summary  TEXT,
    open_summary   TEXT,
    ai_summary     TEXT,
    synced_to_team INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Automated Build Pipeline (Phase D, section 6). One row per headless Unity
-- build Spiced triggered — manually, from the in-app scheduler, or (later,
-- once Phase E's pre-commit hook exists) from a commit. Always read back
-- regardless of the run's exit code, same philosophy as unity_test_runner.
CREATE TABLE IF NOT EXISTS build_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    trigger         TEXT NOT NULL,  -- 'manual' | 'scheduled' | 'commit'
    target_platform TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    succeeded       INTEGER,
    log_tail        TEXT,
    output_path     TEXT,
    marked_stable   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Changelog Generation (Phase D). Spiced's read of the *user's game*'s own
-- git history + locally-resolved known issues, drafted into patch notes the
-- developer reviews/edits before copying out anywhere. Distinct from the
-- Roadmap's changelog (Phase C), which is Spiced's own release notes.
CREATE TABLE IF NOT EXISTS changelog_drafts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_commit_range TEXT,
    raw_git_log_excerpt TEXT,
    ai_draft_text       TEXT,
    edited_text         TEXT,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Asset Optimization Sweep (Phase D). A saved read-only pass over the
-- project's Assets/ folder: oversized/uncompressed files and orphaned-asset
-- suggestions, plus an optional AI summary. Never modifies anything.
CREATE TABLE IF NOT EXISTS asset_scan_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    ai_summary    TEXT,
    provider      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after Phase 0. Applied idempotently so existing databases and
# their project rows keep working; missing values default safely to NULL.
PROJECT_MIGRATIONS = {
    "validation_status": "TEXT",
    "engine_metadata_json": "TEXT",
    "unity_test_run_enabled": "INTEGER NOT NULL DEFAULT 0",
    "unity_editor_path_override": "TEXT",
    # Stable cross-machine identifier, minted lazily the first time a project
    # is linked to a Small-Team Mode team (see core/team_service.py). Null
    # for every project that has never been linked — Solo-Dev Mode never
    # needs one.
    "project_uuid": "TEXT",
    # Automated Build Pipeline (Phase D): off by default, same opt-in shape as
    # unity_test_run_enabled. Only when this is explicitly on does Spiced ever
    # write a build script into the project or launch a headless build.
    "build_pipeline_enabled": "INTEGER NOT NULL DEFAULT 0",
    "build_target_platform": "TEXT",
    # In-app-only nightly scheduler (QTimer while Spiced is running — no OS
    # Task Scheduler entry is ever registered). build_schedule_time is a
    # "HH:MM" 24-hour local-time string.
    "build_schedule_enabled": "INTEGER NOT NULL DEFAULT 0",
    "build_schedule_time": "TEXT",
}


def default_db_path() -> Path:
    """Return the default per-user database location.

    Uses a hidden application folder in the user's home directory so the
    database survives across runs without polluting the working directory.
    """
    base = Path.home() / ".spiced"
    base.mkdir(parents=True, exist_ok=True)
    return base / "spiced.db"


class Database:
    """Owns a single SQLite connection and serializes access across threads."""

    def __init__(self, path: str | Path | None = None) -> None:
        # ":memory:" is honored directly; otherwise fall back to the default.
        if path is None:
            path = default_db_path()
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._migrate_projects()
            self.conn.commit()

    def _migrate_projects(self) -> None:
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(projects)")}
        for column, col_type in PROJECT_MIGRATIONS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {col_type}")

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        """Run a write statement, commit, and return the new row id."""
        with self._lock:
            cur = self.conn.execute(sql, tuple(params or ()))
            self.conn.commit()
            return int(cur.lastrowid)

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params or ())).fetchone()

    def query_all(self, sql: str, params: Sequence[Any] | None = None) -> Iterable[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params or ())).fetchall()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
