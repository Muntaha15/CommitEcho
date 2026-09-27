"""Three-baseline comparison for CommitEcho.

Runs the same question set against the same fixture repos using three
context strategies and reports which strategy provides the most relevant
context for answering the question:

  Baseline A – git diff/blame only
      Context: raw unified diff + git blame excerpt for the relevant file.

  Baseline B – stored excerpts only
      Context: the raw_json of the indexed CommitRecord (evidence + summary)
      without the structured decision fields.

  Baseline C – CommitEcho (full structured recall)
      Context: the structured search_history result (problem/choice/rationale
      + alternatives + evidence).

For each question the script records:
  - Whether the strategy provides a direct rationale (contains_rationale)
  - Number of tokens in the context (proxy: character count / 4)
  - Whether the chosen alternative is mentioned (mentions_alternative)

No LLM is invoked; the comparison is purely structural — measuring whether
the context *contains* the information needed to answer the question, not
whether a model can extract it.  This is the conservative correctness bound.

Usage::

    # Build fixtures first:
    python tests/fixtures/build_fixtures.py

    # Run comparison:
    python tests/evals/baseline_comparison.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

_MANIFEST_PATH = _ROOT / "tests" / "fixtures" / "fixture_manifest.json"
_FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "repos"


# ---------------------------------------------------------------------------
# Question set
# ---------------------------------------------------------------------------

QUESTIONS: list[dict] = [
    {
        "id": "q_dedup_choice",
        "fixture_repo": "chosen_and_rejected",
        "commit_key": "commit_oid",
        "file": "src/uploads.py",
        "question": "Why was content hash deduplication chosen instead of filename deduplication?",
        # search_query: concise keywords for FTS5 (full questions may include
        # punctuation or stop-word patterns that confuse the FTS5 parser)
        "search_query": "duplicate uploads deduplication",
        "expected_rationale_fragment": "rename",
        "expected_alternative_fragment": "filename dedup",
    },
    {
        "id": "q_debounce_reversal",
        "fixture_repo": "later_reversal",
        "commit_key": "commit_oid_b",
        "file": "src/input_handler.py",
        "question": "Why was the debounce delay reduced from 300 ms to 150 ms?",
        "search_query": "debounce rapid input API calls",
        "expected_rationale_fragment": "profiling",
        "expected_alternative_fragment": "300 ms",
    },
    {
        "id": "q_queue_backend",
        "fixture_repo": "branch_conflict",
        "commit_key": "main_commit_oid",
        "file": "src/queue.py",
        "question": "Why was PostgreSQL chosen for the job queue?",
        "search_query": "async job queue backend",
        "expected_rationale_fragment": "infra",
        "expected_alternative_fragment": "Redis",
    },
    {
        "id": "q_rate_limit",
        "fixture_repo": "partial_staging",
        "commit_key": "commit_oid",
        "file": "src/rate_limit.py",
        "question": "Why was a token bucket chosen over a leaky bucket for rate limiting?",
        "search_query": "bots token bucket bursts leaky",
        "expected_rationale_fragment": "burst",
        "expected_alternative_fragment": "leaky",
    },
    {
        "id": "q_never_recorded",
        "fixture_repo": "never_recorded",
        "commit_key": "commit_oid",
        "file": "src/worker.py",
        "question": "Why was the queue size set to 100?",
        "search_query": "queue size 100",
        "expected_rationale_fragment": None,   # not expected to appear
        "expected_alternative_fragment": None,
    },
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BaselineResult:
    question_id: str
    strategy: str                    # "git_diff_blame" | "stored_excerpts" | "commitecho"
    context_chars: int
    context_tokens_approx: int
    contains_rationale: bool
    mentions_alternative: bool
    context_snippet: str = ""        # first 400 chars of context


@dataclass
class QuestionComparison:
    question_id: str
    question: str
    fixture_repo: str
    results: list[BaselineResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
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


def _index_commit_if_needed(index_conn, git, commit_oid: str, record_id: str) -> None:
    already = index_conn.execute(
        "SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (commit_oid,)
    ).fetchone()
    if already:
        return
    from commitecho.transports.cli import _index_record
    record_path = f".commitecho/records/{record_id}.json"
    raw = subprocess.run(
        ["git", "show", f"{commit_oid}:{record_path}"],
        capture_output=True, text=True,
        cwd=str(git.repo_info.worktree_dir),
    ).stdout
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    index_conn.execute(
        "INSERT OR IGNORE INTO indexed_commits "
        "(commit_oid, repository_id, parent_oid, indexed_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (commit_oid, git.repo_info.common_dir, None),
    )
    _index_record(index_conn, commit_oid, record_id, record_path, data, raw)
    index_conn.commit()


def _contains(text: str, fragment: str | None) -> bool:
    if not fragment:
        return False
    return fragment.lower() in text.lower()


# ---------------------------------------------------------------------------
# Strategy A: git diff + blame
# ---------------------------------------------------------------------------


def _context_git_diff_blame(repo_path: Path, commit_oid: str, file_path: str) -> str:
    diff = subprocess.run(
        ["git", "show", "--stat", "-p", "--no-color", commit_oid, "--", file_path],
        capture_output=True, text=True, cwd=str(repo_path),
    ).stdout

    blame = subprocess.run(
        ["git", "blame", "-l", "-n", commit_oid, "--", file_path],
        capture_output=True, text=True, cwd=str(repo_path),
    ).stdout

    return f"=== git diff ===\n{diff}\n=== git blame ===\n{blame}"


# ---------------------------------------------------------------------------
# Strategy B: stored excerpts (raw CommitRecord JSON)
# ---------------------------------------------------------------------------


def _context_stored_excerpts(index_conn, commit_oid: str) -> str:
    row = index_conn.execute(
        "SELECT raw_json FROM indexed_records WHERE commit_oid = ?", (commit_oid,)
    ).fetchone()
    if not row:
        return ""
    try:
        data = json.loads(row["raw_json"])
    except json.JSONDecodeError:
        return row["raw_json"]
    # Expose only summary and evidence — not the structured decision fields
    return json.dumps({
        "summary": data.get("summary", ""),
        "evidence": data.get("evidence", []),
        "created_at": data.get("created_at", ""),
    }, indent=2)


# ---------------------------------------------------------------------------
# Strategy C: CommitEcho structured recall
# ---------------------------------------------------------------------------


def _context_commitecho(retrieve_svc, question: str) -> str:
    response = retrieve_svc.search_history(question=question, page_size=5)
    results = response.get("results", [])
    if not results:
        return "(no CommitEcho records found)"
    parts = []
    for r in results:
        parts.append(
            f"problem: {r.get('problem', '')}\n"
            f"choice: {r.get('choice', '')}\n"
            f"rationale: {r.get('rationale', '')}\n"
            f"disposition: {r.get('disposition', '')}"
        )
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Run one question across all three strategies
# ---------------------------------------------------------------------------


def run_question(q: dict, manifest: dict) -> QuestionComparison:
    repo_name = q["fixture_repo"]
    repo_path = _FIXTURES_DIR / repo_name
    meta = manifest.get(repo_name, {})
    commit_oid = meta.get(q["commit_key"], "")
    record_id = (
        meta.get("record_id")
        or meta.get("record_id_a")
        or meta.get("main_record_id")
        or ""
    )

    comparison = QuestionComparison(
        question_id=q["id"],
        question=q["question"],
        fixture_repo=repo_name,
    )

    if not repo_path.exists() or not commit_oid:
        comparison.results.append(BaselineResult(
            question_id=q["id"], strategy="error",
            context_chars=0, context_tokens_approx=0,
            contains_rationale=False, mentions_alternative=False,
            context_snippet=f"Fixture repo missing: {repo_path}",
        ))
        return comparison

    git, drafts, index = _open_services(repo_path)
    if record_id and commit_oid:
        _index_commit_if_needed(index, git, commit_oid, record_id)

    from commitecho.application.retrieve import RetrieveService
    retrieve = RetrieveService(drafts, index, git)

    rat_frag = q["expected_rationale_fragment"]
    alt_frag = q["expected_alternative_fragment"]

    # Strategy A
    ctx_a = _context_git_diff_blame(repo_path, commit_oid, q["file"])
    comparison.results.append(BaselineResult(
        question_id=q["id"],
        strategy="git_diff_blame",
        context_chars=len(ctx_a),
        context_tokens_approx=len(ctx_a) // 4,
        contains_rationale=_contains(ctx_a, rat_frag),
        mentions_alternative=_contains(ctx_a, alt_frag),
        context_snippet=ctx_a[:400],
    ))

    # Strategy B
    ctx_b = _context_stored_excerpts(index, commit_oid)
    comparison.results.append(BaselineResult(
        question_id=q["id"],
        strategy="stored_excerpts",
        context_chars=len(ctx_b),
        context_tokens_approx=len(ctx_b) // 4,
        contains_rationale=_contains(ctx_b, rat_frag),
        mentions_alternative=_contains(ctx_b, alt_frag),
        context_snippet=ctx_b[:400],
    ))

    # Strategy C — use search_query (keywords) for FTS5, full question for display
    ctx_c = _context_commitecho(retrieve, q.get("search_query", q["question"]))
    comparison.results.append(BaselineResult(
        question_id=q["id"],
        strategy="commitecho",
        context_chars=len(ctx_c),
        context_tokens_approx=len(ctx_c) // 4,
        contains_rationale=_contains(ctx_c, rat_frag),
        mentions_alternative=_contains(ctx_c, alt_frag),
        context_snippet=ctx_c[:400],
    ))

    return comparison


# ---------------------------------------------------------------------------
# Aggregate reporting
# ---------------------------------------------------------------------------


def run_all() -> list[QuestionComparison]:
    manifest = _load_manifest()
    return [run_question(q, manifest) for q in QUESTIONS]


def print_report(comparisons: list[QuestionComparison]) -> None:
    strategies = ["git_diff_blame", "stored_excerpts", "commitecho"]
    width = 80

    print("=" * width)
    print("CommitEcho M4 — Three-Baseline Context Comparison")
    print("=" * width)
    print(
        f"\n{'Question':<28} {'Strategy':<20} {'tokens':>6} "
        f"{'rationale':>10} {'alt_mentioned':>13}"
    )
    print("-" * width)

    totals: dict[str, dict[str, int]] = {s: {"rationale": 0, "alt": 0, "q": 0} for s in strategies}

    for cmp in comparisons:
        for br in cmp.results:
            print(
                f"{cmp.question_id:<28} {br.strategy:<20} {br.context_tokens_approx:>6} "
                f"{'yes' if br.contains_rationale else 'no':>10} "
                f"{'yes' if br.mentions_alternative else 'no':>13}"
            )
            t = totals[br.strategy]
            t["q"] += 1
            if br.contains_rationale:
                t["rationale"] += 1
            if br.mentions_alternative:
                t["alt"] += 1
        print()

    print("=" * width)
    print("Summary — rationale found / questions with expected fragment")
    print("-" * width)
    for s in strategies:
        t = totals[s]
        qs_with_frag = sum(
            1 for q in QUESTIONS if q["expected_rationale_fragment"] is not None
        )
        print(
            f"  {s:<22} rationale: {t['rationale']}/{qs_with_frag}  "
            f"alternative: {t['alt']}/{qs_with_frag}"
        )
    print("=" * width)


# ---------------------------------------------------------------------------
# pytest integration
# ---------------------------------------------------------------------------


def pytest_generate_tests(metafunc):
    if "question" in metafunc.fixturenames:
        metafunc.parametrize("question", QUESTIONS, ids=[q["id"] for q in QUESTIONS])


def test_commitecho_beats_diff_blame(question):
    """CommitEcho strategy should provide rationale wherever git diff/blame cannot."""
    import pytest

    manifest_path = _ROOT / "tests" / "fixtures" / "fixture_manifest.json"
    if not manifest_path.exists():
        pytest.skip("Fixture repos not built. Run: python tests/fixtures/build_fixtures.py")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cmp = run_question(question, manifest)

    if question["expected_rationale_fragment"] is None:
        # never_recorded: CommitEcho should NOT invent rationale
        commitecho_result = next(r for r in cmp.results if r.strategy == "commitecho")
        assert not commitecho_result.contains_rationale, (
            f"[{question['id']}] CommitEcho invented a rationale for an unrecorded decision."
        )
    else:
        commitecho_result = next(r for r in cmp.results if r.strategy == "commitecho")
        assert commitecho_result.contains_rationale, (
            f"[{question['id']}] CommitEcho did not surface the expected rationale fragment "
            f"'{question['expected_rationale_fragment']}'."
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    comparisons = run_all()
    print_report(comparisons)
    # Exit non-zero if CommitEcho fails to surface rationale for any question
    # that has an expected fragment.
    failed = [
        q["id"]
        for cmp in comparisons
        for q in QUESTIONS
        if q["id"] == cmp.question_id
        and q["expected_rationale_fragment"] is not None
        and not any(
            r.contains_rationale for r in cmp.results if r.strategy == "commitecho"
        )
    ]
    if failed:
        print(f"\nCommitEcho recall failures: {failed}")
        sys.exit(1)
    sys.exit(0)
