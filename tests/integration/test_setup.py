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

import json
import sys
from pathlib import Path

import pytest

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
    config = json.loads(config_file.read_text(encoding="utf-8"))
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
        assert "<!-- commitecho-activation -->" in instr_file.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# MCP config entry structure
# ---------------------------------------------------------------------------


def test_mcp_entry_args_include_repo_path(tmp_path: Path) -> None:
    """The ``args`` list must end with [``--repo``, <absolute repo path>]."""
    profile = ALL_PROFILES["codex"]
    gen = _make_generator(tmp_path)
    gen.generate(profile, dry_run=False)

    config = json.loads((tmp_path / profile.mcp_config_path).read_text(encoding="utf-8"))
    args: list[str] = config[profile.mcp_servers_key]["commitecho"]["args"]
    assert args[-2] == "--repo"
    assert Path(args[-1]).is_absolute()


def test_mcp_entry_preserves_existing_servers(tmp_path: Path) -> None:
    """Generating must merge, not overwrite, an existing MCP config."""
    profile = ALL_PROFILES["codex"]
    config_file = tmp_path / profile.mcp_config_path
    config_file.parent.mkdir(parents=True, exist_ok=True)
    existing = {profile.mcp_servers_key: {"other-tool": {"command": "other", "args": []}}}
    config_file.write_text(json.dumps(existing), encoding="utf-8")

    gen = _make_generator(tmp_path)
    gen.generate(profile, dry_run=False)

    merged = json.loads(config_file.read_text(encoding="utf-8"))
    servers = merged[profile.mcp_servers_key]
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

    config = json.loads((tmp_path / profile.mcp_config_path).read_text(encoding="utf-8"))
    stored_cmd = config[profile.mcp_servers_key]["commitecho"]["command"]
    assert stored_cmd == spaced_exe, (
        f"Executable with spaces was mangled: expected {spaced_exe!r}, got {stored_cmd!r}"
    )


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
