"""Verify service – verify_commit application logic."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Any

from commitecho.domain.models import BindingOutcome, ChangeStatus, CommitRecord
from commitecho.git.adapter import GitAdapter, build_code_manifest, fingerprint_manifest
from commitecho.storage.repository import get_decision_state, update_change_status


class VerifyService:
    """Evaluates three independent facts for verify_commit."""

    def __init__(self, conn: sqlite3.Connection, index_conn: sqlite3.Connection, git: GitAdapter) -> None:
        self._conn = conn
        self._index_conn = index_conn
        self._git = git

    def verify_commit(
        self,
        *,
        commit_oid: str,
        record_id: str | None = None,
        keep_open: bool = False,
    ) -> dict[str, Any]:
        """Evaluate the binding between a commit and its CommitEcho record.

        Returns a binding outcome and diagnostic details.
        """
        # Resolve the OID
        try:
            full_oid = self._git.resolve(commit_oid)
        except Exception as exc:
            return _binding_result(
                BindingOutcome.UNVERIFIABLE,
                record_id=record_id,
                commit_oid=commit_oid,
                reasons=[f"Cannot resolve commit OID: {exc}"],
            )

        # Fact 1: Declaration – does the commit carry the trailer?
        try:
            trailers = self._git.read_commit_trailers(full_oid)
        except Exception as exc:
            return _binding_result(
                BindingOutcome.UNVERIFIABLE,
                record_id=record_id,
                commit_oid=full_oid,
                reasons=[f"Cannot read commit trailers: {exc}"],
            )

        declared_ids = trailers.get("CommitEcho-Record", [])
        if not declared_ids:
            # No trailer; check if record file exists in tree anyway
            try:
                contained = record_id and self._git.file_exists_in_commit(
                    full_oid, f".commitecho/records/{record_id}.json"
                )
            except Exception as exc:
                return _binding_result(BindingOutcome.UNVERIFIABLE, record_id=record_id,
                                       commit_oid=full_oid, reasons=[f"Cannot read commit tree: {exc}"])
            if contained:
                return _binding_result(
                    BindingOutcome.CONTAINED_ONLY,
                    record_id=record_id,
                    commit_oid=full_oid,
                    reasons=["Record file present in tree but no CommitEcho-Record trailer found."],
                )
            return _binding_result(
                BindingOutcome.INVALID,
                record_id=record_id,
                commit_oid=full_oid,
                reasons=["No CommitEcho-Record trailer and no record file found in commit."],
            )

        # Use the declared record ID if caller didn't supply one
        effective_record_id = record_id or declared_ids[0]

        if effective_record_id not in declared_ids:
            return _binding_result(
                BindingOutcome.INVALID,
                record_id=effective_record_id,
                commit_oid=full_oid,
                reasons=[
                    f"Supplied record ID '{effective_record_id}' not in trailer. "
                    f"Declared: {declared_ids}"
                ],
            )

        record_path = f".commitecho/records/{effective_record_id}.json"

        try:
            record_bytes = self._git.read_file_from_commit(full_oid, record_path)
        except Exception as exc:
            return _binding_result(BindingOutcome.UNVERIFIABLE, record_id=effective_record_id,
                                   commit_oid=full_oid, reasons=[f"Cannot read committed record: {exc}"])
        if record_bytes is None:
            return _binding_result(
                BindingOutcome.DECLARED_CHANGED,
                record_id=effective_record_id,
                commit_oid=full_oid,
                reasons=[f"Trailer present but record file not found at '{record_path}' in commit tree."],
            )

        try:
            record = CommitRecord.model_validate_json(record_bytes)
        except Exception as exc:
            return _binding_result(BindingOutcome.INVALID, record_id=effective_record_id,
                                   commit_oid=full_oid, reasons=[f"Invalid committed record: {exc}"])
        if (record.schema_version != 1 or record.record_id != effective_record_id
                or record.prepared_for.manifest_version != 1
                or record.prepared_for.object_format != self._git.repo_info.object_format):
            return _binding_result(BindingOutcome.INVALID, record_id=effective_record_id,
                                   commit_oid=full_oid,
                                   reasons=["Committed record identity, version, or object format is invalid."])

        # Fact 2: Integrity – compare the Git blob with the prepared draft when available.
        draft_row = self._conn.execute(
            "SELECT * FROM commit_records WHERE record_id = ?", (effective_record_id,)
        ).fetchone()

        # Fact 3: Code match – compare expected vs actual parent and fingerprint
        try:
            actual_parent = self._git.resolve(f"{full_oid}^")
        except Exception:
            actual_parent = "0" * 40  # root commit

        expected_parent = record.prepared_for.parent_oid
        expected_digest = record.prepared_for.code_manifest_sha256

        reasons: list[str] = []
        local_preparation_verified = False
        if draft_row is not None:
            if draft_row["record_sha256"] is None:
                reasons.append("Local preparation predates record digests; content cannot be authenticated.")
            elif hashlib.sha256(record_bytes).hexdigest() != draft_row["record_sha256"]:
                reasons.append("Committed record differs from the prepared record.")
            else:
                local_preparation_verified = True
            if (draft_row["parent_oid"] != expected_parent
                    or draft_row["code_manifest_sha256"] != expected_digest):
                reasons.append("Committed prepared-for fields differ from the local draft.")
        if actual_parent != expected_parent:
            reasons.append(
                f"Parent mismatch: expected {expected_parent[:12]}, actual {actual_parent[:12]}."
            )

        # Re-derive the fingerprint from the actual committed diff
        actual_digest: str | None = None
        try:
            committed_entries = self._git.staged_entries_for_commit(full_oid)
            actual_manifest = build_code_manifest(
                committed_entries, self._git.repo_info.object_format
            )
            actual_digest = fingerprint_manifest(actual_manifest)
            if actual_digest != expected_digest:
                reasons.append(
                    f"Code manifest mismatch: expected {expected_digest[:12]}, "
                    f"actual {actual_digest[:12]}. "
                    "The commit may include changes not present when the record was prepared."
                )
        except Exception as exc:
            return _binding_result(BindingOutcome.UNVERIFIABLE, record_id=effective_record_id,
                                   commit_oid=full_oid,
                                   reasons=[f"Could not re-derive code manifest: {exc}"])

        if reasons:
            outcome = BindingOutcome.DECLARED_CHANGED
        else:
            outcome = BindingOutcome.EXACT

        result = _binding_result(
            outcome,
            record_id=effective_record_id,
            commit_oid=full_oid,
            reasons=reasons,
            extra={
                "expected_parent": expected_parent,
                "actual_parent": actual_parent,
                "expected_manifest_sha256": expected_digest,
                "actual_manifest_sha256": actual_digest,
                "local_preparation_verified": local_preparation_verified,
            },
        )

        # Persist binding in the index
        self._index_conn.execute(
            """
            INSERT OR REPLACE INTO bindings
                (binding_id, record_id, commit_oid, outcome, validation_details, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"{effective_record_id}:{full_oid}",
                effective_record_id,
                full_oid,
                outcome.value,
                json.dumps(result["details"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._index_conn.commit()

        if outcome == BindingOutcome.EXACT and local_preparation_verified:
            with self._conn:
                self._conn.execute("BEGIN IMMEDIATE")
                pending = self._conn.execute(
                    "SELECT 1 FROM changes WHERE change_id = ? AND status = 'prepared' "
                    "AND worktree_id = ? "
                    "AND ? = (SELECT record_id FROM commit_records WHERE change_id = ? "
                    "ORDER BY rowid DESC LIMIT 1)",
                    (record.change_id, self._git.repo_info.worktree_id, record.record_id, record.change_id),
                ).fetchone()
                if pending:
                    remaining = get_decision_state(
                        self._conn, self._git, record.change_id, self._index_conn
                    )["unpublished_revision_ids"]
                    status = ChangeStatus.OPEN if keep_open or remaining else ChangeStatus.COMMITTED
                    update_change_status(self._conn, record.change_id,
                                         status)
                    result["details"].update(remaining_revision_ids=remaining, change_status=status.value)

        return result


def _binding_result(
    outcome: BindingOutcome,
    *,
    record_id: str | None,
    commit_oid: str,
    reasons: list[str],
    extra: dict | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {"reasons": reasons}
    if extra:
        details.update(extra)
    return {
        "outcome": outcome.value,
        "record_id": record_id,
        "commit_oid": commit_oid,
        "details": details,
    }
