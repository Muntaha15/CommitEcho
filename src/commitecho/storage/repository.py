"""Storage repository — typed helpers for reading/writing draft state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from commitecho.domain.models import (
    Binding,
    BindingOutcome,
    Change,
    ChangeStatus,
    CommitRecord,
    DecisionRevision,
    Evidence,
    PreparedFor,
    Repository,
    Session,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Repository registration
# ---------------------------------------------------------------------------


def upsert_repository(conn: sqlite3.Connection, repo: Repository) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO repositories (installation_id, common_dir, portable_project_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (repo.installation_id, repo.common_dir, repo.portable_project_id, _now()),
    )


def get_repository_by_common_dir(conn: sqlite3.Connection, common_dir: str) -> Repository | None:
    row = conn.execute(
        "SELECT * FROM repositories WHERE common_dir = ?", (common_dir,)
    ).fetchone()
    if row is None:
        return None
    return Repository(
        installation_id=row["installation_id"],
        common_dir=row["common_dir"],
        portable_project_id=row["portable_project_id"],
    )


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def insert_session(conn: sqlite3.Connection, session: Session, repository_id: str) -> None:
    conn.execute(
        """
        INSERT INTO sessions
            (session_id, repository_id, client, client_version, native_session_id, worktree_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.session_id,
            repository_id,
            session.client,
            session.client_version,
            session.native_session_id,
            session.worktree_id,
            session.created_at.isoformat(),
        ),
    )


# ---------------------------------------------------------------------------
# Change
# ---------------------------------------------------------------------------


def insert_change(conn: sqlite3.Connection, change: Change, repository_id: str) -> None:
    conn.execute(
        """
        INSERT INTO changes
            (change_id, repository_id, title, status, worktree_id,
             starting_revision, revision_counter, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            change.change_id,
            repository_id,
            change.title,
            change.status.value,
            change.worktree_id,
            change.starting_revision,
            change.revision_counter,
            change.created_at.isoformat(),
            change.updated_at.isoformat(),
        ),
    )


def update_change_status(
    conn: sqlite3.Connection, change_id: str, status: ChangeStatus
) -> None:
    conn.execute(
        "UPDATE changes SET status = ?, updated_at = ? WHERE change_id = ?",
        (status.value, _now(), change_id),
    )


def update_change_revision_counter(conn: sqlite3.Connection, change_id: str, expected: int) -> bool:
    return conn.execute(
        "UPDATE changes SET revision_counter = revision_counter + 1, updated_at = ? "
        "WHERE change_id = ? AND revision_counter = ?",
        (_now(), change_id, expected),
    ).rowcount == 1


def get_change(conn: sqlite3.Connection, change_id: str) -> Change | None:
    row = conn.execute(
        "SELECT * FROM changes WHERE change_id = ?", (change_id,)
    ).fetchone()
    if row is None:
        return None
    sessions = [
        r["session_id"]
        for r in conn.execute(
            "SELECT session_id FROM change_sessions WHERE change_id = ?", (change_id,)
        ).fetchall()
    ]
    return Change(
        change_id=row["change_id"],
        title=row["title"],
        status=ChangeStatus(row["status"]),
        worktree_id=row["worktree_id"],
        starting_revision=row["starting_revision"],
        contributing_session_ids=sessions,
        revision_counter=row["revision_counter"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def link_session_to_change(conn: sqlite3.Connection, change_id: str, session_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO change_sessions (change_id, session_id) VALUES (?, ?)",
        (change_id, session_id),
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def insert_evidence(
    conn: sqlite3.Connection, evidence: Evidence, change_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO evidence
            (evidence_id, change_id, kind, origin, content, locator,
             client, observed_at, verification_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence.evidence_id,
            change_id,
            evidence.kind.value,
            evidence.origin.value,
            evidence.content,
            evidence.locator,
            evidence.client,
            evidence.observed_at.isoformat(),
            evidence.verification_method,
        ),
    )


# ---------------------------------------------------------------------------
# Decision revisions
# ---------------------------------------------------------------------------


def insert_decision_revision(
    conn: sqlite3.Connection, revision: DecisionRevision, change_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO decision_revisions
            (revision_id, decision_id, change_id, disposition, problem, choice,
             rationale, alternatives, code_scope, evidence_ids, captured_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision.revision_id,
            revision.decision_id,
            change_id,
            revision.disposition.value,
            revision.problem,
            revision.choice,
            revision.rationale,
            json.dumps([a.model_dump() for a in revision.alternatives]),
            json.dumps(revision.code_scope.model_dump()),
            json.dumps(revision.evidence_ids),
            revision.captured_at.isoformat(),
        ),
    )
    for pred_id in revision.predecessor_revision_ids:
        conn.execute(
            "INSERT OR IGNORE INTO revision_predecessors (revision_id, predecessor_id) VALUES (?, ?)",
            (revision.revision_id, pred_id),
        )


def get_decision_state(conn, git, change_id: str, index_conn=None) -> dict[str, Any]:
    """Recover current draft decisions and those not yet verified in this history."""
    revisions = []
    for row in conn.execute(
        """SELECT d.* FROM decision_revisions d WHERE d.change_id = ?
           AND NOT EXISTS (
               SELECT 1 FROM revision_predecessors p
               JOIN decision_revisions successor ON successor.revision_id = p.revision_id
               WHERE p.predecessor_id = d.revision_id AND successor.change_id = d.change_id
           ) ORDER BY d.rowid""", (change_id,),
    ):
        item = dict(row)
        item.pop("change_id")
        for field in ("alternatives", "code_scope", "evidence_ids"):
            item[field] = json.loads(item[field])
        item["predecessor_revision_ids"] = [r[0] for r in conn.execute(
            "SELECT predecessor_id FROM revision_predecessors WHERE revision_id = ? ORDER BY predecessor_id",
            (row["revision_id"],),
        )]
        revisions.append(item)

    published = set()
    records = conn.execute(
        "SELECT record_id, selected_revision_ids FROM commit_records WHERE change_id = ?",
        (change_id,),
    ).fetchall()
    if records:
        from commitecho.storage.db import open_index_db

        owned_index = index_conn is None
        index_conn = index_conn if index_conn is not None else open_index_db(git.repo_info.common_dir)
        try:
            head = git.head_oid()
            reachable, coverage = git.reachable_commit_oids(head) if head else ([], "full")
            reachable = set(reachable) if coverage == "full" else set()
            for record in records:
                for binding in index_conn.execute(
                    "SELECT commit_oid, validation_details FROM bindings WHERE record_id = ? AND outcome = 'exact'",
                    (record["record_id"],),
                ):
                    if not json.loads(binding["validation_details"]).get("local_preparation_verified"):
                        continue
                    if binding["commit_oid"] in reachable:
                        published.update(json.loads(record["selected_revision_ids"]))
                        break
        finally:
            if owned_index:
                index_conn.close()
    return {
        "decision_revisions": revisions,
        "unpublished_revision_ids": [r["revision_id"] for r in revisions if r["revision_id"] not in published],
    }


# ---------------------------------------------------------------------------
# Commit records
# ---------------------------------------------------------------------------


def insert_commit_record(conn: sqlite3.Connection, record: CommitRecord) -> None:
    conn.execute(
        """
        INSERT INTO commit_records
            (record_id, change_id, summary, parent_oid, object_format, manifest_version,
             code_manifest_sha256, selected_revision_ids, evidence_ids, schema_version, created_at,
             record_sha256, record_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.record_id,
            record.change_id,
            record.summary,
            record.prepared_for.parent_oid,
            record.prepared_for.object_format,
            record.prepared_for.manifest_version,
            record.prepared_for.code_manifest_sha256,
            json.dumps([d.revision_id for d in record.decisions]),
            json.dumps([e.evidence_id for e in record.evidence]),
            record.schema_version,
            record.created_at.isoformat(),
            hashlib.sha256(record.model_dump_json(indent=2).encode("utf-8")).hexdigest(),
            record.model_dump_json(indent=2),
        ),
    )


def get_commit_record(conn: sqlite3.Connection, record_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM commit_records WHERE record_id = ?", (record_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Idempotency / operation log
# ---------------------------------------------------------------------------


def check_operation(
    conn: sqlite3.Connection, operation_id: str, tool: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the original response for a matching completed operation.

    Raises ValueError if the same operation_id was used with a different payload.
    """
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()

    row = conn.execute(
        "SELECT tool, payload_hash, response_json FROM operation_log WHERE operation_id = ?", (operation_id,)
    ).fetchone()

    if row is None:
        return None

    if row["tool"] != tool or row["payload_hash"] != payload_hash:
        raise ValueError(
            f"Operation ID '{operation_id}' was already used with a different payload. "
            "Use a new operation ID for a different request."
        )
    return json.loads(row["response_json"])


def record_operation(
    conn: sqlite3.Connection, operation_id: str, tool: str,
    payload: dict[str, Any], response: dict[str, Any],
) -> None:
    """Store a successful mutation and its response in the caller's transaction."""
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    conn.execute(
        "INSERT INTO operation_log "
        "(operation_id, tool, repository_id, payload_hash, response_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (operation_id, tool, payload.get("repository_id", ""), payload_hash,
         json.dumps(response), _now()),
    )
