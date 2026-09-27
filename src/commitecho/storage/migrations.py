"""SQLite schema migrations for CommitEcho.

Migrations are plain SQL blocks keyed by (target, version).  apply_migrations()
brings a connection up to the current DB_VERSION idempotently.
"""

from __future__ import annotations

import sqlite3

from commitecho.storage.db import DB_VERSION

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

_DRAFTS_V1 = """
-- Track schema version
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Repositories seen by this installation
CREATE TABLE IF NOT EXISTS repositories (
    installation_id     TEXT PRIMARY KEY,
    common_dir          TEXT NOT NULL UNIQUE,
    portable_project_id TEXT,
    created_at          TEXT NOT NULL
);

-- Sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    repository_id     TEXT NOT NULL REFERENCES repositories(installation_id),
    client            TEXT NOT NULL,
    client_version    TEXT,
    native_session_id TEXT,
    worktree_id       TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

-- Changes
CREATE TABLE IF NOT EXISTS changes (
    change_id          TEXT PRIMARY KEY,
    repository_id      TEXT NOT NULL REFERENCES repositories(installation_id),
    title              TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open',
    worktree_id        TEXT NOT NULL,
    starting_revision  TEXT,
    revision_counter   INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_sessions (
    change_id  TEXT NOT NULL REFERENCES changes(change_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    PRIMARY KEY (change_id, session_id)
);

-- Evidence items
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id         TEXT PRIMARY KEY,
    change_id           TEXT NOT NULL REFERENCES changes(change_id),
    kind                TEXT NOT NULL,
    origin              TEXT NOT NULL,
    content             TEXT,
    locator             TEXT,
    client              TEXT,
    observed_at         TEXT NOT NULL,
    verification_method TEXT
);

-- Decision revisions (immutable once written)
CREATE TABLE IF NOT EXISTS decision_revisions (
    revision_id     TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL,
    change_id       TEXT NOT NULL REFERENCES changes(change_id),
    disposition     TEXT NOT NULL,
    problem         TEXT NOT NULL,
    choice          TEXT NOT NULL,
    rationale       TEXT NOT NULL,
    alternatives    TEXT NOT NULL DEFAULT '[]',  -- JSON array
    code_scope      TEXT NOT NULL DEFAULT '{}',  -- JSON object
    evidence_ids    TEXT NOT NULL DEFAULT '[]',  -- JSON array
    captured_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revision_predecessors (
    revision_id      TEXT NOT NULL REFERENCES decision_revisions(revision_id),
    predecessor_id   TEXT NOT NULL,
    PRIMARY KEY (revision_id, predecessor_id)
);

-- Commit record preparations (draft state)
CREATE TABLE IF NOT EXISTS commit_records (
    record_id              TEXT PRIMARY KEY,
    change_id              TEXT NOT NULL REFERENCES changes(change_id),
    summary                TEXT NOT NULL,
    parent_oid             TEXT NOT NULL,
    object_format          TEXT NOT NULL DEFAULT 'sha1',
    manifest_version       INTEGER NOT NULL DEFAULT 1,
    code_manifest_sha256   TEXT NOT NULL,
    selected_revision_ids  TEXT NOT NULL DEFAULT '[]',  -- JSON array
    evidence_ids           TEXT NOT NULL DEFAULT '[]',  -- JSON array
    schema_version         INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL
);

-- Idempotency keys for mutations
CREATE TABLE IF NOT EXISTS operation_log (
    operation_id  TEXT PRIMARY KEY,
    tool          TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    payload_hash  TEXT NOT NULL,  -- SHA-256 of canonical request payload
    created_at    TEXT NOT NULL
);
"""

_INDEX_V1 = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Index of committed records read from Git objects
CREATE TABLE IF NOT EXISTS indexed_commits (
    commit_oid    TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    parent_oid    TEXT,
    author_date   TEXT,
    committer_date TEXT,
    indexed_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_records (
    record_id     TEXT PRIMARY KEY,
    commit_oid    TEXT NOT NULL REFERENCES indexed_commits(commit_oid),
    record_path   TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    change_id     TEXT NOT NULL,
    summary       TEXT NOT NULL,
    raw_json      TEXT NOT NULL,
    indexed_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_decisions (
    revision_id   TEXT PRIMARY KEY,
    record_id     TEXT NOT NULL REFERENCES indexed_records(record_id),
    decision_id   TEXT NOT NULL,
    disposition   TEXT NOT NULL,
    problem       TEXT NOT NULL,
    choice        TEXT NOT NULL,
    rationale     TEXT NOT NULL,
    captured_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_paths (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id TEXT NOT NULL REFERENCES indexed_decisions(revision_id),
    path        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_indexed_paths_path ON indexed_paths(path);

CREATE TABLE IF NOT EXISTS bindings (
    binding_id         TEXT PRIMARY KEY,
    record_id          TEXT NOT NULL,
    commit_oid         TEXT NOT NULL,
    outcome            TEXT NOT NULL,
    validation_details TEXT NOT NULL DEFAULT '{}',
    evaluated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bindings_commit ON bindings(commit_oid);
CREATE INDEX IF NOT EXISTS idx_bindings_record ON bindings(record_id);

-- FTS5 full-text search over decision content (standalone; synced manually by _index_record)
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    revision_id UNINDEXED,
    problem,
    choice,
    rationale
);
"""

# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

_SCHEMAS: dict[tuple[str, int], str] = {
    ("drafts", 1): _DRAFTS_V1,
    ("index", 1): _INDEX_V1,
}


def apply_migrations(conn: sqlite3.Connection, target: str) -> None:
    """Bring *conn* up to DB_VERSION for the given target ('drafts' or 'index')."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()

    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'version'"
    ).fetchone()
    current = int(row["value"]) if row else 0

    for version in range(current + 1, DB_VERSION + 1):
        key = (target, version)
        sql = _SCHEMAS.get(key)
        if sql is None:
            raise RuntimeError(f"No migration found for {key}")
        with conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(version),),
            )
