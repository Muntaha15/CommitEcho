"""Integration tests for operation-ID idempotency and crash recovery.

Verifies that replaying a tool call with the same operation_id and payload
is a safe no-op, and that reusing an operation_id with a different payload
is rejected.
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


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@commitecho.test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "CommitEcho Test"], cwd=str(repo), capture_output=True)
    (repo / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo), capture_output=True)
    return repo


def _open_capture(repo: Path):
    from commitecho.application.capture import CaptureService
    git = GitAdapter.from_path(repo)
    drafts = open_drafts_db(git.repo_info.common_dir)
    return CaptureService(drafts, git)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIdempotentRetry:
    def test_begin_change_replayed_with_same_payload_returns_same_change(self, tmp_path):
        """Replaying begin_change with the same operation_id returns the original change_id."""
        svc = _open_capture(_make_repo(tmp_path))
        op_id = str(uuid.uuid4())
        r1 = svc.begin_change(title="retry test", client="test", operation_id=op_id)
        r2 = svc.begin_change(title="retry test", client="test", operation_id=op_id)
        assert r1["change_id"] == r2["change_id"]

    def test_record_decisions_replayed_returns_same_revision_ids(self, tmp_path):
        """Replaying record_decisions with the same operation_id returns the same revision_ids."""
        svc = _open_capture(_make_repo(tmp_path))
        begin = svc.begin_change(title="retry dec", client="test", operation_id=str(uuid.uuid4()))
        change_id = begin["change_id"]

        op_id = str(uuid.uuid4())
        decisions = [{"problem": "p", "choice": "c", "rationale": "r"}]

        r1 = svc.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=op_id,
            decisions=decisions,
        )
        r2 = svc.record_decisions(
            change_id=change_id,
            expected_revision=0,
            operation_id=op_id,
            decisions=decisions,
        )
        assert r1["revision_ids"] == r2["revision_ids"]

    def test_reusing_operation_id_with_different_payload_raises(self, tmp_path):
        """Reusing an operation_id with a different payload raises ValueError."""
        svc = _open_capture(_make_repo(tmp_path))
        op_id = str(uuid.uuid4())
        svc.begin_change(title="original title", client="test", operation_id=op_id)

        with pytest.raises(ValueError, match="different payload"):
            svc.begin_change(title="different title", client="test", operation_id=op_id)
