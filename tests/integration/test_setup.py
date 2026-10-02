"""Smoke tests for SetupGenerator and the ``commitecho setup`` CLI command.

Covers:
- All three profiles write correct config files on a fresh project directory
- Idempotent re-run produces [skip] for every item
- ``--dry-run`` produces changes list but writes no files
- commitecho server entry has the correct structure (command / args)
- Windows-style path with spaces in server_command is stored as a single array element
- ``commitecho doctor`` reports skill version and client config presence
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomlkit

from commitecho.integrations.profiles import (
    ALL_PROFILES,
    SKILL_VERSION,
    SetupGenerator,
    _SKILL_TEMPLATE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generator(tmp_path: Path, server_cmd: list[str] | None = None) -> SetupGenerator:
    cmd = server_cmd or [sys.executable, "-m", "commitecho", "serve"]
    return SetupGenerator(tmp_path, cmd)


def _read_config(path: Path, profile):
    raw = path.read_text(encoding="utf-8")
    return tomlkit.parse(raw) if profile.config_format == "toml" else json.loads(raw)


# ---------------------------------------------------------------------------
# Per-profile: fresh install
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_id", list(ALL_PROFILES))
def test_fresh_install_writes_all_files(tmp_path: Path, client_id: str) -> None:
    """A first run against an empty directory creates all required files."""
    profile = ALL_PROFILES[client_id]
    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    # Every change description must start with [add] or [create]
    for change in changes:
        assert change.startswith("[add]") or change.startswith("[create]"), (
            f"Unexpected action on first run: {change!r}"
        )

    # MCP config file must exist and contain a valid commitecho entry
    config_file = tmp_path / profile.mcp_config_path
    assert config_file.exists(), f"MCP config not created: {profile.mcp_config_path}"
    config = _read_config(config_file, profile)
    servers = config[profile.mcp_servers_key]
    assert "commitecho" in servers, "commitecho key missing from servers map"
    entry = servers["commitecho"]
    assert "command" in entry
    assert "args" in entry
    assert isinstance(entry["args"], list)
    # --repo <path> must be the final two args
    assert entry["args"][-2] == "--repo"

    # Skill file must exist and match the canonical template
    skill_file = tmp_path / profile.skill_path
    assert skill_file.exists(), f"Skill file not created: {profile.skill_path}"
    assert skill_file.read_text(encoding="utf-8") == _SKILL_TEMPLATE

    # Activation instruction file (if defined)
    if profile.instruction_path:
        instr_file = tmp_path / profile.instruction_path
        assert instr_file.exists(), f"Instruction file not created: {profile.instruction_path}"
        content = instr_file.read_text(encoding="utf-8")
        assert "<!-- commitecho-activation -->" in content
        if getattr(profile, "instruction_format", "plain") == "rule":
            assert content.startswith("---")
            assert "trigger: always_on" in content
            assert "description:" in content


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_id", list(ALL_PROFILES))
def test_idempotent_rerun_produces_skips(tmp_path: Path, client_id: str) -> None:
    """A second run against an already-configured directory must produce only [skip]."""
    profile = ALL_PROFILES[client_id]
    gen = _make_generator(tmp_path)
    gen.generate(profile, dry_run=False)  # first run
    changes = gen.generate(profile, dry_run=False)  # second run

    for change in changes:
        assert change.startswith("[skip]"), (
            f"Expected [skip] on idempotent run but got: {change!r}"
        )


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_id", list(ALL_PROFILES))
def test_dry_run_writes_nothing(tmp_path: Path, client_id: str) -> None:
    """dry_run=True must return a non-empty change list but create no files."""
    profile = ALL_PROFILES[client_id]
    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=True)

    assert len(changes) > 0, "dry_run should still report planned changes"
    # No file should have been created
    assert not (tmp_path / profile.mcp_config_path).exists()
    assert not (tmp_path / profile.skill_path).exists()
    if profile.instruction_path:
        assert not (tmp_path / profile.instruction_path).exists()


# ---------------------------------------------------------------------------
# MCP config entry structure
# ---------------------------------------------------------------------------


def test_mcp_entry_args_include_repo_path(tmp_path: Path) -> None:
    """The ``args`` list must end with [``--repo``, <absolute repo path>]."""
    profile = ALL_PROFILES["codex"]
    gen = _make_generator(tmp_path)
    gen.generate(profile, dry_run=False)

    config = _read_config(tmp_path / profile.mcp_config_path, profile)
    args: list[str] = config[profile.mcp_servers_key]["commitecho"]["args"]
    assert args[-2] == "--repo"
    assert Path(args[-1]).is_absolute()


def test_mcp_entry_preserves_existing_servers(tmp_path: Path) -> None:
    """Generating must merge, not overwrite, an existing MCP config."""
    profile = ALL_PROFILES["codex"]
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        '# keep this comment\nmodel = "gpt-test"\n\n'
        '[mcp_servers."other-tool"]\ncommand = "other"\nargs = []\n',
        encoding="utf-8",
    )

    gen = _make_generator(tmp_path)
    gen.generate(profile, dry_run=False)

    merged_text = config_file.read_text(encoding="utf-8")
    merged = _read_config(config_file, profile)
    servers = merged[profile.mcp_servers_key]
    assert "# keep this comment" in merged_text
    assert merged["model"] == "gpt-test"
    assert "other-tool" in servers, "Existing server entry was lost after merge"
    assert "commitecho" in servers, "commitecho entry missing after merge"


# ---------------------------------------------------------------------------
# Windows path with spaces
# ---------------------------------------------------------------------------


def test_server_command_with_spaces_stored_as_single_element(tmp_path: Path) -> None:
    """A server executable path that contains spaces must survive round-trip as one element."""
    spaced_exe = r"C:\Program Files\Python312\python.exe"
    cmd = [spaced_exe, "-m", "commitecho", "serve"]
    profile = ALL_PROFILES["codex"]
    gen = SetupGenerator(tmp_path, cmd)
    gen.generate(profile, dry_run=False)

    config = _read_config(tmp_path / profile.mcp_config_path, profile)
    stored_cmd = config[profile.mcp_servers_key]["commitecho"]["command"]
    assert stored_cmd == spaced_exe, (
        f"Executable with spaces was mangled: expected {spaced_exe!r}, got {stored_cmd!r}"
    )


@pytest.mark.parametrize("client_id", ["codex", "antigravity"])
def test_setup_command_launches_mcp_server(tmp_path: Path, client_id: str) -> None:
    """The generated command must complete a real stdio MCP handshake without PYTHONPATH."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    subprocess.run(
        [sys.executable, "-m", "commitecho", "setup", "--client", client_id, "--repo", str(tmp_path)],
        check=True, capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    profile = ALL_PROFILES[client_id]
    config = _read_config(tmp_path / profile.mcp_config_path, profile)
    entry = config[profile.mcp_servers_key]["commitecho"]
    assert entry["args"] == ["-m", "commitecho", "serve", "--repo", str(tmp_path)]

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def handshake():
        params = StdioServerParameters(
            command=entry["command"], args=entry["args"], env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await asyncio.wait_for(session.initialize(), timeout=10)
                listed = await asyncio.wait_for(session.list_tools(), timeout=10)
                status = await asyncio.wait_for(session.call_tool("get_status", {}), timeout=10)
                return initialized, listed, status

    initialized, listed, status = asyncio.run(handshake())
    assert initialized.server_info.name == "commitecho"
    assert {tool.name for tool in listed.tools} >= {
        "begin_change", "prepare_commit", "verify_commit", "search_history",
    }
    assert not status.is_error


def test_stdio_code_change_lifecycle_survives_restart(tmp_path: Path) -> None:
    """Capture a tested code change, commit it, and recall it through a new server."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from uuid import uuid4

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "CommitEcho Test")
    git("config", "user.email", "test@commitecho.test")
    (tmp_path / "README.md").write_text("# MCP lifecycle test\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "initial commit")
    base_oid = git("rev-parse", "HEAD")

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-m", "commitecho", "setup", "--client", "codex",
         "--repo", str(tmp_path)],
        cwd=tmp_path, env=env, check=True, capture_output=True,
    )
    profile = ALL_PROFILES["codex"]
    entry = _read_config(tmp_path / profile.mcp_config_path, profile)[
        profile.mcp_servers_key
    ]["commitecho"]
    params = StdioServerParameters(command=entry["command"], args=entry["args"], env=env)

    async def call(session, name, **args):
        result = await asyncio.wait_for(session.call_tool(name, args), timeout=10)
        assert not result.is_error, result.content
        return json.loads(result.content[0].text)

    async def lifecycle():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=10)
                change = await call(
                    session, "begin_change", title="Preserve order when removing duplicates",
                    client="codex", operation_id=str(uuid4()),
                )
                change_id = change["change_id"]
                recorded = await call(
                    session, "record_decisions", change_id=change_id,
                    expected_revision=change["revision_counter"], operation_id=str(uuid4()),
                    decisions=[{
                        "problem": "Remove duplicates while preserving input order",
                        "choice": "Use dict.fromkeys", "rationale": "The standard library preserves order",
                        "disposition": "selected", "code_scope": {"paths": ["dedupe.py"]},
                    }],
                )
                (tmp_path / "dedupe.py").write_text(
                    "def dedupe(values):\n    return list(dict.fromkeys(values))\n\n"
                    "assert dedupe([3, 1, 3, 2, 1]) == [3, 1, 2]\n"
                    "assert dedupe([]) == []\n", encoding="utf-8",
                )
                subprocess.run(
                    [sys.executable, "dedupe.py"], cwd=tmp_path, check=True, capture_output=True,
                )
                git("add", "dedupe.py")
                prepared = await call(
                    session, "prepare_commit", change_id=change_id,
                    expected_revision=recorded["revision_counter"],
                    selected_revision_ids=recorded["revision_ids"],
                    summary="Remove duplicates while preserving order", operation_id=str(uuid4()),
                )
                git("add", prepared["record_path"])
                git("commit", "-m", f"Add ordered deduplication\n\n{prepared['trailer']}")
                commit_oid = git("rev-parse", "HEAD")
                verified = await call(session, "verify_commit", commit_oid=commit_oid)
                assert verified["outcome"] == "exact", verified
                assert verified["record_id"] == prepared["record_id"]

        indexed = subprocess.run(
            [sys.executable, "-m", "commitecho", "index", "--repo", str(tmp_path)],
            cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
        )
        assert "Indexed 1 new records." in indexed.stdout

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=10)
                history = await call(session, "search_history", path="dedupe.py")
                assert history["coverage"] == "full", history
                assert [r["revision_id"] for r in history["results"]] == recorded["revision_ids"]
                assert history["results"][0]["choice"] == "Use dict.fromkeys"
                evidence = await call(session, "get_evidence", record_id=prepared["record_id"])
                assert evidence["found"] is True
                assert evidence["commit_oid"] == commit_oid
                comparison = await call(
                    session, "compare_history", from_ref=base_oid, to_ref=commit_oid,
                    path="dedupe.py",
                )
                assert [r["revision_id"] for r in comparison["decisions"]] == recorded["revision_ids"]
                status = await call(session, "get_status", change_id=change_id)
                assert status["open_changes"] == []

    asyncio.run(lifecycle())


def test_malformed_codex_config_is_unchanged(tmp_path: Path) -> None:
    profile = ALL_PROFILES["codex"]
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True)
    config_file.write_text("[broken", encoding="utf-8")

    with pytest.raises(Exception):
        _make_generator(tmp_path).generate(profile)

    assert config_file.read_text(encoding="utf-8") == "[broken"


def test_malformed_antigravity_config_is_unchanged(tmp_path: Path) -> None:
    profile = ALL_PROFILES["antigravity"]
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _make_generator(tmp_path).generate(profile)

    assert config_file.read_text(encoding="utf-8") == "{broken"


def test_antigravity_exact_documented_paths_and_rule_generation(tmp_path: Path) -> None:
    """Exact documented Antigravity skill path asserted independently of profile."""
    # Documented targets
    expected_mcp_path = ".agents/mcp_config.json"
    expected_skill_path = ".agents/skills/commitecho/SKILL.md"
    expected_rule_path = ".agents/rules/commitecho.md"

    profile = ALL_PROFILES["antigravity"]
    assert profile.mcp_config_path == expected_mcp_path
    assert profile.skill_path == expected_skill_path
    assert profile.instruction_path == expected_rule_path

    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    rule_file = tmp_path / expected_rule_path
    assert rule_file.exists()
    content = rule_file.read_text(encoding="utf-8")

    # Valid trigger frontmatter
    assert content.startswith("---\n")
    assert "trigger: always_on" in content
    assert "description: Capture meaningful coding decisions and recall their evidence." in content
    # Activation instructions
    assert "<!-- commitecho-activation -->" in content
    assert "Read the installed CommitEcho skill" in content
    assert "Begin or resume a change" in content
    assert "Search history and fetch evidence" in content
    assert "Prepare and verify records" in content
    assert "Report unavailable tools" in content
    assert "does not imply permission to make Git commits" in content

    # Skill in folder-based path
    skill_file = tmp_path / expected_skill_path
    assert skill_file.exists()
    assert skill_file.read_text(encoding="utf-8") == _SKILL_TEMPLATE


def test_antigravity_repairs_legacy_marker_only_rule(tmp_path: Path) -> None:
    """A legacy rule containing only the activation marker/block must be upgraded."""
    profile = ALL_PROFILES["antigravity"]
    rule_file = tmp_path / profile.instruction_path
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text(
        "<!-- commitecho-activation -->\n"
        "## CommitEcho – decision capture and recall\n\n"
        "Use the CommitEcho MCP tools to preserve and recall the reasoning behind code changes.\n\n"
        "Activate the commitecho skill for detailed capture/recall steps.\n",
        encoding="utf-8",
    )

    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    assert any("[update]" in c and profile.instruction_path in c for c in changes)
    updated = rule_file.read_text(encoding="utf-8")
    assert updated.startswith("---\n")
    assert "trigger: always_on" in updated
    assert "<!-- commitecho-activation -->" in updated

    # Idempotent second run
    second_changes = gen.generate(profile, dry_run=False)
    assert all("[skip]" in c for c in second_changes)


def test_antigravity_preserves_unrelated_rule_and_json_mcp_servers(tmp_path: Path) -> None:
    """Setup must preserve unrelated rules and existing other MCP servers in mcp_config.json."""
    profile = ALL_PROFILES["antigravity"]
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True, exist_ok=True)
    existing_config = {
        "mcpServers": {
            "custom-tool": {"command": "custom", "args": ["--port", "8080"]}
        }
    }
    config_file.write_text(json.dumps(existing_config), encoding="utf-8")

    # Custom rule with custom frontmatter
    rule_file = tmp_path / profile.instruction_path
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    custom_rule = (
        "---\n"
        "trigger: custom\n"
        "description: User custom description\n"
        "---\n"
        "<!-- commitecho-activation -->\n"
        "# Custom Instructions\n"
    )
    rule_file.write_text(custom_rule, encoding="utf-8")

    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    # Config preserved other server
    loaded_config = json.loads(config_file.read_text(encoding="utf-8"))
    assert "custom-tool" in loaded_config["mcpServers"]
    assert "commitecho" in loaded_config["mcpServers"]

    # Rule with custom frontmatter was kept intact
    assert rule_file.read_text(encoding="utf-8") == custom_rule


def test_doctor_distinguishes_readiness_warnings_and_failures(tmp_path: Path) -> None:
    """Doctor command must truthfully report static readiness, warnings, and parse failures."""
    from click.testing import CliRunner
    from commitecho.transports.cli import doctor

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    runner = CliRunner()

    # 1. Fresh repo before setup: missing optional client files must NOT be a fatal exit
    res = runner.invoke(doctor, ["--repo", str(tmp_path)])
    assert res.exit_code == 0
    assert "[missing]" in res.output
    assert "Core checks passed; some client integrations are not installed or have warnings." in res.output
    assert "All checks passed." not in res.output

    # 2. Setup antigravity
    gen = _make_generator(tmp_path)
    gen.generate(ALL_PROFILES["antigravity"], dry_run=False)

    res = runner.invoke(doctor, ["--repo", str(tmp_path)])
    assert res.exit_code == 0
    assert "[ok] Antigravity IDE: valid activation rule" in res.output
    assert "[ok] Antigravity IDE: commitecho entry present" in res.output
    # Optional Codex/Copilot missing does not cause failure
    assert "Core checks passed; some client integrations are not installed or have warnings." in res.output

    # 3. Corrupt mcp config JSON: must cause exit code 1 and [fail]
    config_file = tmp_path / ALL_PROFILES["antigravity"].mcp_config_path
    config_file.write_text("{broken", encoding="utf-8")

    res = runner.invoke(doctor, ["--repo", str(tmp_path)])
    assert res.exit_code == 1
    assert "[fail] Antigravity IDE: could not parse" in res.output
    assert "Some checks failed" in res.output


# ---------------------------------------------------------------------------
# Skill version
# ---------------------------------------------------------------------------


def test_skill_version_is_positive_integer() -> None:
    """SKILL_VERSION must be parsed from skill.md front-matter and be a positive int."""
    assert isinstance(SKILL_VERSION, int)
    assert SKILL_VERSION >= 1


def test_skill_template_contains_version_header() -> None:
    """The bundled skill.md must declare its version in the YAML front-matter."""
    assert "version:" in _SKILL_TEMPLATE
    assert "name: commitecho" in _SKILL_TEMPLATE


# ---------------------------------------------------------------------------
# Update path: stale skill is detected and replaced
# ---------------------------------------------------------------------------


def test_stale_skill_triggers_update(tmp_path: Path) -> None:
    """If the installed skill differs from the canonical template, generate must [update] it."""
    profile = ALL_PROFILES["codex"]
    skill_file = tmp_path / profile.skill_path
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("---\nname: commitecho\nversion: 0\n---\nOld content.\n", encoding="utf-8")

    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    update_changes = [c for c in changes if "[update]" in c and "skill" in c]
    assert update_changes, f"Expected an [update] skill action, got: {changes}"
    assert skill_file.read_text(encoding="utf-8") == _SKILL_TEMPLATE


# ---------------------------------------------------------------------------
# Phase 0 tests: Neutral skill, discovery paths, migration, dry-run & resolution
# ---------------------------------------------------------------------------


def test_skill_version_3_and_neutral_guidance() -> None:
    """Skill must be version 3 with neutral client identification and explicit boundaries."""
    assert SKILL_VERSION == 3
    assert 'version: 3' in _SKILL_TEMPLATE
    # No hardcoded antigravity default in client parameter or begin_change call
    assert 'client="antigravity" (or' not in _SKILL_TEMPLATE
    assert 'client="antigravity",' not in _SKILL_TEMPLATE
    # Must document all active client profiles
    for cid in ["codex", "antigravity", "copilot_vscode", "claude_code"]:
        assert cid in _SKILL_TEMPLATE
    # Must require reporting unavailable tools and state that skill does not authorize commits
    assert "report this to the user rather than inventing successful capture" in _SKILL_TEMPLATE
    assert "Installing or loading this skill does not imply permission to make Git commits" in _SKILL_TEMPLATE


def test_codex_and_copilot_documented_paths() -> None:
    """Codex and Copilot profiles must use folder-based skills in .agents/skills and documented instructions."""
    codex = ALL_PROFILES["codex"]
    assert codex.skill_path == ".agents/skills/commitecho/SKILL.md"
    assert codex.instruction_path == "AGENTS.md"

    copilot = ALL_PROFILES["copilot_vscode"]
    assert copilot.skill_path == ".agents/skills/commitecho/SKILL.md"
    assert copilot.instruction_path == ".github/copilot-instructions.md"


def test_legacy_skill_migration_and_custom_preservation(tmp_path: Path) -> None:
    """Known generated legacy skill files must be migrated; custom files must be preserved."""
    legacy_file = tmp_path / ".codex" / "skills" / "commitecho.md"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    # Write a known v2 generated skill
    v2_content = (
        "---\nname: commitecho\nversion: 2\n"
        "description: Capture decisions made during coding tasks and recall them from Git history.\n---\n\n"
        "# CommitEcho capture and recall workflow\n\n"
        "## When to activate\n\n## Capture workflow\n"
    )
    legacy_file.write_text(v2_content, encoding="utf-8")

    profile = ALL_PROFILES["codex"]
    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    assert any("[migrate]" in c and ".codex/skills/commitecho.md" in c for c in changes)
    assert not legacy_file.exists(), "Known legacy skill file should be removed"
    assert (tmp_path / profile.skill_path).exists(), "New folder-based skill should be created"

    # Now test custom legacy file preservation
    custom_legacy = tmp_path / ".agents" / "skills" / "commitecho.md"
    custom_legacy.parent.mkdir(parents=True, exist_ok=True)
    custom_legacy.write_text("# Custom skill instructions for my team\n", encoding="utf-8")

    gen2 = _make_generator(tmp_path)
    changes2 = gen2.generate(profile, dry_run=False)

    assert any("[warn]" in c and "custom legacy skill detected" in c for c in changes2)
    assert custom_legacy.exists(), "Custom legacy skill must not be deleted"


def test_custom_installed_skill_preserved_with_conflict(tmp_path: Path) -> None:
    """A customized skill in .agents/skills/commitecho/SKILL.md must not be overwritten."""
    profile = ALL_PROFILES["antigravity"]
    skill_file = tmp_path / profile.skill_path
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    custom_text = "---\nname: commitecho\nversion: 3\n---\n# Custom team decisions\nDo not overwrite.\n"
    skill_file.write_text(custom_text, encoding="utf-8")

    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    assert any("[conflict]" in c and profile.skill_path in c for c in changes)
    assert skill_file.read_text(encoding="utf-8") == custom_text


def test_mcp_entry_preserves_custom_user_fields(tmp_path: Path) -> None:
    """Updating commitecho entry must preserve custom user fields like 'env'."""
    profile = ALL_PROFILES["antigravity"]
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True, exist_ok=True)
    existing_config = {
        "mcpServers": {
            "commitecho": {
                "command": "old-python",
                "args": ["-m", "commitecho", "serve"],
                "env": {"MY_CUSTOM_VAR": "42"},
            }
        }
    }
    config_file.write_text(json.dumps(existing_config, indent=2), encoding="utf-8")

    gen = _make_generator(tmp_path)
    changes = gen.generate(profile, dry_run=False)

    assert any("[update]" in c and profile.mcp_config_path in c for c in changes)
    updated = json.loads(config_file.read_text(encoding="utf-8"))
    entry = updated["mcpServers"]["commitecho"]
    assert entry["env"] == {"MY_CUSTOM_VAR": "42"}, "Custom user 'env' field was not preserved"
    assert entry["command"] == sys.executable


def test_setup_preflight_validations(tmp_path: Path) -> None:
    """Preflight must reject empty commands and malformed server mappings."""
    profile = ALL_PROFILES["antigravity"]

    # Empty command
    gen_empty = SetupGenerator(tmp_path, [])
    with pytest.raises(ValueError, match="command cannot be empty"):
        gen_empty.generate(profile)

    # Server mapping is not a dict
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({"mcpServers": "invalid-string"}), encoding="utf-8")

    gen_normal = _make_generator(tmp_path)
    with pytest.raises(ValueError, match="must be a mapping/table"):
        gen_normal.generate(profile)


def test_cli_setup_dry_run_creates_no_databases(tmp_path: Path) -> None:
    """commitecho setup --dry-run must not create SQLite database files."""
    from click.testing import CliRunner
    from commitecho.transports.cli import setup

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    runner = CliRunner()
    res = runner.invoke(setup, ["--dry-run", "--repo", str(tmp_path)])
    assert res.exit_code == 0
    assert "(dry-run: no files were written)" in res.output

    # Verify no private databases exist under .git/commitecho
    git_dir = tmp_path / ".git"
    assert not (git_dir / "commitecho").exists(), "Dry-run created private commitecho database directory"


def test_repo_resolution_precedence(tmp_path: Path, monkeypatch) -> None:
    """Verify repo resolution: explicit --repo > COMMITECHO_REPO > CLAUDE_PROJECT_DIR > cwd."""
    from commitecho.transports.cli import _resolve_repo

    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo3 = tmp_path / "repo3"
    subprocess.run(["git", "init", str(repo1)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo2)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo3)], check=True, capture_output=True)

    # 1. Explicit wins over environment
    monkeypatch.setenv("COMMITECHO_REPO", str(repo2))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo3))
    adapter = _resolve_repo(str(repo1))
    assert Path(adapter.repo_info.worktree_dir).resolve() == repo1.resolve()

    # 2. COMMITECHO_REPO wins when --repo is omitted
    adapter = _resolve_repo(None)
    assert Path(adapter.repo_info.worktree_dir).resolve() == repo2.resolve()

    # 3. CLAUDE_PROJECT_DIR wins when COMMITECHO_REPO is unset
    monkeypatch.delenv("COMMITECHO_REPO")
    adapter = _resolve_repo(None)
    assert Path(adapter.repo_info.worktree_dir).resolve() == repo3.resolve()

    # 4. Fallback to cwd when all unset
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    monkeypatch.chdir(repo1)
    adapter = _resolve_repo(None)
    assert Path(adapter.repo_info.worktree_dir).resolve() == repo1.resolve()


def test_portable_server_command(tmp_path: Path) -> None:
    """Portable mode must use 'commitecho serve' without --repo."""
    profile = ALL_PROFILES["codex"]
    gen = SetupGenerator(tmp_path, ["commitecho", "serve"], portable=True)
    gen.generate(profile, dry_run=False)

    config = _read_config(tmp_path / profile.mcp_config_path, profile)
    entry = config[profile.mcp_servers_key]["commitecho"]
    assert entry["command"] == "commitecho"
    assert entry["args"] == ["serve"]
    assert "--repo" not in entry["args"]

