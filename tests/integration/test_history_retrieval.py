"""Integration tests for history retrieval: temporal scoping, range queries,
branch conflict detection, and shallow clone coverage reporting.

All tests require a real Git executable and create temporary repositories.
"""

from __future__ import annotations

import json
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


def _add_commit(repo: Path, filename: str, content: str, message: str) -> str:
    """Stage a new file and commit it. Returns the full commit OID."""
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(repo), capture_output=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(repo)
    ).stdout.strip()


def _open_services(repo: Path):
    git = GitAdapter.from_path(repo)
    drafts = open_drafts_db(git.repo_info.common_dir)
    index = open_index_db(git.repo_info.common_dir)
    return git, drafts, index


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(repo)
    ).stdout.strip()


def _index_commits(repo: Path, git: GitAdapter, index, *commit_oids: str) -> None:
    """Populate the index database for the given commit OIDs."""
    from commitecho.transports.cli import _index_record
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for oid in commit_oids:
        try:
            parent = git.resolve(f"{oid}^")
        except Exception:
            parent = None
        index.execute(
            "INSERT OR IGNORE INTO indexed_commits "
            "(commit_oid, repository_id, parent_oid, indexed_at) VALUES (?, ?, ?, ?)",
            (oid, git.repo_info.common_dir, parent, now),
        )
        index.commit()

        for record_id in git.read_commit_trailers(oid).get("CommitEcho-Record", []):
            record_path = f".commitecho/records/{record_id}.json"
            r = subprocess.run(
                ["git", "show", f"{oid}:{record_path}"],
                capture_output=True, text=True, cwd=str(repo),
            )
            if r.returncode == 0:
                _index_record(index, oid, record_id, record_path, json.loads(r.stdout), r.stdout)


def test_evidence_links_survive_prepare_and_clone(tmp_path):
    from commitecho.application.capture import CaptureService
    from commitecho.application.prepare import PrepareService
    from commitecho.application.retrieve import RetrieveService

    repo = _make_repo(tmp_path)
    git, drafts, _ = _open_services(repo)
    capture = CaptureService(drafts, git)
    change = capture.begin_change(title="evidence", client="test", operation_id="begin")
    evidence_id = str(uuid.uuid4())
    decision = {"problem": "retry safety", "choice": "dedupe", "rationale": "same input",
                "alternatives": [{"choice": "ignore", "evidence_ids": [evidence_id]}]}

    with pytest.raises(ValueError, match="does not belong"):
        capture.record_decisions(change_id=change["change_id"], expected_revision=0,
                                 operation_id="missing", decisions=[decision])

    result = capture.record_decisions(
        change_id=change["change_id"], expected_revision=0, operation_id="capture",
        decisions=[decision],
        evidence=[{"evidence_id": evidence_id, "kind": "test_result", "origin": "agent_reported",
                   "client": "claude_code", "content": "retry produced one result"}],
    )
    assert result["evidence_ids"] == [evidence_id]

    other = capture.begin_change(title="other", client="test", operation_id="other")
    with pytest.raises(ValueError, match="does not belong"):
        capture.record_decisions(change_id=other["change_id"], expected_revision=0,
                                 operation_id="foreign", decisions=[decision])

    (repo / "code.py").write_text("pass\n")
    subprocess.run(["git", "add", "code.py"], cwd=repo, check=True)
    prepared = PrepareService(drafts, git).prepare_commit(
        change_id=change["change_id"], expected_revision=1,
        selected_revision_ids=result["revision_ids"], summary="retry safety", operation_id="prepare")
    portable = json.loads((repo / prepared["record_path"]).read_text())
    assert [e["evidence_id"] for e in portable["evidence"]] == [evidence_id]
    subprocess.run(["git", "add", prepared["record_path"]], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", f"retry safety\n\n{prepared['trailer']}"],
                   cwd=repo, check=True, capture_output=True)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(repo), str(clone)], check=True, capture_output=True)
    clone_git, clone_drafts, clone_index = _open_services(clone)
    assert clone_drafts.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    _index_commits(clone, clone_git, clone_index, _head(clone))
    retrieve = RetrieveService(clone_drafts, clone_index, clone_git)
    found = retrieve.search_history(question="retry")
    assert evidence_id in found["results"][0]["evidence_ids"]
    evidence = retrieve.get_evidence(evidence_id=evidence_id)
    assert evidence["found"] is True
    assert evidence["source"] == "index"
    assert evidence["content"] == "retry produced one result"
    assert evidence["origin"] == "agent_reported"
    assert evidence["client"] == "claude_code"
    assert evidence["record_id"] == prepared["record_id"]
    assert evidence["commit_oid"] == _head(clone)
    assert retrieve.get_evidence(evidence_id="missing") == {"found": False, "evidence_id": "missing"}


def test_superseding_revision_link_survives_clone(tmp_path):
    from commitecho.application.retrieve import RetrieveService
    from tests.fixtures.build_fixtures import build_later_reversal

    built = build_later_reversal(tmp_path)
    source = Path(built["repo"])
    original = json.loads(subprocess.run(
        ["git", "show", f"{built['commit_oid_a']}:.commitecho/records/{built['record_id_a']}.json"],
        cwd=source, check=True, capture_output=True, text=True,
    ).stdout)
    predecessor_id = original["decisions"][0]["revision_id"]

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(source), str(clone)], check=True, capture_output=True)
    git, drafts, index = _open_services(clone)
    _index_commits(clone, git, index, built["commit_oid_a"], built["commit_oid_b"])
    record = RetrieveService(drafts, index, git).get_evidence(record_id=built["record_id_b"])["record"]
    assert record["decisions"][0]["predecessor_revision_ids"] == [predecessor_id]


# ---------------------------------------------------------------------------
# Temporal scoping
# ---------------------------------------------------------------------------


class TestTemporalScoping:
    def test_search_at_earlier_commit_excludes_later_records(self, tmp_path, monkeypatch):
        """Records committed after at_ref must not appear in search results."""
        from commitecho.application.capture import CaptureService
        from commitecho.application.prepare import PrepareService
        from commitecho.application.retrieve import RetrieveService

        repo = _make_repo(tmp_path)
        git, drafts, index = _open_services(repo)

        capture = CaptureService(drafts, git)
        prepare = PrepareService(drafts, git)

        # --- Commit A: upload dedup decision ---
        begin_a = capture.begin_change(
            title="change-A", client="test", operation_id=str(uuid.uuid4())
        )
        rec_a = capture.record_decisions(
            change_id=begin_a["change_id"],
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{
                "problem": "upload dedup",
                "choice": "content hash",
                "rationale": "avoids rename bypass",
                "disposition": "selected",
                "code_scope": {"paths": ["src/uploads.py"], "line_ranges": [[3, 5]]},
            }],
        )
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "uploads.py").write_text("def upload(): pass\n")
        subprocess.run(["git", "add", "src/uploads.py"], cwd=str(repo), capture_output=True)

        prep_a = prepare.prepare_commit(
            change_id=begin_a["change_id"],
            expected_revision=1,
            selected_revision_ids=[rec_a["revision_ids"][0]],
            summary="Add upload dedup.",
            operation_id=str(uuid.uuid4()),
        )
        subprocess.run(["git", "add", prep_a["record_path"]], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: upload dedup\n\n{prep_a['trailer']}\n"],
            cwd=str(repo), capture_output=True,
        )
        commit_a = _head(repo)

        # --- Commit B: rate limiting decision (later) ---
        git2, drafts2, index2 = _open_services(repo)
        capture2 = CaptureService(drafts2, git2)
        prepare2 = PrepareService(drafts2, git2)

        begin_b = capture2.begin_change(
            title="change-B", client="test", operation_id=str(uuid.uuid4())
        )
        rec_b = capture2.record_decisions(
            change_id=begin_b["change_id"],
            expected_revision=0,
            operation_id=str(uuid.uuid4()),
            decisions=[{
                "problem": "rate limiting",
                "choice": "token bucket",
                "rationale": "smooth traffic",
                "disposition": "selected",
                "code_scope": {"paths": ["src/rate.py"], "line_ranges": [[10, 20]]},
            }],
        )
        (repo / "src" / "rate.py").write_text("class Bucket: pass\n")
        subprocess.run(["git", "add", "src/rate.py"], cwd=str(repo), capture_output=True)

        prep_b = prepare2.prepare_commit(
            change_id=begin_b["change_id"],
            expected_revision=1,
            selected_revision_ids=[rec_b["revision_ids"][0]],
            summary="Add rate limiting.",
            operation_id=str(uuid.uuid4()),
        )
        subprocess.run(["git", "add", prep_b["record_path"]], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: rate limit\n\n{prep_b['trailer']}\n"],
            cwd=str(repo), capture_output=True,
        )
        commit_b = _head(repo)

        # Index both commits
        git3, drafts3, index3 = _open_services(repo)
        _index_commits(repo, git3, index3, commit_a, commit_b)
        retrieve = RetrieveService(drafts3, index3, git3)

        # Query at A: must see upload decision, must NOT see rate decision
        result_a = retrieve.search_history(question="upload", at_ref=commit_a)
        problems_a = [d["problem"] for d in result_a["results"]]
        assert any("upload" in p.lower() or "dedup" in p.lower() for p in problems_a), \
            f"Expected upload decision at A, got: {problems_a}"
        assert all("rate" not in p.lower() for p in problems_a), \
            f"Rate decision must not be visible at A, got: {problems_a}"

        # Query at B: must see rate decision
        result_b = retrieve.search_history(question="rate", at_ref=commit_b)
        problems_b = [d["problem"] for d in result_b["results"]]
        assert any("rate" in p.lower() for p in problems_b), \
            f"Expected rate decision at B, got: {problems_b}"

        assert retrieve.search_history(question="upload", path="src/rate.py")["results"] == []
        assert len(retrieve.search_history(question="upload", path="src/uploads.py")["results"]) == 1
        assert len(retrieve.search_history(path="src/uploads.py", line=4)["results"]) == 1
        assert retrieve.search_history(path="src/uploads.py", line=9)["results"] == []
        ranged = retrieve.search_history(path="src/rate.py", from_ref=commit_a, to_ref=commit_b)
        assert [r["commit_oid"] for r in ranged["results"]] == [commit_b]
        assert retrieve.search_history(path="src/rate.py", from_ref=commit_b,
                                       to_ref=commit_b)["coverage"] == "full"
        assert retrieve.search_history(path="src/rate.py", from_ref=commit_b,
                                       to_ref=commit_b)["results"] == []
        with pytest.raises(ValueError, match="used together"):
            retrieve.search_history(path="src/rate.py", from_ref=commit_a)
        with pytest.raises(ValueError, match="used together"):
            retrieve.search_history(path="src/rate.py", at_ref=commit_b,
                                    from_ref=commit_a, to_ref=commit_b)
        with pytest.raises(ValueError, match="requires path"):
            retrieve.search_history(question="rate", line=12)
        assert retrieve.search_history(path="src/rate.py", from_ref="",
                                       to_ref=commit_b)["coverage"] == "partial"

        invalid = retrieve.search_history(question="rate", at_ref="does-not-exist")
        assert invalid["results"] == [] and invalid["coverage"] == "partial"

        def failed_history(*_args, **_kwargs):
            raise RuntimeError("Git history unavailable")
        monkeypatch.setattr(git3, "reachable_commit_oids", failed_history)
        unavailable = retrieve.search_history(question="rate", at_ref=commit_b)
        assert unavailable["results"] == [] and unavailable["coverage"] == "partial"


# ---------------------------------------------------------------------------
# Range queries
# ---------------------------------------------------------------------------


class TestRangeQueries:
    def test_compare_history_excludes_commits_before_from_ref(self, tmp_path):
        """compare_history(A, B) counts only commits reachable from B but not from A."""
        from commitecho.application.retrieve import RetrieveService

        repo = _make_repo(tmp_path)
        commit_a = _add_commit(repo, "a.py", "a=1", "commit A")
        commit_b = _add_commit(repo, "b.py", "b=2", "commit B")

        git, drafts, index = _open_services(repo)
        result = RetrieveService(drafts, index, git).compare_history(
            from_ref=commit_a, to_ref=commit_b
        )

        assert result["from_oid"] == commit_a
        assert result["to_oid"] == commit_b
        assert result["is_ancestor"] is True
        assert result["range_commit_count"] == 1  # only commit B

    def test_compare_history_reports_branch_divergence(self, tmp_path):
        """compare_history reports is_ancestor=False and a merge_base when the refs diverge."""
        from commitecho.application.retrieve import RetrieveService

        repo = _make_repo(tmp_path)
        _add_commit(repo, "base.py", "x=0", "base commit")

        # Diverge: branch-a and main both extend from base
        subprocess.run(["git", "checkout", "-b", "branch-a"], cwd=str(repo), capture_output=True)
        commit_on_a = _add_commit(repo, "a.py", "a=1", "branch A commit")

        subprocess.run(["git", "checkout", "main"], cwd=str(repo), capture_output=True)
        commit_on_main = _add_commit(repo, "m.py", "m=1", "main commit")

        git, drafts, index = _open_services(repo)
        result = RetrieveService(drafts, index, git).compare_history(
            from_ref=commit_on_a, to_ref=commit_on_main
        )

        assert result["is_ancestor"] is False
        assert result["merge_base"] is not None
        assert len(result["coverage_notes"]) > 0

    def test_linear_supersession_is_not_a_conflict(self, tmp_path):
        from commitecho.application.retrieve import RetrieveService
        from tests.fixtures.build_fixtures import build_later_reversal

        built = build_later_reversal(tmp_path)
        repo = Path(built["repo"])
        git, drafts, index = _open_services(repo)
        _index_commits(repo, git, index, built["commit_oid_a"], built["commit_oid_b"])
        result = RetrieveService(drafts, index, git).compare_history(
            from_ref=git.resolve(f"{built['commit_oid_a']}^"), to_ref=built["commit_oid_b"]
        )
        assert len(result["decisions"]) == 2
        by_commit = {d["commit_oid"]: d for d in result["decisions"]}
        old = by_commit[built["commit_oid_a"]]
        new = by_commit[built["commit_oid_b"]]
        assert old["decision_id"] == new["decision_id"]
        assert old["revision_id"] in new["predecessor_revision_ids"]
        assert result["conflicts"] == []

    def test_divergent_branches_are_a_conflict(self, tmp_path):
        from commitecho.application.retrieve import RetrieveService
        from tests.fixtures.build_fixtures import build_branch_conflict

        built = build_branch_conflict(tmp_path)
        repo = Path(built["repo"])
        git, drafts, index = _open_services(repo)
        _index_commits(repo, git, index, built["main_commit_oid"], built["branch_commit_oid"])
        result = RetrieveService(drafts, index, git).compare_history(
            from_ref=built["main_commit_oid"], to_ref=built["branch_commit_oid"]
        )
        assert len(result["decisions"]) == 1  # to_ref branch only
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["decision_id"] == built["shared_decision_id"]
        assert len(result["conflicts"][0]["conflicting_revision_ids"]) == 2

    def test_explicit_predecessor_resolves_incomparable_commits(self):
        from unittest.mock import Mock
        from commitecho.application.retrieve import _detect_conflicts

        git = Mock()
        git.reachable_commit_oids.side_effect = lambda oid: ([oid], "full")
        revisions = [
            {"decision_id": "decision", "revision_id": "old", "commit_oid": "a",
             "predecessor_revision_ids": []},
            {"decision_id": "decision", "revision_id": "new", "commit_oid": "b",
             "predecessor_revision_ids": ["old"]},
        ]
        assert _detect_conflicts(revisions, git) == []


# ---------------------------------------------------------------------------
# Shallow clone coverage
# ---------------------------------------------------------------------------


class TestShallowCloneCoverage:
    def test_shallow_clone_reports_partial_coverage(self, tmp_path):
        """A shallow clone (via file://) produces coverage=partial when the shallow
        file is present. Skips gracefully if git converts the clone to a full clone."""
        source = _make_repo(tmp_path, "source")
        _add_commit(source, "f1.py", "x=1", "commit 1")
        _add_commit(source, "f2.py", "x=2", "commit 2")

        shallow = tmp_path / "shallow"
        result = subprocess.run(
            ["git", "clone", "--depth=1", source.as_uri(), str(shallow)],
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip("git clone --depth=1 via file:// not available in this environment")

        git = GitAdapter.from_path(shallow)
        head = git.head_oid()
        assert head is not None

        _, coverage = git.reachable_commit_oids(head)

        shallow_file = Path(git.repo_info.common_dir) / "shallow"
        if not shallow_file.exists():
            pytest.skip("git did not create a shallow file; clone may have been converted")

        assert coverage == "partial"
