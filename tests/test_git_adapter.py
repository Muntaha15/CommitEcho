"""Unit tests for the Git adapter (non-filesystem portions)."""

from __future__ import annotations

import pytest
import subprocess
from commitecho.git.adapter import (
    GitAdapter,
    GitError,
    StagedEntry,
    build_code_manifest,
    fingerprint_manifest,
)


def test_sha256_root_diff_and_git_failure(tmp_path, monkeypatch):
    import commitecho.git.adapter as adapter

    repo = tmp_path / "sha256"
    repo.mkdir()
    init = subprocess.run(["git", "init", "--object-format=sha256", str(repo)],
                          capture_output=True)
    if init.returncode:
        pytest.skip("Git has no SHA-256 repository support")
    (repo / "root.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "root.py"], cwd=repo, check=True)
    git = GitAdapter.from_path(repo)
    assert git.repo_info.object_format == "sha256"
    assert [entry.path for entry in git.staged_changes()] == ["root.py"]
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-m", "root"], cwd=repo, check=True, capture_output=True)
    assert [entry.path for entry in git.staged_entries_for_commit(git.head_oid())] == ["root.py"]

    def fail_diff(*_args, **_kwargs):
        raise GitError("diff failed")
    monkeypatch.setattr(adapter, "_run", fail_diff)
    with pytest.raises(GitError):
        git.staged_changes()
    with pytest.raises(GitError):
        git.staged_entries_for_commit("0" * 64)


class TestCodeManifest:
    def test_excludes_commitecho_records(self):
        entries = [
            StagedEntry(
                path=".commitecho/records/abc.json",
                old_oid="0" * 40,
                new_oid="a" * 40,
                old_mode="000000",
                new_mode="100644",
            ),
            StagedEntry(
                path="src/main.py",
                old_oid="b" * 40,
                new_oid="c" * 40,
                old_mode="100644",
                new_mode="100644",
            ),
        ]
        manifest = build_code_manifest(entries)
        paths = [e["path"] for e in manifest["entries"]]
        assert "src/main.py" in paths
        assert ".commitecho/records/abc.json" not in paths

    def test_sorted_deterministically(self):
        entries = [
            StagedEntry(path="z.py", old_oid="0" * 40, new_oid="1" * 40, old_mode="100644", new_mode="100644"),
            StagedEntry(path="a.py", old_oid="0" * 40, new_oid="2" * 40, old_mode="100644", new_mode="100644"),
        ]
        m1 = build_code_manifest(entries)
        m2 = build_code_manifest(list(reversed(entries)))
        assert m1 == m2

    def test_fingerprint_stable(self):
        entries = [
            StagedEntry(path="src/x.py", old_oid="0" * 40, new_oid="a" * 40, old_mode="100644", new_mode="100644"),
        ]
        manifest = build_code_manifest(entries)
        d1 = fingerprint_manifest(manifest)
        d2 = fingerprint_manifest(manifest)
        assert d1 == d2
        assert len(d1) == 64  # SHA-256 hex

    def test_different_entries_different_fingerprint(self):
        e1 = [StagedEntry(path="a.py", old_oid="0" * 40, new_oid="1" * 40, old_mode="100644", new_mode="100644")]
        e2 = [StagedEntry(path="b.py", old_oid="0" * 40, new_oid="2" * 40, old_mode="100644", new_mode="100644")]
        d1 = fingerprint_manifest(build_code_manifest(e1))
        d2 = fingerprint_manifest(build_code_manifest(e2))
        assert d1 != d2
