"""CommitEcho CLI – init, doctor, status, index, show, diff, verify, export."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import click

from commitecho.git.adapter import GitAdapter, GitError, discover_repository
from commitecho.storage.db import open_drafts_db, open_index_db


def _resolve_repo(repo: str | None) -> GitAdapter:
    """Resolve the Git repository according to precedence contract:
    1. Explicit --repo wins, including explicit --repo .
    2. A supplied COMMITECHO_REPO wins when the argument is omitted.
    3. Documented CLAUDE_PROJECT_DIR when the above are absent.
    4. Otherwise use the process working directory and Git discovery.
    """
    if repo is not None:
        target = Path(repo)
    elif os.environ.get("COMMITECHO_REPO"):
        target = Path(os.environ["COMMITECHO_REPO"])
    elif os.environ.get("CLAUDE_PROJECT_DIR"):
        target = Path(os.environ["CLAUDE_PROJECT_DIR"])
    else:
        target = Path.cwd()

    try:
        return GitAdapter.from_path(target)
    except GitError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


def _get_git_and_dbs(repo: str | None):
    """Resolve the Git repository and open database connections."""
    git = _resolve_repo(repo)
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


@main.command()
@click.option("--repo", default=None, help="Path to the Git repository to serve.")
def serve(repo: str | None) -> None:
    """Start the CommitEcho MCP server on stdio for REPO."""
    import asyncio

    from commitecho.transports.mcp_server import run_server

    git = _resolve_repo(repo)
    asyncio.run(run_server(Path(git.repo_info.worktree_dir)))


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
    has_missing = False
    has_warnings = False

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
        has_warnings = True

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
        from commitecho.transports.mcp_server import create_server  # noqa: F401
        click.echo(f"[ok] mcp package available ({getattr(mcp, '__version__', 'unknown')})")
    except ImportError as exc:
        click.echo(f"[fail] mcp package incompatible or not installed: {exc}", err=True)
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
                has_missing = True
            elif skill_file.read_text(encoding="utf-8") == _SKILL_TEMPLATE:
                click.echo(f"[ok] {profile.skill_path}: skill version {SKILL_VERSION} matches")
            else:
                click.echo(
                    f"[warn] {profile.skill_path}: skill file differs from current version "
                    f"{SKILL_VERSION} (run 'commitecho setup' to update)"
                )
                has_warnings = True

        # Activation instructions & rules check
        click.echo("\n--- Activation instructions & rules ---")
        import re
        instr_paths_seen: set[str] = set()
        for profile in ALL_PROFILES.values():
            if not profile.instruction_path or profile.instruction_path in instr_paths_seen:
                continue
            instr_paths_seen.add(profile.instruction_path)
            instr_file = worktree / profile.instruction_path
            if not instr_file.exists():
                click.echo(f"[missing] {profile.display_name}: {profile.instruction_path} not found (run 'commitecho setup')")
                has_missing = True
                continue
            try:
                content = instr_file.read_text(encoding="utf-8")
                if getattr(profile, "instruction_format", "plain") == "rule":
                    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
                    if not fm_match:
                        click.echo(
                            f"[warn] {profile.display_name}: {profile.instruction_path} missing trigger frontmatter (run 'commitecho setup')"
                        )
                        has_warnings = True
                    else:
                        fm_text = fm_match.group(1)
                        has_trigger = bool(re.search(r"^trigger:\s*\S+", fm_text, re.MULTILINE))
                        has_desc = bool(re.search(r"^description:\s*\S+", fm_text, re.MULTILINE))
                        if not (has_trigger and has_desc):
                            click.echo(
                                f"[warn] {profile.display_name}: {profile.instruction_path} frontmatter missing trigger or description"
                            )
                            has_warnings = True
                        elif "<!-- commitecho-activation -->" not in content:
                            click.echo(
                                f"[warn] {profile.display_name}: {profile.instruction_path} missing CommitEcho activation marker"
                            )
                            has_warnings = True
                        else:
                            click.echo(f"[ok] {profile.display_name}: valid activation rule in {profile.instruction_path}")
                else:
                    if "<!-- commitecho-activation -->" in content:
                        click.echo(f"[ok] {profile.display_name}: activation block present in {profile.instruction_path}")
                    else:
                        click.echo(
                            f"[warn] {profile.display_name}: {profile.instruction_path} missing CommitEcho activation block"
                        )
                        has_warnings = True
            except Exception as exc:
                click.echo(f"[fail] {profile.display_name}: could not read {profile.instruction_path}: {exc}", err=True)
                ok = False

        # Check for legacy skill paths and AGENTS.override.md
        legacy_skills = [
            worktree / ".codex/skills/commitecho.md",
            worktree / ".agents/skills/commitecho.md",
        ]
        for leg in legacy_skills:
            if leg.exists():
                click.echo(
                    f"[warn] {leg.relative_to(worktree).as_posix()}: obsolete legacy skill file present "
                    "(run 'commitecho setup' to migrate)"
                )
                has_warnings = True

        if (worktree / "AGENTS.override.md").exists():
            click.echo(
                "[info] AGENTS.override.md is present: this takes precedence over AGENTS.md in Codex sessions"
            )

        # Client config block detection
        click.echo("\n--- Client configuration ---")
        import tomlkit
        for profile in ALL_PROFILES.values():
            config_file = worktree / profile.mcp_config_path
            if not config_file.exists():
                click.echo(f"[missing] {profile.display_name}: {profile.mcp_config_path} not found")
                has_missing = True
                continue
            try:
                raw = config_file.read_text(encoding="utf-8")
                config = (
                    tomlkit.parse(raw)
                    if profile.config_format == "toml"
                    else json.loads(raw)
                )
                servers = config.get(profile.mcp_servers_key, {})
                if "commitecho" in servers:
                    click.echo(f"[ok] {profile.display_name}: commitecho entry present in {profile.mcp_config_path}")
                else:
                    click.echo(
                        f"[warn] {profile.display_name}: {profile.mcp_config_path} exists "
                        "but has no 'commitecho' server entry"
                    )
                    has_warnings = True
            except Exception as exc:
                click.echo(f"[fail] {profile.display_name}: could not parse {profile.mcp_config_path}: {exc}", err=True)
                ok = False

    if not ok:
        click.echo("\nSome checks failed. See above for details.", err=True)
        sys.exit(1)
    elif has_missing or has_warnings:
        click.echo("\nCore checks passed; some client integrations are not installed or have warnings.")
    else:
        click.echo("\nAll checks passed.")


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
    for note in result["coverage_notes"]:
        click.echo(f"  {note}")
    for diagnostic in result["index_diagnostics"]:
        click.echo(
            f"  {diagnostic['commit_oid'][:8]} {diagnostic['record_path']}: "
            f"{diagnostic['error']}"
        )
    if result["open_changes"]:
        click.echo("\nOpen changes:")
        for c in result["open_changes"]:
            click.echo(f"  [{c['status']:9}] {c['change_id'][:8]}  {c['title']}")
    else:
        click.echo("No open changes.")
    if result["abandoned_changes"]:
        click.echo("\nAbandoned changes:")
        for c in result["abandoned_changes"]:
            click.echo(f"  {c['change_id'][:8]}  {c['title']}")


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
    git, drafts, index = _get_git_and_dbs(repo)
    info = git.repo_info

    head_oid = git.head_oid()
    if head_oid is None:
        click.echo("Repository has no commits yet.")
        return

    # Enumerate all commits reachable from HEAD
    try:
        oids, coverage = git.reachable_commit_oids(head_oid)
    except GitError as exc:
        raise click.ClickException(f"Cannot traverse Git history: {exc}") from exc
    if coverage == "partial":
        click.echo("  [warn] Git history is incomplete; index coverage will be partial.")
    click.echo(f"Scanning {len(oids)} commits...")

    from datetime import datetime, timezone

    indexed = 0
    for oid in oids:
        already = index.execute(
            "SELECT 1 FROM indexed_commits WHERE commit_oid = ?", (oid,)
        ).fetchone()
        if already:
            continue

        record_path = "<commit>"
        failures: list[tuple[str, str]] = []
        try:
            trailers = git.read_commit_trailers(oid)
            record_ids = trailers.get("CommitEcho-Record", [])
            records = []
            for record_id in record_ids:
                record_path = f".commitecho/records/{record_id}.json"
                try:
                    content = git.read_file_from_commit(oid, record_path)
                    if content is None:
                        raise ValueError("record file not found")
                    raw = content.decode("utf-8")
                    data = json.loads(raw)
                    _validate_record(data, record_id)
                    records.append((record_id, record_path, data, raw))
                except Exception as exc:
                    failures.append((record_path, str(exc)))
            if failures:
                raise ValueError(f"{len(failures)} invalid record(s)")

            parent_oid: str | None = None
            try:
                parent_oid = git.resolve(f"{oid}^")
            except Exception:
                pass  # root commit
            with index:
                index.execute(
                    "INSERT INTO indexed_commits "
                    "(commit_oid, repository_id, parent_oid, indexed_at) VALUES (?, ?, ?, ?)",
                    (oid, info.common_dir, parent_oid, datetime.now(timezone.utc).isoformat()),
                )
                for record_id, record_path, data, raw in records:
                    _index_record(index, oid, record_id, record_path, data, raw)
                index.execute("DELETE FROM index_diagnostics WHERE commit_oid = ?", (oid,))
            indexed += len(records)
        except Exception as exc:
            with index:
                for failed_path, error in failures or [(record_path, str(exc))]:
                    index.execute(
                        "INSERT OR REPLACE INTO index_diagnostics "
                        "(commit_oid, record_path, error, observed_at) VALUES (?, ?, ?, ?)",
                        (oid, failed_path, error, datetime.now(timezone.utc).isoformat()),
                    )
                    click.echo(f"  [warn] {oid[:8]}: {failed_path}: {error}")

    click.echo(f"Indexed {indexed} new records.")


def _index_record(index, commit_oid: str, record_id: str, record_path: str, data: dict, raw: str) -> None:
    from datetime import datetime, timezone
    _validate_record(data, record_id)
    now = datetime.now(timezone.utc).isoformat()

    existing = index.execute(
        "SELECT raw_json FROM indexed_records WHERE record_id = ?", (record_id,)
    ).fetchone()
    if existing is not None and json.loads(existing["raw_json"]) != data:
        raise ValueError(f"Record '{record_id}' has different content in another commit")

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
    index.execute(
        "INSERT OR IGNORE INTO indexed_commit_records (commit_oid, record_id, record_path) VALUES (?, ?, ?)",
        (commit_oid, record_id, record_path),
    )

    for decision in data.get("decisions", []):
        rev_id = decision.get("revision_id", "")
        if not rev_id:
            continue
        inserted = index.execute(
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
        index.execute(
            "INSERT OR IGNORE INTO indexed_record_decisions (record_id, revision_id) VALUES (?, ?)",
            (record_id, rev_id),
        )
        # Index paths
        if inserted.rowcount:
            for path in decision.get("code_scope", {}).get("paths", []):
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



def _validate_record(data: dict, record_id: str) -> None:
    from uuid import UUID

    from commitecho.domain.models import CommitRecord

    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported or missing record schema version")
    if data.get("record_id") != record_id:
        raise ValueError("record ID does not match commit trailer")
    if str(UUID(record_id)) != record_id:
        raise ValueError("record ID is not a canonical UUID")
    for field in ("change_id", "summary", "prepared_for", "decisions", "evidence", "created_at"):
        if field not in data:
            raise ValueError(f"missing record field: {field}")
    for decision in data["decisions"]:
        if "decision_id" not in decision or "revision_id" not in decision:
            raise ValueError("decision identity is missing")
    for evidence in data["evidence"]:
        if "evidence_id" not in evidence:
            raise ValueError("evidence identity is missing")
    CommitRecord.model_validate(data)


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
@click.option("--keep-open", is_flag=True, help="Keep this change open for another commit.")
@click.option("--repo", default=None)
def verify(commit_oid: str, record_id: str | None, keep_open: bool, repo: str | None) -> None:
    """Verify that COMMIT_OID correctly carries its CommitEcho record."""
    from commitecho.application.verify import VerifyService

    git, drafts, index = _get_git_and_dbs(repo)
    svc = VerifyService(drafts, index, git)
    result = svc.verify_commit(commit_oid=commit_oid, record_id=record_id, keep_open=keep_open)
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
    """Export a readable snapshot of draft decisions for CHANGE_ID as JSON."""
    git, drafts, index = _get_git_and_dbs(repo)

    rows = drafts.execute(
        "SELECT * FROM decision_revisions WHERE change_id = ? ORDER BY captured_at, rowid", (change_id,)
    ).fetchall()
    if not rows:
        click.echo(f"No decisions found for change '{change_id}'.", err=True)
        sys.exit(1)

    exported = []
    evidence_ids = set()
    for row in rows:
        decision = dict(row)
        for field in ("alternatives", "code_scope", "evidence_ids"):
            decision[field] = json.loads(decision[field])
        decision["predecessor_revision_ids"] = [
            r["predecessor_id"] for r in drafts.execute(
                "SELECT predecessor_id FROM revision_predecessors WHERE revision_id = ? ORDER BY predecessor_id",
                (decision["revision_id"],),
            )
        ]
        evidence_ids.update(decision["evidence_ids"])
        for alternative in decision["alternatives"]:
            evidence_ids.update(alternative.get("evidence_ids", []))
        exported.append(decision)
    evidence = [dict(r) for r in drafts.execute(
        "SELECT * FROM evidence WHERE change_id = ? ORDER BY evidence_id", (change_id,)
    ) if r["evidence_id"] in evidence_ids]
    payload = json.dumps({
        "format": "commitecho-draft-snapshot-v1",
        "change_id": change_id,
        "decisions": exported,
        "evidence": evidence,
    }, indent=2)

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
              help="Client IDs to configure (codex, antigravity, copilot_vscode, claude_code). Repeat for multiple.")
@click.option("--repo", default=None, help="Path to the Git repository / project root.")
@click.option("--server-cmd", default=None,
              help="Command used to launch the server (default: auto-detect 'commitecho serve').")
@click.option("--portable", is_flag=True,
              help="Configure portable server command ('commitecho serve') requiring PATH installation.")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files.")
def setup(
    client_ids: tuple[str, ...],
    repo: str | None,
    server_cmd: str | None,
    portable: bool,
    dry_run: bool,
) -> None:
    """Install CommitEcho configuration for one or more coding agent clients.

    Merges into existing config files. Use --dry-run to preview changes.
    """
    from commitecho.integrations.profiles import ALL_PROFILES, SetupGenerator

    if server_cmd and portable:
        raise click.UsageError("Cannot specify both --server-cmd and --portable.")

    # Preflight client IDs
    if not client_ids:
        target_client_ids = tuple(ALL_PROFILES.keys())
    else:
        for cid in client_ids:
            if cid not in ALL_PROFILES:
                raise click.ClickException(
                    f"Unknown client '{cid}'. Supported: {', '.join(ALL_PROFILES)}"
                )
        target_client_ids = client_ids

    # Resolve git worktree WITHOUT opening databases (dry-run safe)
    git = _resolve_repo(repo)
    worktree = git.repo_info.worktree_dir

    cmd: list[str]
    if server_cmd:
        import shlex
        cmd = shlex.split(server_cmd, posix=(sys.platform != "win32"))
        if not cmd:
            raise click.ClickException("Server command cannot be empty.")
    elif portable:
        cmd = ["commitecho", "serve"]
    else:
        cmd = [sys.executable, "-m", "commitecho", "serve"]

    generator = SetupGenerator(worktree, cmd, portable=portable)

    # Preflight configuration files before any writes
    selected_profiles = [ALL_PROFILES[cid] for cid in target_client_ids]
    try:
        generator.preflight(selected_profiles)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    for profile in selected_profiles:
        click.echo(f"\n[{profile.display_name}]")
        changes = generator.generate(profile, dry_run=dry_run)
        for change in changes:
            click.echo(f"  {change}")

    if dry_run:
        click.echo("\n(dry-run: no files were written)")
    else:
        click.echo("\nSetup complete.")


# ---------------------------------------------------------------------------
# check-message
# ---------------------------------------------------------------------------


def _is_merge_in_progress(git: GitAdapter) -> bool:
    try:
        from commitecho.git.adapter import _git_exe
        res = subprocess.run(
            [_git_exe(), "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            cwd=git.repo_info.worktree_dir,
            capture_output=True,
        )
        return res.returncode == 0
    except Exception:
        return False


@main.command("check-message")
@click.argument("message_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--strict", is_flag=True, default=False, help="Reject commits that fail validation.")
def check_message(message_file: Path, repo: str | None, strict: bool) -> None:
    """Validate that a commit message carries a valid, verified CommitEcho record.

    Designed for Git's commit-msg hook. Checks trailer syntax, staged index presence,
    schema validity, parent commit match, and code manifest fingerprint match.
    """
    git = _resolve_repo(repo)
    raw_message = message_file.read_text(encoding="utf-8", errors="replace")

    trailers = git.read_message_trailers(raw_message)
    record_trailers = [
        v for k, vals in trailers.items()
        if k.lower() == "commitecho-record"
        for v in vals
    ]

    staged_changes = git.staged_changes()
    staged_code = [
        e for e in staged_changes
        if not e.path.startswith(".commitecho/records/")
    ]

    # 1. No trailer found
    if not record_trailers:
        if not staged_code:
            click.echo("[info] CommitEcho: No staged code changes; CommitEcho record not required.")
            return

        if _is_merge_in_progress(git):
            click.echo("[info] CommitEcho: Merge commit detected; CommitEcho record not required.")
            return

        msg = (
            "CommitEcho: Missing 'CommitEcho-Record' trailer in commit message.\n"
            "  Capture decisions and prepare a record before committing."
        )
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] {msg}")
            return

    # 2. Multiple trailers found
    if len(record_trailers) > 1:
        msg = f"Multiple 'CommitEcho-Record' trailers found in commit message ({len(record_trailers)})."
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    # 3. Canonical UUID format
    record_id_str = record_trailers[0].strip()
    try:
        record_uuid = uuid.UUID(record_id_str)
        if str(record_uuid) != record_id_str.lower():
            raise ValueError("UUID must be in canonical lowercase hyphenated format.")
    except Exception as exc:
        msg = f"Invalid 'CommitEcho-Record' UUID '{record_id_str}': {exc}"
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    # 4. Inspect referenced record from the STAGED GIT INDEX
    record_path = f".commitecho/records/{record_uuid}.json"
    record_bytes = git.read_file_from_index(record_path)
    if record_bytes is None:
        msg = (
            f"Referenced record '{record_path}' is not staged in the Git index.\n"
            f"  Run 'git add {record_path}' to stage the record."
        )
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    # 5. Validate record JSON and schema
    try:
        record_data = json.loads(record_bytes.decode("utf-8"))
    except Exception as exc:
        msg = f"Staged record '{record_path}' contains malformed JSON: {exc}"
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    if record_data.get("record_id") != str(record_uuid):
        msg = (
            f"Staged record '{record_path}' ID mismatch: "
            f"expected '{record_uuid}', got '{record_data.get('record_id')}'."
        )
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    # 6. Verify parent OID match against HEAD
    head_oid = git.head_oid()
    prepared_parent = record_data.get("prepared_for", {}).get("parent_oid")
    expected_parent_for_head = head_oid if head_oid is not None else ("0" * len(prepared_parent) if prepared_parent else "0" * 40)

    is_parent_match = (prepared_parent == expected_parent_for_head)
    if not is_parent_match and head_oid is not None:
        try:
            head_parent = git.resolve(f"{head_oid}^")
        except Exception:
            head_parent = "0" * len(prepared_parent) if prepared_parent else "0" * 40
        if prepared_parent == head_parent:
            is_parent_match = True

    if not is_parent_match:
        msg = (
            f"Record prepared for parent {prepared_parent or '(root)'}, "
            f"but current HEAD is {head_oid or '(root)'} (stale preparation)."
        )
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    # 7. Compare code manifest SHA256 digest
    expected_digest = record_data.get("prepared_for", {}).get("code_manifest_sha256")
    actual_digest, _ = git.code_fingerprint()
    if actual_digest != expected_digest:
        # Check if amending message only with existing HEAD record
        if head_oid is not None and not staged_code:
            head_trailers = git.read_commit_trailers(head_oid)
            head_records = [
                v for k, vs in head_trailers.items()
                if k.lower() == "commitecho-record"
                for v in vs
            ]
            if any(v.strip().lower() == str(record_uuid).lower() for v in head_records):
                click.echo(f"[ok] CommitEcho record {record_uuid} verified (amending message for HEAD).")
                return

        msg = (
            f"Staged changes do not match CommitEcho record preparation:\n"
            f"  Expected manifest digest: {expected_digest}\n"
            f"  Actual staged digest:     {actual_digest}\n"
            "  The staged code has changed since preparation; please re-prepare."
        )
        if strict:
            click.echo(f"[error] Commit rejected: {msg}", err=True)
            sys.exit(1)
        else:
            click.echo(f"[warn] CommitEcho: {msg}")
            return

    click.echo(f"[ok] CommitEcho record {record_uuid} verified against staged changes.")


# ---------------------------------------------------------------------------
# hook
# ---------------------------------------------------------------------------

_HOOK_START_MARKER = "# --- commitecho-hook-start ---"
_HOOK_END_MARKER = "# --- commitecho-hook-end ---"


def _generate_hook_block(strict: bool) -> str:
    py_path = Path(sys.executable).as_posix()
    strict_flag = "--strict" if strict else ""
    return (
        f"{_HOOK_START_MARKER}\n"
        "# Managed by CommitEcho. Do not edit this block.\n"
        f'TARGET_PYTHON="{py_path}"\n'
        f'STRICT_FLAG="{strict_flag}"\n'
        'if [ -x "$TARGET_PYTHON" ]; then\n'
        '    "$TARGET_PYTHON" -m commitecho check-message "$1" $STRICT_FLAG || exit $?\n'
        'elif command -v commitecho >/dev/null 2>&1; then\n'
        '    commitecho check-message "$1" $STRICT_FLAG || exit $?\n'
        'elif command -v python3 >/dev/null 2>&1; then\n'
        '    python3 -m commitecho check-message "$1" $STRICT_FLAG || exit $?\n'
        'elif command -v python >/dev/null 2>&1; then\n'
        '    python -m commitecho check-message "$1" $STRICT_FLAG || exit $?\n'
        'else\n'
        '    echo "[commitecho] Warning: Neither python nor commitecho found on PATH; skipping message check." >&2\n'
        'fi\n'
        f"{_HOOK_END_MARKER}\n"
    )


def _display_rel_path(path: Path, worktree: Path | str) -> str:
    try:
        return path.relative_to(worktree).as_posix()
    except ValueError:
        return path.as_posix()


@main.group()
def hook() -> None:
    """Manage Git and agent lifecycle hooks."""


@hook.command("install")
@click.option("--git", "use_git", is_flag=True, default=True, help="Install Git commit-msg hook.")
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--strict", is_flag=True, default=False, help="Reject commits that fail message validation.")
@click.option("--dry-run", is_flag=True, help="Show planned changes without writing.")
def hook_install(use_git: bool, repo: str | None, strict: bool, dry_run: bool) -> None:
    """Install the Git commit-msg message validation hook.

    Safely installs or updates the CommitEcho commit-msg hook. Preserves foreign hooks.
    """
    git = _resolve_repo(repo)
    hook_file, is_local = git.get_hook_path("commit-msg")
    wt = Path(git.repo_info.worktree_dir)

    if not is_local:
        click.echo(
            f"[warn] core.hooksPath resolves to external/global location '{hook_file.parent}'.\n"
            "Refusing to modify global configuration. Configure repository-local hooks or integrate manually.",
            err=True,
        )
        sys.exit(1)

    block = _generate_hook_block(strict)
    display_path = _display_rel_path(hook_file, wt)

    if not hook_file.exists():
        action = f"[create] {display_path}: install CommitEcho commit-msg hook (strict={strict})."
        new_content = f"#!/bin/sh\n\n{block}"
    else:
        existing = hook_file.read_text(encoding="utf-8", errors="replace")
        if _HOOK_START_MARKER in existing and _HOOK_END_MARKER in existing:
            pattern = re.compile(
                rf"{re.escape(_HOOK_START_MARKER)}.*?{re.escape(_HOOK_END_MARKER)}\n?",
                re.DOTALL,
            )
            new_content = pattern.sub(block, existing)
            if new_content == existing:
                click.echo(f"[skip] {display_path}: hook already up to date (strict={strict}).")
                return
            action = f"[update] {display_path}: update CommitEcho commit-msg hook (strict={strict})."
        else:
            click.echo(
                f"[warn] Existing commit-msg hook found at '{display_path}' not managed by CommitEcho.\n"
                "Leaving existing hook unchanged to preserve foreign tools.\n\n"
                "To integrate CommitEcho into your existing hook, add the following line:\n"
                f'  commitecho check-message "$1" {"--strict" if strict else ""}\n',
                err=True,
            )
            return

    click.echo(action)
    if not dry_run:
        hook_file.parent.mkdir(parents=True, exist_ok=True)
        hook_file.write_text(new_content, encoding="utf-8")
        try:
            mode = os.stat(hook_file).st_mode
            os.chmod(hook_file, mode | 0o755)
        except OSError:
            pass
        click.echo("Hook installed successfully.")
    else:
        click.echo("(dry-run: no files were written)")


@hook.command("uninstall")
@click.option("--git", "use_git", is_flag=True, default=True, help="Uninstall Git commit-msg hook.")
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--dry-run", is_flag=True, help="Show planned changes without writing.")
def hook_uninstall(use_git: bool, repo: str | None, dry_run: bool) -> None:
    """Uninstall the CommitEcho Git commit-msg hook."""
    git = _resolve_repo(repo)
    hook_file, is_local = git.get_hook_path("commit-msg")
    wt = Path(git.repo_info.worktree_dir)
    display_path = _display_rel_path(hook_file, wt)

    if not hook_file.exists():
        click.echo(f"[skip] No hook file found at '{display_path}'.")
        return

    existing = hook_file.read_text(encoding="utf-8", errors="replace")
    if _HOOK_START_MARKER not in existing or _HOOK_END_MARKER not in existing:
        click.echo(f"[skip] '{display_path}' is not managed by CommitEcho; leaving unchanged.")
        return

    pattern = re.compile(
        rf"{re.escape(_HOOK_START_MARKER)}.*?{re.escape(_HOOK_END_MARKER)}\n?",
        re.DOTALL,
    )
    remainder = pattern.sub("", existing).strip()

    clean_lines = [l for l in remainder.splitlines() if l.strip() and not l.strip().startswith("#!")]
    if not clean_lines:
        action = f"[remove] {display_path}: delete CommitEcho commit-msg hook file."
        click.echo(action)
        if not dry_run:
            hook_file.unlink()
            click.echo("Hook uninstalled successfully.")
        else:
            click.echo("(dry-run: no files were changed)")
    else:
        action = f"[update] {display_path}: remove CommitEcho block, preserving other hook contents."
        click.echo(action)
        if not dry_run:
            hook_file.write_text(remainder + "\n", encoding="utf-8")
            click.echo("Hook block removed successfully.")
        else:
            click.echo("(dry-run: no files were changed)")
