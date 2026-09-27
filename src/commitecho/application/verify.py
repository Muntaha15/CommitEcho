"""Verify service – verify_commit application logic."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from commitecho.domain.models import BindingOutcome
from commitecho.git.adapter import GitAdapter, build_code_manifest, fingerprint_manifest


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
            if record_id and self._git.file_exists_in_commit(full_oid, f".commitecho/records/{record_id}.json"):
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

        # Check record file exists in commit tree
        if not self._git.file_exists_in_commit(full_oid, record_path):
            return _binding_result(
                BindingOutcome.DECLARED_CHANGED,
                record_id=effective_record_id,
                commit_oid=full_oid,
                reasons=[f"Trailer present but record file not found at '{record_path}' in commit tree."],
            )

        # Fact 2: Integrity – load draft record from DB and compare
        draft_row = self._conn.execute(
            "SELECT * FROM commit_records WHERE record_id = ?", (effective_record_id,)
        ).fetchone()
        if draft_row is None:
            return _binding_result(
                BindingOutcome.CONTAINED_ONLY,
                record_id=effective_record_id,
                commit_oid=full_oid,
                reasons=["Record file in commit but no draft record found in local DB. "
                         "Run `commitecho index` to rebuild."],
            )

        # Fact 3: Code match – compare expected vs actual parent and fingerprint
        try:
            actual_parent = self._git.resolve(f"{full_oid}^")
        except Exception:
            actual_parent = "0" * 40  # root commit

        expected_parent = draft_row["parent_oid"]
        expected_digest = draft_row["code_manifest_sha256"]

        reasons: list[str] = []
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
            reasons.append(f"Could not re-derive code manifest: {exc}")

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
