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


def test_status_checks_all_reachable_commits_and_diagnostics(tmp_path):
    from datetime import datetime, timezone
    from commitecho.application.retrieve import RetrieveService

    repo = _make_repo(tmp_path)
    parent = _head(repo)
    (repo / "next.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "next.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "next"], cwd=repo, check=True, capture_output=True)
    head = _head(repo)
    git, drafts, index = _open_services(repo)
    now = datetime.now(timezone.utc).isoformat()
    index.execute(
        "INSERT INTO indexed_commits VALUES (?, ?, ?, ?, ?, ?)",
        (head, "repo", parent, now, now, now),
    )
    index.execute(
        "INSERT INTO index_diagnostics VALUES (?, ?, ?, ?)",
        (parent, ".commitecho/records/bad.json", "invalid record", now),
    )
    index.commit()

    result = RetrieveService(drafts, index, git).get_status()
    assert result["head_indexed"] is True
    assert result["coverage"] == "partial"
    assert any("1 reachable commit" in note for note in result["coverage_notes"])
    assert result["index_diagnostics"][0]["commit_oid"] == parent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_change_completion_and_multi_commit(tmp_path):
    from commitecho.application.capture import CaptureService
    from commitecho.application.prepare import PrepareService
    from commitecho.application.retrieve import RetrieveService
    from commitecho.application.verify import VerifyService

    repo = _make_repo(tmp_path)
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(title="two commits", client="test", operation_id="begin")["change_id"]
    revisions = capture.record_decisions(
        change_id=change_id, expected_revision=0, operation_id="decisions",
        decisions=[{"problem": name, "choice": "do it", "rationale": "needed"}
                   for name in ("first", "second")],
    )["revision_ids"]
    prepare = PrepareService(drafts, git)
    verify = VerifyService(drafts, index, git)
    first_oid = None

    for number, keep_open in ((1, False), (2, False)):
        path = f"code{number}.py"
        (repo / path).write_text(f"value = {number}\n")
        subprocess.run(["git", "add", path], cwd=repo, capture_output=True, check=True)
        prepared = prepare.prepare_commit(
            change_id=change_id, expected_revision=1,
            selected_revision_ids=[revisions[number - 1]], summary=f"commit {number}",
            operation_id=f"prepare-{number}",
        )
        assert prepared["omitted_revision_ids"] == ([revisions[1]] if number == 1 else [])
        if first_oid:
            assert verify.verify_commit(commit_oid=first_oid)["outcome"] == "exact"
            assert drafts.execute("SELECT status FROM changes WHERE change_id = ?", (change_id,)).fetchone()[0] == "prepared"
        subprocess.run(["git", "add", prepared["record_path"]], cwd=repo,
                       capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", f"commit {number}\n\n{prepared['trailer']}"],
                       cwd=repo, capture_output=True, check=True)
        assert verify.verify_commit(commit_oid=_head(repo), keep_open=keep_open)["outcome"] == "exact"
        if number == 1:
            first_oid = _head(repo)
        expected = "open" if number == 1 else "committed"
        assert drafts.execute("SELECT status FROM changes WHERE change_id = ?", (change_id,)).fetchone()[0] == expected

    abandoned_id = capture.begin_change(title="abandoned", client="test", operation_id="abandoned")["change_id"]
    drafts.execute("UPDATE changes SET status = 'abandoned' WHERE change_id = ?", (abandoned_id,))
    drafts.commit()
    status = RetrieveService(drafts, index, git).get_status()
    assert status["open_changes"] == []
    assert [c["change_id"] for c in status["abandoned_changes"]] == [abandoned_id]


def test_restart_recovers_decisions_and_partial_commit_keeps_change_open(tmp_path):
    from commitecho.application.capture import CaptureService
    from commitecho.application.prepare import PrepareService
    from commitecho.application.retrieve import RetrieveService
    from commitecho.application.verify import VerifyService

    repo = _make_repo(tmp_path, "repository with spaces")
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    begin = capture.begin_change(title="resume", client="claude_code", operation_id="begin")
    change_id = begin["change_id"]
    evidence_id = str(uuid.uuid4())
    first = capture.record_decisions(
        change_id=change_id, expected_revision=0, operation_id="first",
        decisions=[{"problem": "deduplicate", "choice": "dictionary", "rationale": "preserve order",
                    "disposition": "selected", "code_scope": {"paths": ["code.py"]},
                    "alternatives": [{"choice": "set", "reason": "loses order",
                                      "evidence_ids": [evidence_id]}]}],
        evidence=[{"evidence_id": evidence_id, "kind": "test_result", "client": "claude_code",
                   "origin": "agent_reported", "content": "order preserved"}],
    )["revision_ids"][0]
    drafts.close()
    index.close()

    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    resumed = capture.begin_change(title="resume", client="codex", operation_id="resume",
                                   prior_change_id=change_id)
    assert resumed["revision_counter"] == 1
    assert resumed["unpublished_revision_ids"] == [first]
    assert resumed["decision_revisions"][0]["alternatives"][0]["reason"] == "loses order"
    assert resumed["decision_revisions"][0]["alternatives"][0]["evidence_ids"] == [evidence_id]
    assert capture.begin_change(title="resume", client="claude_code", operation_id="begin") == begin
    second = capture.record_decisions(
        change_id=change_id, expected_revision=1, operation_id="second",
        decisions=[{"problem": "types", "choice": "raise TypeError", "rationale": "explicit error",
                    "disposition": "selected", "code_scope": {"paths": ["code.py"]}}],
    )["revision_ids"][0]
    (repo / "code.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "code.py"], cwd=repo, capture_output=True, check=True)
    prepare = PrepareService(drafts, git)
    partial = prepare.prepare_commit(change_id=change_id, expected_revision=2,
        selected_revision_ids=[second], summary="types", operation_id="partial")
    assert partial["uncovered_paths"] == []
    assert partial["omitted_revision_ids"] == [first]
    subprocess.run(["git", "add", partial["record_path"]], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"types\n\n{partial['trailer']}"],
                   cwd=repo, capture_output=True, check=True)
    verified = VerifyService(drafts, index, git).verify_commit(commit_oid=_head(repo))
    assert verified["outcome"] == "exact"
    assert verified["details"]["change_status"] == "open"
    assert verified["details"]["remaining_revision_ids"] == [first]
    scoped = RetrieveService(drafts, index, git).get_status(change_id)["open_changes"][0]
    assert scoped["revision_counter"] == 2
    assert scoped["unpublished_revision_ids"] == [first]
    assert {r["revision_id"] for r in scoped["decision_revisions"]} == {first, second}

    other = tmp_path / "linked worktree"
    subprocess.run(["git", "worktree", "add", "-b", "other", str(other)],
                   cwd=repo, capture_output=True, check=True)
    other_git, other_drafts, other_index = _open_services(other)
    assert RetrieveService(other_drafts, other_index, other_git).get_status(change_id)["open_changes"] == []

    # An indexed history rebuild must not treat prior exact bindings as uncommitted.
    from click.testing import CliRunner
    from commitecho.transports.cli import main
    assert CliRunner().invoke(main, ["index", "--repo", str(repo)]).exit_code == 0
    complete = prepare.prepare_commit(change_id=change_id, expected_revision=2,
        selected_revision_ids=[first], summary="ordering", operation_id="complete")
    assert complete["omitted_revision_ids"] == []
    subprocess.run(["git", "add", complete["record_path"]], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"ordering\n\n{complete['trailer']}"],
                   cwd=repo, capture_output=True, check=True)
    verified = VerifyService(drafts, index, git).verify_commit(commit_oid=_head(repo))
    assert verified["details"]["change_status"] == "committed"
    assert verified["details"]["remaining_revision_ids"] == []


def test_late_and_superseding_revisions_remain_recoverable_after_verification(tmp_path):
    from commitecho.application.capture import CaptureService
    from commitecho.application.prepare import PrepareService
    from commitecho.application.retrieve import RetrieveService
    from commitecho.application.verify import VerifyService

    repo = _make_repo(tmp_path)
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(title="revisions", client="test", operation_id="begin")["change_id"]
    first = capture.record_decisions(change_id=change_id, expected_revision=0, operation_id="first",
        decisions=[{"problem": "p", "choice": "old", "rationale": "r"}])["revision_ids"][0]
    prepare = PrepareService(drafts, git)
    original = prepare.prepare_commit(change_id=change_id, expected_revision=1,
        selected_revision_ids=[first], summary="original", operation_id="original")
    late = capture.record_decisions(change_id=change_id, expected_revision=1, operation_id="late",
        decisions=[{"predecessor_revision_ids": [first], "problem": "p", "choice": "new", "rationale": "revised"},
                   {"problem": "another", "choice": "late", "rationale": "r"}])["revision_ids"]
    subprocess.run(["git", "add", original["record_path"]], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"original\n\n{original['trailer']}"],
                   cwd=repo, capture_output=True, check=True)
    verified = VerifyService(drafts, index, git).verify_commit(commit_oid=_head(repo))
    assert verified["details"]["change_status"] == "open"
    assert verified["details"]["remaining_revision_ids"] == late
    current = RetrieveService(drafts, index, git).get_status(change_id)["open_changes"][0]
    assert [r["revision_id"] for r in current["decision_revisions"]] == late
    replacement = prepare.prepare_commit(change_id=change_id, expected_revision=2,
        selected_revision_ids=late, summary="replacement", operation_id="replacement")
    assert replacement["omitted_revision_ids"] == []
    subprocess.run(["git", "add", replacement["record_path"]], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"replacement\n\n{replacement['trailer']}"],
                   cwd=repo, capture_output=True, check=True)
    assert VerifyService(drafts, index, git).verify_commit(commit_oid=_head(repo))["details"]["change_status"] == "committed"


@pytest.mark.parametrize("summary,rationale,evidence_content,error", [
    ("safe", "x" * 65_000, None, "64 KiB"),
    ("api_key=abcdefghijklmnopqrstuvwxyz", "safe", None, "credential or private path"),
    ("safe", "See C:\\Users\\alice\\notes.txt", None, "credential or private path"),
    ("safe", "safe", "password=verylongpassword", "credential or private path"),
], ids=["record_size", "credential", "private_path", "evidence_credential"])
def test_prepare_rejects_oversize_and_private_content(tmp_path, summary, rationale, evidence_content, error):
    from commitecho.application.capture import CaptureService
    from commitecho.application.prepare import PrepareService

    repo = _make_repo(tmp_path)
    git, drafts, _ = _open_services(repo)
    capture = CaptureService(drafts, git)
    change = capture.begin_change(title="safe", client="test", operation_id="begin")
    evidence_id = str(uuid.uuid4()) if evidence_content else None
    result = capture.record_decisions(
        change_id=change["change_id"], expected_revision=0, operation_id="capture",
        decisions=[{"problem": "safe", "choice": "safe", "rationale": rationale,
                    "evidence_ids": [evidence_id] if evidence_id else []}],
        evidence=[{"evidence_id": evidence_id, "kind": "test_result", "content": evidence_content}]
        if evidence_id else None,
    )
    (repo / "code.py").write_text("pass\n")
    subprocess.run(["git", "add", "code.py"], cwd=repo, check=True, capture_output=True)
    with pytest.raises(ValueError, match=error):
        PrepareService(drafts, git).prepare_commit(
            change_id=change["change_id"], expected_revision=1,
            selected_revision_ids=result["revision_ids"], summary=summary, operation_id="prepare",
        )
    assert drafts.execute("SELECT count(*) FROM commit_records").fetchone()[0] == 0
    assert not list((repo / ".commitecho" / "records").glob("*.json"))


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
        assert drafts2.execute("SELECT status FROM changes WHERE change_id = ?", (change_id,)).fetchone()[0] == "prepared"


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
