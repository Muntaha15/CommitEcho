"""Eval runner for CommitEcho M4 evaluation.

Runs the 6 fixture scenarios and records three metrics per scenario:

  capture_completeness  – fraction of expected_decisions found after indexing
  linkage_correctness   – verify_commit outcome matches scenario.linkage_check
  retrieval_recall_at_k – recall@5: fraction of expected_decisions in top-5
                          search_history results

Usage::

    # Build fixtures first (idempotent):
    python tests/fixtures/build_fixtures.py

    # Run eval:
    python tests/evals/eval_runner.py

    # Pretty-print results to stdout; non-zero exit when any metric < 1.0.

The runner is also importable as a pytest module; ``test_eval_scenarios``
parametrizes over the 6 scenarios.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Make sure the package is importable when run directly.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

sys.path.insert(0, str(_ROOT / "tests"))
from evals.scenarios import EVAL_SCENARIOS  # noqa: E402

_FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "repos"
_MANIFEST_PATH = _ROOT / "tests" / "fixtures" / "fixture_manifest.json"

RECALL_K = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    scenario_id: str
    capture_completeness: float       # 0.0 – 1.0
    linkage_correctness: float        # 0.0 or 1.0
    retrieval_recall_at_k: float      # 0.0 – 1.0
    details: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.capture_completeness >= 1.0
            and self.linkage_correctness >= 1.0
            and self.retrieval_recall_at_k >= 1.0
            and not self.errors
        )


# ---------------------------------------------------------------------------
# Helpers: fixture repo setup
# ---------------------------------------------------------------------------


def _load_manifest() -> dict[str, dict]:
    if not _MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Fixture manifest not found at {_MANIFEST_PATH}. "
            "Run: python tests/fixtures/build_fixtures.py"
        )
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _open_services(repo_path: Path):
    from commitecho.git.adapter import GitAdapter
    from commitecho.storage.db import open_drafts_db, open_index_db

    git = GitAdapter.from_path(repo_path)
    drafts = open_drafts_db(git.repo_info.common_dir)
    index = open_index_db(git.repo_info.common_dir)
    return git, drafts, index


def _index_commit(index_conn, git, commit_oid: str, record_id: str, record_path: str) -> bool:
    """Index one commit+record into the index DB.  Returns True on success."""
    from commitecho.transports.cli import _index_record

    raw = subprocess.run(
        ["git", "show", f"{commit_oid}:{record_path}"],
        capture_output=True, text=True,
        cwd=str(git.repo_info.worktree_dir),
    ).stdout
    if not raw:
        return False

    try:
        record_data = json.loads(raw)
    except json.JSONDecodeError:
        return False

    index_conn.execute(
        "INSERT OR IGNORE INTO indexed_commits "
        "(commit_oid, repository_id, parent_oid, indexed_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (commit_oid, git.repo_info.common_dir, None),
    )
    _index_record(index_conn, commit_oid, record_id, record_path, record_data, raw)
    return True


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(repo),
    ).stdout.strip()


def _resolve_ref(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        capture_output=True, text=True, cwd=str(repo),
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


def _decisions_match(results: list[dict], expected: list[tuple[str, str]]) -> list[bool]:
    """For each (problem_substr, choice_substr) in expected, return True if found."""
    hits = []
    for prob_sub, choice_sub in expected:
        found = any(
            prob_sub.lower() in r.get("problem", "").lower()
            and choice_sub.lower() in r.get("choice", "").lower()
            for r in results
        )
        hits.append(found)
    return hits


def run_scenario(scenario: dict, manifest: dict) -> ScenarioResult:
    repo_name = scenario.get("fixture_repo", scenario["id"])
    repo_path = _FIXTURES_DIR / repo_name
    meta = manifest.get(repo_name, {})

    result = ScenarioResult(scenario_id=scenario["id"], capture_completeness=0.0,
                            linkage_correctness=0.0, retrieval_recall_at_k=0.0)

    if not repo_path.exists():
        result.errors.append(f"Fixture repo not found: {repo_path}")
        return result

    try:
        from commitecho.application.retrieve import RetrieveService
        from commitecho.application.verify import VerifyService

        git, drafts, index = _open_services(repo_path)
        retrieve = RetrieveService(drafts, index, git)

        # ----------------------------------------------------------------
        # Index all records present in the fixture manifest for this repo
        # ----------------------------------------------------------------
        indexed_any = False
        for key in ("record_id", "record_id_a", "record_id_b", "main_record_id", "branch_record_id"):
            rec_id = meta.get(key)
            if not rec_id:
                continue
            rec_path = f".commitecho/records/{rec_id}.json"
            commit_key = {
                "record_id": "commit_oid",
                "record_id_a": "commit_oid_a",
                "record_id_b": "commit_oid_b",
                "main_record_id": "main_commit_oid",
                "branch_record_id": "branch_commit_oid",
            }[key]
            commit = meta.get(commit_key)
            if commit:
                ok = _index_commit(index, git, commit, rec_id, rec_path)
                if ok:
                    indexed_any = True
        index.commit()

        # ----------------------------------------------------------------
        # Metric 1: capture_completeness
        # ----------------------------------------------------------------
        expected = scenario.get("expected_decisions", [])
        # For branch scenarios, expected_branch_decisions provides per-ref tuples
        branch_expected = scenario.get("expected_branch_decisions", [])
        all_expected = expected + [(p, c) for p, c, _ in branch_expected]

        if not all_expected:
            result.capture_completeness = 1.0
        else:
            # Pull all indexed decisions and check presence
            all_rows = index.execute(
                "SELECT problem, choice FROM indexed_decisions"
            ).fetchall()
            all_decisions = [{"problem": r["problem"], "choice": r["choice"]} for r in all_rows]
            hits = _decisions_match(all_decisions, all_expected)
            result.capture_completeness = sum(hits) / len(hits)
            result.details["capture_hits"] = list(zip(
                [f"{p[:40]}…" for p, _ in all_expected], hits
            ))

        # ----------------------------------------------------------------
        # Metric 2: linkage_correctness (verify_commit)
        # ----------------------------------------------------------------
        linkage_check = scenario.get("linkage_check")
        if linkage_check is None:
            # never_recorded: no record — linkage check is N/A (pass trivially)
            result.linkage_correctness = 1.0
            result.details["linkage"] = "n/a (no record expected)"
        else:
            commit_oid = meta.get("commit_oid") or meta.get("commit_oid_a") or meta.get("main_commit_oid")
            record_id = meta.get("record_id") or meta.get("record_id_a") or meta.get("main_record_id")
            if not commit_oid or not record_id:
                result.errors.append("Cannot determine commit_oid or record_id for linkage check")
                result.linkage_correctness = 0.0
            else:
                verify_result = VerifyService(drafts, index, git).verify_commit(
                    commit_oid=commit_oid, record_id=record_id
                )
                actual_outcome = verify_result.get("outcome", "")
                result.linkage_correctness = 1.0 if actual_outcome == linkage_check else 0.0
                result.details["linkage"] = {
                    "expected": linkage_check,
                    "actual": actual_outcome,
                    "details": verify_result.get("details", {}),
                }

        # ----------------------------------------------------------------
        # Metric 3: retrieval_recall@k
        # ----------------------------------------------------------------
        expected = scenario.get("expected_decisions", [])
        branch_expected = scenario.get("expected_branch_decisions", [])
        gap_query = scenario.get("gap_query")

        if not expected and not branch_expected and gap_query:
            # Gap scenario: search_history should return ZERO results for this query
            response = retrieve.search_history(question=gap_query, page_size=RECALL_K)
            found_count = len(response.get("results", []))
            # Pass if nothing is invented
            result.retrieval_recall_at_k = 1.0 if found_count == 0 else 0.0
            result.details["gap_query_result_count"] = found_count
            if found_count > 0:
                result.errors.append(
                    f"Gap query '{gap_query}' returned {found_count} result(s); "
                    "expected 0 (no rationale should be invented)."
                )
        elif branch_expected:
            # Branch-scoped recall: each decision is searched at its own branch HEAD.
            recall_hits = []
            for prob_sub, choice_sub, commit_key in branch_expected:
                at_ref = meta.get(commit_key, "")
                resp = retrieve.search_history(
                    question=prob_sub, page_size=RECALL_K, at_ref=at_ref or None
                )
                top_k = resp.get("results", [])
                found = any(
                    prob_sub.lower() in r.get("problem", "").lower()
                    and choice_sub.lower() in r.get("choice", "").lower()
                    for r in top_k
                )
                recall_hits.append(found)
            result.retrieval_recall_at_k = sum(recall_hits) / len(recall_hits)
            result.details["branch_recall_hits"] = list(zip(
                [f"{p[:40]}…/{c}" for p, c, _ in branch_expected], recall_hits
            ))
            if not indexed_any:
                result.errors.append("No records were indexed; retrieval will be empty.")
        elif expected:
            # Use the first expected problem as the search question
            first_problem = expected[0][0]
            response = retrieve.search_history(question=first_problem, page_size=RECALL_K)
            top_k = response.get("results", [])
            hits = _decisions_match(top_k, expected)
            result.retrieval_recall_at_k = sum(hits) / len(hits) if hits else 0.0
            result.details["recall_hits"] = list(zip(
                [f"{p[:40]}…" for p, _ in expected], hits
            ))
            if not indexed_any:
                result.errors.append("No records were indexed; retrieval will be empty.")
        else:
            # No expected decisions and no gap query
            result.retrieval_recall_at_k = 1.0

        # ----------------------------------------------------------------
        # Extra: conflict check for branch_conflict scenario
        # Conflict detection works by verifying that both branches indexed
        # revisions with the shared decision_id.
        # ----------------------------------------------------------------
        if scenario.get("conflict_check"):
            shared_id = meta.get("shared_decision_id", "")
            if shared_id:
                rows = index.execute(
                    "SELECT revision_id FROM indexed_decisions WHERE decision_id = ?",
                    (shared_id,),
                ).fetchall()
                conflict_count = len(rows)
                result.details["branch_conflict_revision_count"] = conflict_count
                if conflict_count < 2:
                    result.errors.append(
                        f"branch_conflict: expected ≥2 indexed revisions with "
                        f"shared decision_id {shared_id!r}, found {conflict_count}. "
                        "Both branch commits must be indexed for conflict detection."
                    )

        # ----------------------------------------------------------------
        # Extra: uncovered_paths check for partial_staging
        # The fixture writes src/utils.py but never stages it.
        # Verify it is absent from staged_paths (correctly not covered).
        # ----------------------------------------------------------------
        if scenario.get("uncovered_paths_nonempty"):
            unstaged_file = meta.get("unstaged_file", "")
            staged = meta.get("staged_paths", [])
            result.details["staged_paths"] = staged
            result.details["unstaged_file"] = unstaged_file
            if unstaged_file and unstaged_file in staged:
                result.errors.append(
                    f"partial_staging: '{unstaged_file}' must not appear in staged_paths."
                )
            if not staged:
                result.errors.append(
                    "partial_staging: staged_paths is empty; "
                    "src/rate_limit.py should have been staged."
                )

    except Exception as exc:
        result.errors.append(f"Unhandled exception: {exc}")
        import traceback
        result.details["traceback"] = traceback.format_exc()

    return result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all() -> list[ScenarioResult]:
    manifest = _load_manifest()
    return [run_scenario(s, manifest) for s in EVAL_SCENARIOS]


def print_report(results: list[ScenarioResult]) -> None:
    width = 72
    print("=" * width)
    print("CommitEcho M4 Eval Results")
    print("=" * width)

    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        if not r.passed:
            all_passed = False
        print(f"\n[{status}] {r.scenario_id}")
        print(f"  capture_completeness  : {r.capture_completeness:.2f}")
        print(f"  linkage_correctness   : {r.linkage_correctness:.2f}")
        print(f"  retrieval_recall@{RECALL_K}   : {r.retrieval_recall_at_k:.2f}")
        if r.errors:
            for err in r.errors:
                wrapped = textwrap.fill(err, width=width - 4, initial_indent="  ! ")
                print(wrapped)
        for k, v in r.details.items():
            if k == "traceback":
                continue
            print(f"  {k}: {v}")

    print("\n" + "=" * width)
    overall = "ALL PASS" if all_passed else "FAILURES DETECTED"
    print(f"Overall: {overall}")
    print("=" * width)


# ---------------------------------------------------------------------------
# pytest integration
# ---------------------------------------------------------------------------


def pytest_generate_tests(metafunc):
    if "scenario" in metafunc.fixturenames:
        metafunc.parametrize("scenario", EVAL_SCENARIOS, ids=[s["id"] for s in EVAL_SCENARIOS])


def test_eval_scenario(scenario):
    """Pytest entry point: each EVAL_SCENARIO must pass all three metrics."""
    import pytest

    manifest_path = _ROOT / "tests" / "fixtures" / "fixture_manifest.json"
    if not manifest_path.exists():
        pytest.skip("Fixture repos not built. Run: python tests/fixtures/build_fixtures.py")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = run_scenario(scenario, manifest)

    assert result.capture_completeness >= 1.0, (
        f"[{scenario['id']}] capture_completeness={result.capture_completeness:.2f}. "
        f"Errors: {result.errors}. Details: {result.details}"
    )
    assert result.linkage_correctness >= 1.0, (
        f"[{scenario['id']}] linkage_correctness={result.linkage_correctness:.2f}. "
        f"Expected outcome: {scenario.get('linkage_check')}. "
        f"Details: {result.details.get('linkage')}"
    )
    assert result.retrieval_recall_at_k >= 1.0, (
        f"[{scenario['id']}] retrieval_recall@{RECALL_K}={result.retrieval_recall_at_k:.2f}. "
        f"Details: {result.details}"
    )
    assert not result.errors, (
        f"[{scenario['id']}] extra check errors: {result.errors}"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    results = run_all()
    print_report(results)
    sys.exit(0 if all(r.passed for r in results) else 1)
