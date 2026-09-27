"""Integration tests for operation-ID idempotency and crash recovery.

Verifies that replaying a tool call with the same operation_id and payload
is a safe no-op, and that reusing an operation_id with a different payload
is rejected.
"""

from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path

import pytest

from commitecho.git.adapter import GitAdapter
from commitecho.storage.db import open_drafts_db, open_index_db
from commitecho.application.capture import CaptureService
from commitecho.application.prepare import PrepareService


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
    def test_failed_capture_can_retry_without_partial_rows(self, tmp_path):
        svc = _open_capture(_make_repo(tmp_path))
        change_id = svc.begin_change(title="failure", client="test", operation_id="begin")["change_id"]
        with pytest.raises(KeyError):
            svc.record_decisions(change_id=change_id, expected_revision=0, operation_id="record",
                                 evidence=[{"kind": "test_result", "content": "temporary"}],
                                 decisions=[{"problem": "missing choice"}])
        assert svc._conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
        assert svc._conn.execute("SELECT COUNT(*) FROM operation_log WHERE operation_id='record'").fetchone()[0] == 0
        result = svc.record_decisions(change_id=change_id, expected_revision=0, operation_id="record",
                                      decisions=[{"problem": "p", "choice": "c", "rationale": "r"}])
        assert result["revision_counter"] == 1

    def test_changed_content_and_later_replay(self, tmp_path):
        svc = _open_capture(_make_repo(tmp_path))
        first = svc.begin_change(title="same", client="test", operation_id="begin-1")
        second = svc.begin_change(title="same", client="test", operation_id="begin-2")
        assert svc.begin_change(title="same", client="test", operation_id="begin-1") == first
        assert first["change_id"] != second["change_id"]
        one = [{"problem": "p", "choice": "one", "rationale": "r"}]
        response = svc.record_decisions(change_id=first["change_id"], expected_revision=0,
                                        operation_id="record-1", decisions=one)
        svc.record_decisions(change_id=first["change_id"], expected_revision=1,
                             operation_id="record-2", decisions=one)
        assert svc.record_decisions(change_id=first["change_id"], expected_revision=0,
                                    operation_id="record-1", decisions=one) == response
        with pytest.raises(ValueError, match="different payload"):
            svc.record_decisions(change_id=first["change_id"], expected_revision=0,
                                 operation_id="record-1",
                                 decisions=[{"problem": "p", "choice": "changed", "rationale": "r"}])

    def test_concurrent_expected_revision_one_wins(self, tmp_path):
        repo = _make_repo(tmp_path)
        first, second = _open_capture(repo), _open_capture(repo)
        change_id = first.begin_change(title="race", client="test", operation_id="begin")["change_id"]
        barrier = threading.Barrier(2)
        results = []
        def write(svc, op):
            barrier.wait()
            try:
                results.append(svc.record_decisions(change_id=change_id, expected_revision=0,
                                                     operation_id=op,
                                                     decisions=[{"problem": "p", "choice": op, "rationale": "r"}]))
            except ValueError as exc:
                results.append(str(exc))
        threads = [threading.Thread(target=write, args=(svc, f"race-{i}"))
                   for i, svc in enumerate((first, second))]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert sum(isinstance(value, dict) for value in results) == 1
        assert first._conn.execute("SELECT COUNT(*) FROM decision_revisions").fetchone()[0] == 1

    def test_prepare_replay_restores_missing_file_and_original_response(self, tmp_path):
        repo = _make_repo(tmp_path)
        svc = _open_capture(repo)
        change_id = svc.begin_change(title="prepare", client="test", operation_id="begin")["change_id"]
        revision_id = svc.record_decisions(change_id=change_id, expected_revision=0,
                                           operation_id="record", decisions=[
                                               {"problem": "p", "choice": "c", "rationale": "r"}])["revision_ids"][0]
        prep = PrepareService(svc._conn, svc._git)
        first = prep.prepare_commit(change_id=change_id, expected_revision=1,
                                    selected_revision_ids=[revision_id], summary="first",
                                    operation_id="prepare-1")
        path = repo / first["record_path"]
        original = path.read_bytes()
        path.unlink()
        prep.prepare_commit(change_id=change_id, expected_revision=1,
                            selected_revision_ids=[revision_id], summary="second",
                            operation_id="prepare-2")
        assert prep.prepare_commit(change_id=change_id, expected_revision=1,
                                   selected_revision_ids=[revision_id], summary="first",
                                   operation_id="prepare-1") == first
        assert path.read_bytes() == original
        with pytest.raises(ValueError, match="different payload"):
            prep.prepare_commit(change_id=change_id, expected_revision=1,
                                selected_revision_ids=[revision_id], summary="changed",
                                operation_id="prepare-1")

    def test_prepare_retry_after_file_write_failure(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        svc = _open_capture(repo)
        change_id = svc.begin_change(title="file failure", client="test", operation_id="begin")["change_id"]
        revision_id = svc.record_decisions(change_id=change_id, expected_revision=0,
                                           operation_id="record", decisions=[
                                               {"problem": "p", "choice": "c", "rationale": "r"}])["revision_ids"][0]
        prep = PrepareService(svc._conn, svc._git)
        original = prep._write_record_file
        def fail_once(record):
            monkeypatch.setattr(prep, "_write_record_file", original)
            raise OSError("disk unavailable")
        monkeypatch.setattr(prep, "_write_record_file", fail_once)
        args = dict(change_id=change_id, expected_revision=1,
                    selected_revision_ids=[revision_id], summary="recovery",
                    operation_id="prepare")
        with pytest.raises(OSError, match="disk unavailable"):
            prep.prepare_commit(**args)
        response = prep.prepare_commit(**args)
        assert (repo / response["record_path"]).exists()
        assert svc._conn.execute("SELECT COUNT(*) FROM commit_records").fetchone()[0] == 1
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
