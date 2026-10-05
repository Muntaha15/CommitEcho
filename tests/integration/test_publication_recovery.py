"""Publication lifecycle survives shallow history, index rebuilds, and delayed verification."""

from pathlib import Path
import subprocess
import uuid

import pytest
from click.testing import CliRunner

from commitecho.application.capture import CaptureService
from commitecho.application.prepare import PrepareService
from commitecho.application.verify import VerifyService
from commitecho.storage.repository import get_decision_state
from commitecho.transports.cli import main
from tests.integration.test_prepare_verify import _git_available, _head, _make_repo, _open_services


pytestmark = pytest.mark.skipif(not _git_available(), reason="Git executable not available")


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def shallow_services(tmp_path):
    source = _make_repo(tmp_path, "source")
    (source / "boundary.py").write_text("value = 0\n")
    _git(source, "add", "boundary.py")
    _git(source, "commit", "-m", "shallow boundary")
    repo = tmp_path / "shallow repository with spaces"
    _git(tmp_path, "clone", "--depth=1", source.as_uri(), str(repo))
    _git(repo, "config", "user.name", "CommitEcho Test")
    _git(repo, "config", "user.email", "test@commitecho.test")
    git, drafts, index = _open_services(repo)
    assert Path(git.repo_info.common_dir, "shallow").exists()
    try:
        yield repo, git, drafts, index
    finally:
        drafts.close()
        index.close()


def _capture(git, drafts, count):
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(
        title="shallow lifecycle", client="codex", operation_id=str(uuid.uuid4())
    )["change_id"]
    revisions = capture.record_decisions(
        change_id=change_id, expected_revision=0, operation_id=str(uuid.uuid4()),
        decisions=[{
            "problem": f"change {number}", "choice": "implement", "rationale": "needed",
            "disposition": "selected", "code_scope": {"paths": [f"code{number}.py"]},
        } for number in range(count)],
    )["revision_ids"]
    return change_id, revisions


def _commit_revision(repo, git, drafts, change_id, revision_id, number):
    path = f"code{number}.py"
    (repo / path).write_text(f"value = {number}\n")
    _git(repo, "add", path)
    prepared = PrepareService(drafts, git).prepare_commit(
        change_id=change_id, expected_revision=1, selected_revision_ids=[revision_id],
        summary=f"change {number}", operation_id=str(uuid.uuid4()),
    )
    _git(repo, "add", prepared["record_path"])
    _git(repo, "commit", "-m", f"change {number}\n\n{prepared['trailer']}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("count", [1, 2])
def test_exact_local_commits_complete_changes_in_shallow_clone(shallow_services, count):
    repo, git, drafts, index = shallow_services
    change_id, revisions = _capture(git, drafts, count)
    verify = VerifyService(drafts, index, git)
    for number, revision_id in enumerate(revisions):
        oid = _commit_revision(repo, git, drafts, change_id, revision_id, number)
        reachable, coverage = git.reachable_commit_oids(oid)
        assert coverage == "partial"
        assert oid in reachable
        verified = verify.verify_commit(commit_oid=oid)
        assert verified["outcome"] == "exact"
        expected_remaining = revisions[number + 1:]
        assert verified["details"]["remaining_revision_ids"] == expected_remaining
        assert verified["details"]["change_status"] == (
            "open" if expected_remaining else "committed"
        )
        assert get_decision_state(drafts, git, change_id, index)[
            "unpublished_revision_ids"
        ] == expected_remaining


def test_shallow_boundary_does_not_prove_unseen_commit_reachable(shallow_services):
    repo, git, drafts, index = shallow_services
    change_id, revisions = _capture(git, drafts, 2)
    verify = VerifyService(drafts, index, git)
    commits = []
    for number, revision_id in enumerate(revisions):
        oid = _commit_revision(repo, git, drafts, change_id, revision_id, number)
        assert verify.verify_commit(commit_oid=oid)["outcome"] == "exact"
        commits.append(oid)

    # Git treats the shallow marker as a root even if older objects remain on disk.
    Path(git.repo_info.common_dir, "shallow").write_text(commits[-1] + "\n")
    reachable, coverage = git.reachable_commit_oids(commits[-1])
    assert coverage == "partial"
    assert reachable == [commits[-1]]
    assert _git(repo, "cat-file", "-t", commits[0]) == "commit"
    assert get_decision_state(drafts, git, change_id, index)[
        "unpublished_revision_ids"
    ] == [revisions[0]]


@pytest.mark.parametrize("upgrade_v4", [False, True])
def test_cache_deletion_and_rebuild_preserves_partial_completion(tmp_path, upgrade_v4):
    repo = _make_repo(tmp_path)
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(title="two parts", client="codex", operation_id="begin")["change_id"]
    revisions = capture.record_decisions(
        change_id=change_id, expected_revision=0, operation_id="decisions",
        decisions=[{"problem": str(number), "choice": "implement", "rationale": "needed"}
                   for number in range(2)],
    )["revision_ids"]
    first = _commit_revision(repo, git, drafts, change_id, revisions[0], 0)
    assert VerifyService(drafts, index, git).verify_commit(commit_oid=first)["outcome"] == "exact"
    if upgrade_v4:
        drafts.execute("DROP TABLE verified_bindings")
        drafts.execute("UPDATE schema_meta SET value = '4' WHERE key = 'version'")
        drafts.execute("DELETE FROM schema_meta WHERE key = 'verified_bindings_backfilled'")
        drafts.commit()
    drafts.close()
    index.close()

    # Upgrade preserves the old locally authenticated result while its cache exists.
    git, drafts, index = _open_services(repo)
    assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == [revisions[1]]
    common_dir = Path(git.repo_info.common_dir)
    drafts.close()
    index.close()
    for suffix in ("", "-wal", "-shm"):
        (common_dir / "commitecho" / f"index.sqlite{suffix}").unlink(missing_ok=True)
    assert CliRunner().invoke(main, ["index", "--repo", str(repo)]).exit_code == 0

    git, drafts, index = _open_services(repo)
    try:
        assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == [revisions[1]]
        second = _commit_revision(repo, git, drafts, change_id, revisions[1], 1)
        verified = VerifyService(drafts, index, git).verify_commit(commit_oid=second)
        assert verified["details"]["remaining_revision_ids"] == []
        assert verified["details"]["change_status"] == "committed"
        _git(repo, "checkout", "--detach", f"{first}^")
        assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == revisions
    finally:
        drafts.close()
        index.close()


def test_indexing_a_prepared_commit_does_not_authenticate_local_publication(tmp_path):
    repo = _make_repo(tmp_path)
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(title="unverified", client="codex", operation_id="begin")["change_id"]
    revision = capture.record_decisions(change_id=change_id, expected_revision=0,
        operation_id="decision", decisions=[{"problem": "problem", "choice": "fix", "rationale": "needed"}]
    )["revision_ids"][0]
    _commit_revision(repo, git, drafts, change_id, revision, 0)
    assert CliRunner().invoke(main, ["index", "--repo", str(repo)]).exit_code == 0
    assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == [revision]
    drafts.close()
    index.close()


def test_multiple_verified_oids_for_one_record_survive_index_deletion(tmp_path):
    repo = _make_repo(tmp_path)
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(title="amended message", client="codex", operation_id="begin")["change_id"]
    revision = capture.record_decisions(change_id=change_id, expected_revision=0,
        operation_id="decision", decisions=[{"problem": "problem", "choice": "fix", "rationale": "needed"}]
    )["revision_ids"][0]
    first = _commit_revision(repo, git, drafts, change_id, revision, 0)
    verify = VerifyService(drafts, index, git)
    assert verify.verify_commit(commit_oid=first)["outcome"] == "exact"
    message = _git(repo, "log", "-1", "--format=%B")
    _git(repo, "commit", "--amend", "-m", f"New subject\n\n{message}")
    second = _git(repo, "rev-parse", "HEAD")
    assert first != second
    assert verify.verify_commit(commit_oid=second)["outcome"] == "exact"
    assert drafts.execute("SELECT count(*) FROM verified_bindings").fetchone()[0] == 2
    common_dir = Path(git.repo_info.common_dir)
    drafts.close()
    index.close()
    for suffix in ("", "-wal", "-shm"):
        (common_dir / "commitecho" / f"index.sqlite{suffix}").unlink(missing_ok=True)
    git, drafts, index = _open_services(repo)
    try:
        for oid in (first, second):
            _git(repo, "checkout", "--detach", oid)
            assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == []
    finally:
        drafts.close()
        index.close()


@pytest.fixture
def partial_change(tmp_path):
    repo = _make_repo(tmp_path)
    git, drafts, index = _open_services(repo)
    capture = CaptureService(drafts, git)
    change_id = capture.begin_change(
        title="partial commits", client="test", operation_id="begin",
    )["change_id"]
    revisions = capture.record_decisions(
        change_id=change_id, expected_revision=0, operation_id="decisions",
        decisions=[{"problem": name, "choice": "implement", "rationale": "required"}
                   for name in ("first", "second")],
    )["revision_ids"]
    yield repo, git, drafts, index, change_id, revisions
    drafts.close()
    index.close()


def _prepare(repo, git, drafts, change_id, revisions, number, expected_revision=1):
    path = f"code{number}.py"
    (repo / path).write_text(f"value = {number}\n")
    subprocess.run(["git", "add", path], cwd=repo, check=True, capture_output=True)
    return PrepareService(drafts, git).prepare_commit(
        change_id=change_id, expected_revision=expected_revision,
        selected_revision_ids=revisions, summary=f"commit {number}",
        operation_id=f"prepare-{number}",
    )


def _commit_prepared(repo, prepared):
    subprocess.run(["git", "add", prepared["record_path"]], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"change\n\n{prepared['trailer']}"],
                   cwd=repo, check=True, capture_output=True)
    return _head(repo)


def _status(drafts, change_id):
    return drafts.execute(
        "SELECT status FROM changes WHERE change_id = ?", (change_id,),
    ).fetchone()[0]


@pytest.mark.parametrize("keep_open", [False, True], ids=["complete", "explicitly-open"])
def test_delayed_verification_uses_latest_preparation_intent(partial_change, keep_open):
    repo, git, drafts, index, change_id, revisions = partial_change
    first = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[:1], 1))
    second = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[1:], 2))
    verify = VerifyService(drafts, index, git)

    result = verify.verify_commit(commit_oid=second, keep_open=keep_open)
    assert result["outcome"] == "exact"
    assert result["details"]["remaining_revision_ids"] == revisions[:1]
    assert _status(drafts, change_id) == "open"

    for _ in range(2):
        result = verify.verify_commit(commit_oid=first)
        assert result["outcome"] == "exact"
        assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == []
        assert _status(drafts, change_id) == ("open" if keep_open else "committed")


def test_historical_verification_preserves_newer_unverified_preparation(partial_change):
    repo, git, drafts, index, change_id, revisions = partial_change
    # Publishing every current revision does not authorize closing a newer preparation.
    first = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions, 1))
    newer = _prepare(repo, git, drafts, change_id, revisions, 2)
    verify = VerifyService(drafts, index, git)
    assert verify.verify_commit(commit_oid=first)["outcome"] == "exact"
    assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == []
    assert _status(drafts, change_id) == "prepared"

    assert verify.verify_commit(commit_oid=_commit_prepared(repo, newer))["outcome"] == "exact"
    assert _status(drafts, change_id) == "committed"


def test_historical_verification_preserves_late_superseding_revisions(partial_change):
    repo, git, drafts, index, change_id, revisions = partial_change
    first = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[:1], 1))
    second = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[1:], 2))
    late = CaptureService(drafts, git).record_decisions(
        change_id=change_id, expected_revision=1, operation_id="late",
        decisions=[{"problem": "second", "choice": "revised", "rationale": "new requirement",
                    "predecessor_revision_ids": revisions[1:]},
                   {"problem": "third", "choice": "add", "rationale": "new requirement"}],
    )["revision_ids"]
    verify = VerifyService(drafts, index, git)
    assert verify.verify_commit(commit_oid=second)["outcome"] == "exact"
    result = verify.verify_commit(commit_oid=first)
    assert result["outcome"] == "exact"
    assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == late
    assert _status(drafts, change_id) == "open"

    final = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, late, 3, expected_revision=2))
    assert verify.verify_commit(commit_oid=final)["outcome"] == "exact"
    assert _status(drafts, change_id) == "committed"


def test_verification_in_other_worktree_cannot_complete_change(partial_change, tmp_path):
    repo, git, drafts, index, change_id, revisions = partial_change
    commit_oid = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions, 1))
    other = tmp_path / "other worktree"
    subprocess.run(["git", "worktree", "add", "-b", "other", str(other)],
                   cwd=repo, check=True, capture_output=True)
    other_git, other_drafts, other_index = _open_services(other)
    try:
        result = VerifyService(other_drafts, other_index, other_git).verify_commit(commit_oid=commit_oid)
        assert result["outcome"] == "exact"
        assert _status(drafts, change_id) == "prepared"
    finally:
        other_drafts.close()
        other_index.close()
    assert VerifyService(drafts, index, git).verify_commit(commit_oid=commit_oid)["outcome"] == "exact"
    assert _status(drafts, change_id) == "committed"


@pytest.mark.parametrize("foreign_keep_open", [False, True])
def test_foreign_verification_preserves_owner_keep_open_intent(partial_change, tmp_path, foreign_keep_open):
    repo, git, drafts, index, change_id, revisions = partial_change
    first = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[:1], 1))
    second = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[1:], 2))
    verify = VerifyService(drafts, index, git)
    assert verify.verify_commit(commit_oid=second, keep_open=True)["outcome"] == "exact"
    other = tmp_path / "other worktree"
    subprocess.run(["git", "worktree", "add", "-b", "other", str(other)],
                   cwd=repo, check=True, capture_output=True)
    other_git, other_drafts, other_index = _open_services(other)
    try:
        result = VerifyService(other_drafts, other_index, other_git).verify_commit(
            commit_oid=second, keep_open=foreign_keep_open,
        )
        assert result["outcome"] == "exact"
    finally:
        other_drafts.close()
        other_index.close()

    assert verify.verify_commit(commit_oid=first)["outcome"] == "exact"
    assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == []
    assert _status(drafts, change_id) == "open"


def test_legacy_latest_binding_requires_explicit_verification_to_close(partial_change):
    repo, git, drafts, index, change_id, revisions = partial_change
    first = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[:1], 1))
    second = _commit_prepared(repo, _prepare(repo, git, drafts, change_id, revisions[1:], 2))
    assert VerifyService(drafts, index, git).verify_commit(commit_oid=second)["outcome"] == "exact"
    # A version-4 index did not retain keep_open; upgrading must not guess that intent.
    drafts.execute("DROP TABLE verified_bindings")
    drafts.execute("UPDATE schema_meta SET value = '4' WHERE key = 'version'")
    drafts.execute("DELETE FROM schema_meta WHERE key = 'verified_bindings_backfilled'")
    drafts.commit()
    drafts.close()
    index.close()
    git, drafts, index = _open_services(repo)
    try:
        verify = VerifyService(drafts, index, git)
        assert verify.verify_commit(commit_oid=first)["outcome"] == "exact"
        assert get_decision_state(drafts, git, change_id)["unpublished_revision_ids"] == []
        assert _status(drafts, change_id) == "open"
        assert verify.verify_commit(commit_oid=second)["outcome"] == "exact"
        assert _status(drafts, change_id) == "committed"
    finally:
        drafts.close()
        index.close()
