"""Capture service – begin_change and record_decisions application logic."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from commitecho.domain.models import (
    Alternative,
    Change,
    ChangeStatus,
    CodeScope,
    DecisionDisposition,
    DecisionRevision,
    Evidence,
    EvidenceKind,
    EvidenceOrigin,
    Repository,
    Session,
)
from commitecho.git.adapter import GitAdapter
from commitecho.storage.repository import (
    get_change,
    get_repository_by_common_dir,
    insert_change,
    insert_decision_revision,
    insert_evidence,
    insert_session,
    link_session_to_change,
    update_change_revision_counter,
    upsert_repository,
    check_operation,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CaptureService:
    """Orchestrates begin_change and record_decisions."""

    def __init__(self, conn: sqlite3.Connection, git: GitAdapter) -> None:
        self._conn = conn
        self._git = git

    # ------------------------------------------------------------------
    # begin_change
    # ------------------------------------------------------------------

    def begin_change(
        self,
        *,
        title: str,
        client: str,
        client_version: str | None = None,
        native_session_id: str | None = None,
        operation_id: str,
        prior_change_id: str | None = None,
    ) -> dict[str, Any]:
        """Open or resume a Change for the current worktree.

        Returns change_id, session_id, base_oid, and current revision_counter.
        """
        repo_info = self._git.repo_info
        payload = {
            "title": title,
            "client": client,
            "operation_id": operation_id,
            "repository_id": repo_info.common_dir,
        }

        # Idempotency check
        already_done = check_operation(self._conn, operation_id, "begin_change", payload)

        # Ensure repository is registered
        repo = get_repository_by_common_dir(self._conn, repo_info.common_dir)
        if repo is None:
            repo = Repository(common_dir=repo_info.common_dir)
            upsert_repository(self._conn, repo)

        # Resume a prior change if requested
        if prior_change_id:
            change = get_change(self._conn, prior_change_id)
            if change is None:
                raise ValueError(f"Prior change '{prior_change_id}' not found.")
            if change.status == ChangeStatus.COMMITTED:
                raise ValueError(
                    f"Change '{prior_change_id}' is already committed and cannot be reopened."
                )
        elif already_done:
            # Find the most recently opened change for this operation replay
            row = self._conn.execute(
                "SELECT change_id FROM changes WHERE title = ? ORDER BY created_at DESC LIMIT 1",
                (title,),
            ).fetchone()
            change = get_change(self._conn, row["change_id"]) if row else None
            if change is None:
                raise RuntimeError("Idempotent replay but change record not found.")
        else:
            change = None

        if change is None:
            head_oid = self._git.head_oid()
            change = Change(
                title=title,
                worktree_id=repo_info.worktree_id,
                starting_revision=head_oid,
            )
            insert_change(self._conn, change, repo.installation_id)

        # Register session
        session = Session(
            client=client,
            client_version=client_version,
            native_session_id=native_session_id,
            worktree_id=repo_info.worktree_id,
        )
        insert_session(self._conn, session, repo.installation_id)
        link_session_to_change(self._conn, change.change_id, session.session_id)

        return {
            "change_id": change.change_id,
            "session_id": session.session_id,
            "base_oid": change.starting_revision,
            "revision_counter": change.revision_counter,
        }

    # ------------------------------------------------------------------
    # record_decisions
    # ------------------------------------------------------------------

    def record_decisions(
        self,
        *,
        change_id: str,
        expected_revision: int,
        operation_id: str,
        decisions: list[dict[str, Any]],
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist one or more decision revisions for *change_id*.

        Implements optimistic concurrency: refuses if revision_counter !=
        expected_revision.
        """
        payload = {
            "change_id": change_id,
            "operation_id": operation_id,
            "expected_revision": expected_revision,
        }
        already_done = check_operation(self._conn, operation_id, "record_decisions", payload)

        change = get_change(self._conn, change_id)
        if change is None:
            raise ValueError(f"Change '{change_id}' not found.")
        if change.revision_counter != expected_revision and not already_done:
            raise ValueError(
                f"Optimistic conflict: expected revision {expected_revision}, "
                f"actual {change.revision_counter}. Reload and retry."
            )

        if already_done:
            # Return stored revision IDs
            rows = self._conn.execute(
                "SELECT revision_id FROM decision_revisions WHERE change_id = ? ORDER BY captured_at",
                (change_id,),
            ).fetchall()
            return {
                "revision_ids": [r["revision_id"] for r in rows],
                "revision_counter": change.revision_counter,
            }

        # Persist evidence items first so IDs are available
        ev_objects: list[Evidence] = []
        for ev_data in (evidence or []):
            ev = Evidence(
                kind=EvidenceKind(ev_data["kind"]),
                origin=EvidenceOrigin(ev_data.get("origin", "agent_reported")),
                content=ev_data.get("content"),
                locator=ev_data.get("locator"),
                client=ev_data.get("client"),
                verification_method=ev_data.get("verification_method"),
            )
            insert_evidence(self._conn, ev, change_id)
            ev_objects.append(ev)

        ev_by_local_id = {ev.evidence_id: ev for ev in ev_objects}

        revision_ids: list[str] = []
        for dec_data in decisions:
            alts = [
                Alternative(
                    choice=a["choice"],
                    disposition=DecisionDisposition(a.get("disposition", "rejected")),
                    reason=a.get("reason"),
                    evidence_ids=a.get("evidence_ids", []),
                )
                for a in dec_data.get("alternatives", [])
            ]
            code_scope_data = dec_data.get("code_scope", {})
            revision = DecisionRevision(
                decision_id=dec_data.get("decision_id") or str(__import__("uuid").uuid4()),
                predecessor_revision_ids=dec_data.get("predecessor_revision_ids", []),
                disposition=DecisionDisposition(dec_data.get("disposition", "proposed")),
                problem=dec_data["problem"],
                choice=dec_data["choice"],
                rationale=dec_data["rationale"],
                alternatives=alts,
                code_scope=CodeScope(
                    paths=code_scope_data.get("paths", []),
                    base_blob_oid=code_scope_data.get("base_blob_oid"),
                    line_ranges=code_scope_data.get("line_ranges"),
                    symbol_label=code_scope_data.get("symbol_label"),
                ),
                evidence_ids=dec_data.get("evidence_ids", []),
            )
            insert_decision_revision(self._conn, revision, change_id)
            revision_ids.append(revision.revision_id)

        new_counter = change.revision_counter + 1
        update_change_revision_counter(self._conn, change_id, new_counter)

        return {
            "revision_ids": revision_ids,
            "revision_counter": new_counter,
        }
