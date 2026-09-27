"""Retrieve service – search_history, get_evidence, compare_history, get_status."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from commitecho.git.adapter import GitAdapter


_DEFAULT_PAGE_SIZE = 20


class RetrieveService:
    """Read-only retrieval over the history index and draft state."""

    def __init__(
        self,
        drafts_conn: sqlite3.Connection,
        index_conn: sqlite3.Connection,
        git: GitAdapter,
    ) -> None:
        self._drafts = drafts_conn
        self._index = index_conn
        self._git = git

    # ------------------------------------------------------------------
    # search_history
    # ------------------------------------------------------------------

    def search_history(
        self,
        *,
        question: str | None = None,
        path: str | None = None,
        line: int | None = None,
        at_ref: str | None = None,
        from_ref: str | None = None,
        to_ref: str | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return ranked records matching *question* and/or *path*.

        Scoped to the ancestry of *at_ref* (default: HEAD).
        Only records whose commit is reachable from *at_ref* are returned.
        Returns bounded list with explicit cursor and coverage information.
        """
        # Step 1: Resolve the anchor ref to an immutable OID
        anchor_oid: str | None = None
        coverage = "full"
        coverage_notes: list[str] = []

        if at_ref:
            try:
                anchor_oid = self._git.resolve(at_ref)
            except Exception as exc:
                coverage = "partial"
                coverage_notes.append(f"Cannot resolve at_ref '{at_ref}': {exc}")
                return {"results": [], "anchor_oid": None, "anchor_ref": at_ref,
                        "coverage": coverage, "coverage_notes": coverage_notes,
                        "next_cursor": None}
        else:
            anchor_oid = self._git.head_oid()
            if anchor_oid is None:
                return {
                    "results": [],
                    "anchor_oid": None,
                    "anchor_ref": at_ref,
                    "coverage": "partial",
                    "coverage_notes": ["HEAD is unborn; no commits to search."],
                    "next_cursor": None,
                }

        # Step 2: Determine the reachable commit set and indexing completeness
        reachable_oids: set[str] = set()
        if anchor_oid:
            try:
                oids, cov = self._git.reachable_commit_oids(anchor_oid)
                reachable_oids = set(oids)
                if cov == "partial":
                    coverage = "partial"
                    coverage_notes.append(
                        "Shallow clone or missing objects detected; history may be incomplete."
                    )
            except Exception as exc:
                coverage = "partial"
                coverage_notes.append(f"Cannot enumerate reachable commits: {exc}")
        if not reachable_oids:
            return {"results": [], "anchor_oid": anchor_oid, "anchor_ref": at_ref,
                    "coverage": "partial", "coverage_notes": coverage_notes or
                    ["No reachable commits could be verified."], "next_cursor": None}

        # Check indexing completeness: any reachable commit not in the index?
        if reachable_oids:
            indexed_rows = self._index.execute(
                "SELECT commit_oid FROM indexed_commits"
            ).fetchall()
            indexed_oids = {r["commit_oid"] for r in indexed_rows}
            unindexed = reachable_oids - indexed_oids
            if unindexed:
                coverage = "partial"
                coverage_notes.append(
                    f"{len(unindexed)} reachable commit(s) not yet indexed. "
                    "Run `commitecho index` to improve coverage."
                )

        # Step 3: Filter candidate OIDs to the reachable set
        results: list[dict[str, Any]] = []
        offset = int(cursor) if cursor else 0

        if question:
            # FTS5 lexical search scoped to reachable commits
            try:
                rows = self._index.execute(
                    """
                    SELECT d.revision_id, d.decision_id, d.record_id, d.disposition,
                           d.problem, d.choice, d.rationale, r.commit_oid, r.summary, r.raw_json
                    FROM decisions_fts f
                    JOIN indexed_decisions d ON d.revision_id = f.revision_id
                    JOIN indexed_records r ON r.record_id = d.record_id
                    WHERE decisions_fts MATCH ?
                    ORDER BY rank
                    """,
                    (question,),
                ).fetchall()
                # Apply ancestry filter in Python (SQLite has no reachable-set function)
                for row in rows:
                    if row["commit_oid"] in reachable_oids:
                        results.append(_decision_row_to_dict(row))
                # Apply pagination after filtering
                results = results[offset: offset + page_size]
            except Exception as exc:
                coverage = "partial"
                coverage_notes.append(f"FTS search error: {exc}")

        if path and not results:
            # Path-based lookup scoped to reachable commits
            try:
                rows = self._index.execute(
                    """
                    SELECT d.revision_id, d.decision_id, d.record_id, d.disposition,
                           d.problem, d.choice, d.rationale, r.commit_oid, r.summary, r.raw_json
                    FROM indexed_paths p
                    JOIN indexed_decisions d ON d.revision_id = p.revision_id
                    JOIN indexed_records r ON r.record_id = d.record_id
                    WHERE p.path = ?
                    ORDER BY r.commit_oid DESC
                    """,
                    (path,),
                ).fetchall()
                for row in rows:
                    if row["commit_oid"] in reachable_oids:
                        results.append(_decision_row_to_dict(row))
                results = results[offset: offset + page_size]
            except Exception as exc:
                coverage = "partial"
                coverage_notes.append(f"Path lookup error: {exc}")

        next_cursor = str(offset + page_size) if len(results) == page_size else None

        return {
            "results": results,
            "anchor_oid": anchor_oid,
            "anchor_ref": at_ref,
            "coverage": coverage,
            "coverage_notes": coverage_notes,
            "next_cursor": next_cursor,
        }

    # ------------------------------------------------------------------
    # get_evidence
    # ------------------------------------------------------------------

    def get_evidence(
        self,
        *,
        evidence_id: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        """Return bounded source material and provenance for an evidence or record ID."""
        if evidence_id:
            row = self._drafts.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
            if row:
                return {
                    "found": True,
                    "source": "draft",
                    "evidence_id": row["evidence_id"],
                    "kind": row["kind"],
                    "origin": row["origin"],
                    "content": row["content"],
                    "locator": row["locator"],
                    "client": row["client"],
                    "observed_at": row["observed_at"],
                }
            # ponytail: linear scan; add an evidence index if clone lookups become slow.
            for record in self._index.execute("SELECT record_id, commit_oid, raw_json FROM indexed_records"):
                for item in json.loads(record["raw_json"]).get("evidence", []):
                    if item["evidence_id"] == evidence_id:
                        return {"found": True, "source": "index", "record_id": record["record_id"],
                                "commit_oid": record["commit_oid"], **item}
            return {"found": False, "evidence_id": evidence_id}

        if record_id:
            row = self._index.execute(
                "SELECT * FROM indexed_records WHERE record_id = ?", (record_id,)
            ).fetchone()
            if row:
                # Return the full raw record so the agent has all evidence
                try:
                    raw = json.loads(row["raw_json"])
                except Exception:
                    raw = {}
                return {
                    "found": True,
                    "source": "index",
                    "record_id": row["record_id"],
                    "commit_oid": row["commit_oid"],
                    "summary": row["summary"],
                    "record": raw,
                }
            return {"found": False, "record_id": record_id}

        return {"found": False, "error": "Provide either evidence_id or record_id."}

    # ------------------------------------------------------------------
    # compare_history
    # ------------------------------------------------------------------

    def compare_history(
        self,
        *,
        from_ref: str,
        to_ref: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Return decision revisions introduced in the A..B range.

        Commits reachable from to_ref excluding those reachable from from_ref.
        Branch divergence and merge-base are reported when from_ref is not
        an ancestor of to_ref.
        """
        coverage_notes: list[str] = []
        try:
            from_oid = self._git.resolve(from_ref)
            to_oid = self._git.resolve(to_ref)
        except Exception as exc:
            return {
                "error": str(exc),
                "coverage": "partial",
                "coverage_notes": [str(exc)],
                "decisions": [],
                "from_oid": None,
                "to_oid": None,
                "is_ancestor": None,
                "merge_base": None,
                "conflicts": [],
            }

        # Check ancestry and find merge base
        is_ancestor, merge_base = _check_ancestry(
            from_oid, to_oid, self._git.repo_info.worktree_dir
        )
        if is_ancestor is False:
            coverage_notes.append(
                f"{from_ref} ({from_oid[:8]}) is not an ancestor of "
                f"{to_ref} ({to_oid[:8]}). "
                f"Merge base: {merge_base[:8] if merge_base else 'unknown'}. "
                "Results show commits reachable from to_ref but not from_ref."
            )

        # Enumerate the A..B commit set using git rev-list
        try:
            range_oids, cov = self._git.reachable_commit_oids(to_oid, exclude_ref=from_oid)
            if cov == "partial":
                coverage_notes.append(
                    "Shallow clone or missing objects; range may be incomplete."
                )
        except Exception as exc:
            return {
                "error": str(exc),
                "coverage": "partial",
                "coverage_notes": [str(exc)],
                "decisions": [],
                "from_oid": from_oid,
                "to_oid": to_oid,
                "is_ancestor": is_ancestor,
                "merge_base": merge_base,
                "conflicts": [],
            }

        range_set = set(range_oids)

        # Fetch records whose commit is in the range
        if range_set:
            placeholders = ",".join("?" * len(range_set))
            rows = self._index.execute(
                f"""
                SELECT r.record_id, r.commit_oid, r.summary, r.raw_json,
                       d.revision_id, d.decision_id, d.disposition,
                       d.problem, d.choice, d.rationale
                FROM indexed_records r
                JOIN indexed_decisions d ON d.record_id = r.record_id
                WHERE r.commit_oid IN ({placeholders})
                ORDER BY r.commit_oid
                """,
                tuple(range_set),
            ).fetchall()
        else:
            rows = []

        decisions = [_decision_row_to_dict(row) for row in rows]

        # Filter by path if requested
        if path and decisions:
            path_revision_ids = {
                r["revision_id"]
                for r in self._index.execute(
                    "SELECT revision_id FROM indexed_paths WHERE path = ?", (path,)
                ).fetchall()
            }
            decisions = [d for d in decisions if d["revision_id"] in path_revision_ids]

        # Detect branch conflicts: same decision_id with multiple revision_ids
        conflicts = _detect_conflicts(decisions)

        # Indexing completeness for this range
        indexed_oids = {
            r["commit_oid"]
            for r in self._index.execute(
                "SELECT commit_oid FROM indexed_commits"
            ).fetchall()
        }
        unindexed_in_range = range_set - indexed_oids
        if unindexed_in_range:
            coverage_notes.append(
                f"{len(unindexed_in_range)} commit(s) in range not yet indexed. "
                "Run `commitecho index` to improve coverage."
            )

        return {
            "from_oid": from_oid,
            "to_oid": to_oid,
            "is_ancestor": is_ancestor,
            "merge_base": merge_base,
            "range_commit_count": len(range_oids),
            "decisions": decisions,
            "conflicts": conflicts,
            "coverage": "partial" if coverage_notes else "full",
            "coverage_notes": coverage_notes,
        }

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def get_status(self, change_id: str | None = None) -> dict[str, Any]:
        """Return pending changes, indexing coverage, and setup capability."""
        repo_info = self._git.repo_info

        open_changes = []
        query = "SELECT change_id, title, status, updated_at FROM changes WHERE status != 'committed'"
        if change_id:
            query += " AND change_id = ?"
            rows = self._drafts.execute(query, (change_id,)).fetchall()
        else:
            rows = self._drafts.execute(query).fetchall()

        for row in rows:
            open_changes.append({
                "change_id": row["change_id"],
                "title": row["title"],
                "status": row["status"],
                "updated_at": row["updated_at"],
            })

        indexed_count = self._index.execute(
            "SELECT COUNT(*) as c FROM indexed_commits"
        ).fetchone()["c"]

        head_oid = self._git.head_oid()

        # Check if HEAD is indexed
        head_indexed = False
        if head_oid:
            head_indexed = bool(
                self._index.execute(
                    "SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (head_oid,)
                ).fetchone()
            )

        return {
            "worktree": repo_info.worktree_id,
            "head_oid": head_oid,
            "head_indexed": head_indexed,
            "open_changes": open_changes,
            "indexed_commit_count": indexed_count,
            "coverage": "partial" if (head_oid and not head_indexed) else "full",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision_row_to_dict(row: Any) -> dict[str, Any]:
    decision = next((d for d in json.loads(row["raw_json"])["decisions"]
                     if d["revision_id"] == row["revision_id"]), {})
    evidence_ids = set(decision.get("evidence_ids", []))
    for alternative in decision.get("alternatives", []):
        evidence_ids.update(alternative.get("evidence_ids", []))
    return {
        "revision_id": row["revision_id"],
        "decision_id": row["decision_id"],
        "record_id": row["record_id"],
        "commit_oid": row["commit_oid"],
        "summary": row["summary"],
        "disposition": row["disposition"],
        "problem": row["problem"],
        "choice": row["choice"],
        "rationale": row["rationale"],
        "evidence_ids": sorted(evidence_ids),
    }


def _check_ancestry(
    from_oid: str, to_oid: str, worktree_dir: str
) -> tuple[bool | None, str | None]:
    """Return (is_ancestor, merge_base_oid).

    is_ancestor is True if from_oid is an ancestor of to_oid, False otherwise,
    None if the check fails.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", from_oid, to_oid],
            capture_output=True,
            cwd=worktree_dir,
        )
        is_ancestor = result.returncode == 0
    except Exception:
        return None, None

    merge_base: str | None = None
    if not is_ancestor:
        try:
            mb_result = subprocess.run(
                ["git", "merge-base", from_oid, to_oid],
                capture_output=True, text=True,
                cwd=worktree_dir,
            )
            merge_base = mb_result.stdout.strip() or None
        except Exception:
            pass

    return is_ancestor, merge_base


def _detect_conflicts(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a list of conflict descriptors for decisions with the same decision_id
    but different revision_ids within the result set.

    This surfaces branch-local incompatible revisions.
    """
    from collections import defaultdict

    by_decision: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in decisions:
        by_decision[d["decision_id"]].append(d)

    conflicts = []
    for decision_id, revs in by_decision.items():
        if len(revs) > 1:
            rev_ids = [r["revision_id"] for r in revs]
            conflicts.append({
                "decision_id": decision_id,
                "conflicting_revision_ids": rev_ids,
                "note": (
                    "Multiple revisions of the same decision appear in this range. "
                    "They may reflect independent branch-local changes that have not been resolved."
                ),
            })
    return conflicts
