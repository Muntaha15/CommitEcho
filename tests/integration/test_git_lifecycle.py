"""Integration test scaffold – Git lifecycle and MCP contract checks.

These tests require a real Git executable and create temporary repositories.
They are tagged with pytest markers and are skipped if Git is not available.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from commitecho.git.adapter import GitAdapter, GitError, discover_repository


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="Git executable not available")


@pytest.fixture
def git_repo(tmp_path: Path):
    """Create a minimal Git repository with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
    # Create initial commit
    (repo / "README.md").write_text("# Test repo")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo), capture_output=True)
    return repo


class TestDiscoverRepository:
    def test_discovers_repo(self, git_repo):
        info = discover_repository(git_repo)
        assert Path(info.worktree_dir).resolve() == git_repo.resolve()
        assert Path(info.common_dir).exists()

    def test_fails_outside_repo(self, tmp_path):
        with pytest.raises(GitError):
            discover_repository(tmp_path / "not_a_repo")


class TestGitAdapterIntegration:
    def test_head_oid(self, git_repo):
        git = GitAdapter.from_path(git_repo)
        oid = git.head_oid()
        assert oid is not None
        assert len(oid) == 40

    def test_staged_changes_empty(self, git_repo):
        git = GitAdapter.from_path(git_repo)
        staged = git.staged_changes()
        assert staged == []

    def test_staged_changes_after_add(self, git_repo):
        (git_repo / "new_file.py").write_text("print('hello')")
        subprocess.run(["git", "add", "new_file.py"], cwd=str(git_repo))
        git = GitAdapter.from_path(git_repo)
        staged = git.staged_changes()
        paths = [e.path for e in staged]
        assert "new_file.py" in paths

    def test_code_fingerprint(self, git_repo):
        (git_repo / "src.py").write_text("x = 1")
        subprocess.run(["git", "add", "src.py"], cwd=str(git_repo))
        git = GitAdapter.from_path(git_repo)
        digest, manifest = git.code_fingerprint()
        assert len(digest) == 64
        assert manifest["manifest_version"] == 1


class TestCaptureServiceIntegration:
    def test_begin_change_and_record(self, git_repo):
        import uuid
        import sqlite3
        from commitecho.storage.db import open_drafts_db
        from commitecho.application.capture import CaptureService

        git = GitAdapter.from_path(git_repo)
        conn = open_drafts_db(git.repo_info.common_dir)

        svc = CaptureService(conn, git)
        result = svc.begin_change(
            title="test change",
            client="test",
            operation_id=str(uuid.uuid4()),
        )
        assert "change_id" in result
        assert "session_id" in result

        change_id = result["change_id"]
        rev_result = svc.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[
                {
                    "problem": "duplicate uploads on retry",
                    "choice": "content hash deduplication",
                    "rationale": "same content should produce one job",
                    "disposition": "selected",
                    "alternatives": [
                        {
                            "choice": "filename deduplication",
                            "disposition": "rejected",
                            "reason": "renames bypass it",
                        }
                    ],
                    "code_scope": {"paths": ["src/uploads.py"]},
                }
            ],
            evidence=[
                {
                    "kind": "discussion_summary",
                    "origin": "agent_reported",
                    "content": "We discussed renamed retries.",
                }
            ],
        )
        assert len(rev_result["revision_ids"]) == 1
        assert rev_result["revision_counter"] == 1
