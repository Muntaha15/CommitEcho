"""Declarative client profiles for CommitEcho setup generation.

Each profile describes how to configure a specific coding agent client
to use the CommitEcho MCP server.  The setup generator uses these profiles
to produce client-specific config files without manual editing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Skill asset – loaded from the bundled skill.md file at import time
# ---------------------------------------------------------------------------

_SKILL_FILE = Path(__file__).parent / "skill.md"
_SKILL_TEMPLATE: str = _SKILL_FILE.read_text(encoding="utf-8")

# Extract the declared version from the YAML front-matter (``version: N``).
_version_match = re.search(r"^version:\s*(\d+)", _SKILL_TEMPLATE, re.MULTILINE)
SKILL_VERSION: int = int(_version_match.group(1)) if _version_match else 0


@dataclass
class ClientProfile:
    """Declarative description of how a client hosts the CommitEcho MCP server."""

    client_id: str
    display_name: str
    # Path relative to the project root where the MCP config file lives
    mcp_config_path: str
    # Key inside the config file that holds the server map
    mcp_servers_key: str
    # Path relative to the project root for skill installation
    skill_path: str
    # Path relative to the project root for activation instructions
    instruction_path: str | None
    # Known limitations for this client
    known_limitations: list[str] = field(default_factory=list)

    def mcp_config_entry(self, server_command: list[str], repo_path: str) -> dict[str, Any]:
        """Return the MCP server config block for this client.

        Each element of *server_command* is stored as-is; JSON serialisation
        preserves spaces so clients that consume the array directly (Codex,
        Antigravity, VS Code all use the array form) never need shell quoting.
        """
        return {
            "command": server_command[0],
            "args": server_command[1:] + ["--repo", repo_path],
        }


# ---------------------------------------------------------------------------
# Supported client profiles
# ---------------------------------------------------------------------------

CODEX = ClientProfile(
    client_id="codex",
    display_name="Codex (local)",
    mcp_config_path=".codex/mcp.json",
    mcp_servers_key="mcpServers",
    skill_path=".codex/skills/commitecho.md",
    instruction_path=".codex/AGENTS.md",
    known_limitations=[
        "Lifecycle hooks are optional; baseline uses explicit tool calls only.",
        "Exact supported Codex version must be validated during M0 spike.",
    ],
)

ANTIGRAVITY = ClientProfile(
    client_id="antigravity",
    display_name="Antigravity IDE",
    mcp_config_path=".agents/mcp_config.json",
    mcp_servers_key="mcpServers",
    skill_path=".agents/skills/commitecho.md",
    instruction_path=None,  # uses persistent rules instead
    known_limitations=[
        "IDE and CLI hook parity not assumed.",
        "Use skills rather than legacy Workflows (deprecated).",
    ],
)

COPILOT_VSCODE = ClientProfile(
    client_id="copilot_vscode",
    display_name="GitHub Copilot in VS Code",
    mcp_config_path=".vscode/mcp.json",
    mcp_servers_key="servers",
    skill_path=".agents/skills/commitecho.md",
    instruction_path=".github/copilot-instructions.md",
    known_limitations=[
        "Hook behavior depends on the active session harness and VS Code version.",
        "Copilot cloud agent is a separate surface; do not inherit VS Code results.",
    ],
)

ALL_PROFILES: dict[str, ClientProfile] = {
    p.client_id: p for p in [CODEX, ANTIGRAVITY, COPILOT_VSCODE]
}


# ---------------------------------------------------------------------------
# Setup generator
# ---------------------------------------------------------------------------


class SetupGenerator:
    """Generates per-client configuration files for CommitEcho.

    Merges into existing config files without replacing other MCP servers
    or user instructions.  Provides dry-run diff before writing.
    """

    def __init__(self, worktree: str | Path, server_command: list[str]) -> None:
        self._root = Path(worktree)
        self._cmd = server_command

    def generate(
        self,
        profile: ClientProfile,
        dry_run: bool = False,
    ) -> list[str]:
        """Generate configuration for *profile*.

        Returns a list of human-readable change descriptions.
        If *dry_run* is True, no files are written.
        """
        changes: list[str] = []
        repo_path = str(self._root.resolve())

        # 1. MCP config
        changes.extend(
            self._update_mcp_config(profile, repo_path, dry_run=dry_run)
        )

        # 2. Skill file
        changes.extend(self._install_skill(profile, dry_run=dry_run))

        # 3. Activation instruction block
        if profile.instruction_path:
            changes.extend(self._update_instructions(profile, dry_run=dry_run))

        return changes

    def _update_mcp_config(
        self, profile: ClientProfile, repo_path: str, *, dry_run: bool
    ) -> list[str]:
        config_file = self._root / profile.mcp_config_path
        entry = profile.mcp_config_entry(self._cmd, repo_path)
        servers_key = profile.mcp_servers_key

        if config_file.exists():
            config = json.loads(config_file.read_text(encoding="utf-8"))
        else:
            config = {}

        servers = config.setdefault(servers_key, {})
        if "commitecho" in servers:
            if servers["commitecho"] == entry:
                return [f"[skip] {profile.mcp_config_path}: commitecho entry already up to date."]
            action = f"[update] {profile.mcp_config_path}: update commitecho server entry."
        else:
            action = f"[add] {profile.mcp_config_path}: add commitecho server entry."

        servers["commitecho"] = entry

        if not dry_run:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

        return [action]

    def _install_skill(self, profile: ClientProfile, *, dry_run: bool) -> list[str]:
        skill_file = self._root / profile.skill_path
        skill_content = _SKILL_TEMPLATE  # read from skill.md at import time

        if skill_file.exists():
            if skill_file.read_text(encoding="utf-8") == skill_content:
                return [f"[skip] {profile.skill_path}: skill already installed."]
            action = f"[update] {profile.skill_path}: update shared capture/recall skill."
        else:
            action = f"[add] {profile.skill_path}: install shared capture/recall skill."

        if not dry_run:
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(skill_content, encoding="utf-8")

        return [action]

    def _update_instructions(self, profile: ClientProfile, *, dry_run: bool) -> list[str]:
        if not profile.instruction_path:
            return []
        instr_file = self._root / profile.instruction_path
        block = _ACTIVATION_BLOCK

        if instr_file.exists():
            content = instr_file.read_text(encoding="utf-8")
            if _ACTIVATION_MARKER in content:
                return [f"[skip] {profile.instruction_path}: activation block already present."]
            new_content = content.rstrip() + "\n\n" + block
            action = f"[add] {profile.instruction_path}: append CommitEcho activation block."
        else:
            new_content = block
            action = f"[create] {profile.instruction_path}: create with CommitEcho activation block."

        if not dry_run:
            instr_file.parent.mkdir(parents=True, exist_ok=True)
            instr_file.write_text(new_content, encoding="utf-8")

        return [action]


# ---------------------------------------------------------------------------
# Shared activation block (appended to per-client instruction files)
# ---------------------------------------------------------------------------

_ACTIVATION_MARKER = "<!-- commitecho-activation -->"

_ACTIVATION_BLOCK = f"""{_ACTIVATION_MARKER}
## CommitEcho – decision capture and recall

Use the CommitEcho MCP tools to preserve and recall the reasoning behind code changes.

Activate the commitecho skill for detailed capture/recall steps.
"""
