"""Integration tests for the prepare_commit → commit → verify_commit lifecycle.

Covers:
- Full round-trip producing outcome=exact
- Extra staged file after prepare producing outcome=declared_changed
- INDEX_CHANGED guard when the staged index moves between snapshots
"""

from __future__ import annotations

import subprocess
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


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a minimal Git repo with an initial commit."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@commitecho.test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "CommitEcho Test"], cwd=str(repo), capture_output=True)
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPrepareVerifyRoundTrip:
    def test_committed_record_tamper_is_not_exact(self, tmp_path, monkeypatch):
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)
        capture = CaptureService(drafts, git)
        begin = capture.begin_change(title="tamper test", client="test", operation_id=str(uuid.uuid4()))
        result = capture.record_decisions(
            change_id=begin["change_id"], expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{"problem": "p", "choice": "c", "rationale": "r"}],
        )
        (repo / "code.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "code.py"], cwd=repo, check=True, capture_output=True)
        prep = PrepareService(drafts, git).prepare_commit(
            change_id=begin["change_id"], expected_revision=1,
            selected_revision_ids=result["revision_ids"], summary="summary",
            operation_id=str(uuid.uuid4()),
        )
        record_path = repo / prep["record_path"]
        record_path.write_text(record_path.read_text().replace('"summary": "summary"',
                                                             '"summary": "changed"'))
        subprocess.run(["git", "add", prep["record_path"]], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"change\n\n{prep['trailer']}"],
                       cwd=repo, check=True, capture_output=True)
        verification = VerifyService(drafts, index, git).verify_commit(commit_oid=_head(repo))
        assert verification["outcome"] == "declared_changed"

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(repo), str(clone)], check=True, capture_output=True)
        clone_git, clone_drafts, clone_index = _open_services(clone)
        verification = VerifyService(clone_drafts, clone_index, clone_git).verify_commit(
            commit_oid=_head(clone))
        assert verification["outcome"] == "exact"
        assert verification["details"]["local_preparation_verified"] is False
        def fail_read(*_args):
            raise OSError("object read failed")
        monkeypatch.setattr(clone_git, "read_file_from_commit", fail_read)
        assert VerifyService(clone_drafts, clone_index, clone_git).verify_commit(
            commit_oid=_head(clone))["outcome"] == "unverifiable"

    def test_exact_binding(self, tmp_path):
        """prepare_commit followed by a real Git commit produces outcome=exact."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)

        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="test round-trip",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        change_id = begin["change_id"]

        rec = capture.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{
                "problem": "p",
                "choice": "c",
                "rationale": "r",
                "disposition": "selected",
                "code_scope": {"paths": ["src/feature.py"]},
            }],
        )
        rev_id = rec["revision_ids"][0]

        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "feature.py").write_text("def feature(): pass\n")
        subprocess.run(["git", "add", "src/feature.py"], cwd=str(repo), capture_output=True)

        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="Add feature function.",
            operation_id=str(uuid.uuid4()),
        )
        assert prep["trailer"].startswith("CommitEcho-Record:")

        subprocess.run(["git", "add", prep["record_path"]], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: add feature\n\n{prep['trailer']}\n"],
            cwd=str(repo), capture_output=True,
        )
        commit_oid = _head(repo)

        git2, drafts2, index2 = _open_services(repo)
        result = VerifyService(drafts2, index2, git2).verify_commit(commit_oid=commit_oid)

        assert result["outcome"] == "exact", f"Expected exact, got: {result}"
        assert result["record_id"] == prep["record_id"]

    def test_declared_changed_when_extra_file_committed(self, tmp_path):
        """verify_commit returns declared_changed when the commit includes a file
        not present in the staged index when prepare_commit was called."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.verify import VerifyService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)

        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="partial staging test",
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

        # Stage only file_a.py when prepare is called
        (repo / "file_a.py").write_text("a = 1\n")
        subprocess.run(["git", "add", "file_a.py"], cwd=str(repo), capture_output=True)

        prep = prepare.prepare_commit(
            change_id=change_id,
            expected_revision=1,
            selected_revision_ids=[rev_id],
            summary="Add file_a.",
            operation_id=str(uuid.uuid4()),
        )

        # Add file_b.py to the commit after prepare — not in the recorded fingerprint
        (repo / "file_b.py").write_text("b = 2\n")
        subprocess.run(
            ["git", "add", prep["record_path"], "file_b.py"],
            cwd=str(repo), capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"add files\n\n{prep['trailer']}\n"],
            cwd=str(repo), capture_output=True,
        )
        commit_oid = _head(repo)

        git2, drafts2, index2 = _open_services(repo)
        result = VerifyService(drafts2, index2, git2).verify_commit(commit_oid=commit_oid)
        assert result["outcome"] == "declared_changed"


class TestIndexChangedGuard:
    def test_index_changed_raises(self, tmp_path, monkeypatch):
        """If the staged index digest changes between the two prepare snapshots,
        IndexChangedError is raised so the agent retries with fresh staging."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService, IndexChangedError

        repo = _make_repo(tmp_path)
        git, drafts, _ = _open_services(repo)

        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        begin = capture.begin_change(
            title="index guard test",
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

        (repo / "side.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "side.py"], cwd=str(repo), capture_output=True)

        # Patch code_fingerprint to return a different digest on the second call
        call_count = {"n": 0}
        original_fp = git.code_fingerprint

        def alternating_fp():
            call_count["n"] += 1
            digest, manifest = original_fp()
            if call_count["n"] > 1:
                return "0" * 64, manifest
            return digest, manifest

        monkeypatch.setattr(git, "code_fingerprint", alternating_fp)

        with pytest.raises(IndexChangedError):
            prepare.prepare_commit(
                change_id=change_id,
                expected_revision=1,
                selected_revision_ids=[rec["revision_ids"][0]],
                summary="should fail",
                operation_id=str(uuid.uuid4()),
            )
