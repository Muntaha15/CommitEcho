"""SQLite connection helpers for CommitEcho.

Two databases are maintained under <git-common-dir>/commitecho/:

  drafts.sqlite  – authoritative private draft state; not reconstructable from Git
  index.sqlite   – disposable projection of committed records; rebuilt by `commitecho index`

Both use WAL mode where the filesystem supports it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Bump this when the schema changes; migrations are keyed on this value.
DB_VERSION = 3

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
    return conn


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
