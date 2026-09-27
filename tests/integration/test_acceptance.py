"""End-to-end integration acceptance tests.

Each test works through the 7-step acceptance scenario from docs/integrations.md
§Integration acceptance scenario.  The three "client" variants (codex, antigravity,
copilot_vscode) share the same underlying service layer; what varies is which
client_id token is passed to begin_change and which profile is used for setup.

Steps:
  1. Discuss two approaches and select one (captured as decisions with dispositions).
  2. Make a code change and stage only part of it.
  3. Capture chosen + rejected approaches, prepare memory, commit, and verify.
  4. Start a new conversation: search history to answer why committed lines changed.
  5. Change the index after preparation — verify outcome is not exact.
  6. Restart the client: recover a pending change.
  7. Clone into a fresh directory, rebuild the index, and recall from the clone.

The tests do not connect to any real client process.  They exercise the service layer
directly, which is the shared component that any correctly-configured client calls.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from commitecho.git.adapter import GitAdapter
from commitecho.storage.db import open_drafts_db, open_index_db


# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="Git executable not available")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Initialise a minimal Git repo with one commit."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@commitecho.test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "CommitEcho Test"], cwd=str(repo), capture_output=True)
    (repo / "README.md").write_text("# Acceptance test repo\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo), capture_output=True)
    return repo


def _open_services(repo: Path):
    git = GitAdapter.from_path(repo)
    drafts = open_drafts_db(git.repo_info.common_dir)
    index = open_index_db(git.repo_info.common_dir)
    return git, drafts, index


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(repo)
    ).stdout.strip()


def _git(args: list[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(repo), capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Full 7-step acceptance scenario (parameterised over client_id token)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_id", ["codex", "antigravity", "copilot_vscode"])
class TestAcceptanceScenario:
    """7-step acceptance scenario executed for each of the three supported clients."""

    # ------------------------------------------------------------------
    # Steps 1-3: capture, prepare, commit, verify
    # ------------------------------------------------------------------

    def test_steps_1_to_3_capture_prepare_commit_verify(self, tmp_path: Path, client_id: str) -> None:
        """Steps 1-3: discuss approaches, stage part of a change, capture, prepare, commit, verify."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)
        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        # Step 1: begin a change representing a task; capture two approaches.
        begin = capture.begin_change(
            title="fix duplicate requests",
            client=client_id,
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]
        assert begin["revision_counter"] == 0

        # Record: one selected approach + one rejected alternative.
        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[
                {
                    "problem": "duplicate HTTP requests sent on rapid user input",
                    "choice": "debounce at 300ms on the input handler",
                    "rationale": "meets the <500ms constraint; simpler than request cancellation",
                    "disposition": "selected",
                    "code_scope": {"paths": ["src/api_client.py"]},
                },
                {
                    "problem": "duplicate HTTP requests sent on rapid user input",
                    "choice": "cancel in-flight requests via AbortController",
                    "rationale": "rejected: adds browser-compat complexity beyond stated constraint",
                    "disposition": "rejected",
                    "code_scope": {"paths": ["src/api_client.py"]},
                },
            ],
        )
        assert len(rec["revision_ids"]) == 2
        selected_rev_id = rec["revision_ids"][0]

        # Step 2: write the fix and stage ONLY the target file (partial staging).
        src = repo / "src"
        src.mkdir(exist_ok=True)
        (src / "api_client.py").write_text("import time\nDEBOUNCE_MS = 300\n")
        (src / "utils.py").write_text("# unstaged helper\n")
        _git(["git", "add", "src/api_client.py"], repo)

        # Step 3a: prepare commit record.
        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[selected_rev_id],
            summary="Debounce input handler to fix duplicate requests.",
            operation_id=str(uuid.uuid4()),
        )
        assert prep["trailer"].startswith("CommitEcho-Record:")
        record_path = prep["record_path"]

        # Step 3b: stage the record file and commit.
        _git(["git", "add", record_path], repo)
        _git(["git", "commit", "-m", f"fix: debounce input\n\n{prep['trailer']}\n"], repo)
        commit_oid = _head(repo)

        # Step 3c: verify the commit.
        git2, drafts2, index2 = _open_services(repo)
        result = VerifyService(drafts2, index2, git2).verify_commit(commit_oid=commit_oid)
        assert result["outcome"] == "exact", f"verify_commit outcome: {result}"
        assert result["record_id"] == prep["record_id"]

    # ------------------------------------------------------------------
    # Step 4: new conversation — recall why lines changed
    # ------------------------------------------------------------------

    def _setup_committed_change(self, tmp_path: Path, client_id: str):
        """Helper: run steps 1-3 and return (repo, commit_oid, record_id)."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)
        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="fix duplicate requests",
            client=client_id,
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]
        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{
                "problem": "duplicate requests",
                "choice": "debounce",
                "rationale": "meets constraint",
                "disposition": "selected",
                "code_scope": {"paths": ["src/api_client.py"]},
            }],
        )
        rev_id = rec["revision_ids"][0]
        src = repo / "src"
        src.mkdir(exist_ok=True)
        (src / "api_client.py").write_text("DEBOUNCE_MS = 300\n")
        _git(["git", "add", "src/api_client.py"], repo)
        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="Debounce to fix duplicates.",
            operation_id=str(uuid.uuid4()),
        )
        _git(["git", "add", prep["record_path"]], repo)
        _git(["git", "commit", "-m", f"fix: debounce\n\n{prep['trailer']}\n"], repo)
        return repo, _head(repo), prep["record_id"]

    def test_step_4_recall_from_search_history(self, tmp_path: Path, client_id: str) -> None:
        """Step 4: in a new conversation, search_history returns the committed decision."""
        from commitecho.application.retrieve import RetrieveService
        from commitecho.transports.cli import _index_record
        import json

        repo, commit_oid, record_id = self._setup_committed_change(tmp_path, client_id)
        git, drafts, index = _open_services(repo)

        # Rebuild index (simulates a fresh session or fresh index).
        record_path = f".commitecho/records/{record_id}.json"
        raw = subprocess.run(
            ["git", "show", f"{commit_oid}:{record_path}"],
            capture_output=True, text=True, cwd=str(repo),
        ).stdout
        assert raw, "Record blob not found in commit tree"
        record_data = json.loads(raw)
        # Mark the commit as indexed.
        index.execute(
            "INSERT OR IGNORE INTO indexed_commits (commit_oid, repository_id, parent_oid, indexed_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (commit_oid, git.repo_info.common_dir, None),
        )
        _index_record(index, commit_oid, record_id, record_path, record_data, raw)

        retrieve = RetrieveService(drafts, index, git)
        response = retrieve.search_history(question="duplicate requests", page_size=10)
        results = response["results"]
        assert len(results) > 0, "search_history returned no results"
        problems = [r["problem"] for r in results]
        assert any("duplicate" in p.lower() for p in problems), (
            f"Expected duplicate-related result, got: {problems}"
        )

    # ------------------------------------------------------------------
    # Step 5: mutate index after prepare — verify is not exact
    # ------------------------------------------------------------------

    def test_step_5_post_prepare_mutation_not_exact(self, tmp_path: Path, client_id: str) -> None:
        """Step 5: adding a file after prepare produces declared_changed, not exact."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)
        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="step-5 test",
            client=client_id,
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]
        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{"problem": "p", "choice": "c", "rationale": "r"}],
        )
        rev_id = rec["revision_ids"][0]

        (repo / "main.py").write_text("print('hello')\n")
        _git(["git", "add", "main.py"], repo)

        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="Initial main.",
            operation_id=str(uuid.uuid4()),
        )

        # After prepare: add an extra file to the commit (not in snapshot).
        (repo / "extra.py").write_text("x = 1\n")
        _git(["git", "add", prep["record_path"], "extra.py"], repo)
        _git(["git", "commit", "-m", f"add files\n\n{prep['trailer']}\n"], repo)
        commit_oid = _head(repo)

        git2, drafts2, index2 = _open_services(repo)
        result = VerifyService(drafts2, index2, git2).verify_commit(commit_oid=commit_oid)
        assert result["outcome"] != "exact", (
            f"Expected non-exact outcome when extra file added post-prepare, got: {result['outcome']}"
        )

    # ------------------------------------------------------------------
    # Step 6: pending change recovery after "restart"
    # ------------------------------------------------------------------

    def test_step_6_pending_change_survives_new_db_connection(
        self, tmp_path: Path, client_id: str
    ) -> None:
        """Step 6: an open draft change is still retrievable after re-opening the databases."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.retrieve import RetrieveService

        repo = _make_repo(tmp_path)
        git, drafts, _ = _open_services(repo)
        capture = CaptureService(drafts, git)

        begin = capture.begin_change(
            title="pending work on restart",
            client=client_id,
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]
        capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{"problem": "needs fix", "choice": "approach A", "rationale": "fast"}],
        )

        # Simulate restart: open fresh database connections.
        git2, drafts2, index2 = _open_services(repo)
        retrieve = RetrieveService(drafts2, index2, git2)
        status = retrieve.get_status(change_id=change_id)

        open_ids = {c["change_id"] for c in status["open_changes"]}
        assert change_id in open_ids, (
            f"Pending change {change_id!r} not found after simulated restart. "
            f"Open changes: {status['open_changes']}"
        )

    # ------------------------------------------------------------------
    # Step 7: clone, rebuild index, recall from the clone
    # ------------------------------------------------------------------

    def test_step_7_clone_rebuild_and_recall(self, tmp_path: Path, client_id: str) -> None:
        """Step 7: clone the repo, rebuild the index, and recall committed decisions."""
        from commitecho.application.retrieve import RetrieveService
        from commitecho.transports.cli import _index_record
        import json

        repo, commit_oid, record_id = self._setup_committed_change(tmp_path, client_id)

        # Clone into a fresh directory.
        clone = tmp_path / "clone"
        result = subprocess.run(
            ["git", "clone", str(repo), str(clone)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"git clone failed: {result.stderr}"

        git_clone, drafts_clone, index_clone = _open_services(clone)

        # Rebuild the index in the clone (mirrors `commitecho index`).
        record_path = f".commitecho/records/{record_id}.json"
        head_in_clone = _head(clone)
        raw = subprocess.run(
            ["git", "show", f"{head_in_clone}:{record_path}"],
            capture_output=True, text=True, cwd=str(clone),
        ).stdout
        assert raw, "Record blob not found in clone"
        record_data = json.loads(raw)
        index_clone.execute(
            "INSERT OR IGNORE INTO indexed_commits (commit_oid, repository_id, parent_oid, indexed_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (head_in_clone, git_clone.repo_info.common_dir, None),
        )
        _index_record(index_clone, head_in_clone, record_id, record_path, record_data, raw)

        # Recall — different client_id, same decision should be found.
        retrieve = RetrieveService(drafts_clone, index_clone, git_clone)
        response = retrieve.search_history(question="duplicate requests", page_size=10)
        results = response["results"]
        assert len(results) > 0, "Recall from clone returned no results"
        problems = [r["problem"] for r in results]
        assert any("duplicate" in p.lower() for p in problems), (
            f"Expected to recall duplicate-requests decision from clone, got: {problems}"
        )
