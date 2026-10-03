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
        raise click.ClickException(str(exc)) from exc


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
    """CommitEcho - preserve and recall the decisions behind code changes."""


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

    from commitecho.integrations.profiles import ALL_PROFILES, SKILL_VERSION, _SKILL_TEMPLATE, validate_mcp_config

    ok = True
    has_missing = False
    has_warnings = False

    # Git availability
    try:
        git = _resolve_repo(repo)
        click.echo(f"[ok] Git: worktree={git.repo_info.worktree_dir}")
    except click.ClickException as exc:
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
            for open_db in (open_drafts_db, open_index_db):
                connection = open_db(git.repo_info.common_dir)
                connection.close()
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
            else:
                try:
                    if skill_file.read_text(encoding="utf-8") == _SKILL_TEMPLATE:
                        click.echo(f"[ok] {profile.skill_path}: skill version {SKILL_VERSION} matches")
                    else:
                        click.echo(
                            f"[warn] {profile.skill_path}: differs from current version {SKILL_VERSION}; "
                            "setup updates known generated assets and preserves custom content. Review custom content manually."
                        )
                        has_warnings = True
                except (OSError, UnicodeError) as exc:
                    click.echo(f"[fail] Could not read {profile.skill_path}: {exc}", err=True)
                    ok = False

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
                "[warn] AGENTS.override.md takes precedence over AGENTS.md in Codex sessions; "
                "add the CommitEcho activation instructions to the override manually."
            )
            has_warnings = True

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
                validate_mcp_config(config, profile)
                servers = config.get(profile.mcp_servers_key, {})
                if "commitecho" in servers:
                    click.echo(f"[ok] {profile.display_name}: commitecho entry present in {profile.mcp_config_path} (static structure checked; no live handshake)")
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


def _positive_timeout(ctx, param, value):
    import math
    if value is not None and (not math.isfinite(value) or value <= 0):
        raise click.BadParameter("must be a finite positive number of seconds", param=param)
    return value


@main.command("index")
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--timeout", default=None, type=float, callback=_positive_timeout, help="Maximum seconds for the complete indexing process.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress informational messages (errors/warnings only).")
def rebuild_index(repo: str | None, timeout: float | None, quiet: bool) -> None:
    """Rebuild the history index from committed Git objects.

    Scans .commitecho/records/ JSON files reachable from HEAD and populates
    index.sqlite.  Safe to re-run; existing entries are skipped.
    """
    if timeout is not None:
        command = [sys.executable, "-m", "commitecho", "index"]
        if repo is not None:
            command.extend(["--repo", repo])
        if quiet:
            command.append("--quiet")
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            for output, is_error in ((exc.stdout, False), (exc.stderr, True)):
                if output:
                    click.echo(output.decode("utf-8", errors="replace"), nl=False, err=is_error)
            click.echo(f"[warn] CommitEcho: Indexing stopped after reaching timeout of {timeout:g}s; coverage may be incomplete.", err=True)
            return
        except OSError as exc:
            raise click.ClickException(f"Cannot launch the indexing worker: {exc}") from exc
        click.echo(result.stdout.decode("utf-8", errors="replace"), nl=False)
        click.echo(result.stderr.decode("utf-8", errors="replace"), nl=False, err=True)
        if result.returncode:
            raise click.exceptions.Exit(result.returncode)
        return

    from contextlib import closing
    git = _resolve_repo(repo)
    with closing(open_index_db(git.repo_info.common_dir)) as index:
        _index_history(git, index, quiet)


def _index_history(git, index, quiet: bool) -> None:
    info = git.repo_info
    head_oid = git.head_oid()
    if head_oid is None:
        if not quiet:
            click.echo("Repository has no commits yet.")
        return

    # Enumerate all commits reachable from HEAD
    try:
        oids, coverage = git.reachable_commit_oids(head_oid)
    except GitError as exc:
        raise click.ClickException(f"Cannot traverse Git history: {exc}") from exc
    if coverage == "partial":
        click.echo("  [warn] Git history is incomplete; index coverage will be partial.", err=True)
    if not quiet:
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
                    click.echo(f"  [warn] {oid[:8]}: {failed_path}: {error}", err=True)

    if not quiet:
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


def _parse_server_command(command: str, *, windows: bool | None = None) -> list[str]:
    """Parse shell-style argv, preserving Windows paths and removing quote delimiters.

    On Windows, quote each whole argument; embedded/mixed quotes are rejected
    rather than silently generating a different executable or argument list.
    """
    import shlex

    windows = sys.platform == "win32" if windows is None else windows
    try:
        args = shlex.split(command, posix=not windows)
        if windows:
            parsed = []
            for arg in args:
                if arg and arg[0] in ("'", '"') and arg[-1] == arg[0]:
                    arg = arg[1:-1]
                if '"' in arg:
                    raise ValueError("on Windows quote each whole argument; embedded quotes are unsupported")
                parsed.append(arg)
            args = parsed
        if not args or not args[0].strip():
            raise ValueError("server command cannot be empty")
        if any("\x00" in arg for arg in args):
            raise ValueError("server command cannot contain NUL bytes")
        return args
    except ValueError as exc:
        raise click.ClickException(f"Invalid --server-cmd: {exc}") from exc


@main.command()
@click.option("--client", "client_ids", multiple=True,
              help="Client IDs to configure (codex, antigravity, copilot_vscode, claude_code). Repeat for multiple.")
@click.option("--repo", default=None, help="Path to the Git repository / project root.")
@click.option("--server-cmd", default=None,
              help="Server argv (default: current Python -m commitecho serve). Quote whole arguments on Windows.")
@click.option("--portable", is_flag=True,
              help="Claude-only portable command ('commitecho serve'); requires PATH installation.")
@click.option("--regenerate-server", is_flag=True,
              help="Replace an existing CommitEcho command/args; otherwise preserve user launch overrides.")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files.")
def setup(
    client_ids: tuple[str, ...],
    repo: str | None,
    server_cmd: str | None,
    portable: bool,
    regenerate_server: bool,
    dry_run: bool,
) -> None:
    """Install CommitEcho configuration for one or more coding agent clients.

    Merges into existing config files. Use --dry-run to preview changes.
    """
    from commitecho.integrations.profiles import ALL_PROFILES, SetupGenerator

    if server_cmd is not None and portable:
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
    if server_cmd is not None:
        cmd = _parse_server_command(server_cmd)
    elif portable:
        cmd = ["commitecho", "serve"]
    else:
        cmd = [sys.executable, "-m", "commitecho", "serve"]

    generator = SetupGenerator(worktree, cmd, portable=portable, regenerate_server=regenerate_server)

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

    if "claude_code" in target_client_ids:
        when = "After applying setup" if dry_run else "Next"
        click.echo(
            f"\n{when}: open Claude Code in this repository, complete workspace trust "
            "and approve the project commitecho MCP server, then start a fresh session/reload. "
            "Call get_status and compare head_oid with git rev-parse HEAD. "
            "For unattended approval, see README's Claude Code section for "
            "enabledMcpjsonServers in .claude/settings.local.json; setup does not change approvals."
        )


# ---------------------------------------------------------------------------
# check-message
# ---------------------------------------------------------------------------


@main.command("check-message")
@click.argument("message_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--strict", is_flag=True, default=False, help="Reject commits that fail validation.")
def check_message(message_file: Path, repo: str | None, strict: bool) -> None:
    """Validate a message's record against current HEAD and the Git index.

    A commit-msg hook receives no reliable amend flag; reused amend records
    are rejected instead of guessing the prospective commit's parent.
    """
    try:
        git = _resolve_repo(repo)
        trailers = git.read_message_trailers(message_file.read_text(encoding="utf-8"))
        declarations = [
            (key, value) for key, values in trailers.items()
            if key.lower() == "commitecho-record" for value in values
        ]
        if not declarations:
            raise ValueError("Missing 'CommitEcho-Record' trailer. Capture decisions and prepare a record before committing.")
        if len(declarations) != 1:
            raise ValueError(f"Multiple 'CommitEcho-Record' trailers found ({len(declarations)}).")
        key, record_id = declarations[0]
        if key != "CommitEcho-Record":
            raise ValueError("Trailer key must be exactly 'CommitEcho-Record'.")
        try:
            if str(uuid.UUID(record_id)) != record_id:
                raise ValueError("UUID must be canonical lowercase hyphenated format.")
        except ValueError as exc:
            raise ValueError(f"Invalid 'CommitEcho-Record' UUID '{record_id}': {exc}") from exc
        record_path = f".commitecho/records/{record_id}.json"
        record_bytes = git.read_file_from_index(record_path)
        if record_bytes is None:
            raise ValueError(f"Referenced record '{record_path}' is not staged in the Git index. Run 'git add {record_path}'.")
        try:
            record_data = json.loads(record_bytes.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Staged record '{record_path}' contains malformed JSON: {exc}") from exc
        try:
            _validate_record(record_data, record_id)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Invalid staged record '{record_path}': {exc}") from exc
        prepared = record_data["prepared_for"]
        if (type(prepared.get("manifest_version")) is not int or prepared["manifest_version"] != 1
                or prepared.get("object_format") != git.repo_info.object_format):
            raise ValueError("Record manifest version or object format is invalid.")
        head_oid = git.head_oid()
        expected_parent = head_oid or ("0" * (64 if git.repo_info.object_format == "sha256" else 40))
        if prepared["parent_oid"] != expected_parent:
            raise ValueError(
                f"Record prepared for parent {prepared['parent_oid']}, "
                f"but current HEAD is {head_oid or '(root)'} (stale preparation)."
            )
        actual_digest, _ = git.code_fingerprint()
        if actual_digest != prepared["code_manifest_sha256"]:
            raise ValueError("Staged changes do not match CommitEcho record preparation; re-prepare after staging code.")
    except (click.ClickException, GitError, OSError, ValueError, TypeError, KeyError) as exc:
        click.echo(f"[{'error' if strict else 'warn'}] CommitEcho: {exc}", err=True)
        if strict:
            raise click.exceptions.Exit(1) from exc
        return
    click.echo(f"[ok] CommitEcho record {record_id} verified against current HEAD and staged changes.")

# ---------------------------------------------------------------------------
# hook
# ---------------------------------------------------------------------------

_HOOK_START_MARKER = "# --- commitecho-hook-start ---"
_HOOK_END_MARKER = "# --- commitecho-hook-end ---"


def _generate_hook_block(strict: bool) -> str:
    import shlex

    py_path = shlex.quote(Path(sys.executable).as_posix())
    strict_flag = "--strict" if strict else ""
    return (
        f"{_HOOK_START_MARKER}\n"
        "# Managed by CommitEcho. Do not edit this block.\n"
        f"TARGET_PYTHON={py_path}\n"
        f'STRICT_FLAG="{strict_flag}"\n'
        'if [ -x "$TARGET_PYTHON" ]; then\n'
        '    if "$TARGET_PYTHON" -m commitecho check-message "$1" --repo "$PWD" $STRICT_FLAG; then\n'
        '        :\n'
        '    else\n'
        '        echo "[warn] CommitEcho: message validation failed; reinstall the hook if its runtime changed." >&2\n'
        '        if [ -n "$STRICT_FLAG" ]; then exit 1; fi\n'
        '    fi\n'
        'else\n'
        '    echo "[warn] CommitEcho: installed Python runtime is unavailable; reinstall the hook." >&2\n'
        '    if [ -n "$STRICT_FLAG" ]; then exit 1; fi\n'
        'fi\n'
        f"{_HOOK_END_MARKER}\n"
    )


def _display_rel_path(path: Path, worktree: Path | str) -> str:
    try:
        return path.relative_to(worktree).as_posix()
    except ValueError:
        return path.as_posix()


def _hook_block_span(content: bytes) -> tuple[int, int] | None:
    """Identify exactly one complete managed block without decoding foreign bytes."""
    start = _HOOK_START_MARKER.encode()
    end = _HOOK_END_MARKER.encode()
    if content.count(start) != 1 or content.count(end) != 1:
        return None
    match = re.search(
        rb"(?ms)^" + re.escape(start) + rb"\r?\n.*?^" + re.escape(end) + rb"(?:\r?\n|$)",
        content,
    )
    return match.span() if match else None


def _local_git_hook(git: GitAdapter) -> Path:
    hook_file, is_local = git.get_hook_path("commit-msg")
    if not is_local:
        raise click.ClickException(
            f"core.hooksPath resolves to external/global location '{hook_file.parent}'. "
            "Configure repository-local hooks or integrate manually."
        )
    if hook_file.is_symlink():
        raise click.ClickException(f"Refusing to modify symlink hook '{hook_file}'. Integrate manually.")
    return hook_file


def _install_git_hook(git: GitAdapter, strict: bool, dry_run: bool) -> None:
    import shlex

    hook_file = _local_git_hook(git)
    display_path = _display_rel_path(hook_file, git.repo_info.worktree_dir)
    block = _generate_hook_block(strict).encode()
    if not hook_file.exists():
        action = f"[create] {display_path}: install CommitEcho commit-msg hook (strict={strict})."
        new_content = b"#!/bin/sh\n\n" + block
    else:
        existing = hook_file.read_bytes()
        span = _hook_block_span(existing)
        if span is None:
            click.echo(
                f"[warn] Existing commit-msg hook at '{display_path}' is not managed by CommitEcho; leaving unchanged.\n"
                "To integrate, invoke this command before any unconditional exit:\n"
                f"  {shlex.quote(Path(sys.executable).as_posix())} -m commitecho check-message \"$1\" --repo \"$PWD\" {'--strict' if strict else ''}",
                err=True,
            )
            return
        new_content = existing[:span[0]] + block + existing[span[1]:]
        if new_content == existing:
            click.echo(f"[skip] {display_path}: Git hook already up to date (strict={strict}).")
            return
        action = f"[update] {display_path}: update CommitEcho commit-msg hook (strict={strict})."
    click.echo(action)
    if dry_run:
        click.echo("(dry-run: no files were written)")
        return
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_bytes(new_content)
    os.chmod(hook_file, os.stat(hook_file).st_mode | 0o111)
    click.echo("Git hook installed successfully.")


def _preflight_git_hook_cleanup(git: GitAdapter) -> tuple[Path, bytes | None]:
    hook_file = _local_git_hook(git)
    try:
        return hook_file, hook_file.read_bytes()
    except FileNotFoundError:
        return hook_file, None


def _uninstall_git_hook(
    git: GitAdapter, dry_run: bool, validated: tuple[Path, bytes | None] | None = None,
) -> None:
    hook_file, existing = validated if validated is not None else _preflight_git_hook_cleanup(git)
    display_path = _display_rel_path(hook_file, git.repo_info.worktree_dir)
    if existing is None:
        click.echo(f"[skip] No hook file found at '{display_path}'.")
        return
    span = _hook_block_span(existing)
    if span is None:
        click.echo(f"[skip] '{display_path}' is not managed by CommitEcho; leaving unchanged.")
        return
    remainder = existing[:span[0]] + existing[span[1]:]
    pure_launcher = remainder.replace(b"\r\n", b"\n") in (b"#!/bin/sh\n", b"#!/bin/sh\n\n")
    action = "remove" if pure_launcher else "update"
    click.echo(f"[{action}] {display_path}: remove CommitEcho hook content, preserving foreign bytes.")
    if dry_run:
        click.echo("(dry-run: no files were changed)")
    elif pure_launcher:
        hook_file.unlink()
        click.echo("Git hook uninstalled successfully.")
    else:
        hook_file.write_bytes(remainder)
        click.echo("Git hook block removed successfully.")


def _is_generated_claude_hook(handler: object) -> bool:
    """Recognize only the exact exec-form handler emitted by the old installer."""
    if not isinstance(handler, dict) or set(handler) != {"type", "command", "args"}:
        return False
    command, args = handler["command"], handler["args"]
    if handler["type"] != "command" or not isinstance(command, str) or not isinstance(args, list):
        return False
    if command != "commitecho":
        if not Path(command).is_absolute() or not re.fullmatch(r"python(?:\d+(?:\.\d+)?)?(?:\.exe)?", Path(command).name, re.IGNORECASE):
            return False
        if args[:2] != ["-m", "commitecho"]:
            return False
        args = args[2:]
    if len(args) != 4 or args[:2] != ["index", "--timeout"] or args[3] != "--quiet":
        return False
    try:
        return isinstance(args[2], str) and str(float(args[2])) == args[2]
    except ValueError:
        return False


def _preflight_claude_hook_cleanup(wt: Path) -> tuple[Path, dict | None]:
    from commitecho.integrations.profiles import validate_repo_path

    settings_file = wt / ".claude" / "settings.json"
    display_path = _display_rel_path(settings_file, wt)
    try:
        validate_repo_path(wt, settings_file)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        settings_data = json.loads(settings_file.read_text(encoding="utf-8"))
        if not isinstance(settings_data, dict):
            raise ValueError("root is not a JSON object")
    except FileNotFoundError:
        return settings_file, None
    except (OSError, UnicodeError, ValueError) as exc:
        raise click.ClickException(f"Failed to parse '{display_path}': {exc}") from exc
    return settings_file, settings_data


def _uninstall_claude_code_hook(
    wt: Path, dry_run: bool, validated: tuple[Path, dict | None] | None = None,
) -> None:
    settings_file, settings_data = validated if validated is not None else _preflight_claude_hook_cleanup(wt)
    display_path = _display_rel_path(settings_file, wt)
    if settings_data is None:
        click.echo(f"[skip] No settings file found at '{display_path}'.")
        return

    hooks_dict = settings_data.get("hooks")
    if not isinstance(hooks_dict, dict):
        click.echo(f"[skip] No 'hooks' configuration in '{display_path}'.")
        return

    session_start_list = hooks_dict.get("SessionStart")
    if not isinstance(session_start_list, list):
        click.echo(f"[skip] No 'SessionStart' hooks in '{display_path}'.")
        return

    new_session_start = []
    removed = False
    for item in session_start_list:
        if not isinstance(item, dict) or not isinstance(item.get("hooks"), list):
            new_session_start.append(item)
            continue
        retained = [sub for sub in item["hooks"] if not _is_generated_claude_hook(sub)]
        if len(retained) == len(item["hooks"]):
            new_session_start.append(item)
            continue
        removed = True
        if retained or set(item) != {"matcher", "hooks"} or item.get("matcher") != "startup|resume":
            new_session_start.append({**item, "hooks": retained})

    if not removed:
        click.echo(f"[skip] No CommitEcho SessionStart hook found in '{display_path}'.")
        return

    if new_session_start:
        hooks_dict["SessionStart"] = new_session_start
    else:
        hooks_dict.pop("SessionStart", None)

    if not hooks_dict:
        settings_data.pop("hooks", None)

    if not settings_data:
        action = f"[remove] {display_path}: delete empty settings file."
        click.echo(action)
        if not dry_run:
            settings_file.unlink()
            click.echo("Claude Code lifecycle hook uninstalled successfully.")
        else:
            click.echo("(dry-run: no files were changed)")
    else:
        action = f"[update] {display_path}: remove CommitEcho SessionStart hook, preserving other settings."
        click.echo(action)
        if not dry_run:
            settings_file.write_text(json.dumps(settings_data, indent=2) + "\n", encoding="utf-8")
            click.echo("Claude Code lifecycle hook uninstalled successfully.")
        else:
            click.echo("(dry-run: no files were changed)")


@main.group()
def hook() -> None:
    """Manage Git and agent lifecycle hooks."""


@hook.command("install")
@click.option("--git", "use_git", is_flag=True, default=False, help="Install Git commit-msg hook.")
@click.option("--client", "client_id", default=None, type=click.Choice(["claude_code"]),
              help="Claude Code lifecycle installation is gated pending native-client qualification.")
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--strict", is_flag=True, default=False, help="Reject commits that fail message validation (Git hook only).")
@click.option("--timeout", default=5.0, type=float, callback=_positive_timeout, help="Timeout in seconds for bounded indexing hook (default: 5.0).")
@click.option("--portable", is_flag=True, help="Use portable command ('commitecho') requiring PATH installation.")
@click.option("--dry-run", is_flag=True, help="Show planned changes without writing.")
def hook_install(
    use_git: bool,
    client_id: str | None,
    repo: str | None,
    strict: bool,
    timeout: float,
    portable: bool,
    dry_run: bool,
) -> None:
    """Install Git commit-msg hook or client lifecycle hooks.

    Default: installs the Git commit-msg hook if neither --git nor --client is specified.
    """
    if not use_git and not client_id:
        use_git = True

    if client_id == "claude_code":
        raise click.ClickException(
            "Claude Code lifecycle hooks are not qualified for a recorded client version/OS. "
            "No native hook was installed. Use 'commitecho index --timeout 5' explicitly; "
            "qualify actual Claude loading, execution, timeout and diagnostics before enabling this adapter."
        )

    git = _resolve_repo(repo)
    if use_git:
        try:
            _install_git_hook(git, strict=strict, dry_run=dry_run)
        except (GitError, OSError) as exc:
            raise click.ClickException(str(exc)) from exc


@hook.command("uninstall")
@click.option("--git", "use_git", is_flag=True, default=False, help="Uninstall Git commit-msg hook.")
@click.option("--client", "client_id", default=None, type=click.Choice(["claude_code"]),
              help="Uninstall client lifecycle hook (claude_code SessionStart bounded indexing).")
@click.option("--repo", default=None, help="Path to the Git repository.")
@click.option("--dry-run", is_flag=True, help="Show planned changes without writing.")
def hook_uninstall(
    use_git: bool,
    client_id: str | None,
    repo: str | None,
    dry_run: bool,
) -> None:
    """Uninstall CommitEcho Git or client lifecycle hooks."""
    if not use_git and not client_id:
        use_git = True

    git = _resolve_repo(repo)
    wt = Path(git.repo_info.worktree_dir)

    try:
        git_cleanup = _preflight_git_hook_cleanup(git) if use_git else None
        claude_cleanup = _preflight_claude_hook_cleanup(wt) if client_id == "claude_code" else None
        if git_cleanup is not None:
            _uninstall_git_hook(git, dry_run=dry_run, validated=git_cleanup)
        if claude_cleanup is not None:
            _uninstall_claude_code_hook(wt, dry_run=dry_run, validated=claude_cleanup)
    except (GitError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


# ---------------------------------------------------------------------------
# plugin (Claude Code plugin generator)
# ---------------------------------------------------------------------------


def _render_plugin_manifest(version: str) -> str:
    return json.dumps(
        {
            "name": "commitecho",
            "version": version,
            "description": "Preserve the decisions behind code changes and recall them through your coding agent.",
            "author": {"name": "CommitEcho Contributors"},
            "homepage": "https://github.com/Muntaha15/CommitEcho",
            "repository": "https://github.com/Muntaha15/CommitEcho",
        },
        indent=2,
    ) + "\n"


@main.command("plugin")
@click.option("--output-dir", default=None, help="Directory to generate the Claude plugin into (default: commitecho-plugin in repo root).")
@click.option("--repo", default=None, help="Path to the Git repository / project root.")
@click.option("--portable", is_flag=True, help="Use portable server command ('commitecho serve') on PATH.")
@click.option("--dry-run", is_flag=True, help="Show what would be created without writing files.")
def plugin(
    output_dir: str | None,
    repo: str | None,
    portable: bool,
    dry_run: bool,
) -> None:
    """Generate a local Claude plugin requiring an installed CommitEcho runtime.

    Creates standard plugin layout:
      <output_dir>/
      |-- .claude-plugin/plugin.json
      |-- .mcp.json
      `-- skills/commitecho/SKILL.md
    """
    from commitecho.integrations.profiles import SKILL_TEMPLATE, is_known_generated_skill

    git = _resolve_repo(repo)
    wt = Path(git.repo_info.worktree_dir)

    target_dir = Path(output_dir) if output_dir else wt / "commitecho-plugin"
    if not target_dir.is_absolute():
        target_dir = (wt / target_dir).resolve()

    manifest_file = target_dir / ".claude-plugin" / "plugin.json"
    mcp_file = target_dir / ".mcp.json"
    skill_file = target_dir / "skills" / "commitecho" / "SKILL.md"

    # Directory safety check: if directory exists and is nonempty, ensure it is a commitecho plugin directory
    if target_dir.exists() and not target_dir.is_dir():
        raise click.ClickException(f"Target '{target_dir}' is not a directory.")
    if target_dir.exists() and any(target_dir.iterdir()):
        if not manifest_file.exists():
            raise click.ClickException(
                f"Target directory '{target_dir}' exists and is not a CommitEcho plugin directory. "
                "Refusing to overwrite unrelated files."
            )

    import importlib.metadata
    try:
        pkg_version = importlib.metadata.version("commitecho")
    except importlib.metadata.PackageNotFoundError as exc:
        raise click.ClickException("Install the CommitEcho package before generating a plugin.") from exc

    manifest_content = _render_plugin_manifest(pkg_version.replace(".dev", "-dev."))

    cmd = (
        ["commitecho", "serve"]
        if portable
        else [Path(sys.executable).as_posix(), "-m", "commitecho", "serve"]
    )
    mcp_content = json.dumps(
        {
            "mcpServers": {
                "commitecho": {
                    "command": cmd[0],
                    "args": cmd[1:],
                }
            }
        },
        indent=2,
    ) + "\n"

    skill_content = SKILL_TEMPLATE

    plan = [
        (manifest_file, manifest_content),
        (mcp_file, mcp_content),
        (skill_file, skill_content),
    ]

    # Preflight every generated asset before creating or updating any file.
    for fpath, content in plan:
        ancestor = fpath.parent
        while ancestor != target_dir:
            if ancestor.exists() and not ancestor.is_dir():
                raise click.ClickException(f"Expected a directory at '{ancestor}'; nothing was written.")
            ancestor = ancestor.parent
        if fpath.is_symlink() or not fpath.resolve().is_relative_to(target_dir.resolve()):
            raise click.ClickException(f"Generated path '{fpath}' is linked outside its owned location; nothing was written.")
        if not fpath.exists():
            continue
        if not fpath.is_file():
            raise click.ClickException(f"Expected a file at '{fpath}'; nothing was written.")
        existing = fpath.read_text(encoding="utf-8")
        if fpath == skill_file and is_known_generated_skill(existing):
            continue
        allowed = {content}
        if fpath == manifest_file:
            try:
                prior = json.loads(existing)
            except ValueError:
                prior = None
            prior_version = prior.get("version") if isinstance(prior, dict) else None
            if isinstance(prior_version, str) and re.fullmatch(
                r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-dev\.(?:0|[1-9][0-9]*))?",
                prior_version,
            ):
                allowed.add(_render_plugin_manifest(prior_version))
        if fpath == mcp_file:
            for runtime in (["commitecho", "serve"], [Path(sys.executable).as_posix(), "-m", "commitecho", "serve"]):
                allowed.add(json.dumps({"mcpServers": {"commitecho": {"command": runtime[0], "args": runtime[1:]}}}, indent=2) + "\n")
        if existing not in allowed:
            raise click.ClickException(
                f"'{fpath}' is customized or belongs to another plugin. "
                "Preserving all files; choose an empty output directory."
            )

    for fpath, content in plan:
        disp = _display_rel_path(fpath, wt)
        if not fpath.exists():
            click.echo(f"[create] {disp}")
            if not dry_run:
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
        else:
            existing = fpath.read_text(encoding="utf-8")
            if existing == content:
                click.echo(f"[skip] {disp}: already up to date.")
            else:
                click.echo(f"[update] {disp}")
                if not dry_run:
                    fpath.write_text(content, encoding="utf-8")

    if dry_run:
        click.echo("\n(dry-run: no files were written)")
    else:
        click.echo("\nPlugin generated successfully. An installed CommitEcho runtime is required. Validate loading and repository binding in Claude Code before use.")
