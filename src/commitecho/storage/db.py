"""SQLite connection helpers for CommitEcho.

Two databases are maintained under <git-common-dir>/commitecho/:

  drafts.sqlite  – authoritative private draft state; not reconstructable from Git
  index.sqlite   – disposable projection of committed records; rebuilt by `commitecho index`

Both use WAL mode where the filesystem supports it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Bump this when the schema changes; migrations are keyed on this value.
DB_VERSION = 5

_BUSY_TIMEOUT_MS = 5_000  # 5 seconds; avoids indefinite blocking


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")


def open_drafts_db(common_dir: str | Path) -> sqlite3.Connection:
    """Open (and initialise if new) the private drafts database."""
    path = _ensure_commitecho_dir(common_dir) / "drafts.sqlite"
    conn = sqlite3.connect(str(path), check_same_thread=False)
    _configure(conn)
    from commitecho.storage.migrations import apply_migrations
    apply_migrations(conn, target="drafts")
    _backfill_verified_bindings(conn, path.parent / "index.sqlite")
    return conn


def _backfill_verified_bindings(conn: sqlite3.Connection, index_path: Path) -> None:
    """Preserve pre-v5 local verification results before their cache is discarded."""
    marker = "verified_bindings_backfilled"
    if conn.execute("SELECT 1 FROM schema_meta WHERE key = ?", (marker,)).fetchone():
        return
    bindings = []
    if index_path.exists():
        legacy = None
        try:
            legacy = sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True)
            bindings = legacy.execute(
                "SELECT record_id, commit_oid, validation_details FROM bindings WHERE outcome = 'exact'"
            ).fetchall()
        except sqlite3.DatabaseError:
            # The disposable index may be absent, corrupt, or from an older schema.
            # Leave the marker unset so a repaired or temporarily locked cache can retry.
            return
        finally:
            if legacy is not None:
                legacy.close()
    with conn:
        for record_id, commit_oid, details in bindings:
            try:
                authenticated = json.loads(details).get("local_preparation_verified") is True
            except (TypeError, ValueError, AttributeError):
                continue
            if authenticated:
                conn.execute(
                    "INSERT OR IGNORE INTO verified_bindings (record_id, commit_oid, keep_open) "
                    "SELECT record_id, ?, NULL FROM commit_records "
                    "WHERE record_id = ? AND record_sha256 IS NOT NULL",
                    (commit_oid, record_id),
                )
        conn.execute("INSERT OR IGNORE INTO schema_meta (key, value) VALUES (?, '1')", (marker,))


def open_index_db(common_dir: str | Path) -> sqlite3.Connection:
    """Open (and initialise if new) the rebuildable history index database."""
    path = _ensure_commitecho_dir(common_dir) / "index.sqlite"
    conn = sqlite3.connect(str(path), check_same_thread=False)
    _configure(conn)
    from commitecho.storage.migrations import apply_migrations
    apply_migrations(conn, target="index")
    return conn


def _ensure_commitecho_dir(common_dir: str | Path) -> Path:
    p = Path(common_dir) / "commitecho"
    p.mkdir(parents=True, exist_ok=True)
    return p
