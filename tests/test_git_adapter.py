"""Unit tests for the Git adapter (non-filesystem portions)."""

from __future__ import annotations

import pytest
from commitecho.git.adapter import (
    StagedEntry,
    build_code_manifest,
    fingerprint_manifest,
)


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
