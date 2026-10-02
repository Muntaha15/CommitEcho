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

import tomlkit

# ---------------------------------------------------------------------------
# Skill asset – loaded from the bundled skill.md file at import time
# ---------------------------------------------------------------------------

_SKILL_FILE = Path(__file__).parent / "skill.md"
_SKILL_TEMPLATE: str = _SKILL_FILE.read_text(encoding="utf-8")

# Extract the declared version from the YAML front-matter (``version: N``).
_version_match = re.search(r"^version:\s*(\d+)", _SKILL_TEMPLATE, re.MULTILINE)
SKILL_VERSION: int = int(_version_match.group(1)) if _version_match else 0


def is_known_generated_skill(content: str) -> bool:
    """Check if content matches a known generated CommitEcho skill asset or test stub."""
    if content.strip() == _SKILL_TEMPLATE.strip():
        return True

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n(.*))?$", content, re.DOTALL)
    if not fm_match:
        return False
    fm_text = fm_match.group(1)
    body_text = (fm_match.group(2) or "").strip()

    if not re.search(r"^name:\s*commitecho\b", fm_text, re.MULTILINE):
        return False

    v_match = re.search(r"^version:\s*(\d+)", fm_text, re.MULTILINE)
    if not v_match:
        return False
    version = int(v_match.group(1))

    # Version 0 test stub
    if version == 0:
        return True

    # Known versions 1, 2, 3
    if version in (1, 2, 3) and "# CommitEcho capture and recall workflow" in body_text:
        return True

    return False


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
    config_format: str = "json"
    instruction_format: str = "plain"
    # Known limitations for this client
    known_limitations: list[str] = field(default_factory=list)

    def mcp_config_entry(
        self, server_command: list[str], repo_path: str | None = None
    ) -> dict[str, Any]:
        """Return the MCP server config block for this client.

        Each element of *server_command* is stored as-is; JSON serialisation
        preserves spaces so clients that consume the array directly (Codex,
        Antigravity, VS Code all use the array form) never need shell quoting.
        """
        args = list(server_command[1:])
        if repo_path is not None:
            args.extend(["--repo", repo_path])
        return {
            "command": server_command[0],
            "args": args,
        }


# ---------------------------------------------------------------------------
# Supported client profiles
# ---------------------------------------------------------------------------

CODEX = ClientProfile(
    client_id="codex",
    display_name="Codex (local)",
    mcp_config_path=".codex/config.toml",
    mcp_servers_key="mcp_servers",
    config_format="toml",
    skill_path=".agents/skills/commitecho/SKILL.md",
    instruction_path="AGENTS.md",
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
    skill_path=".agents/skills/commitecho/SKILL.md",
    instruction_path=".agents/rules/commitecho.md",
    instruction_format="rule",
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
    skill_path=".agents/skills/commitecho/SKILL.md",
    instruction_path=".github/copilot-instructions.md",
    known_limitations=[
        "Hook behavior depends on the active session harness and VS Code version.",
        "Copilot cloud agent is a separate surface; do not inherit VS Code results.",
    ],
)

CLAUDE_CODE = ClientProfile(
    client_id="claude_code",
    display_name="Claude Code",
    mcp_config_path=".mcp.json",
    mcp_servers_key="mcpServers",
    config_format="json",
    skill_path=".claude/skills/commitecho/SKILL.md",
    instruction_path="CLAUDE.md",
    instruction_format="plain",
    known_limitations=[
        "Claude Code requires explicit approval to load project-local MCP servers.",
        "Project .mcp.json is shareable only when using portable configuration.",
    ],
)

ALL_PROFILES: dict[str, ClientProfile] = {
    p.client_id: p for p in [CODEX, ANTIGRAVITY, COPILOT_VSCODE, CLAUDE_CODE]
}


# ---------------------------------------------------------------------------
# Setup generator
# ---------------------------------------------------------------------------


class SetupGenerator:
    """Generates per-client configuration files for CommitEcho.

    Merges into existing config files without replacing other MCP servers
    or user instructions.  Provides dry-run diff before writing.
    """

    def __init__(
        self,
        worktree: str | Path,
        server_command: list[str],
        *,
        portable: bool = False,
    ) -> None:
        self._root = Path(worktree)
        self._cmd = server_command
        self._portable = portable
        self._migrated_legacy: set[Path] = set()

    def preflight(self, profiles: list[ClientProfile]) -> None:
        """Preflight selected profiles, command input, and existing configuration files.

        Raises ValueError on validation failure before any file write.
        """
        if not self._cmd or not any(part.strip() for part in self._cmd):
            raise ValueError("Server command cannot be empty.")

        for profile in profiles:
            config_file = self._root / profile.mcp_config_path
            if config_file.exists():
                raw = config_file.read_text(encoding="utf-8")
                config = (
                    tomlkit.parse(raw)
                    if profile.config_format == "toml"
                    else json.loads(raw)
                )

                servers_key = profile.mcp_servers_key
                if servers_key in config and not isinstance(config[servers_key], dict):
                    raise ValueError(
                        f"Invalid configuration in '{profile.mcp_config_path}': '{servers_key}' must be a mapping/table."
                    )

    def generate(
        self,
        profile: ClientProfile,
        dry_run: bool = False,
    ) -> list[str]:
        """Generate configuration for *profile*.

        Returns a list of human-readable change descriptions.
        If *dry_run* is True, no files are written.
        """
        self.preflight([profile])
        changes: list[str] = []
        repo_path = None if self._portable else str(self._root.resolve())

        # 1. MCP config
        changes.extend(
            self._update_mcp_config(profile, repo_path, dry_run=dry_run)
        )

        # 2. Skill file & legacy cleanup
        changes.extend(self._install_skill(profile, dry_run=dry_run))

        # 3. Activation instruction block
        if profile.instruction_path:
            changes.extend(self._update_instructions(profile, dry_run=dry_run))

        return changes

    def _update_mcp_config(
        self, profile: ClientProfile, repo_path: str | None, *, dry_run: bool
    ) -> list[str]:
        config_file = self._root / profile.mcp_config_path
        entry = profile.mcp_config_entry(self._cmd, repo_path)
        servers_key = profile.mcp_servers_key

        if config_file.exists():
            raw = config_file.read_text(encoding="utf-8")
            config = tomlkit.parse(raw) if profile.config_format == "toml" else json.loads(raw)
        else:
            config = tomlkit.document() if profile.config_format == "toml" else {}

        servers = config.setdefault(servers_key, {})
        if "commitecho" in servers:
            existing = servers["commitecho"]
            if not isinstance(existing, dict):
                raise ValueError(
                    f"Existing 'commitecho' entry in '{profile.mcp_config_path}' is not a mapping."
                )
            if existing.get("command") == entry["command"] and existing.get("args") == entry["args"]:
                return [f"[skip] {profile.mcp_config_path}: commitecho entry already up to date."]
            action = f"[update] {profile.mcp_config_path}: update commitecho server entry."
            # Preserve user overrides in unowned keys
            merged_entry = dict(existing)
            merged_entry["command"] = entry["command"]
            merged_entry["args"] = entry["args"]
            servers["commitecho"] = merged_entry
        else:
            action = f"[add] {profile.mcp_config_path}: add commitecho server entry."
            servers["commitecho"] = entry

        if not dry_run:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            rendered = (
                tomlkit.dumps(config)
                if profile.config_format == "toml"
                else json.dumps(config, indent=2)
            )
            config_file.write_text(rendered, encoding="utf-8")

        return [action]

    def _install_skill(self, profile: ClientProfile, *, dry_run: bool) -> list[str]:
        changes: list[str] = []
        skill_file = self._root / profile.skill_path
        skill_content = _SKILL_TEMPLATE  # read from skill.md at import time

        if skill_file.exists():
            existing = skill_file.read_text(encoding="utf-8")
            if existing == skill_content:
                changes.append(f"[skip] {profile.skill_path}: skill already installed.")
            elif is_known_generated_skill(existing):
                changes.append(f"[update] {profile.skill_path}: update shared capture/recall skill.")
                if not dry_run:
                    skill_file.parent.mkdir(parents=True, exist_ok=True)
                    skill_file.write_text(skill_content, encoding="utf-8")
            else:
                changes.append(
                    f"[conflict] {profile.skill_path}: custom skill content detected; preserving without overwrite."
                )
        else:
            changes.append(f"[add] {profile.skill_path}: install shared capture/recall skill.")
            if not dry_run:
                skill_file.parent.mkdir(parents=True, exist_ok=True)
                skill_file.write_text(skill_content, encoding="utf-8")

        # Legacy skill migration / cleanup
        legacy_paths = [
            Path(".codex/skills/commitecho.md"),
            Path(".agents/skills/commitecho.md"),
        ]
        for rel_legacy in legacy_paths:
            if rel_legacy in self._migrated_legacy:
                continue
            legacy_file = self._root / rel_legacy
            if legacy_file.exists() and legacy_file.resolve() != skill_file.resolve():
                self._migrated_legacy.add(rel_legacy)
                legacy_content = legacy_file.read_text(encoding="utf-8")
                if is_known_generated_skill(legacy_content):
                    changes.append(f"[migrate] {rel_legacy.as_posix()}: remove obsolete legacy skill file.")
                    if not dry_run:
                        try:
                            legacy_file.unlink()
                            try:
                                legacy_file.parent.rmdir()
                            except OSError:
                                pass
                        except OSError as exc:
                            changes.append(f"[warn] {rel_legacy.as_posix()}: failed to remove legacy file: {exc}")
                else:
                    changes.append(
                        f"[warn] {rel_legacy.as_posix()}: custom legacy skill detected; preserved (please migrate manually to {profile.skill_path})."
                    )

        return changes

    def _update_instructions(self, profile: ClientProfile, *, dry_run: bool) -> list[str]:
        if not profile.instruction_path:
            return []
        if getattr(profile, "instruction_format", "plain") == "rule":
            return self._update_rule(profile, dry_run=dry_run)
        instr_file = self._root / profile.instruction_path
        block = _ACTIVATION_BLOCK

        changes: list[str] = []
        if (self._root / "AGENTS.override.md").exists() and profile.instruction_path == "AGENTS.md":
            changes.append("[info] AGENTS.override.md detected: will take precedence over AGENTS.md in Codex sessions.")

        if instr_file.exists():
            content = instr_file.read_text(encoding="utf-8")
            if _ACTIVATION_MARKER in content:
                changes.append(f"[skip] {profile.instruction_path}: activation block already present.")
                return changes
            new_content = content.rstrip() + "\n\n" + block
            action = f"[add] {profile.instruction_path}: append CommitEcho activation block."
        else:
            new_content = block
            action = f"[create] {profile.instruction_path}: create with CommitEcho activation block."

        changes.append(action)
        if not dry_run:
            instr_file.parent.mkdir(parents=True, exist_ok=True)
            instr_file.write_text(new_content, encoding="utf-8")

        return changes

    def _update_rule(self, profile: ClientProfile, *, dry_run: bool) -> list[str]:
        assert profile.instruction_path is not None
        rule_file = self._root / profile.instruction_path

        if not rule_file.exists():
            action = f"[create] {profile.instruction_path}: create CommitEcho activation rule."
            new_content = _ANTIGRAVITY_RULE_CONTENT
        else:
            raw = rule_file.read_text(encoding="utf-8")
            if raw.strip() == _ANTIGRAVITY_RULE_CONTENT.strip():
                return [f"[skip] {profile.instruction_path}: activation rule already up to date."]

            # Check if valid frontmatter exists
            fm_match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n(.*))?$", raw, re.DOTALL)
            if fm_match:
                fm_text = fm_match.group(1)
                has_trigger = bool(re.search(r"^trigger:\s*\S+", fm_text, re.MULTILINE))
                has_desc = bool(re.search(r"^description:\s*\S+", fm_text, re.MULTILINE))
                has_marker = _ACTIVATION_MARKER in raw

                if has_trigger and has_desc and has_marker:
                    return [f"[skip] {profile.instruction_path}: activation rule already up to date."]
                else:
                    return [
                        f"[skip] {profile.instruction_path}: custom frontmatter found but missing trigger/description; "
                        "leaving intact (please configure 'trigger: always_on' and 'description: ...' manually)."
                    ]
            else:
                # No frontmatter. Check if this is the known generated legacy rule
                has_marker = _ACTIVATION_MARKER in raw
                cleaned = raw.replace(_ACTIVATION_MARKER, "").strip()
                known_legacy_phrases = [
                    "## CommitEcho – decision capture and recall",
                    "## CommitEcho - decision capture and recall",
                    "# CommitEcho – decision capture and recall",
                    "# CommitEcho - decision capture and recall",
                    "# CommitEcho",
                    "Use the CommitEcho MCP tools to preserve and recall the reasoning behind code changes.",
                    "Activate the commitecho skill for detailed capture/recall steps.",
                ]
                remainder = cleaned
                for phrase in known_legacy_phrases:
                    remainder = remainder.replace(phrase, "")
                is_known_legacy = (remainder.strip() == "")

                if has_marker and is_known_legacy:
                    action = f"[update] {profile.instruction_path}: repair legacy activation rule with trigger frontmatter."
                    new_content = _ANTIGRAVITY_RULE_CONTENT
                elif has_marker and not is_known_legacy:
                    return [
                        f"[skip] {profile.instruction_path}: contains custom instructions without rule frontmatter; "
                        "leaving custom content intact (add frontmatter with 'trigger: always_on' manually)."
                    ]
                else:
                    return [
                        f"[skip] {profile.instruction_path}: existing file without CommitEcho activation marker; "
                        "leaving intact to avoid overwriting custom content."
                    ]

        if not dry_run:
            rule_file.parent.mkdir(parents=True, exist_ok=True)
            rule_file.write_text(new_content, encoding="utf-8")

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

_ANTIGRAVITY_RULE_CONTENT = f"""---
trigger: always_on
description: Capture meaningful coding decisions and recall their evidence.
---
{_ACTIVATION_MARKER}
# CommitEcho decision capture and recall

When working on code or design tasks in this repository:
- Read the installed CommitEcho skill for meaningful code/design tasks.
- Begin or resume a change and record actual choices/rejections.
- Search history and fetch evidence for historical questions.
- Prepare and verify records when committing is authorized.
- Report unavailable tools rather than inventing successful capture.

Loading this rule does not imply permission to make Git commits; follow normal project authorization.
"""
