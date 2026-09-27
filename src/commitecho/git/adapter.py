"""Git adapter – repository discovery, object reads, ref resolution, and staged-index inspection.

All Git commands are executed with explicit argument lists; no shell expansion.
The Git executable path can be overridden via the COMMITECHO_GIT environment variable.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

_ROOT_COMMIT_MARKER = "0000000000000000000000000000000000000000"


class GitError(Exception):
    """Raised when a Git command fails or returns unexpected output."""


def _git_exe() -> str:
    return os.environ.get("COMMITECHO_GIT", "git")


def _run(args: Sequence[str], cwd: str | None = None) -> str:
    """Run a Git sub-command and return stdout as a stripped string.

    Raises GitError on non-zero exit or if cwd does not exist.
    """
    if cwd is not None and not os.path.isdir(cwd):
        raise GitError(f"Working directory does not exist or is not a directory: {cwd}")
    cmd = [_git_exe(), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            # Never inherit shell; arguments are passed directly.
            shell=False,
        )
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise GitError(f"Failed to run git {' '.join(str(a) for a in args)}: {exc}") from exc
    if result.returncode != 0:
        raise GitError(
            f"git {' '.join(str(a) for a in args)} failed "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Repository discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoInfo:
    """Resolved paths for a Git repository."""

    common_dir: str  # absolute path to git common dir (handles linked worktrees)
    worktree_dir: str  # absolute path to the worktree root
    worktree_id: str  # repo-relative identifier for the worktree
    object_format: str  # "sha1" | "sha256"


def discover_repository(path: str | Path | None = None) -> RepoInfo:
    """Discover the Git repository enclosing *path* (default: cwd).

    Raises GitError if no repository is found.
    """
    cwd = str(path) if path else None
    worktree_dir = _run(["rev-parse", "--show-toplevel"], cwd=cwd)
    common_dir = _run(["rev-parse", "--git-common-dir"], cwd=worktree_dir)

    # Normalize to absolute paths
    wt_path = Path(worktree_dir).resolve()
    if Path(common_dir).is_absolute():
        cd_path = Path(common_dir).resolve()
    else:
        cd_path = (wt_path / common_dir).resolve()

    # Derive a stable worktree identifier relative to the common dir
    try:
        wt_id = str(wt_path.relative_to(cd_path.parent))
    except ValueError:
        wt_id = wt_path.name

    # Determine object format (sha1 / sha256)
    try:
        obj_fmt = _run(
            ["rev-parse", "--show-object-format"], cwd=str(wt_path)
        )
    except GitError:
        obj_fmt = "sha1"

    return RepoInfo(
        common_dir=str(cd_path),
        worktree_dir=str(wt_path),
        worktree_id=wt_id,
        object_format=obj_fmt,
    )


# ---------------------------------------------------------------------------
# Ref resolution
# ---------------------------------------------------------------------------


def resolve_ref(ref: str, repo_info: RepoInfo) -> str:
    """Resolve *ref* to a full commit OID.

    Returns the full OID string.  Raises GitError if the ref cannot be resolved.
    """
    return _run(["rev-parse", "--verify", ref], cwd=repo_info.worktree_dir)


def get_head_oid(repo_info: RepoInfo) -> str | None:
    """Return the full OID of HEAD, or None for an unborn branch."""
    try:
        return resolve_ref("HEAD", repo_info)
    except GitError:
        return None  # unborn / empty repository


# ---------------------------------------------------------------------------
# Staged index inspection
# ---------------------------------------------------------------------------


@dataclass
class StagedEntry:
    """A single entry in the Git staged index."""

    path: str
    old_oid: str  # zero OID means the file did not exist
    new_oid: str  # zero OID means the file is being deleted
    old_mode: str
    new_mode: str


def _empty_tree_oid(repo_info: RepoInfo) -> str:
    result = subprocess.run(
        [_git_exe(), "hash-object", "-t", "tree", "--stdin"],
        input=b"", capture_output=True, cwd=repo_info.worktree_dir,
    )
    if result.returncode:
        raise GitError(f"Cannot hash empty tree: {result.stderr.decode(errors='replace')}")
    return result.stdout.decode().strip()


def read_staged_changes(repo_info: RepoInfo) -> list[StagedEntry]:
    """Return the list of changes staged in the Git index.

    Uses ``git diff-index --cached HEAD`` for normal commits and
    ``git diff-index --cached <empty-tree>`` for root commits (unborn HEAD).
    """
    head_oid = get_head_oid(repo_info)
    if head_oid is None:
        # Root commit: diff against this repository's empty tree.
        # ``--root`` is not accepted as a tree-ish by diff-index.
        args = ["diff-index", "--cached", "--raw", "-z", _empty_tree_oid(repo_info)]
    else:
        args = ["diff-index", "--cached", "--raw", "-z", "HEAD"]

    raw = _run(args, cwd=repo_info.worktree_dir)

    if not raw:
        return []

    entries: list[StagedEntry] = []
    # --raw -z output: NUL-separated fields
    # :old_mode new_mode old_oid new_oid status\0path\0...
    parts = raw.split("\0")
    i = 0
    while i < len(parts):
        meta = parts[i]
        if not meta.startswith(":"):
            i += 1
            continue
        # meta = ":100644 100644 abc... def... M"
        fields = meta[1:].split()
        if len(fields) < 5:
            i += 1
            continue
        old_mode, new_mode, old_oid, new_oid = fields[0], fields[1], fields[2], fields[3]
        i += 1
        path = parts[i] if i < len(parts) else ""
        i += 1
        entries.append(
            StagedEntry(
                path=path,
                old_oid=old_oid,
                new_oid=new_oid,
                old_mode=old_mode,
                new_mode=new_mode,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Code manifest / fingerprint
# ---------------------------------------------------------------------------

_MANIFEST_VERSION = 1
_COMMITECHO_RECORD_PREFIX = ".commitecho/records/"


def build_code_manifest(
    staged: list[StagedEntry], object_format: str = "sha1"
) -> dict:
    """Build a canonical code-change manifest for fingerprinting.

    Excludes generated .commitecho/records/ paths.  Sorted deterministically.
    Rename detection is disabled: a rename is delete + add.
    """
    entries = [
        {
            "path": e.path,
            "old_oid": e.old_oid,
            "new_oid": e.new_oid,
            "old_mode": e.old_mode,
            "new_mode": e.new_mode,
        }
        for e in sorted(staged, key=lambda x: x.path)
        if not e.path.startswith(_COMMITECHO_RECORD_PREFIX)
    ]
    return {
        "manifest_version": _MANIFEST_VERSION,
        "object_format": object_format,
        "entries": entries,
    }


def fingerprint_manifest(manifest: dict) -> str:
    """Return the SHA-256 hex digest of the canonical manifest bytes."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# High-level adapter
# ---------------------------------------------------------------------------


class GitAdapter:
    """Facade combining discovery, object reads, and manifest building."""

    def __init__(self, repo_info: RepoInfo) -> None:
        self._info = repo_info

    @classmethod
    def from_path(cls, path: str | Path | None = None) -> "GitAdapter":
        return cls(discover_repository(path))

    @property
    def repo_info(self) -> RepoInfo:
        return self._info

    def head_oid(self) -> str | None:
        return get_head_oid(self._info)

    def resolve(self, ref: str) -> str:
        return resolve_ref(ref, self._info)

    def staged_changes(self) -> list[StagedEntry]:
        return read_staged_changes(self._info)

    def code_fingerprint(self) -> tuple[str, dict]:
        """Return (sha256_hex_digest, manifest_dict) for currently staged changes."""
        staged = self.staged_changes()
        manifest = build_code_manifest(staged, self._info.object_format)
        digest = fingerprint_manifest(manifest)
        return digest, manifest

    def commit_exists(self, oid: str) -> bool:
        try:
            _run(["cat-file", "-t", oid], cwd=self._info.worktree_dir)
            return True
        except GitError:
            return False

    def read_commit_trailers(self, oid: str) -> dict[str, list[str]]:
        """Return all Git trailers for *oid* as {key: [value, ...]}."""
        msg = _run(["log", "-1", "--format=%B", oid], cwd=self._info.worktree_dir)
        result = subprocess.run(
            [_git_exe(), "interpret-trailers", "--parse"],
            input=msg,
            capture_output=True,
            text=True,
            cwd=self._info.worktree_dir,
        )
        if result.returncode:
            raise GitError(f"Cannot parse commit trailers: {result.stderr.strip()}")
        trailers: dict[str, list[str]] = {}
        for line in result.stdout.splitlines():
            if ": " in line:
                k, _, v = line.partition(": ")
                trailers.setdefault(k.strip(), []).append(v.strip())
        return trailers

    def file_exists_in_commit(self, oid: str, path: str) -> bool:
        """Check whether *path* exists in the tree of commit *oid*."""
        result = _run(
            ["ls-tree", "--name-only", oid, "--", path],
            cwd=self._info.worktree_dir,
        )
        return bool(result.strip())

    def read_file_from_commit(self, oid: str, path: str) -> bytes | None:
        """Read a committed file; return None only when the path is absent."""
        if not self.file_exists_in_commit(oid, path):
            return None
        result = subprocess.run(
            [_git_exe(), "show", f"{oid}:{path}"],
            cwd=self._info.worktree_dir,
            capture_output=True,
        )
        if result.returncode:
            raise GitError(f"Cannot read committed file {path}: {result.stderr.decode(errors='replace')}")
        return result.stdout

    def staged_entries_for_commit(self, commit_oid: str) -> list[StagedEntry]:
        """Return the diff entries introduced by *commit_oid* vs its parent.

        For root commits (no parent), diffs against the empty tree.
        Uses diff-tree so this works on any reachable commit, not only HEAD.
        """
        parents = _run(["rev-list", "--parents", "-n", "1", commit_oid],
                       cwd=self._info.worktree_dir).split()
        if not parents or parents[0] != commit_oid:
            raise GitError(f"Cannot read parents of commit {commit_oid}")
        base = parents[1] if len(parents) > 1 else _empty_tree_oid(self._info)
        # -r recurses into subtrees so we get blob-level entries, matching
        # what diff-index --cached produces for staged changes.
        args = ["diff-tree", "--raw", "-r", "-z", base, commit_oid]

        raw = _run(args, cwd=self._info.worktree_dir)

        if not raw:
            return []

        entries: list[StagedEntry] = []
        parts = raw.split("\0")
        i = 0
        while i < len(parts):
            meta = parts[i]
            if not meta.startswith(":"):
                i += 1
                continue
            fields = meta[1:].split()
            if len(fields) < 5:
                i += 1
                continue
            old_mode, new_mode, old_oid, new_oid = fields[0], fields[1], fields[2], fields[3]
            i += 1
            path = parts[i] if i < len(parts) else ""
            i += 1
            entries.append(
                StagedEntry(
                    path=path,
                    old_oid=old_oid,
                    new_oid=new_oid,
                    old_mode=old_mode,
                    new_mode=new_mode,
                )
            )
        return entries

    def reachable_commit_oids(
        self, include_ref: str, exclude_ref: str | None = None
    ) -> tuple[list[str], str]:
        """Return commit OIDs reachable from *include_ref*, optionally excluding *exclude_ref*.

        Returns (oids, coverage) where coverage is "full" or "partial".
        A shallow clone or missing objects causes coverage="partial".
        """
        args = ["rev-list", include_ref]
        if exclude_ref:
            args.append(f"^{exclude_ref}")
        try:
            raw = _run(args, cwd=self._info.worktree_dir)
            oids = [o for o in raw.splitlines() if o]
            # Check for shallow markers — shallow file exists in partial clones
            shallow_file = Path(self._info.common_dir) / "shallow"
            coverage = "partial" if shallow_file.exists() else "full"
            return oids, coverage
        except GitError as exc:
            err = str(exc)
            if "shallow" in err or "missing" in err or "bad object" in err:
                return [], "partial"
            raise
