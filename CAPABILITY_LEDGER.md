# CommitEcho Client Capability Ledger

Last updated: 2026-10-02

This ledger documents verified client surfaces, environments, MCP configurations, skill discovery paths, and integration statuses. Validation must be performed against actual client runtime sessions and documented schemas, rather than assuming protocol parity.

| Client Profile | Surface / Harness | Platform / OS | MCP Configuration | Skill Path | Status | Notes / Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `antigravity` | Antigravity IDE | Windows / POSIX | `.agents/mcp_config.json` (`mcpServers`) | `.agents/skills/commitecho/SKILL.md` | Verified | Tested with MCP SDK 2.2+. Native rule in `.agents/rules/commitecho.md`. Stdio handshake verified. |
| `codex` | Codex (local) | Windows / POSIX | `.codex/config.toml` (`mcp_servers`) | `.agents/skills/commitecho/SKILL.md` | Verified | Folder-based skill in `.agents/skills`. Project instructions in root `AGENTS.md`. Stdio handshake verified. |
| `copilot_vscode` | GitHub Copilot in VS Code | Windows / POSIX | `.vscode/mcp.json` (`servers`) | `.agents/skills/commitecho/SKILL.md` | Untested | Config generator implemented; live session acceptance pending Copilot environment. |
| `claude_code` | Claude Code CLI | Windows / POSIX | `.mcp.json` (`mcpServers`) | `.claude/skills/commitecho/SKILL.md` | Protocol verified | Config generator, stdio handshake, and `CLAUDE_PROJECT_DIR` support verified. Live interactive session check pending. |

## Notes on Native Integration and Hook Contracts

- **Git Message Enforcement**: Use repository Git `commit-msg` hooks for universal message validation across all clients. Native tool-interception hooks are optional reminders/automation only.
- **Client Identification**: Each client passes its active profile ID (`antigravity`, `codex`, `copilot_vscode`, `claude_code`) in `client` during `begin_change`.
- **Status Accounting**: Clients without verified live runtime tests are marked as **Untested** or **Pending**, never claimed as validated through static SDK checks alone.

## Phase 2: Universal Git Message Validation & Hook Management

- **CLI Commands**:
  - `commitecho check-message MESSAGE_FILE [--repo PATH] [--strict]`: Inspects commit message trailers, index-staged record JSON, schema validity, parent commit match, and staged code manifest SHA-256 fingerprint.
  - `commitecho hook install --git [--strict] [--dry-run]`: Installs marked, idempotent launcher in repository-local hook path (respects `core.hooksPath` and linked worktrees; refuses external/global hooks).
  - `commitecho hook uninstall [--dry-run]`: Deletes CommitEcho hook file or removes managed block, preserving foreign hooks.
- **Verified Policies**:
  - Empty commits without staged code are permitted without records.
  - In-progress merges (`MERGE_HEAD`) are permitted without records.
  - Amending message of an already-verified HEAD commit is permitted.
  - Code changes during amend or stale preparations are rejected in strict mode.
  - Foreign hooks without CommitEcho markers are left untouched with manual integration instructions.
- **Verification**: 29/29 tests passing in `tests/integration/test_hooks.py`.
