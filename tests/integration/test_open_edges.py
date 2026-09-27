"""Integration tests for M4 open edges.

Covers:
  1. Root commit prepare + verify  (_ROOT_OID path)
  2. Optimistic concurrency conflict in record_decisions (wrong expected_revision)
  3. prepare_commit idempotent replay returns the original record path / id
  4. Multi-record commit (one commit, multiple decisions)
  5. commitecho index CLI entrypoint end-to-end
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from commitecho.git.adapter import GitAdapter
from commitecho.storage.db import open_drafts_db, open_index_db


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


def _make_empty_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Initialise a Git repo with NO initial commit (truly empty / unborn HEAD)."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@commitecho.test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "CommitEcho Test"], cwd=str(repo), capture_output=True)
    return repo


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Initialise a minimal Git repo with one commit."""
    repo = _make_empty_repo(tmp_path, name)
    (repo / "README.md").write_text("# Test repo\n")
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
# Edge 1: Root commit prepare + verify
# ---------------------------------------------------------------------------


class TestRootCommitPrepareVerify:
    """_ROOT_OID = '0'*40 path is exercised against an actual root commit."""

    def test_prepare_and_verify_on_root_commit(self, tmp_path: Path) -> None:
        """prepare_commit → commit → verify_commit on the very first commit in a repo."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        # Empty repo — no commits yet
        repo = _make_empty_repo(tmp_path)
        git, drafts, index = _open_services(repo)

        assert git.head_oid() is None, "Expected unborn HEAD"

        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="root commit change",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]
        # starting_revision is None for unborn HEAD
        assert begin["base_oid"] is None

        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{
                "problem": "initial repository structure",
                "choice": "flat src layout",
                "rationale": "minimal for MVP",
                "disposition": "selected",
                "code_scope": {"paths": ["README.md"]},
            }],
        )
        rev_id = rec["revision_ids"][0]

        # Stage a file — this will be the root commit's entire tree
        (repo / "README.md").write_text("# Root commit project\n")
        _git(["git", "add", "README.md"], repo)

        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="Bootstrap repository",
            operation_id=str(uuid.uuid4()),
        )

        assert prep["trailer"].startswith("CommitEcho-Record:")
        # The parent_oid in the record should be the 40-zero root marker
        record_file = Path(prep["record_path"])
        assert record_file.exists() or (repo / record_file).exists()
        record_json = (repo / prep["record_path"]).read_text(encoding="utf-8")
        record_data = json.loads(record_json)
        assert record_data["prepared_for"]["parent_oid"] == "0" * 40, (
            f"Expected root OID marker, got: {record_data['prepared_for']['parent_oid']}"
        )

        _git(["git", "add", prep["record_path"]], repo)
        _git(["git", "commit", "-m", f"chore: bootstrap\n\n{prep['trailer']}\n"], repo)
        commit_oid = _head(repo)
        assert commit_oid, "Root commit did not produce an OID"

        # verify_commit on root commit
        git2, drafts2, index2 = _open_services(repo)
        result = VerifyService(drafts2, index2, git2).verify_commit(commit_oid=commit_oid)
        assert result["outcome"] == "exact", (
            f"Root commit verify_commit expected 'exact', got: {result}"
        )
        assert result["record_id"] == prep["record_id"]


# ---------------------------------------------------------------------------
# Edge 2: Optimistic concurrency conflict in record_decisions
# ---------------------------------------------------------------------------


class TestOptimisticConcurrencyConflict:
    """record_decisions with wrong expected_revision raises ValueError."""

    def test_wrong_revision_raises(self, tmp_path: Path) -> None:
        from commitecho.application.capture import CaptureService

        repo = _make_repo(tmp_path)
        git, drafts, _ = _open_services(repo)
        capture = CaptureService(drafts, git)

        begin = capture.begin_change(
            title="conflict test",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]

        # First record_decisions advances counter to 1
        capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{"problem": "p1", "choice": "c1", "rationale": "r1"}],
        )

        # Attempt with stale expected_revision=0 (counter is now 1)
        with pytest.raises(ValueError, match="Optimistic conflict"):
            capture.record_decisions(
                change_id=change_id,
                expected_revision=0,          # stale — should be 1
                operation_id=str(uuid.uuid4()),  # new operation_id so not idempotent
                decisions=[{"problem": "p2", "choice": "c2", "rationale": "r2"}],
            )

    def test_correct_revision_succeeds_after_first(self, tmp_path: Path) -> None:
        """Consecutive record_decisions with correct expected_revision both succeed."""
        from commitecho.application.capture import CaptureService

        repo = _make_repo(tmp_path)
        git, drafts, _ = _open_services(repo)
        capture = CaptureService(drafts, git)

        begin = capture.begin_change(
            title="sequential decisions",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]

        r1 = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{"problem": "p1", "choice": "c1", "rationale": "r1"}],
        )
        assert r1["revision_counter"] == 1

        r2 = capture.record_decisions(
            change_id=change_id,
            expected_revision=1,
            operation_id=str(uuid.uuid4()),
            decisions=[{"problem": "p2", "choice": "c2", "rationale": "r2"}],
        )
        assert r2["revision_counter"] == 2
        assert len(r2["revision_ids"]) == 1


# ---------------------------------------------------------------------------
# Edge 3: prepare_commit idempotent replay returns original record path
# ---------------------------------------------------------------------------


class TestPrepareCommitIdempotentReplay:
    """Replaying prepare_commit with the same operation_id returns the original record_id."""

    def test_replay_returns_original_record_id(self, tmp_path: Path) -> None:
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService

        repo = _make_repo(tmp_path)
        git, drafts, _ = _open_services(repo)
        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="idempotent prepare",
            client="test",
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

        (repo / "main.py").write_text("x = 1\n")
        _git(["git", "add", "main.py"], repo)

        op_id = str(uuid.uuid4())

        prep1 = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="First prepare",
            operation_id=op_id,
        )
        original_record_id = prep1["record_id"]
        original_record_path = prep1["record_path"]

        # Replay with same operation_id
        prep2 = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="First prepare",
            operation_id=op_id,  # same op_id!
        )

        assert prep2["record_id"] == original_record_id, (
            f"Idempotent replay returned a different record_id: "
            f"{prep2['record_id']} != {original_record_id}"
        )
        assert prep2["record_path"] == original_record_path, (
            f"Idempotent replay returned a different record_path: "
            f"{prep2['record_path']} != {original_record_path}"
        )
        assert prep2["trailer"] == prep1["trailer"], (
            "Idempotent replay returned a different trailer"
        )


# ---------------------------------------------------------------------------
# Edge 4: Multi-record commit (one commit, multiple decisions)
# ---------------------------------------------------------------------------


class TestMultiDecisionCommit:
    """One commit can carry multiple decision revisions in one CommitRecord."""

    def test_multi_decision_prepare_and_verify(self, tmp_path: Path) -> None:
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)
        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="multi-decision change",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]

        # Record THREE distinct decisions in one call
        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[
                {
                    "problem": "serialization format",
                    "choice": "JSON over MessagePack",
                    "rationale": "human-readable; easier to debug",
                    "disposition": "selected",
                    "code_scope": {"paths": ["src/serializer.py"]},
                },
                {
                    "problem": "transport protocol",
                    "choice": "HTTP/2 over HTTP/1.1",
                    "rationale": "multiplexing reduces connection overhead",
                    "disposition": "selected",
                    "code_scope": {"paths": ["src/transport.py"]},
                },
                {
                    "problem": "authentication scheme",
                    "choice": "JWT bearer token",
                    "rationale": "stateless; compatible with microservice topology",
                    "disposition": "selected",
                    "code_scope": {"paths": ["src/auth.py"]},
                },
            ],
        )
        assert len(rec["revision_ids"]) == 3, "Expected 3 revision IDs"

        # Stage files for all three paths
        src = repo / "src"
        src.mkdir(exist_ok=True)
        (src / "serializer.py").write_text("FORMAT = 'json'\n")
        (src / "transport.py").write_text("PROTOCOL = 'http2'\n")
        (src / "auth.py").write_text("SCHEME = 'jwt'\n")
        _git(["git", "add", "src/"], repo)

        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=rec["revision_ids"],  # all three
            summary="Set serialization, transport, and auth choices",
            operation_id=str(uuid.uuid4()),
        )
        assert prep["trailer"].startswith("CommitEcho-Record:")

        # Verify the record file contains all 3 decisions
        record_json = (repo / prep["record_path"]).read_text(encoding="utf-8")
        record_data = json.loads(record_json)
        assert len(record_data["decisions"]) == 3, (
            f"CommitRecord should contain 3 decisions, got {len(record_data['decisions'])}"
        )
        problems = {d["problem"] for d in record_data["decisions"]}
        assert "serialization format" in problems
        assert "transport protocol" in problems
        assert "authentication scheme" in problems

        _git(["git", "add", prep["record_path"]], repo)
        _git(["git", "commit", "-m", f"feat: multi-decision commit\n\n{prep['trailer']}\n"], repo)
        commit_oid = _head(repo)

        git2, drafts2, index2 = _open_services(repo)
        result = VerifyService(drafts2, index2, git2).verify_commit(commit_oid=commit_oid)
        assert result["outcome"] == "exact", f"Multi-decision commit: {result}"
        assert result["record_id"] == prep["record_id"]


# ---------------------------------------------------------------------------
# Edge 5: commitecho index CLI entrypoint end-to-end
# ---------------------------------------------------------------------------


class TestIndexCLIEntrypoint:
    """The `commitecho index` CLI command is tested end-to-end against a real repo."""

    def _setup_committed_repo(self, tmp_path: Path):
        """Helper: build a repo with one committed CommitEcho record."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)
        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="cli index test",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]
        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{
                "problem": "logging strategy",
                "choice": "structured JSON logs",
                "rationale": "machine-parseable for log aggregation",
                "disposition": "selected",
                "code_scope": {"paths": ["src/logger.py"]},
            }],
        )
        rev_id = rec["revision_ids"][0]
        src = repo / "src"
        src.mkdir(exist_ok=True)
        (src / "logger.py").write_text("LOG_FORMAT = 'json'\n")
        _git(["git", "add", "src/logger.py"], repo)

        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="Use structured JSON logging",
            operation_id=str(uuid.uuid4()),
        )
        _git(["git", "add", prep["record_path"]], repo)
        _git(
            ["git", "commit", "-m", f"feat: json logging\n\n{prep['trailer']}\n"],
            repo,
        )
        return repo, prep["record_id"]

    def test_index_command_populates_index_db(self, tmp_path: Path) -> None:
        """Running `commitecho index` from the CLI indexes the committed record."""
        repo, record_id = self._setup_committed_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "commitecho", "index", "--repo", str(repo)],
            capture_output=True,
            text=True,
            cwd=str(repo),
        )
        assert result.returncode == 0, (
            f"commitecho index failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

        # The index DB should now contain the record
        git, drafts, index = _open_services(repo)
        row = index.execute(
            "SELECT record_id FROM indexed_records WHERE record_id = ?", (record_id,)
        ).fetchone()
        assert row is not None, (
            f"Record {record_id!r} not found in index DB after `commitecho index`"
        )

    def test_index_command_enables_search_history(self, tmp_path: Path) -> None:
        """After `commitecho index`, search_history returns the committed decision."""
        from commitecho.application.retrieve import RetrieveService

        repo, record_id = self._setup_committed_repo(tmp_path)

        subprocess.run(
            [sys.executable, "-m", "commitecho", "index", "--repo", str(repo)],
            capture_output=True, text=True, cwd=str(repo), check=True,
        )

        git, drafts, index = _open_services(repo)
        retrieve = RetrieveService(drafts, index, git)
        response = retrieve.search_history(question="logging strategy", page_size=5)
        results = response.get("results", [])
        assert len(results) > 0, "search_history returned nothing after commitecho index"
        choices = [r["choice"] for r in results]
        assert any("json" in c.lower() for c in choices), (
            f"Expected JSON logging decision, got: {choices}"
        )
        by_path = retrieve.search_history(path="src/logger.py")
        assert any(r["record_id"] == record_id for r in by_path["results"])
        earlier = git.resolve("HEAD^")
        compared = retrieve.compare_history(from_ref=earlier, to_ref="HEAD", path="src/logger.py")
        assert any(d["record_id"] == record_id for d in compared["decisions"])

    def test_index_and_compare_use_configured_git(self, tmp_path: Path, monkeypatch) -> None:
        import shutil
        from click.testing import CliRunner
        from commitecho.application.retrieve import RetrieveService
        from commitecho.transports.cli import main

        repo, record_id = self._setup_committed_repo(tmp_path)
        git_exe = shutil.which("git")
        assert git_exe
        empty_path = tmp_path / "empty-path"
        empty_path.mkdir()
        monkeypatch.setenv("COMMITECHO_GIT", git_exe)
        monkeypatch.setenv("PATH", str(empty_path))

        result = CliRunner().invoke(main, ["index", "--repo", str(repo)])
        assert result.exit_code == 0, result.output
        git, drafts, index = _open_services(repo)
        assert index.execute("SELECT 1 FROM indexed_records WHERE record_id = ?", (record_id,)).fetchone()
        compared = RetrieveService(drafts, index, git).compare_history(
            from_ref=git.resolve("HEAD^"), to_ref="HEAD"
        )
        assert compared["is_ancestor"] is True
        assert any(d["record_id"] == record_id for d in compared["decisions"])

    def test_failed_insert_retries_entire_commit(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from commitecho.transports.cli import main

        repo, record_id = self._setup_committed_repo(tmp_path)
        git, _, index = _open_services(repo)
        head = git.head_oid()
        index.execute("CREATE TRIGGER fail_decision BEFORE INSERT ON indexed_decisions "
                      "BEGIN SELECT RAISE(ABORT, 'interrupted insert'); END")
        index.commit()

        first = CliRunner().invoke(main, ["index", "--repo", str(repo)])
        assert first.exit_code == 0
        assert index.execute("SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (head,)).fetchone() is None
        assert index.execute("SELECT 1 FROM indexed_records WHERE record_id = ?", (record_id,)).fetchone() is None
        assert "interrupted insert" in index.execute(
            "SELECT error FROM index_diagnostics WHERE commit_oid = ?", (head,)
        ).fetchone()["error"]

        index.execute("DROP TRIGGER fail_decision")
        index.commit()
        retry = CliRunner().invoke(main, ["index", "--repo", str(repo)])
        assert retry.exit_code == 0
        assert index.execute("SELECT 1 FROM indexed_records WHERE record_id = ?", (record_id,)).fetchone()
        assert index.execute("SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (head,)).fetchone()
        assert index.execute("SELECT 1 FROM index_diagnostics WHERE commit_oid = ?", (head,)).fetchone() is None

    def test_old_index_is_rebuilt_with_paths(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from commitecho.transports.cli import main

        repo, record_id = self._setup_committed_repo(tmp_path)
        git, _, index = _open_services(repo)
        assert CliRunner().invoke(main, ["index", "--repo", str(repo)]).exit_code == 0
        index.execute("DELETE FROM indexed_paths")
        index.execute("UPDATE schema_meta SET value = '2' WHERE key = 'version'")
        index.commit()
        index.close()

        migrated = open_index_db(git.repo_info.common_dir)
        assert migrated.execute("SELECT count(*) FROM indexed_commits").fetchone()[0] == 0
        assert CliRunner().invoke(main, ["index", "--repo", str(repo)]).exit_code == 0
        assert migrated.execute(
            "SELECT 1 FROM indexed_paths p JOIN indexed_decisions d ON d.revision_id = p.revision_id "
            "WHERE d.record_id = ? AND p.path = ?", (record_id, "src/logger.py")
        ).fetchone()

    @pytest.mark.parametrize("fault", ["schema", "identity", "json", "missing"])
    def test_invalid_record_remains_unindexed_with_diagnostic(self, tmp_path: Path, fault: str) -> None:
        from click.testing import CliRunner
        from commitecho.transports.cli import main

        repo, record_id = self._setup_committed_repo(tmp_path)
        path = repo / ".commitecho" / "records" / f"{record_id}.json"
        if fault == "missing":
            record_id = str(uuid.uuid4())
            (repo / "marker.txt").write_text("missing record\n")
            _git(["git", "add", "marker.txt"], repo)
        else:
            data = json.loads(path.read_text())
            if fault == "schema":
                data["schema_version"] = 99
            elif fault == "identity":
                data["record_id"] = str(uuid.uuid4())
            path.write_text("{" if fault == "json" else json.dumps(data))
            _git(["git", "add", str(path)], repo)
        _git(["git", "commit", "-m", f"invalid record\n\nCommitEcho-Record: {record_id}\n"], repo)
        git, _, index = _open_services(repo)
        head = git.head_oid()

        result = CliRunner().invoke(main, ["index", "--repo", str(repo)])
        assert result.exit_code == 0
        assert index.execute("SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (head,)).fetchone() is None
        diagnostic = index.execute(
            "SELECT error FROM index_diagnostics WHERE commit_oid = ?", (head,)
        ).fetchone()["error"]
        assert diagnostic
        retry = CliRunner().invoke(main, ["index", "--repo", str(repo)])
        assert retry.exit_code == 0
        assert diagnostic in retry.output
        assert index.execute("SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (head,)).fetchone() is None
