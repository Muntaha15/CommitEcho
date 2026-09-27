"""Unit tests for SQLite storage layer."""

from __future__ import annotations

import sqlite3
import pytest

from commitecho.storage.db import open_drafts_db, open_index_db
from commitecho.storage.migrations import apply_migrations
from commitecho.storage.repository import (
    check_operation,
    get_change,
    get_repository_by_common_dir,
    insert_change,
    insert_session,
    link_session_to_change,
    upsert_repository,
)
from commitecho.domain.models import Change, Repository, Session


@pytest.fixture
def mem_db():
    """In-memory SQLite connection with drafts schema applied."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn, target="drafts")
    return conn


@pytest.fixture
def index_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn, target="index")
    return conn


class TestMigrations:
    def test_drafts_schema_applied(self, mem_db):
        tables = {
            row[0]
            for row in mem_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "changes" in tables
        assert "decision_revisions" in tables
        assert "commit_records" in tables

    def test_index_schema_applied(self, index_db):
        tables = {
            row[0]
            for row in index_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "indexed_records" in tables
        assert "indexed_decisions" in tables
        assert "bindings" in tables

    def test_idempotent(self, mem_db):
        # Applying migrations twice should not raise
        apply_migrations(mem_db, target="drafts")


class TestRepository:
    def test_upsert_and_get(self, mem_db):
        repo = Repository(common_dir="/tmp/repo/.git")
        upsert_repository(mem_db, repo)
        found = get_repository_by_common_dir(mem_db, "/tmp/repo/.git")
        assert found is not None
        assert found.installation_id == repo.installation_id

    def test_upsert_idempotent(self, mem_db):
        repo = Repository(common_dir="/tmp/repo2/.git")
        upsert_repository(mem_db, repo)
        upsert_repository(mem_db, repo)  # should not raise
        found = get_repository_by_common_dir(mem_db, "/tmp/repo2/.git")
        assert found.installation_id == repo.installation_id

    def test_not_found(self, mem_db):
        assert get_repository_by_common_dir(mem_db, "/nonexistent") is None


class TestChangeStorage:
    def test_insert_and_get(self, mem_db):
        repo = Repository(common_dir="/tmp/r3/.git")
        upsert_repository(mem_db, repo)
        change = Change(title="fix bug", worktree_id="main")
        insert_change(mem_db, change, repo.installation_id)
        found = get_change(mem_db, change.change_id)
        assert found is not None
        assert found.title == "fix bug"

    def test_session_link(self, mem_db):
        repo = Repository(common_dir="/tmp/r4/.git")
        upsert_repository(mem_db, repo)
        change = Change(title="add feature", worktree_id="main")
        insert_change(mem_db, change, repo.installation_id)
        session = Session(client="codex", worktree_id="main")
        insert_session(mem_db, session, repo.installation_id)
        link_session_to_change(mem_db, change.change_id, session.session_id)
        found = get_change(mem_db, change.change_id)
        assert session.session_id in found.contributing_session_ids


class TestOperationIdempotency:
    def test_new_operation(self, mem_db):
        # Need a repository row for operation_log
        payload = {"repository_id": "r1", "title": "t"}
        already = check_operation(mem_db, "op-001", "begin_change", payload)
        assert already is False

    def test_same_operation_same_payload(self, mem_db):
        payload = {"repository_id": "r1", "title": "t"}
        check_operation(mem_db, "op-002", "begin_change", payload)
        already = check_operation(mem_db, "op-002", "begin_change", payload)
        assert already is True

    def test_same_operation_different_payload_raises(self, mem_db):
        check_operation(mem_db, "op-003", "begin_change", {"repository_id": "r1", "title": "a"})
        with pytest.raises(ValueError, match="different payload"):
            check_operation(mem_db, "op-003", "begin_change", {"repository_id": "r1", "title": "b"})
