"""Unit tests for SQLite storage layer."""

from __future__ import annotations

import sqlite3
import pytest

from commitecho.storage.db import open_drafts_db, open_index_db
from commitecho.storage.migrations import apply_migrations
from commitecho.storage.repository import (
    check_operation,
    record_operation,
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
        assert "indexed_commit_records" in tables
        assert "indexed_record_decisions" in tables
        assert "bindings" in tables

    def test_idempotent(self, mem_db):
        # Applying migrations twice should not raise
        apply_migrations(mem_db, target="drafts")


def test_index_reuses_record_and_revision_across_commits(index_db):
    import json
    from unittest.mock import Mock

    from commitecho.application.retrieve import RetrieveService
    from commitecho.domain.models import CodeScope, CommitRecord, DecisionRevision, PreparedFor
    from commitecho.transports.cli import _index_record

    commits = ["a" * 40, "b" * 40]
    for oid in commits:
        index_db.execute(
            "INSERT INTO indexed_commits (commit_oid, repository_id, indexed_at) VALUES (?, ?, ?)",
            (oid, "repo", "now"),
        )
    revision = DecisionRevision(problem="shared revision", choice="reuse it", rationale="same reason",
                                code_scope=CodeScope(paths=["src/shared.py"]))
    records = [CommitRecord(change_id="change", summary="shared", decisions=[revision],
                            prepared_for=PreparedFor(parent_oid=commits[0],
                                                     code_manifest_sha256="0" * 64))
               for _ in range(2)]
    for oid, record in ((commits[0], records[0]), (commits[1], records[0]),
                        (commits[1], records[1])):
        raw = record.model_dump_json()
        _index_record(index_db, oid, record.record_id, record.record_path(), json.loads(raw), raw)

    assert index_db.execute("SELECT count(*) FROM indexed_commit_records").fetchone()[0] == 3
    assert index_db.execute("SELECT count(*) FROM indexed_record_decisions").fetchone()[0] == 2
    assert index_db.execute("SELECT count(*) FROM indexed_records").fetchone()[0] == 2
    assert index_db.execute("SELECT count(*) FROM indexed_decisions").fetchone()[0] == 1
    assert index_db.execute("SELECT count(*) FROM indexed_paths").fetchone()[0] == 1

    git = Mock()
    git.head_oid.return_value = commits[1]
    git.reachable_commit_oids.return_value = (commits, "full")
    found = RetrieveService(index_db, index_db, git).search_history(question="shared")
    assert {(r["commit_oid"], r["record_id"]) for r in found["results"]} == {
        (commits[0], records[0].record_id),
        (commits[1], records[0].record_id),
        (commits[1], records[1].record_id),
    }
    assert RetrieveService(index_db, index_db, git).get_evidence(
        record_id=records[0].record_id
    )["commit_oids"] == commits
    retrieve = RetrieveService(index_db, index_db, git)
    first = retrieve.search_history(question="shared", page_size=1)
    second = retrieve.search_history(question="shared", page_size=1, cursor=first["next_cursor"])
    third = retrieve.search_history(question="shared", page_size=1, cursor=second["next_cursor"])
    assert [r["record_id"] for page in (first, second, third) for r in page["results"]] == [
        r["record_id"] for r in found["results"]
    ]
    assert third["next_cursor"] is None
    with pytest.raises(ValueError, match="page_size"):
        retrieve.search_history(question="shared", page_size=101)
    with pytest.raises(ValueError, match="cursor"):
        retrieve.search_history(question="shared", cursor="-1")

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
        payload = {"repository_id": "r1", "title": "t"}
        already = check_operation(mem_db, "op-001", "begin_change", payload)
        assert already is None
        assert mem_db.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0] == 0

    def test_same_operation_same_payload(self, mem_db):
        payload = {"repository_id": "r1", "title": "t"}
        record_operation(mem_db, "op-002", "begin_change", payload, {"change_id": "c1"})
        already = check_operation(mem_db, "op-002", "begin_change", payload)
        assert already == {"change_id": "c1"}

    def test_same_operation_different_payload_raises(self, mem_db):
        record_operation(mem_db, "op-003", "begin_change", {"repository_id": "r1", "title": "a"}, {})
        with pytest.raises(ValueError, match="different payload"):
            check_operation(mem_db, "op-003", "begin_change", {"repository_id": "r1", "title": "b"})
