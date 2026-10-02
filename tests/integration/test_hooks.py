"""Integration tests for universal Git message validation and hook installation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner

from commitecho.git.adapter import GitAdapter, fingerprint_manifest, build_code_manifest
from commitecho.transports.cli import check_message, hook, main


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="Git executable not available")


@pytest.fixture
def test_repo(tmp_path: Path):
    """Create a temporary Git repository with initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo), check=True, capture_output=True)
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), check=True, capture_output=True)
    return repo


def _create_staged_record(repo: Path, record_uuid: uuid.UUID | None = None, parent_oid: str | None = None):
    """Helper to stage a file change and matching CommitEcho record."""
    if record_uuid is None:
        record_uuid = uuid.uuid4()
    git = GitAdapter.from_path(repo)
    if parent_oid is None:
        parent_oid = git.head_oid() or "0" * 40

    # Stage a code change
    code_file = repo / "hello.py"
    code_file.write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.py"], cwd=str(repo), check=True, capture_output=True)

    git = GitAdapter.from_path(repo)
    code_digest, _ = git.code_fingerprint()

    record_dir = repo / ".commitecho" / "records"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_file = record_dir / f"{record_uuid}.json"

    record_payload = {
        "schema_version": 1,
        "record_id": str(record_uuid),
        "change_id": str(uuid.uuid4()),
        "summary": "Test commit record",
        "prepared_at": "2026-10-02T12:00:00Z",
        "prepared_for": {
            "parent_oid": parent_oid,
            "object_format": git.repo_info.object_format,
            "manifest_version": 1,
            "code_manifest_sha256": code_digest,
        },
        "decisions": [],
        "evidence": [],
    }
    record_file.write_text(json.dumps(record_payload, indent=2), encoding="utf-8")
    subprocess.run(["git", "add", str(record_file)], cwd=str(repo), check=True, capture_output=True)
    return record_uuid, record_file, record_payload


class TestCheckMessage:
    def test_valid_record_passes(self, test_repo):
        record_uuid, _, _ = _create_staged_record(test_repo)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: add hello\n\nCommitEcho-Record: {record_uuid}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code == 0
        assert f"CommitEcho record {record_uuid} verified" in res.output

    def test_case_insensitive_trailer_key(self, test_repo):
        record_uuid, _, _ = _create_staged_record(test_repo)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: add hello\n\ncommitecho-record: {record_uuid}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code == 0
        assert f"CommitEcho record {record_uuid} verified" in res.output

    def test_missing_trailer_with_staged_code_advisory(self, test_repo):
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text("feat: unrecorded commit\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[warn]" in res.output
        assert "Missing 'CommitEcho-Record' trailer" in res.output

    def test_missing_trailer_with_staged_code_strict_fails(self, test_repo):
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text("feat: unrecorded commit\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "[error]" in res.output
        assert "Missing 'CommitEcho-Record' trailer" in res.output

    def test_empty_commit_without_trailer_passes(self, test_repo):
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text("chore: empty commit\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code == 0
        assert "[info]" in res.output
        assert "No staged code changes" in res.output

    def test_multiple_trailers_strict_fails(self, test_repo):
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: two trailers\n\nCommitEcho-Record: {id1}\nCommitEcho-Record: {id2}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "Multiple 'CommitEcho-Record' trailers found" in res.output

    def test_invalid_uuid_strict_fails(self, test_repo):
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text("feat: bad uuid\n\nCommitEcho-Record: not-a-uuid\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "Invalid 'CommitEcho-Record' UUID" in res.output

    def test_unstaged_record_strict_fails(self, test_repo):
        rec_id = uuid.uuid4()
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        # Create record file on disk but DO NOT git add it
        rec_file = test_repo / ".commitecho" / "records" / f"{rec_id}.json"
        rec_file.parent.mkdir(parents=True, exist_ok=True)
        rec_file.write_text("{}", encoding="utf-8")

        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: unstaged record\n\nCommitEcho-Record: {rec_id}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "is not staged in the Git index" in res.output

    def test_malformed_record_json_strict_fails(self, test_repo):
        rec_id = uuid.uuid4()
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        rec_file = test_repo / ".commitecho" / "records" / f"{rec_id}.json"
        rec_file.parent.mkdir(parents=True, exist_ok=True)
        rec_file.write_text("not json content", encoding="utf-8")
        subprocess.run(["git", "add", str(rec_file)], cwd=str(test_repo), check=True)

        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: malformed json\n\nCommitEcho-Record: {rec_id}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "contains malformed JSON" in res.output

    def test_record_id_mismatch_strict_fails(self, test_repo):
        rec_id = uuid.uuid4()
        other_id = uuid.uuid4()
        (test_repo / "foo.txt").write_text("bar\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.txt"], cwd=str(test_repo), check=True)
        rec_file = test_repo / ".commitecho" / "records" / f"{rec_id}.json"
        rec_file.parent.mkdir(parents=True, exist_ok=True)
        rec_file.write_text(json.dumps({"record_id": str(other_id)}), encoding="utf-8")
        subprocess.run(["git", "add", str(rec_file)], cwd=str(test_repo), check=True)

        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: id mismatch\n\nCommitEcho-Record: {rec_id}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "ID mismatch" in res.output

    def test_stale_parent_strict_fails(self, test_repo):
        record_uuid, _, _ = _create_staged_record(test_repo, parent_oid="1" * 40)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: stale parent\n\nCommitEcho-Record: {record_uuid}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "stale preparation" in res.output

    def test_manifest_mismatch_strict_fails(self, test_repo):
        record_uuid, _, _ = _create_staged_record(test_repo)
        # Modify and stage additional code change after record preparation
        (test_repo / "extra.py").write_text("x = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "extra.py"], cwd=str(test_repo), check=True)

        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: modified staged\n\nCommitEcho-Record: {record_uuid}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code != 0
        assert "Staged changes do not match CommitEcho record preparation" in res.output

    def test_root_commit_validation(self, tmp_path):
        root_repo = tmp_path / "root_repo"
        root_repo.mkdir()
        subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(root_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(root_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(root_repo), check=True, capture_output=True)

        record_uuid, _, _ = _create_staged_record(root_repo, parent_oid="0" * 40)
        msg_file = root_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text(f"feat: root commit\n\nCommitEcho-Record: {record_uuid}\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(root_repo), "--strict"])
        assert res.exit_code == 0
        assert f"CommitEcho record {record_uuid} verified" in res.output

    def test_merge_in_progress_without_trailer_passes(self, test_repo):
        # Create a branch and a diverged commit
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(test_repo), check=True, capture_output=True)
        (test_repo / "feature.txt").write_text("feature content\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=str(test_repo), check=True)
        subprocess.run(["git", "commit", "-m", "commit on feature"], cwd=str(test_repo), check=True, capture_output=True)

        subprocess.run(["git", "checkout", "main"], cwd=str(test_repo), check=True, capture_output=True)
        (test_repo / "main.txt").write_text("main content\n", encoding="utf-8")
        subprocess.run(["git", "add", "main.txt"], cwd=str(test_repo), check=True)
        subprocess.run(["git", "commit", "-m", "commit on main"], cwd=str(test_repo), check=True, capture_output=True)

        # Merge feature without committing
        subprocess.run(["git", "merge", "--no-ff", "--no-commit", "feature"], cwd=str(test_repo), check=True, capture_output=True)
        msg_file = test_repo / ".git" / "COMMIT_EDITMSG"
        msg_file.write_text("Merge branch 'feature'\n", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(check_message, [str(msg_file), "--repo", str(test_repo), "--strict"])
        assert res.exit_code == 0
        assert "[info]" in res.output
        assert "Merge commit detected" in res.output


class TestHookInstallAndUninstall:
    def test_install_creates_hook(self, test_repo):
        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[create]" in res.output
        hook_path = test_repo / ".git" / "hooks" / "commit-msg"
        assert hook_path.exists()
        content = hook_path.read_text(encoding="utf-8")
        assert "commitecho check-message" in content
        assert "# --- commitecho-hook-start ---" in content

    def test_install_idempotent(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        res = runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[skip]" in res.output
        assert "already up to date" in res.output

    def test_install_strict_toggle(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        res = runner.invoke(hook, ["install", "--git", "--strict", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[update]" in res.output
        hook_path = test_repo / ".git" / "hooks" / "commit-msg"
        assert 'STRICT_FLAG="--strict"' in hook_path.read_text(encoding="utf-8")

    def test_install_dry_run(self, test_repo):
        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--git", "--dry-run", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "(dry-run: no files were written)" in res.output
        assert not (test_repo / ".git" / "hooks" / "commit-msg").exists()

    def test_install_preserves_foreign_hook(self, test_repo):
        hook_path = test_repo / ".git" / "hooks" / "commit-msg"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        foreign_content = "#!/bin/sh\n# Custom linter hook\nexit 0\n"
        hook_path.write_text(foreign_content, encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[warn]" in res.output
        assert "not managed by CommitEcho" in res.output
        # File must remain untouched
        assert hook_path.read_text(encoding="utf-8") == foreign_content

    def test_install_refuses_global_hooks_path(self, test_repo, tmp_path):
        external_hooks = tmp_path / "global_hooks"
        external_hooks.mkdir()
        # Configure global core.hooksPath using environment override or test git config
        subprocess.run(["git", "config", "--file", str(test_repo / ".git" / "config"), "core.hooksPath", str(external_hooks)], cwd=str(test_repo), check=True)

        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        assert res.exit_code != 0
        assert "resolves to external/global location" in res.output

    def test_install_supports_repo_local_hooks_path(self, test_repo):
        local_hooks = test_repo / ".githooks"
        local_hooks.mkdir()
        subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=str(test_repo), check=True)

        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[create]" in res.output
        installed_hook = local_hooks / "commit-msg"
        assert installed_hook.exists()
        assert "commitecho check-message" in installed_hook.read_text(encoding="utf-8")

    def test_linked_worktree_hook_path(self, test_repo, tmp_path):
        wt_dir = tmp_path / "linked_worktree"
        subprocess.run(["git", "worktree", "add", str(wt_dir), "-b", "linked-branch"], cwd=str(test_repo), check=True, capture_output=True)

        git = GitAdapter.from_path(wt_dir)
        hook_path, is_local = git.get_hook_path("commit-msg")
        assert is_local is True
        # In linked worktree, hooks default to main common dir hooks
        expected_hook = test_repo / ".git" / "hooks" / "commit-msg"
        assert hook_path.resolve() == expected_hook.resolve()

    def test_uninstall_pure_commitecho_hook(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])
        hook_path = test_repo / ".git" / "hooks" / "commit-msg"
        assert hook_path.exists()

        res = runner.invoke(hook, ["uninstall", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[remove]" in res.output
        assert not hook_path.exists()

    def test_uninstall_mixed_hook_preserves_foreign_content(self, test_repo):
        hook_path = test_repo / ".git" / "hooks" / "commit-msg"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        custom_header = "#!/bin/sh\n# External security check\ncheck_sec\n"
        from commitecho.transports.cli import _generate_hook_block
        hook_path.write_text(custom_header + _generate_hook_block(strict=False), encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(hook, ["uninstall", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[update]" in res.output
        assert hook_path.exists()
        remaining = hook_path.read_text(encoding="utf-8")
        assert "External security check" in remaining
        assert "commitecho" not in remaining

    def test_uninstall_unmanaged_hook_skipped(self, test_repo):
        hook_path = test_repo / ".git" / "hooks" / "commit-msg"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        foreign = "#!/bin/sh\nexit 0\n"
        hook_path.write_text(foreign, encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(hook, ["uninstall", "--git", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[skip]" in res.output
        assert hook_path.read_text(encoding="utf-8") == foreign


class TestGitCommitWithHook:
    def test_strict_hook_blocks_unrecorded_commit(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--strict", "--repo", str(test_repo)])

        # Stage a code change
        (test_repo / "code.py").write_text("val = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "code.py"], cwd=str(test_repo), check=True)

        head_before = GitAdapter.from_path(test_repo).head_oid()
        res = subprocess.run(
            ["git", "commit", "-m", "unrecorded change"],
            cwd=str(test_repo),
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        head_after = GitAdapter.from_path(test_repo).head_oid()
        assert head_after == head_before  # HEAD remained unchanged

    def test_strict_hook_allows_valid_commit(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--strict", "--repo", str(test_repo)])

        record_uuid, _, _ = _create_staged_record(test_repo)
        head_before = GitAdapter.from_path(test_repo).head_oid()

        res = subprocess.run(
            ["git", "commit", "-m", f"feat: recorded change\n\nCommitEcho-Record: {record_uuid}\n"],
            cwd=str(test_repo),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        head_after = GitAdapter.from_path(test_repo).head_oid()
        assert head_after != head_before

    def test_strict_hook_allows_commit_with_message_file(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--strict", "--repo", str(test_repo)])

        record_uuid, _, _ = _create_staged_record(test_repo)
        msg_file = test_repo / "my_msg.txt"
        msg_file.write_text(f"feat: from file\n\nCommitEcho-Record: {record_uuid}\n", encoding="utf-8")

        res = subprocess.run(
            ["git", "commit", "-F", "my_msg.txt"],
            cwd=str(test_repo),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0

    def test_advisory_hook_permits_unrecorded_commit_with_diagnostic(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)])

        (test_repo / "code.py").write_text("val = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "code.py"], cwd=str(test_repo), check=True)

        head_before = GitAdapter.from_path(test_repo).head_oid()
        res = subprocess.run(
            ["git", "commit", "-m", "unrecorded change"],
            cwd=str(test_repo),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "CommitEcho: Missing 'CommitEcho-Record' trailer" in (res.stdout + res.stderr)
        head_after = GitAdapter.from_path(test_repo).head_oid()
        assert head_after != head_before
