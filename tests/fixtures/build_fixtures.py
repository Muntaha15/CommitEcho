"""Build the six tiny fixture Git repositories used by the M4 eval runner.

Run once to create the repos under tests/fixtures/repos/:

    python tests/fixtures/build_fixtures.py

Each repo is self-contained and carries CommitEcho records committed alongside
the code changes.  The script is idempotent: it deletes and recreates any
existing repos directory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# Ensure the package is importable when run directly.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from commitecho.application.capture import CaptureService
from commitecho.application.prepare import PrepareService
from commitecho.git.adapter import GitAdapter
from commitecho.storage.db import open_drafts_db, open_index_db

FIXTURES_DIR = Path(__file__).parent / "repos"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False)


def _init_repo(path: Path, name: str) -> Path:
    repo = path / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    _git(["git", "init", "--initial-branch=main"], repo)
    _git(["git", "config", "user.email", "fixture@commitecho.test"], repo)
    _git(["git", "config", "user.name", "CommitEcho Fixture"], repo)
    return repo


def _open_services(repo: Path):
    git = GitAdapter.from_path(repo)
    drafts = open_drafts_db(git.repo_info.common_dir)
    index = open_index_db(git.repo_info.common_dir)
    return git, drafts, index


def _commit(repo: Path, message: str) -> str:
    _git(["git", "commit", "-m", message], repo)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()


def _write_and_stage(repo: Path, rel_path: str, content: str) -> None:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(["git", "add", rel_path], repo)


def _full_workflow(
    repo: Path,
    git,
    drafts,
    *,
    title: str,
    decisions: list[dict],
    selected_indices: list[int],
    summary: str,
    staged_files: list[tuple[str, str]],  # (rel_path, content)
    commit_msg_prefix: str = "feat",
    client: str = "test",
) -> dict:
    """Run begin_change → record_decisions → stage files → prepare → add record → commit."""
    capture = CaptureService(drafts, git)
    prepare = PrepareService(drafts, git)

    begin = capture.begin_change(
        title=title,
        client=client,
        operation_id=str(uuid.uuid4()),
    )
    change_id = begin["change_id"]

    rec = capture.record_decisions(
        change_id=change_id,
        expected_revision=0,
        operation_id=str(uuid.uuid4()),
        decisions=decisions,
    )
    selected_rev_ids = [rec["revision_ids"][i] for i in selected_indices]

    for rel_path, content in staged_files:
        _write_and_stage(repo, rel_path, content)

    prep = prepare.prepare_commit(
        change_id=change_id,
        expected_revision=1,
        selected_revision_ids=selected_rev_ids,
        summary=summary,
        operation_id=str(uuid.uuid4()),
    )

    _git(["git", "add", prep["record_path"]], repo)
    oid = _commit(repo, f"{commit_msg_prefix}: {summary}\n\n{prep['trailer']}")

    return {
        "change_id": change_id,
        "record_id": prep["record_id"],
        "record_path": prep["record_path"],
        "commit_oid": oid,
        "revision_ids": rec["revision_ids"],
        "selected_revision_ids": selected_rev_ids,
    }


# ---------------------------------------------------------------------------
# Scenario 1 – chosen_and_rejected
# ---------------------------------------------------------------------------


def build_chosen_and_rejected(base: Path) -> dict:
    """Chosen approach and rejected alternative captured together.

    Decision: deduplicate uploads by content hash (chosen) vs
              filename-based dedup (rejected).
    """
    repo = _init_repo(base, "chosen_and_rejected")
    git, drafts, index = _open_services(repo)

    # Bootstrap: initial commit so HEAD exists
    _write_and_stage(repo, "README.md", "# Upload service\n")
    _git(["git", "commit", "-m", "initial commit"], repo)

    result = _full_workflow(
        repo, git, drafts,
        title="deduplicate uploads",
        decisions=[
            {
                "problem": "duplicate uploads on retry",
                "choice": "content hash deduplication",
                "rationale": "same bytes always produce the same job ID; rename-safe",
                "disposition": "selected",
                "code_scope": {"paths": ["src/uploads.py"]},
                "alternatives": [
                    {
                        "choice": "filename deduplication",
                        "disposition": "rejected",
                        "reason": "renames bypass it; collision-prone on large buckets",
                    }
                ],
            }
        ],
        selected_indices=[0],
        summary="Deduplicate by content hash to prevent retry storms",
        staged_files=[
            ("src/uploads.py", "DEDUP_STRATEGY = 'content_hash'\n"),
        ],
    )

    return {
        "repo": str(repo),
        "scenario": "chosen_and_rejected",
        "commit_oid": result["commit_oid"],
        "record_id": result["record_id"],
        "expected_problem": "duplicate uploads on retry",
        "expected_choice": "content hash deduplication",
    }


# ---------------------------------------------------------------------------
# Scenario 2 – later_reversal
# ---------------------------------------------------------------------------


def build_later_reversal(base: Path) -> dict:
    """Decision recorded at commit A is superseded by a new decision at commit B.

    First commit: debounce at 300 ms.
    Second commit: switch to 150 ms after profiling shows UI lag.
    """
    repo = _init_repo(base, "later_reversal")
    git, drafts, index = _open_services(repo)

    _write_and_stage(repo, "README.md", "# Input handler\n")
    _git(["git", "commit", "-m", "initial commit"], repo)

    # Commit A – original decision
    result_a = _full_workflow(
        repo, git, drafts,
        title="set debounce delay",
        decisions=[
            {
                "problem": "rapid input generates too many API calls",
                "choice": "debounce at 300 ms",
                "rationale": "300 ms is within the 500 ms acceptable-latency budget",
                "disposition": "selected",
                "code_scope": {"paths": ["src/input_handler.py"]},
            }
        ],
        selected_indices=[0],
        summary="Debounce input handler at 300 ms",
        staged_files=[
            ("src/input_handler.py", "DEBOUNCE_MS = 300\n"),
        ],
    )

    # Commit B – reversal with predecessor pointing at commit A's decision
    git2, drafts2, index2 = _open_services(repo)
    capture2 = CaptureService(drafts2, git2)
    prepare2 = PrepareService(drafts2, git2)

    begin2 = capture2.begin_change(
        title="reduce debounce delay after profiling",
        client="test",
        operation_id=str(uuid.uuid4()),
    )
    change_id_b = begin2["change_id"]

    rec2 = capture2.record_decisions(
        change_id=change_id_b,
        expected_revision=0,
        operation_id=str(uuid.uuid4()),
        decisions=[
            {
                "decision_id": str(uuid.uuid4()),  # same decision_id could link, here independent
                "problem": "rapid input generates too many API calls",
                "choice": "reduce debounce to 150 ms after profiling",
                "rationale": (
                    "Profiling showed 300 ms causes noticeable UI lag; "
                    "150 ms keeps call rate acceptable"
                ),
                "disposition": "selected",
                "predecessor_revision_ids": result_a["revision_ids"],
                "code_scope": {"paths": ["src/input_handler.py"]},
            }
        ],
    )
    rev_id_b = rec2["revision_ids"][0]
    _write_and_stage(repo, "src/input_handler.py", "DEBOUNCE_MS = 150\n")

    prep2 = prepare2.prepare_commit(
        change_id=change_id_b,
        expected_revision=1,
        selected_revision_ids=[rev_id_b],
        summary="Reduce debounce to 150 ms after profiling",
        operation_id=str(uuid.uuid4()),
    )
    _git(["git", "add", prep2["record_path"]], repo)
    commit_oid_b = _commit(
        repo,
        f"perf: reduce debounce to 150 ms\n\n{prep2['trailer']}"
    )

    return {
        "repo": str(repo),
        "scenario": "later_reversal",
        "commit_oid_a": result_a["commit_oid"],
        "commit_oid_b": commit_oid_b,
        "record_id_a": result_a["record_id"],
        "record_id_b": prep2["record_id"],
        "original_choice": "debounce at 300 ms",
        "superseding_choice": "reduce debounce to 150 ms after profiling",
    }


# ---------------------------------------------------------------------------
# Scenario 3 – branch_conflict
# ---------------------------------------------------------------------------


def build_branch_conflict(base: Path) -> dict:
    """Two branches carry incompatible decisions for the same problem.

    main: chooses PostgreSQL for the job queue.
    feature/redis-queue: chooses Redis Streams.
    Neither is merged; both decisions are indexable.
    """
    repo = _init_repo(base, "branch_conflict")
    git, drafts, index = _open_services(repo)

    _write_and_stage(repo, "README.md", "# Queue backend\n")
    _git(["git", "commit", "-m", "initial commit"], repo)

    # Shared decision_id so the conflict is detectable by compare_history
    shared_decision_id = str(uuid.uuid4())

    # Branch: main
    result_main = _full_workflow(
        repo, git, drafts,
        title="choose queue backend",
        decisions=[
            {
                "decision_id": shared_decision_id,
                "problem": "which backend to use for the async job queue",
                "choice": "PostgreSQL SKIP LOCKED",
                "rationale": "already in the stack; no new infra dependency",
                "disposition": "selected",
                "code_scope": {"paths": ["src/queue.py"]},
            }
        ],
        selected_indices=[0],
        summary="Use PostgreSQL SKIP LOCKED for job queue",
        staged_files=[
            ("src/queue.py", "BACKEND = 'postgresql'\n"),
        ],
    )

    # Branch: feature/redis-queue
    _git(["git", "checkout", "-b", "feature/redis-queue"], repo)
    git3, drafts3, index3 = _open_services(repo)

    result_branch = _full_workflow(
        repo, git3, drafts3,
        title="choose queue backend (redis alternative)",
        decisions=[
            {
                "decision_id": shared_decision_id,
                "problem": "which backend to use for the async job queue",
                "choice": "Redis Streams",
                "rationale": "lower latency for high-throughput; acceptable infra cost",
                "disposition": "selected",
                "code_scope": {"paths": ["src/queue.py"]},
            }
        ],
        selected_indices=[0],
        summary="Use Redis Streams for job queue",
        staged_files=[
            ("src/queue.py", "BACKEND = 'redis_streams'\n"),
        ],
    )

    _git(["git", "checkout", "main"], repo)

    return {
        "repo": str(repo),
        "scenario": "branch_conflict",
        "shared_decision_id": shared_decision_id,
        "main_commit_oid": result_main["commit_oid"],
        "branch_commit_oid": result_branch["commit_oid"],
        "main_record_id": result_main["record_id"],
        "branch_record_id": result_branch["record_id"],
        "main_choice": "PostgreSQL SKIP LOCKED",
        "branch_choice": "Redis Streams",
    }


# ---------------------------------------------------------------------------
# Scenario 4 – partial_staging
# ---------------------------------------------------------------------------


def build_partial_staging(base: Path) -> dict:
    """Only staged paths are covered; unstaged paths are reported as uncovered."""
    repo = _init_repo(base, "partial_staging")
    git, drafts, index = _open_services(repo)

    _write_and_stage(repo, "README.md", "# Partial staging demo\n")
    _git(["git", "commit", "-m", "initial commit"], repo)

    capture = CaptureService(drafts, git)
    prepare = PrepareService(drafts, git)

    begin = capture.begin_change(
        title="rate limiting implementation",
        client="test",
        operation_id=str(uuid.uuid4()),
    )
    change_id = begin["change_id"]

    rec = capture.record_decisions(
        change_id=change_id,
        expected_revision=0,
        operation_id=str(uuid.uuid4()),
        decisions=[
            {
                "problem": "API endpoint hit too frequently by bots",
                "choice": "token bucket rate limiter at 100 req/min",
                "rationale": "token bucket allows short bursts; simpler than leaky bucket",
                "disposition": "selected",
                "code_scope": {"paths": ["src/rate_limit.py"]},
            }
        ],
    )
    rev_id = rec["revision_ids"][0]

    # Stage only the rate_limit file; leave utils.py unstaged
    _write_and_stage(repo, "src/rate_limit.py", "RATE_LIMIT = 100\n")
    (repo / "src" / "utils.py").write_text("# unstaged helper\n")
    # NOT staged: src/utils.py

    prep = prepare.prepare_commit(
        change_id=change_id,
        expected_revision=1,
        selected_revision_ids=[rev_id],
        summary="Add token bucket rate limiter",
        operation_id=str(uuid.uuid4()),
    )

    _git(["git", "add", prep["record_path"]], repo)
    commit_oid = _commit(repo, f"feat: add rate limiter\n\n{prep['trailer']}")

    return {
        "repo": str(repo),
        "scenario": "partial_staging",
        "commit_oid": commit_oid,
        "record_id": prep["record_id"],
        "staged_paths": prep["staged_paths"],
        "uncovered_paths": prep["uncovered_paths"],
        "unstaged_file": "src/utils.py",
    }


# ---------------------------------------------------------------------------
# Scenario 5 – stale_preparation
# ---------------------------------------------------------------------------


def build_stale_preparation(base: Path) -> dict:
    """Index changes after prepare; verify outcome is not 'exact'.

    We prepare normally, then add an extra file to the commit.
    The record manifest won't match, so verify returns declared_changed.
    """
    repo = _init_repo(base, "stale_preparation")
    git, drafts, index = _open_services(repo)

    _write_and_stage(repo, "README.md", "# Stale prep demo\n")
    _git(["git", "commit", "-m", "initial commit"], repo)

    capture = CaptureService(drafts, git)
    prepare = PrepareService(drafts, git)

    begin = capture.begin_change(
        title="cache layer",
        client="test",
        operation_id=str(uuid.uuid4()),
    )
    change_id = begin["change_id"]

    rec = capture.record_decisions(
        change_id=change_id,
        expected_revision=0,
        operation_id=str(uuid.uuid4()),
        decisions=[
            {
                "problem": "repeated DB reads for hot keys slow response time",
                "choice": "in-process LRU cache with 60 s TTL",
                "rationale": "avoids external cache dependency; good for read-heavy workloads",
                "disposition": "selected",
                "code_scope": {"paths": ["src/cache.py"]},
            }
        ],
    )
    rev_id = rec["revision_ids"][0]

    _write_and_stage(repo, "src/cache.py", "TTL = 60\n")

    # prepare snapshot taken here
    prep = prepare.prepare_commit(
        change_id=change_id,
        expected_revision=1,
        selected_revision_ids=[rev_id],
        summary="Add LRU cache with 60 s TTL",
        operation_id=str(uuid.uuid4()),
    )
    manifest_sha_at_prepare = prep["code_manifest_sha256"]

    # After prepare: add an extra file — this makes the commit's manifest differ
    _write_and_stage(repo, "src/cache_warmup.py", "# added after prepare\n")
    _git(["git", "add", prep["record_path"], "src/cache_warmup.py"], repo)
    commit_oid = _commit(repo, f"feat: add cache layer\n\n{prep['trailer']}")

    return {
        "repo": str(repo),
        "scenario": "stale_preparation",
        "commit_oid": commit_oid,
        "record_id": prep["record_id"],
        "manifest_sha_at_prepare": manifest_sha_at_prepare,
        "extra_file_added_post_prepare": "src/cache_warmup.py",
    }


# ---------------------------------------------------------------------------
# Scenario 6 – never_recorded
# ---------------------------------------------------------------------------


def build_never_recorded(base: Path) -> dict:
    """A commit exists whose rationale was never captured.

    The queue size is hardcoded but never explained in any CommitEcho record.
    search_history must return no results for the gap question.
    """
    repo = _init_repo(base, "never_recorded")
    git, drafts, index = _open_services(repo)

    # Commit a file with a magic constant — no CommitEcho record attached
    _write_and_stage(repo, "src/worker.py", "QUEUE_SIZE = 100\n")
    commit_oid = _commit(
        repo,
        "feat: add worker queue\n\nQueue size set to 100 (no decision recorded)."
    )

    return {
        "repo": str(repo),
        "scenario": "never_recorded",
        "commit_oid": commit_oid,
        "gap_question": "Why was the queue size set to 100?",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _force_rmtree(path: Path) -> None:
    """Remove a directory tree, handling read-only files on Windows."""
    import os as _os
    import stat

    def _on_error(func, fpath, exc_info):
        # Make the file writable and retry
        _os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(str(path), onerror=_on_error)


def main() -> None:
    if FIXTURES_DIR.exists():
        _force_rmtree(FIXTURES_DIR)
    FIXTURES_DIR.mkdir(parents=True)

    manifest: dict[str, dict] = {}

    builders = [
        build_chosen_and_rejected,
        build_later_reversal,
        build_branch_conflict,
        build_partial_staging,
        build_stale_preparation,
        build_never_recorded,
    ]

    for builder in builders:
        try:
            info = builder(FIXTURES_DIR)
            manifest[info["scenario"]] = info
            print(f"  [ok] {info['scenario']}")
        except Exception as exc:
            print(f"  [FAIL] {builder.__name__}: {exc}", file=sys.stderr)
            raise

    # Write a JSON manifest so the eval runner can locate repos without
    # hard-coding paths.
    manifest_path = FIXTURES_DIR.parent / "fixture_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    main()
