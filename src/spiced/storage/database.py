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

-- Dependency & Plugin Update Checks (Phase E, section 6). A saved pass
-- comparing Packages/manifest.json against the public Unity Package
-- Registry (read-only network lookups by package name only), plus an
-- optional AI summary.
CREATE TABLE IF NOT EXISTS dependency_check_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    ai_summary    TEXT,
    provider      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Auto-Generated Unit Tests (Phase E). One row per AI-drafted NUnit test
-- file. ``approved``/``written_path`` stay NULL/0 until the developer clicks
-- "Approve" on that specific draft — Spiced never writes to disk before then.
CREATE TABLE IF NOT EXISTS generated_test_drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    system_label    TEXT,
    source_excerpt  TEXT,
    draft_text      TEXT,
    provider        TEXT,
    approved        INTEGER NOT NULL DEFAULT 0,
    written_path    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Pre-Commit Review (Phase E). An optional log of past local pre-commit
-- checks (never required for the hook itself to work — the hook always
-- exits 0 whether or not Spiced's GUI/DB is even reachable).
CREATE TABLE IF NOT EXISTS precommit_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    file_count    INTEGER NOT NULL DEFAULT 0,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Economy/Balance Simulation (Phase E). A saved deterministic Monte-Carlo-
-- style simulation over developer-supplied economy data (see
-- core.economy_simulator for the documented input schema), plus an optional
-- AI plain-language summary.
CREATE TABLE IF NOT EXISTS economy_simulation_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    input_json    TEXT,
    findings_json TEXT,
    ai_summary    TEXT,
    provider      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Save/Load Integrity Testing (Phase E). One row per run across a folder of
-- save files: launches the project's own built executable (not the Unity
-- Editor) with SPICED_LOAD_TEST_SAVE_PATH / SPICED_LOAD_TEST_RESULT_PATH env
-- vars per save; only works for games implementing that hook (see
-- core.save_load_tester / docs/save_load_integrity_hook.md).
CREATE TABLE IF NOT EXISTS save_integrity_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    executable_path TEXT,
    saves_folder    TEXT,
    results_json    TEXT,
    passed_count    INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Auto-Generated Dev Docs (Phase F, section 6). One row per "Regenerate
-- docs" click (never a background file-watcher, per spec) — a versioned
-- history the Scope-Creep Flagging feature diffs against, not just a
-- single "latest" cache. source_summary_json is the raw local .cs scan
-- (connectors.unity_docs_scan); ai_summary is the AI's plain-language pass
-- over it.
CREATE TABLE IF NOT EXISTS dev_docs_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL,
    source_summary_json TEXT,
    ai_summary          TEXT,
    provider            TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Design Doc Sync (Phase F, section 6, Stretch). The developer's own game
-- design doc (never the Spiced product spec), pasted or imported per
-- project. Opt-in per project — see projects.design_doc_sync_enabled.
CREATE TABLE IF NOT EXISTS design_doc_uploads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    filename    TEXT,
    text        TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Design Doc Sync's saved AI comparisons: the uploaded design doc text
-- against a Dev Docs snapshot, flagging drift either direction, framed as
-- "reconcile the doc or rein in scope" — never a verdict.
CREATE TABLE IF NOT EXISTS design_doc_sync_reports (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            INTEGER NOT NULL,
    design_doc_upload_id  INTEGER NOT NULL,
    dev_docs_snapshot_id  INTEGER NOT NULL,
    ai_summary            TEXT,
    provider              TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Store Page Optimization Advisor (Phase G, section 7). One row per reviewed
-- Steam/itch store page draft (title/description/tags the developer pasted
-- or imported) plus the AI's suggestions-only review. Never a guarantee of
-- sales, never published anywhere by Spiced.
CREATE TABLE IF NOT EXISTS store_page_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL,
    title        TEXT,
    description  TEXT,
    tags_json    TEXT,
    ai_summary   TEXT,
    provider     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Wishlist/Analytics Summary (Phase G, section 7). Scoped down to a
-- documented paste/import CSV format (see core.wishlist_analytics) rather
-- than a live Steam/itch API — no public, OAuth-free wishlist/analytics API
-- exists for either store. Each row is one snapshot; the developer's next
-- import is diffed against the most recent previous one for the same
-- project, purely locally (no AI call needed for a numeric diff).
CREATE TABLE IF NOT EXISTS wishlist_analytics_imports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL,
    metrics_json     TEXT NOT NULL,
    raw_excerpt      TEXT,
    source_filename  TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Trailer & Screenshot Checklist (Phase G, section 7, Stretch tier). Scoped
-- down to screenshots only (no video trailer analysis — see
-- core.trailer_screenshot_checklist). findings_json holds Spiced's own
-- deterministic per-image Pillow-based checks (resolution/aspect ratio,
-- blank-shot heuristic); ai_summary is the AI's review of those structured
-- findings plus any developer-supplied captions — raw image bytes are never
-- sent to the AI provider.
CREATE TABLE IF NOT EXISTS screenshot_checklist_reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL,
    findings_json  TEXT,
    ai_summary     TEXT,
    provider       TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Playtester Recruitment Assistant (Phase G, section 7). Scoped down to a
-- local sign-up list the developer tracks by hand (name/contact/status) —
-- Spiced has no real build-distribution infrastructure and never sends
-- anything on the developer's behalf. Separate from the AI-drafted
-- recruitment post itself, which is not persisted (copy-paste scratch text,
-- same philosophy as Changelog Generation's draft-then-copy flow).
CREATE TABLE IF NOT EXISTS playtester_signups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    name        TEXT NOT NULL,
    contact     TEXT,
    status      TEXT NOT NULL DEFAULT 'invited',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Player Crash & Error Reporting (Phase G, section 7). Local idempotency
-- log for ingesting player-submitted crash reports (fetched from the
-- backend, see backend_client + docs/player_crash_reporting.md) into Known
-- Issues via the same signature-matching pipeline as internally found
-- issues (core.regression). Each remote report id is recorded here once so
-- re-syncing never inflates known_issues.occurrences by re-counting a
-- report Spiced already merged in.
CREATE TABLE IF NOT EXISTS player_crash_sync_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL,
    remote_report_id  TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, remote_report_id)
);

-- Contract/License Checklist (Phase H, section 7 part 2, Stretch tier). The
-- developer's own pasted/imported contract or license text is never stored
-- in full here, on purpose -- this is more sensitive than a debug log or
-- player feedback batch (see core.contract_checklist for the excerpt-
-- capping discipline this mirrors from debugging/feedback). Only a short
-- preview excerpt, a hash reference to the full text the developer pasted,
-- and the AI's "things to double check" output are kept. Never legal advice
-- -- see the prompt/UI copy for the repeated caveats.
CREATE TABLE IF NOT EXISTS contract_checklist_reviews (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL,
    source_filename  TEXT,
    excerpt_hash     TEXT,
    excerpt_preview  TEXT,
    ai_summary       TEXT,
    provider         TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Budget/Runway Tracker (Phase H, section 7 part 2, Phase 2 tier). Purely
-- local, offline bookkeeping of the *studio's own* recurring costs -- this
-- is not Spiced's own billing (Spiced has none, anywhere). Project-scoped,
-- consistent with the rest of the app's per-project data model. No AI is
-- required for the runway arithmetic itself (see core.budget_tracker).
CREATE TABLE IF NOT EXISTS budget_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    name        TEXT NOT NULL,
    amount      REAL NOT NULL,
    frequency   TEXT NOT NULL DEFAULT 'monthly',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per project holding the developer's manually-entered "funds
-- currently available" figure used by the runway calculation above. A
-- separate tiny table (rather than a settings key) keeps it project-scoped
-- and queryable the same way as budget_entries.
CREATE TABLE IF NOT EXISTS budget_available_funds (
    project_id  INTEGER PRIMARY KEY,
    amount      REAL NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Competitive Landscape Scan (Phase H, section 7 part 2, Phase 2 tier).
-- AI-assisted only (no live market data integration this session -- see
-- core.competitive_landscape for why): the developer describes their game
-- and the AI suggests comparable existing titles and positioning thoughts
-- from its general knowledge, always labeled approximate/not live data.
CREATE TABLE IF NOT EXISTS competitive_landscape_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL,
    description_excerpt TEXT,
    ai_summary        TEXT,
    provider          TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Localization Readiness Check (Phase H, section 7 part 2, Phase 2 tier). A
-- read-only recursive scan (core.localization_readiness) of a project's .cs
-- scripts for likely-hardcoded user-facing strings, plus a scan of prefab/
-- scene text components that aren't obviously parameterized. Heuristic,
-- deterministic, no AI call -- see the module for the documented heuristic
-- and its known false positive/negative shape.
CREATE TABLE IF NOT EXISTS localization_readiness_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL,
    findings_json     TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Draft Translation Pass (Phase H, section 7 part 2, Stretch tier). The
-- developer pastes/imports a dialogue file and picks a target language;
-- Spiced drafts a machine translation, always labeled a draft for a human
-- translator to refine -- never ship-ready (see core.draft_translation).
CREATE TABLE IF NOT EXISTS draft_translations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL,
    source_filename  TEXT,
    source_format    TEXT,
    target_language  TEXT,
    entry_count      INTEGER NOT NULL DEFAULT 0,
    raw_excerpt      TEXT,
    ai_draft_text    TEXT,
    provider         TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Asset Review Queue (Phase I, section 8, Core tier). One row per saved
-- review run: local, deterministic Pillow + .meta-text findings per asset
-- (core.asset_review_queue). No AI call -- findings_json holds a list, one
-- entry per reviewed asset, same shape as screenshot_checklist_reports.
CREATE TABLE IF NOT EXISTS asset_review_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Audio Implementation Checklist (Phase I, section 8, Core tier). One row
-- per saved scan cross-referencing .cs audio-triggering code against audio
-- assets under Assets/ (core.audio_implementation_checklist). No AI call.
CREATE TABLE IF NOT EXISTS audio_checklist_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Mix/Level QA (Phase I, section 8, Phase 2 tier). One row per saved WAV
-- batch analysis -- peak/RMS/clipping/silence-gap findings plus relative
-- loudness outliers (core.mix_level_qa, pure wave/struct/array, no
-- audioop -- see that module's docstring). No AI call.
CREATE TABLE IF NOT EXISTS mix_qa_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- State Machine Sanity Check (Phase I, section 8, Phase 2 tier). One row
-- per saved static-analysis pass over the project's .controller files --
-- unreachable states and missing transition targets
-- (core.animation_state_machine_check). No AI call. Animation Bug Detection
-- (Core tier, the same section) is deliberately NOT wired to its own table
-- here -- it's a live, un-persisted scan, same as Code Health's Naming
-- Consistency / Dead Reference Detection checks.
CREATE TABLE IF NOT EXISTS animation_state_machine_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Shader Performance Profiling (Phase J, section 8 part 2, Core tier). One
-- row per saved static-heuristic scan of .shader/.shadergraph files under
-- Assets/ (core.shader_performance_profiling). No AI call -- findings_json
-- holds the same shape as the other local, deterministic report tables
-- above (e.g. animation_state_machine_reports).
CREATE TABLE IF NOT EXISTS shader_profiling_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Visual Regression Testing (Phase J, section 8 part 2, Phase 2 tier). One
-- row per saved before/after screenshot-folder diff pass
-- (core.visual_regression) -- local Pillow pixel-difference comparison
-- only, no live engine screenshot capture, no AI call. findings_json holds
-- the per-pair diff summary; the highlighted diff images themselves are
-- saved as files alongside the report (see core.visual_regression for the
-- output folder), not embedded in this row.
CREATE TABLE IF NOT EXISTS visual_regression_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    findings_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Art/Audio/Animation/VFX Automation (SPICED_IMPLEMENTATION_BIBLE.md,
-- Feature 0 foundation). One row per automation run's Finding -- the shared
-- JSON contract every Bible feature (#1-13) returns, regardless of
-- discipline, instead of each feature inventing its own report table.
-- feature_id namespaces rows (e.g. 'audio.loudness_normalize',
-- 'vfx.visual_regression') so this one table serves every current and
-- future automation feature. Unlike the local, deterministic report tables
-- above, Bible features are expected to drive live engine hooks and
-- external tools (ffmpeg, RenderDoc, xatlas, ...), which is why this is a
-- distinct track from the offline paste/import features already listed.
CREATE TABLE IF NOT EXISTS automation_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL UNIQUE,
    feature_id    TEXT NOT NULL,
    project_id    INTEGER NOT NULL,
    status        TEXT NOT NULL,
    summary       TEXT NOT NULL,
    items_json    TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Visual Regression Testing (SPICED_IMPLEMENTATION_BIBLE.md, Feature 2). Each
-- row names one "key scene" to capture each run: a scene file plus a marker
-- GameObject already placed in that scene, which the capture camera snaps to
-- (see docs/visual_regression_capture_hook.md). Findings from comparing runs
-- go in the shared automation_findings table, not here.
CREATE TABLE IF NOT EXISTS visual_regression_key_scenes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    scene_path    TEXT NOT NULL,
    label         TEXT NOT NULL,
    marker_name   TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Visual Regression Testing (SPICED_IMPLEMENTATION_BIBLE.md, Feature 2). One
-- row per capture run -- just enough to find the immediately preceding
-- build's screenshots directory to diff the next run against.
CREATE TABLE IF NOT EXISTS visual_regression_captures (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL,
    screenshots_dir   TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Texture & Palette Drift Detection (SPICED_IMPLEMENTATION_BIBLE.md,
-- Feature 4). Each row is one hex color in a project's established style
-- reference -- either added directly or materialized from a reference
-- folder (see storage.palette_reference_colors). Findings from checking
-- assets against this reference go in the shared automation_findings
-- table, not here.
CREATE TABLE IF NOT EXISTS palette_reference_colors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    hex_color     TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cross-Feature Rules/Trigger Engine (Market-Viability Roadmap, Phase 4).
-- The local-only half of the "queue_changelog_note" action: never sent
-- anywhere, purely scratch space Changelog Generation reads from and
-- clears the next time a draft is generated (see core.changelog_draft's
-- module docstring on why this feature is entirely local, same as its
-- git-log source). consumed_at is NULL until a draft incorporates the
-- note; nothing ever deletes a row outright, so a project's full
-- queue-and-consume history stays inspectable.
CREATE TABLE IF NOT EXISTS pending_changelog_notes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         INTEGER NOT NULL,
    note_text          TEXT NOT NULL,
    source_event_kind  TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    consumed_at        TEXT
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
    # Pre-Commit Review (Phase E): off by default, same opt-in shape as the
    # other per-project toggles. Only when explicitly on does the Projects
    # screen install a .git/hooks/pre-commit script into the project.
    "precommit_review_enabled": "INTEGER NOT NULL DEFAULT 0",
    # Design Doc Sync (Phase F, section 6): off by default, same opt-in shape
    # as the other per-project toggles. Only when explicitly on does the
    # Debugging Buddy page's Design Drift section become active for this
    # project.
    "design_doc_sync_enabled": "INTEGER NOT NULL DEFAULT 0",
    # Batch Processing & Loudness Normalization (SPICED_IMPLEMENTATION_BIBLE.md,
    # Feature 1): per-project EBU R128 integrated-loudness target in LUFS.
    # NULL means "use core.automation.loudness_normalize.DEFAULT_TARGET_LUFS
    # (-23.0)" -- games sometimes target a different level than broadcast.
    "loudness_normalize_target_lufs": "REAL",
    # Asset Technical QA Scan (SPICED_IMPLEMENTATION_BIBLE.md, Feature 3).
    # NULL falls back to automation.asset_technical_qa's documented defaults
    # (DEFAULT_NAMING_PATTERN / DEFAULT_PIVOT_TOLERANCE).
    "asset_naming_pattern": "TEXT",
    "asset_pivot_tolerance": "REAL",
    # Texture & Palette Drift Detection (SPICED_IMPLEMENTATION_BIBLE.md,
    # Feature 4). NULL falls back to
    # automation.palette_drift.DEFAULT_DELTA_E_THRESHOLD.
    "palette_drift_threshold": "REAL",
    # Mix Technical QA (SPICED_IMPLEMENTATION_BIBLE.md, Feature 5). NULL
    # falls back to automation.mix_technical_qa.DEFAULT_SILENCE_MS.
    "mix_qa_silence_ms": "REAL",
    # Shader Variant & Compile Bloat Analysis (SPICED_IMPLEMENTATION_BIBLE.md,
    # Feature 6). NULL falls back to
    # automation.shader_variant_analysis.DEFAULT_VARIANT_THRESHOLD.
    "shader_variant_threshold": "INTEGER",
    # State Machine & Retarget Validation (SPICED_IMPLEMENTATION_BIBLE.md,
    # Feature 7). Comma-separated bone-name alias prefixes to strip before
    # matching (e.g. "mixamorig:"). NULL falls back to
    # automation.state_machine_validation.DEFAULT_ALIAS_PREFIXES.
    "retarget_alias_prefixes": "TEXT",
    # Shader Performance Profiling (SPICED_IMPLEMENTATION_BIBLE.md, Feature
    # 9). NULL falls back to
    # automation.gpu_shader_profiling.tier_budget_ms(DEFAULT_HARDWARE_TIER).
    "gpu_shader_budget_ms": "REAL",
    "gpu_shader_tier": "TEXT",
    # Version Control connector (Market-Viability Roadmap, Phase 1): off by
    # default, same opt-in shape as the other per-project toggles. Only when
    # explicitly on does the Projects screen's "Version Control" section
    # read/write this project's git repository.
    "git_integration_enabled": "INTEGER NOT NULL DEFAULT 0",
}


def default_db_path() -> Path:
    """Return the default per-user database location.

    Uses a hidden application folder in the user's home directory so the
    database survives across runs without polluting the working directory.
    """
    base = Path.home() / ".spiced"
    base.mkdir(parents=True, exist_ok=True)
    return base / "spiced.db"


class DatabaseUnavailableError(RuntimeError):
    """Raised when Spiced's local SQLite database can't be opened or set up.

    Wraps whatever sqlite3 raised -- a locked file from another running
    Spiced instance, a permissions problem, a full disk, a corrupted file --
    with the database path and a plain-language hint, since the raw sqlite3
    message alone isn't actionable for someone who just wants Spiced to open.
    """


class Database:
    """Owns a single SQLite connection and serializes access across threads."""

    def __init__(self, path: str | Path | None = None) -> None:
        # ":memory:" is honored directly; otherwise fall back to the default.
        if path is None:
            path = default_db_path()
        self.path = str(path)
        self._lock = threading.RLock()
        try:
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self._init_schema()
        except sqlite3.Error as exc:
            raise DatabaseUnavailableError(
                f"Couldn't open Spiced's local database at {self.path}: {exc}. This usually "
                "means another Spiced window already has it open, this machine's account "
                "doesn't have permission to write there, or the disk is full."
            ) from exc

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
