"""Prepare service – prepare_commit application logic."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from commitecho.domain.models import (
    ChangeStatus,
    CommitRecord,
    DecisionRevision,
    Evidence,
    EvidenceKind,
    EvidenceOrigin,
    PreparedFor,
)
from commitecho.git.adapter import GitAdapter, StagedEntry, _COMMITECHO_RECORD_PREFIX
from commitecho.storage.repository import (
    check_operation,
    get_change,
    insert_commit_record,
    record_operation,
    update_change_status,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


_ROOT_OID = "0" * 40


class IndexChangedError(Exception):
    """Raised when the staged index moves between snapshot and write."""


class PrepareService:
    """Orchestrates prepare_commit."""

    def __init__(self, conn: sqlite3.Connection, git: GitAdapter) -> None:
        self._conn = conn
        self._git = git

    def prepare_commit(
        self,
        *,
        change_id: str,
        expected_revision: int,
        selected_revision_ids: list[str],
        summary: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """Prepare a CommitRecord for the currently staged changes.

        Writes the record JSON to .commitecho/records/<uuid>.json in the worktree.
        Returns the record path, suggested trailer, staged-scope preview,
        and uncovered paths.

        Does NOT stage or commit anything.

        Raises IndexChangedError if HEAD or the staged index moves between the
        initial snapshot and the moment the record is written.
        """
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            response, record = self._prepare_commit(
                change_id, expected_revision, selected_revision_ids, summary, operation_id
            )
        # A committed preparation can survive a crash before this write. A replay
        # restores the same bytes from commit_records.record_json.
        self._write_record_file(record)
        return response

    def _prepare_commit(self, change_id, expected_revision, selected_revision_ids,
                        summary, operation_id):
        payload = {
            "change_id": change_id,
            "expected_revision": expected_revision,
            "selected_revision_ids": selected_revision_ids,
            "summary": summary,
        }
        replay = check_operation(self._conn, operation_id, "prepare_commit", payload)
        if replay is not None:
            row = self._conn.execute(
                "SELECT record_json FROM commit_records WHERE record_id = ?",
                (replay["record_id"],),
            ).fetchone()
            if row is None or row["record_json"] is None:
                raise RuntimeError("Prepared record missing for completed operation.")
            return replay, row["record_json"]

        change = get_change(self._conn, change_id)
        if change is None:
            raise ValueError(f"Change '{change_id}' not found.")
        if change.revision_counter != expected_revision:
            raise ValueError(
                f"Optimistic conflict: expected revision {expected_revision}, "
                f"actual {change.revision_counter}."
            )

        # Fetch the selected decision revisions
        revisions: list[DecisionRevision] = []
        for rev_id in selected_revision_ids:
            row = self._conn.execute(
                "SELECT * FROM decision_revisions WHERE revision_id = ?", (rev_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Decision revision '{rev_id}' not found.")
            revisions.append(_row_to_revision(self._conn, row))

        # Fetch evidence referenced by any selected revision
        all_ev_ids: set[str] = set()
        for rev in revisions:
            all_ev_ids.update(rev.evidence_ids)
            for alternative in rev.alternatives:
                all_ev_ids.update(alternative.evidence_ids)
        evidence_items: list[Evidence] = []
        for ev_id in all_ev_ids:
            row = self._conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ? AND change_id = ?", (ev_id, change_id)
            ).fetchone()
            if row is None:
                raise ValueError(f"Evidence '{ev_id}' does not belong to change '{change_id}'.")
            evidence_items.append(_row_to_evidence(row))

        # --- Snapshot 1: freeze HEAD and index digest -------------------------
        head_oid_before = self._git.head_oid() or _ROOT_OID
        staged_before = self._git.staged_changes()
        digest_before, _ = self._git.code_fingerprint()
        # ----------------------------------------------------------------------

        staged_paths = {e.path for e in staged_before if not e.path.startswith(_COMMITECHO_RECORD_PREFIX)}
        covered_paths: set[str] = set()
        for rev in revisions:
            covered_paths.update(rev.code_scope.paths)
        uncovered = sorted(staged_paths - covered_paths)

        record = CommitRecord(
            change_id=change_id,
            summary=summary,
            prepared_for=PreparedFor(
                parent_oid=head_oid_before,
                object_format=self._git.repo_info.object_format,
                manifest_version=1,
                code_manifest_sha256=digest_before,
            ),
            decisions=revisions,
            evidence=evidence_items,
        )

        # --- Snapshot 2: re-check before writing ------------------------------
        head_oid_after = self._git.head_oid() or _ROOT_OID
        digest_after, _ = self._git.code_fingerprint()
        if head_oid_after != head_oid_before or digest_after != digest_before:
            raise IndexChangedError(
                "The staged index or HEAD changed between prepare snapshots. "
                "Stage your changes again and retry with a new operation_id."
            )
        # ----------------------------------------------------------------------
        insert_commit_record(self._conn, record)
        update_change_status(self._conn, change_id, ChangeStatus.PREPARED)

        response = {
            "record_id": record.record_id,
            "record_path": record.record_path(),
            "trailer": record.trailer(),
            "staged_paths": sorted(staged_paths),
            "uncovered_paths": uncovered,
            "code_manifest_sha256": digest_before,
        }
        record_operation(self._conn, operation_id, "prepare_commit", payload, response)
        return response, record

    def _write_record_file(self, record: CommitRecord | str) -> None:
        """Write the record JSON to the worktree, atomically."""
        import os, tempfile

        record_json = record if isinstance(record, str) else record.model_dump_json(indent=2)
        record_path = (CommitRecord.model_validate_json(record_json) if isinstance(record, str)
                       else record).record_path()
        worktree = self._git.repo_info.worktree_dir
        dest = Path(worktree) / record_path

        if dest.exists():
            existing = dest.read_bytes()
            new_bytes = record_json.encode("utf-8")
            if existing != new_bytes:
                raise RuntimeError(
                    f"Record file already exists at {dest} with different content. "
                    "UUID collision or concurrent write."
                )
            return  # idempotent

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Validate destination is within the worktree (no symlink escape)
        real_dest = dest.resolve()
        real_wt = Path(worktree).resolve()
        if not str(real_dest).startswith(str(real_wt)):
            raise ValueError(f"Record path escapes worktree: {real_dest}")

        # Reject symlinks in the path
        for part in dest.parents:
            if part.is_symlink():
                raise ValueError(f"Symlink detected in record path: {part}")

        # Atomic write via temp file + rename
        fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".commitecho_tmp_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(record_json.encode("utf-8"))
            Path(tmp_path).rename(dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _row_to_revision(conn: sqlite3.Connection, row: Any) -> DecisionRevision:
    from commitecho.domain.models import (
        Alternative,
        CodeScope,
        DecisionDisposition,
    )
    import json as _json

    alts_raw = _json.loads(row["alternatives"])
    scope_raw = _json.loads(row["code_scope"])
    ev_ids = _json.loads(row["evidence_ids"])
    predecessor_ids = [r["predecessor_id"] for r in conn.execute(
        "SELECT predecessor_id FROM revision_predecessors WHERE revision_id = ? ORDER BY predecessor_id",
        (row["revision_id"],),
    )]

    return DecisionRevision(
        decision_id=row["decision_id"],
        revision_id=row["revision_id"],
        predecessor_revision_ids=predecessor_ids,
        disposition=DecisionDisposition(row["disposition"]),
        problem=row["problem"],
        choice=row["choice"],
        rationale=row["rationale"],
        alternatives=[
            Alternative(
                choice=a["choice"],
                disposition=DecisionDisposition(a["disposition"]),
                reason=a.get("reason"),
                evidence_ids=a.get("evidence_ids", []),
            )
            for a in alts_raw
        ],
        code_scope=CodeScope(**scope_raw),
        evidence_ids=ev_ids,
        captured_at=datetime.fromisoformat(row["captured_at"]),
    )


def _row_to_evidence(row: Any) -> Evidence:
    return Evidence(
        evidence_id=row["evidence_id"],
        kind=EvidenceKind(row["kind"]),
        origin=EvidenceOrigin(row["origin"]),
        content=row["content"],
        locator=row["locator"],
        client=row["client"],
        observed_at=datetime.fromisoformat(row["observed_at"]),
        verification_method=row["verification_method"],
    )
