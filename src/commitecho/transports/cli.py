"""CommitEcho CLI – init, doctor, status, index, show, diff, verify, export."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from commitecho.git.adapter import GitAdapter, GitError, discover_repository
from commitecho.storage.db import open_drafts_db, open_index_db


def _get_git_and_dbs(repo: str | None):
    """Resolve the Git repository and open database connections."""
    try:
        git = GitAdapter.from_path(repo or Path.cwd())
    except GitError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    drafts = open_drafts_db(git.repo_info.common_dir)
    index = open_index_db(git.repo_info.common_dir)
    return git, drafts, index


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="commitecho")
def main() -> None:
    """CommitEcho – preserve and recall the decisions behind code changes."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command()
@click.option("--repo", default=None, help="Path to the Git repository.")
def init(repo: str | None) -> None:
    """Initialise CommitEcho for the current repository.

    Creates .commitecho/config.json and the commitecho/ private store directory.
    """
    git, drafts, index = _get_git_and_dbs(repo)
    info = git.repo_info

    commitecho_dir = Path(info.worktree_dir) / ".commitecho"
    commitecho_dir.mkdir(exist_ok=True)
    (commitecho_dir / "records").mkdir(exist_ok=True)

    config_path = commitecho_dir / "config.json"
    if not config_path.exists():
        config = {
            "schema_version": 1,
            "portable_project_id": None,
        }
        config_path.write_text(json.dumps(config, indent=2))
        click.echo(f"Created {config_path}")
    else:
        click.echo(f"Already initialised: {config_path}")

    click.echo(f"Private store: {Path(info.common_dir) / 'commitecho'}")
    click.echo("Done. Add .commitecho/records/ to version control and .commitecho/config.json.")
    click.echo("Add commitecho/drafts.sqlite and commitecho/index.sqlite to .gitignore.")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@main.command()
@click.option("--repo", default=None, help="Path to the Git repository.")
def doctor(repo: str | None) -> None:
    """Check Git, Python, SQLite FTS5, server availability, skill version, and client configs."""
    import sqlite3

    from commitecho.integrations.profiles import ALL_PROFILES, SKILL_VERSION, _SKILL_TEMPLATE

    ok = True

    # Git availability
    try:
        git = GitAdapter.from_path(repo or Path.cwd())
        click.echo(f"[ok] Git: worktree={git.repo_info.worktree_dir}")
    except GitError as exc:
        click.echo(f"[fail] Git: {exc}", err=True)
        ok = False
        git = None

    # Python version
    pv = sys.version_info
    if pv >= (3, 12):
        click.echo(f"[ok] Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        click.echo(f"[warn] Python {pv.major}.{pv.minor}.{pv.micro} – 3.12+ recommended")

    # SQLite FTS5
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
        click.echo("[ok] SQLite FTS5 available")
    except Exception as exc:
        click.echo(f"[fail] SQLite FTS5 not available: {exc}", err=True)
        ok = False

    # MCP package
    try:
        import mcp
        click.echo(f"[ok] mcp package available ({getattr(mcp, '__version__', 'unknown')})")
    except ImportError:
        click.echo("[fail] mcp package not installed", err=True)
        ok = False

    if git:
        # Database connectivity
        try:
            open_drafts_db(git.repo_info.common_dir)
            open_index_db(git.repo_info.common_dir)
            click.echo("[ok] Draft and index databases opened successfully")
        except Exception as exc:
            click.echo(f"[fail] Database error: {exc}", err=True)
            ok = False

        # Skill version check
        click.echo(f"\n--- Skill (version {SKILL_VERSION}) ---")
        worktree = Path(git.repo_info.worktree_dir)
        skill_paths_seen: set[str] = set()
        for profile in ALL_PROFILES.values():
            if profile.skill_path in skill_paths_seen:
                continue
            skill_paths_seen.add(profile.skill_path)
            skill_file = worktree / profile.skill_path
            if not skill_file.exists():
                click.echo(f"[missing] {profile.skill_path}: skill not installed (run 'commitecho setup')")
            elif skill_file.read_text(encoding="utf-8") == _SKILL_TEMPLATE:
                click.echo(f"[ok] {profile.skill_path}: skill version {SKILL_VERSION} matches")
            else:
                click.echo(
                    f"[warn] {profile.skill_path}: skill file differs from current version "
                    f"{SKILL_VERSION} (run 'commitecho setup' to update)"
                )

        # Client config block detection
        click.echo("\n--- Client configuration ---")
        import json as _json
        for profile in ALL_PROFILES.values():
            config_file = worktree / profile.mcp_config_path
            if not config_file.exists():
                click.echo(f"[missing] {profile.display_name}: {profile.mcp_config_path} not found")
                continue
            try:
                config = _json.loads(config_file.read_text(encoding="utf-8"))
                servers = config.get(profile.mcp_servers_key, {})
                if "commitecho" in servers:
                    click.echo(f"[ok] {profile.display_name}: commitecho entry present in {profile.mcp_config_path}")
                else:
                    click.echo(
                        f"[warn] {profile.display_name}: {profile.mcp_config_path} exists "
                        "but has no 'commitecho' server entry"
                    )
            except Exception as exc:
                click.echo(f"[fail] {profile.display_name}: could not parse {profile.mcp_config_path}: {exc}", err=True)

    if ok:
        click.echo("\nAll checks passed.")
    else:
        click.echo("\nSome checks failed. See above for details.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command()
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--change-id", default=None, help="Filter to a specific change.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def status(repo: str | None, change_id: str | None, as_json: bool) -> None:
    """Show pending changes and indexing coverage."""
    from commitecho.application.retrieve import RetrieveService

    git, drafts, index = _get_git_and_dbs(repo)
    retrieve = RetrieveService(drafts, index, git)
    result = retrieve.get_status(change_id=change_id)

    if as_json:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    click.echo(f"Worktree:  {result['worktree']}")
    click.echo(f"HEAD:      {result['head_oid'] or '(unborn)'}")
    click.echo(f"Indexed commits: {result['indexed_commit_count']} ({result['coverage']})")
    if result["open_changes"]:
        click.echo("\nOpen changes:")
        for c in result["open_changes"]:
            click.echo(f"  [{c['status']:9}] {c['change_id'][:8]}  {c['title']}")
    else:
        click.echo("No open changes.")


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------


@main.command("index")
@click.option("--repo", default=None, help="Path to the Git repository.")
def rebuild_index(repo: str | None) -> None:
    """Rebuild the history index from committed Git objects.

    Scans .commitecho/records/ JSON files reachable from HEAD and populates
    index.sqlite.  Safe to re-run; existing entries are skipped.
    """
    import subprocess
    git, drafts, index = _get_git_and_dbs(repo)
    info = git.repo_info

    head_oid = git.head_oid()
    if head_oid is None:
        click.echo("Repository has no commits yet.")
        return

    # Enumerate all commits reachable from HEAD
    result = subprocess.run(
        ["git", "log", "--format=%H", head_oid],
        capture_output=True, text=True,
        cwd=info.worktree_dir,
    )
    oids = result.stdout.strip().splitlines()
    click.echo(f"Scanning {len(oids)} commits...")

    from datetime import datetime, timezone

    indexed = 0
    for oid in oids:
        already = index.execute(
            "SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (oid,)
        ).fetchone()
        if already:
            continue

        now = datetime.now(timezone.utc).isoformat()

        # Always mark the commit as scanned so ancestry queries work correctly
        # even for commits that carry no CommitEcho records.
        try:
            parent_oid: str | None = None
            try:
                parent_oid = git.resolve(f"{oid}^")
            except Exception:
                pass  # root commit
            index.execute(
                "INSERT OR IGNORE INTO indexed_commits "
                "(commit_oid, repository_id, parent_oid, indexed_at) VALUES (?, ?, ?, ?)",
                (oid, info.common_dir, parent_oid, now),
            )
            index.commit()
        except Exception as exc:
            click.echo(f"  [warn] {oid[:8]}: could not mark commit: {exc}")
            continue

        # Check for CommitEcho-Record trailer
        trailers = git.read_commit_trailers(oid)
        record_ids = trailers.get("CommitEcho-Record", [])
        if not record_ids:
            continue

        for record_id in record_ids:
            record_path = f".commitecho/records/{record_id}.json"
            # Read the record blob from the commit tree
            read_result = subprocess.run(
                ["git", "show", f"{oid}:{record_path}"],
                capture_output=True, text=True,
                cwd=info.worktree_dir,
            )
            if read_result.returncode != 0:
                click.echo(f"  [warn] {oid[:8]}: record file not found at {record_path}")
                continue
            try:
                raw = read_result.stdout
                record_data = json.loads(raw)
                _index_record(index, oid, record_id, record_path, record_data, raw)
                indexed += 1
            except Exception as exc:
                click.echo(f"  [warn] {oid[:8]}: failed to parse {record_path}: {exc}")

    click.echo(f"Indexed {indexed} new records.")


def _index_record(index, commit_oid: str, record_id: str, record_path: str, data: dict, raw: str) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    index.execute(
        """
        INSERT OR IGNORE INTO indexed_records
            (record_id, commit_oid, record_path, schema_version, change_id, summary, raw_json, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            commit_oid,
            record_path,
            data.get("schema_version", 1),
            data.get("change_id", ""),
            data.get("summary", ""),
            raw,
            now,
        ),
    )

    for decision in data.get("decisions", []):
        rev_id = decision.get("revision_id", "")
        if not rev_id:
            continue
        index.execute(
            """
            INSERT OR IGNORE INTO indexed_decisions
                (revision_id, record_id, decision_id, disposition, problem, choice, rationale, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rev_id,
                record_id,
                decision.get("decision_id", ""),
                decision.get("disposition", "proposed"),
                decision.get("problem", ""),
                decision.get("choice", ""),
                decision.get("rationale", ""),
                decision.get("captured_at", now),
            ),
        )
        # Index paths
        for path in decision.get("paths", []):
            index.execute(
                "INSERT INTO indexed_paths (revision_id, path) VALUES (?, ?)",
                (rev_id, path),
            )
        # FTS5 insert — guard against duplicates (FTS5 has no OR IGNORE)
        fts_exists = index.execute(
            "SELECT 1 FROM decisions_fts WHERE revision_id = ?", (rev_id,)
        ).fetchone()
        if not fts_exists:
            index.execute(
                "INSERT INTO decisions_fts (revision_id, problem, choice, rationale) VALUES (?, ?, ?, ?)",
                (rev_id, decision.get("problem", ""), decision.get("choice", ""), decision.get("rationale", "")),
            )

    index.commit()


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@main.command()
@click.argument("record_id")
@click.option("--repo", default=None, help="Path to the Git repository.")
def show(record_id: str, repo: str | None) -> None:
    """Show a specific committed record by ID."""
    git, drafts, index = _get_git_and_dbs(repo)

    row = index.execute(
        "SELECT * FROM indexed_records WHERE record_id = ?", (record_id,)
    ).fetchone()
    if row is None:
        # Try the draft store
        row = drafts.execute(
            "SELECT * FROM commit_records WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row is None:
            click.echo(f"Record '{record_id}' not found.", err=True)
            sys.exit(1)
        click.echo(json.dumps(dict(row), indent=2, default=str))
        return

    click.echo(json.dumps(json.loads(row["raw_json"]), indent=2))


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@main.command()
@click.argument("commit_oid")
@click.option("--record-id", default=None)
@click.option("--repo", default=None)
def verify(commit_oid: str, record_id: str | None, repo: str | None) -> None:
    """Verify that COMMIT_OID correctly carries its CommitEcho record."""
    from commitecho.application.verify import VerifyService

    git, drafts, index = _get_git_and_dbs(repo)
    svc = VerifyService(drafts, index, git)
    result = svc.verify_commit(commit_oid=commit_oid, record_id=record_id)
    click.echo(json.dumps(result, indent=2, default=str))
    if result.get("outcome") != "exact":
        sys.exit(1)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@main.command()
@click.argument("from_ref")
@click.argument("to_ref")
@click.option("--path", "path_filter", default=None)
@click.option("--repo", default=None)
@click.option("--json", "as_json", is_flag=True)
def diff(from_ref: str, to_ref: str, path_filter: str | None, repo: str | None, as_json: bool) -> None:
    """Compare CommitEcho decision history between FROM_REF and TO_REF."""
    from commitecho.application.retrieve import RetrieveService

    git, drafts, index = _get_git_and_dbs(repo)
    retrieve = RetrieveService(drafts, index, git)
    result = retrieve.compare_history(from_ref=from_ref, to_ref=to_ref, path=path_filter)

    if as_json:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    click.echo(f"Range: {from_ref}..{to_ref}")
    if result.get("is_ancestor") is False:
        click.echo("[warn] from_ref is not an ancestor of to_ref.")
    for note in result.get("coverage_notes", []):
        click.echo(f"[coverage] {note}")
    decisions = result.get("decisions", [])
    if not decisions:
        click.echo("No CommitEcho decisions found in this range.")
        return
    for d in decisions:
        click.echo(f"\n  [{d['disposition']:9}] {d['problem']}")
        click.echo(f"             -> {d['choice']}")


# ---------------------------------------------------------------------------
# export (draft)
# ---------------------------------------------------------------------------


@main.command()
@click.argument("change_id")
@click.option("--repo", default=None)
@click.option("--output", "-o", default=None, help="Output file path (default: stdout).")
def export(change_id: str, repo: str | None, output: str | None) -> None:
    """Export draft decision records for CHANGE_ID as JSON.

    This is for backup/handoff purposes.  Exported content has not been committed.
    """
    git, drafts, index = _get_git_and_dbs(repo)

    rows = drafts.execute(
        "SELECT * FROM decision_revisions WHERE change_id = ?", (change_id,)
    ).fetchall()
    if not rows:
        click.echo(f"No decisions found for change '{change_id}'.", err=True)
        sys.exit(1)

    exported = [dict(r) for r in rows]
    payload = json.dumps({"change_id": change_id, "decisions": exported}, indent=2, default=str)

    if output:
        Path(output).write_text(payload, encoding="utf-8")
        click.echo(f"Exported {len(exported)} decisions to {output}")
    else:
        click.echo(payload)

# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@main.command()
@click.option("--client", "client_ids", multiple=True,
              help="Client IDs to configure (codex, antigravity, copilot_vscode). Repeat for multiple.")
@click.option("--repo", default=None, help="Path to the Git repository / project root.")
@click.option("--server-cmd", default=None,
              help="Command used to launch the server (default: auto-detect 'commitecho serve').")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files.")
def setup(client_ids: tuple[str, ...], repo: str | None, server_cmd: str | None, dry_run: bool) -> None:
    """Install CommitEcho configuration for one or more coding agent clients.

    Merges into existing config files.  Use --dry-run to preview changes.
    """
    from commitecho.integrations.profiles import ALL_PROFILES, SetupGenerator

    git, _, _ = _get_git_and_dbs(repo)
    worktree = git.repo_info.worktree_dir

    if not client_ids:
        client_ids = tuple(ALL_PROFILES.keys())

    cmd: list[str]
    if server_cmd:
        # shlex-split so quoted paths with spaces survive (cross-platform via
        # posix=False on Windows keeps backslashes intact).
        import shlex
        cmd = shlex.split(server_cmd, posix=(sys.platform != "win32"))
    else:
        # sys.executable may contain spaces on Windows (e.g. "C:\Program Files\…").
        # Store it as a single array element; all three clients consume the array
        # directly in JSON so no shell quoting is needed.
        cmd = [sys.executable, "-m", "commitecho", "serve"]

    generator = SetupGenerator(worktree, cmd)

    for cid in client_ids:
        profile = ALL_PROFILES.get(cid)
        if profile is None:
            click.echo(f"[warn] Unknown client '{cid}'. Supported: {', '.join(ALL_PROFILES)}", err=True)
            continue
        click.echo(f"\n[{profile.display_name}]")
        changes = generator.generate(profile, dry_run=dry_run)
        for change in changes:
            click.echo(f"  {change}")

    if dry_run:
        click.echo("\n(dry-run: no files were written)")
    else:
        click.echo("\nSetup complete.")

