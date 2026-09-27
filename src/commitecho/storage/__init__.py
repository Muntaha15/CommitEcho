"""Storage layer for CommitEcho – SQLite-backed drafts and history index."""

from commitecho.storage.db import DB_VERSION, open_drafts_db, open_index_db
from commitecho.storage.migrations import apply_migrations

__all__ = ["DB_VERSION", "open_drafts_db", "open_index_db", "apply_migrations"]
