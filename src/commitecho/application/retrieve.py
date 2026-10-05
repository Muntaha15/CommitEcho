"""Retrieve service – search_history, get_evidence, compare_history, get_status."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from commitecho.git.adapter import GitAdapter
from commitecho.storage.repository import get_decision_state


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
        """Search the reachable history or the from_ref..to_ref commit range."""
        if not question and not path:
            raise ValueError("Provide question or path.")
        if line is not None and (not path or type(line) is not int or line < 1):
            raise ValueError("line must be a positive integer and requires path.")
        if (from_ref is None) != (to_ref is None) or (at_ref is not None and to_ref is not None):
            raise ValueError("from_ref and to_ref must be used together without at_ref.")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100.")
        if cursor is not None and (not isinstance(cursor, str) or not cursor.isdecimal() or int(cursor) > 10_000):
            raise ValueError("cursor must be an offset between 0 and 10000.")
        if question:
            terms = re.findall(r"\w+", question)
            if not terms:
                raise ValueError("question must contain searchable words.")
            literal_query = " ".join(f'"{term}"' for term in terms)

        # Step 1: Resolve the anchor ref to an immutable OID
        anchor_oid: str | None = None
        anchor_ref = to_ref if to_ref is not None else at_ref
        from_oid: str | None = None
        coverage = "full"
        coverage_notes: list[str] = []

        if anchor_ref is not None:
            try:
                anchor_oid = self._git.resolve(anchor_ref)
                if from_ref is not None:
                    from_oid = self._git.resolve(from_ref)
            except Exception as exc:
                return {"results": [], "anchor_oid": None, "anchor_ref": anchor_ref,
                        "coverage": "partial", "coverage_notes": [f"Cannot resolve history ref: {exc}"],
                        "next_cursor": None}
        else:
            anchor_oid = self._git.head_oid()
            if anchor_oid is None:
                return {
                    "results": [],
                    "anchor_oid": None,
                    "anchor_ref": anchor_ref,
                    "coverage": "partial",
                    "coverage_notes": ["HEAD is unborn; no commits to search."],
                    "next_cursor": None,
                }

        # Step 2: Determine the reachable commit set and indexing completeness
        reachable_oids: set[str] = set()
        if anchor_oid:
            try:
                oids, cov = self._git.reachable_commit_oids(anchor_oid, exclude_ref=from_oid)
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
            return {"results": [], "anchor_oid": anchor_oid, "anchor_ref": anchor_ref,
                    "coverage": "full" if from_oid and coverage == "full" else "partial",
                    "coverage_notes": coverage_notes or
                    ([] if from_oid else ["No reachable commits could be verified."]),
                    "next_cursor": None}

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

        # Step 3: Match filters before applying bounded pagination.
        results: list[dict[str, Any]] = []
        offset = int(cursor) if cursor else 0
        joins = "JOIN decisions_fts f ON f.revision_id = d.revision_id" if question else ""
        clauses: list[str] = []
        params: list[str] = []
        if question:
            clauses.append("decisions_fts MATCH ?")
            params.append(literal_query)
        if path:
            clauses.append("EXISTS (SELECT 1 FROM indexed_paths p WHERE p.revision_id = d.revision_id AND p.path = ?)")
            params.append(path)
        ordering = "rank, cr.commit_oid DESC" if question else "cr.commit_oid DESC"
        try:
            rows = self._index.execute(
                f"""SELECT d.revision_id, d.decision_id, rd.record_id, d.disposition,
                           d.problem, d.choice, d.rationale, cr.commit_oid, r.summary, r.raw_json
                    FROM indexed_decisions d
                    {joins}
                    JOIN indexed_record_decisions rd ON rd.revision_id = d.revision_id
                    JOIN indexed_records r ON r.record_id = rd.record_id
                    JOIN indexed_commit_records cr ON cr.record_id = r.record_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY {ordering}, rd.record_id, d.revision_id""",
                params,
            )
            matched = 0
            for row in rows:
                if row["commit_oid"] not in reachable_oids:
                    continue
                result = _decision_row_to_dict(row)
                if line is not None and not any(
                    start <= line <= end for start, end in result["code_scope"].get("line_ranges") or []
                ):
                    continue
                if matched >= offset:
                    results.append(result)
                    if len(results) > page_size:
                        break
                matched += 1
        except Exception as exc:
            coverage = "partial"
            coverage_notes.append(f"Search error: {exc}")

        has_more = len(results) > page_size
        next_cursor = str(offset + page_size) if has_more and offset + page_size <= 10_000 else None
        if has_more and next_cursor is None:
            coverage = "partial"
            coverage_notes.append("Pagination is limited to the first 10000 matches.")
        results = results[:page_size]

        return {
            "results": results,
            "anchor_oid": anchor_oid,
            "anchor_ref": anchor_ref,
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
            for record in self._index.execute(
                "SELECT r.record_id, cr.commit_oid, r.raw_json FROM indexed_records r "
                "JOIN indexed_commit_records cr ON cr.record_id = r.record_id"
            ):
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
                commit_oids = [r["commit_oid"] for r in self._index.execute(
                    "SELECT commit_oid FROM indexed_commit_records WHERE record_id = ? ORDER BY commit_oid",
                    (record_id,),
                )]
                return {
                    "found": True,
                    "source": "index",
                    "record_id": row["record_id"],
                    "commit_oid": commit_oids[0],
                    "commit_oids": commit_oids,
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
        is_ancestor, merge_base = self._git.check_ancestry(from_oid, to_oid)
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
                SELECT r.record_id, cr.commit_oid, r.summary, r.raw_json,
                       d.revision_id, d.decision_id, d.disposition,
                       d.problem, d.choice, d.rationale
                FROM indexed_records r
                JOIN indexed_commit_records cr ON cr.record_id = r.record_id
                JOIN indexed_record_decisions rd ON rd.record_id = r.record_id
                JOIN indexed_decisions d ON d.revision_id = rd.revision_id
                WHERE cr.commit_oid IN ({placeholders})
                ORDER BY cr.commit_oid
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

        conflicts: list[dict[str, Any]] = []
        if decisions:
            try:
                if is_ancestor is None:
                    raise ValueError("Git ancestry could not be verified")
                reachable, reachability = self._git.reachable_commit_oids(to_oid)
                candidate_oids = set(reachable)
                if is_ancestor is False:
                    other, other_coverage = self._git.reachable_commit_oids(from_oid)
                    candidate_oids.update(other)
                    if other_coverage == "partial":
                        reachability = "partial"
                if reachability == "partial":
                    raise ValueError("Git ancestry is incomplete")
                decision_ids = sorted({d["decision_id"] for d in decisions})
                placeholders = ",".join("?" * len(decision_ids))
                candidate_rows = self._index.execute(
                    f"""SELECT r.record_id, cr.commit_oid, r.summary, r.raw_json,
                               d.revision_id, d.decision_id, d.disposition,
                               d.problem, d.choice, d.rationale
                        FROM indexed_records r
                        JOIN indexed_commit_records cr ON cr.record_id = r.record_id
                        JOIN indexed_record_decisions rd ON rd.record_id = r.record_id
                        JOIN indexed_decisions d ON d.revision_id = rd.revision_id
                        WHERE d.decision_id IN ({placeholders})""",
                    decision_ids,
                )
                candidates = [_decision_row_to_dict(row) for row in candidate_rows
                              if row["commit_oid"] in candidate_oids]
                if path:
                    candidates = [d for d in candidates if d["revision_id"] in path_revision_ids]
                conflicts = _detect_conflicts(candidates, self._git)
            except Exception as exc:
                coverage_notes.append(f"Conflict assessment incomplete: {exc}")

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
        abandoned_changes = []
        query = "SELECT change_id, title, status, updated_at, revision_counter FROM changes WHERE worktree_id = ? AND status IN ('open', 'prepared', 'abandoned')"
        params = [repo_info.worktree_id]
        if change_id:
            query += " AND change_id = ?"
            params.append(change_id)
        rows = self._drafts.execute(query, params).fetchall()

        for row in rows:
            item = {
                "change_id": row["change_id"],
                "title": row["title"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "revision_counter": row["revision_counter"],
            }
            if change_id:
                item.update(get_decision_state(self._drafts, self._git, change_id, self._index))
            (abandoned_changes if row["status"] == "abandoned" else open_changes).append(item)

        indexed_count = self._index.execute(
            "SELECT COUNT(*) as c FROM indexed_commits"
        ).fetchone()["c"]

        head_oid = self._git.head_oid()
        coverage_notes: list[str] = []
        reachable_oids: set[str] = set()
        if head_oid:
            try:
                oids, git_coverage = self._git.reachable_commit_oids(head_oid)
                reachable_oids = set(oids)
                if git_coverage != "full":
                    coverage_notes.append("Git history is shallow or incomplete.")
            except Exception as exc:
                coverage_notes.append(f"Cannot enumerate reachable commits: {exc}")
        else:
            coverage_notes.append(
                "HEAD is unborn or unavailable; history coverage cannot be verified."
            )

        indexed_oids = {
            row["commit_oid"]
            for row in self._index.execute("SELECT commit_oid FROM indexed_commits")
        }
        missing_oids = reachable_oids - indexed_oids
        if missing_oids:
            coverage_notes.append(
                f"{len(missing_oids)} reachable commit(s) not yet indexed. "
                "Run `commitecho index` to improve coverage."
            )
        head_indexed = bool(head_oid and head_oid in indexed_oids)

        diagnostics: list[dict[str, Any]] = []
        if reachable_oids:
            placeholders = ",".join("?" * len(reachable_oids))
            diagnostics = [dict(row) for row in self._index.execute(
                f"""SELECT commit_oid, record_path, error, observed_at
                    FROM index_diagnostics WHERE commit_oid IN ({placeholders})
                    ORDER BY observed_at, commit_oid, record_path""",
                tuple(sorted(reachable_oids)),
            )]
            if diagnostics:
                coverage_notes.append(
                    f"{len(diagnostics)} indexing diagnostic(s) affect reachable history."
                )

        return {
            "worktree": repo_info.worktree_id,
            "head_oid": head_oid,
            "head_indexed": head_indexed,
            "open_changes": open_changes,
            "abandoned_changes": abandoned_changes,
            "indexed_commit_count": indexed_count,
            "coverage": "partial" if coverage_notes else "full",
            "coverage_notes": coverage_notes,
            "index_diagnostics": diagnostics,
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
        "code_scope": decision.get("code_scope", {}),
        "predecessor_revision_ids": decision.get("predecessor_revision_ids", []),
    }


def _detect_conflicts(decisions: list[dict[str, Any]], git: GitAdapter) -> list[dict[str, Any]]:
    """Report revisions with neither lineage nor commit ancestry in common."""
    from collections import defaultdict

    by_decision: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for d in decisions:
        revision = by_decision[d["decision_id"]].setdefault(
            d["revision_id"], {"predecessors": set(), "commits": set()}
        )
        revision["predecessors"].update(d["predecessor_revision_ids"])
        revision["commits"].add(d["commit_oid"])

    ancestors: dict[str, set[str]] = {}

    def reachable(oid: str) -> set[str]:
        if oid not in ancestors:
            oids, coverage = git.reachable_commit_oids(oid)
            if coverage != "full":
                raise ValueError("Git ancestry is incomplete")
            ancestors[oid] = set(oids)
        return ancestors[oid]

    def supersedes(revisions: dict[str, dict[str, Any]], newer: str, older: str) -> bool:
        pending = list(revisions[newer]["predecessors"])
        seen: set[str] = set()
        while pending:
            predecessor = pending.pop()
            if predecessor == older:
                return True
            if predecessor not in seen:
                seen.add(predecessor)
                pending.extend(revisions.get(predecessor, {}).get("predecessors", ()))
        return False

    conflicts = []
    for decision_id, revisions in by_decision.items():
        conflicting_ids: set[str] = set()
        ids = sorted(revisions)
        # ponytail: pairwise revisions; index lineage if one decision gains many revisions.
        for i, left in enumerate(ids):
            for right in ids[i + 1:]:
                if supersedes(revisions, left, right) or supersedes(revisions, right, left):
                    continue
                if any(a == b or a in reachable(b) or b in reachable(a)
                       for a in revisions[left]["commits"] for b in revisions[right]["commits"]):
                    continue
                conflicting_ids.update((left, right))
        if conflicting_ids:
            conflicts.append({
                "decision_id": decision_id,
                "conflicting_revision_ids": sorted(conflicting_ids),
                "note": "Unresolved revisions of this decision appear on divergent commits.",
            })
    return conflicts
