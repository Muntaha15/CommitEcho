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
    get_decision_state,
    get_repository_by_common_dir,
    insert_change,
    insert_decision_revision,
    insert_evidence,
    insert_session,
    link_session_to_change,
    update_change_revision_counter,
    upsert_repository,
    check_operation,
    record_operation,
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
            "client_version": client_version,
            "native_session_id": native_session_id,
            "prior_change_id": prior_change_id,
            "repository_id": repo_info.common_dir,
            "worktree_id": repo_info.worktree_id,
        }
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            replay = check_operation(self._conn, operation_id, "begin_change", payload)
            if replay is not None:
                return replay
            repo = get_repository_by_common_dir(self._conn, repo_info.common_dir)
            if repo is None:
                repo = Repository(common_dir=repo_info.common_dir)
                upsert_repository(self._conn, repo)
            change = get_change(self._conn, prior_change_id) if prior_change_id else None
            if prior_change_id and change is None:
                raise ValueError(f"Prior change '{prior_change_id}' not found.")
            if change is not None and change.worktree_id != repo_info.worktree_id:
                raise ValueError(f"Change '{prior_change_id}' belongs to another worktree.")
            if change is not None and change.status not in (
                ChangeStatus.OPEN, ChangeStatus.PREPARED
            ):
                raise ValueError(
                    f"Change '{prior_change_id}' is {change.status.value} and cannot be reopened."
                )
            if change is None:
                change = Change(title=title, worktree_id=repo_info.worktree_id,
                                starting_revision=self._git.head_oid())
                insert_change(self._conn, change, repo.installation_id)
            session = Session(client=client, client_version=client_version,
                              native_session_id=native_session_id,
                              worktree_id=repo_info.worktree_id)
            insert_session(self._conn, session, repo.installation_id)
            link_session_to_change(self._conn, change.change_id, session.session_id)
            response = {"change_id": change.change_id, "session_id": session.session_id,
                        "base_oid": change.starting_revision,
                        "revision_counter": change.revision_counter,
                        **get_decision_state(self._conn, self._git, change.change_id)}
            record_operation(self._conn, operation_id, "begin_change", payload, response)
            return response

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
            "expected_revision": expected_revision,
            "decisions": decisions,
            "evidence": evidence or [],
        }
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            change = get_change(self._conn, change_id)
            if change is None:
                raise ValueError(f"Change '{change_id}' not found.")
            if change.worktree_id != self._git.repo_info.worktree_id:
                raise ValueError(f"Change '{change_id}' belongs to another worktree.")
            replay = check_operation(self._conn, operation_id, "record_decisions", payload)
            if replay is not None:
                return replay
            if change.status not in (ChangeStatus.OPEN, ChangeStatus.PREPARED):
                raise ValueError(
                    f"Change '{change_id}' is {change.status.value} and cannot be updated."
                )
            if change.revision_counter != expected_revision:
                raise ValueError(
                    f"Optimistic conflict: expected revision {expected_revision}, "
                    f"actual {change.revision_counter}. Reload and retry."
                )
            return self._record_decisions(change_id, expected_revision, operation_id,
                                          payload, decisions, evidence)

    def _record_decisions(self, change_id, expected_revision, operation_id,
                          payload, decisions, evidence):

        # Persist evidence items first so IDs are available
        ev_objects: list[Evidence] = []
        for ev_data in (evidence or []):
            ev = Evidence(
                **({"evidence_id": ev_data["evidence_id"]} if "evidence_id" in ev_data else {}),
                kind=EvidenceKind(ev_data["kind"]),
                origin=EvidenceOrigin(ev_data.get("origin", "agent_reported")),
                content=ev_data.get("content"),
                locator=ev_data.get("locator"),
                client=ev_data.get("client"),
                verification_method=ev_data.get("verification_method"),
            )
            insert_evidence(self._conn, ev, change_id)
            ev_objects.append(ev)

        revision_ids: list[str] = []
        current_repository = self._conn.execute(
            "SELECT repository_id FROM changes WHERE change_id = ?", (change_id,)
        ).fetchone()["repository_id"]
        for dec_data in decisions:
            predecessor_ids = dec_data.get("predecessor_revision_ids", [])
            predecessors = []
            for predecessor_id in predecessor_ids:
                row = self._conn.execute(
                    """SELECT d.decision_id, c.repository_id
                       FROM decision_revisions d
                       JOIN changes c ON c.change_id = d.change_id
                       WHERE d.revision_id = ?""",
                    (predecessor_id,),
                ).fetchone()
                if row is None or row["repository_id"] != current_repository:
                    raise ValueError(
                        f"Predecessor revision '{predecessor_id}' does not exist in this "
                        "repository."
                    )
                predecessors.append(row)
            decision_id = dec_data.get("decision_id") or (
                predecessors[0]["decision_id"]
                if predecessors
                else str(__import__("uuid").uuid4())
            )
            if any(row["decision_id"] != decision_id for row in predecessors):
                raise ValueError(
                    f"A predecessor revision does not belong to decision '{decision_id}'."
                )
            alts = [Alternative.model_validate(a) for a in dec_data.get("alternatives", [])]
            referenced_ids = set(dec_data.get("evidence_ids", []))
            for alternative in alts:
                referenced_ids.update(alternative.evidence_ids)
            for ev_id in referenced_ids:
                row = self._conn.execute(
                    "SELECT change_id FROM evidence WHERE evidence_id = ?", (ev_id,)
                ).fetchone()
                if row is None or row["change_id"] != change_id:
                    raise ValueError(f"Evidence '{ev_id}' does not belong to change '{change_id}'.")
            code_scope_data = dec_data.get("code_scope", {})
            revision = DecisionRevision(
                decision_id=decision_id,
                predecessor_revision_ids=predecessor_ids,
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

        new_counter = expected_revision + 1
        if not update_change_revision_counter(self._conn, change_id, expected_revision):
            raise ValueError("Optimistic conflict: change revision moved. Reload and retry.")
        response = {
            "revision_ids": revision_ids,
            "evidence_ids": [ev.evidence_id for ev in ev_objects],
            "revision_counter": new_counter,
        }
        record_operation(self._conn, operation_id, "record_decisions", payload, response)
        return response
