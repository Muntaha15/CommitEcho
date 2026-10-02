# CommitEcho Client Capability Ledger

Last updated: 2026-10-02

This ledger documents verified client surfaces, environments, MCP configurations, skill discovery paths, and integration statuses. Validation must be performed against actual client runtime sessions and documented schemas, rather than assuming protocol parity.

| Client Profile | Surface / Harness | Platform / OS | MCP Configuration | Skill Path | Status | Notes / Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `antigravity` | Antigravity IDE | Windows / POSIX | `.agents/mcp_config.json` (`mcpServers`) | `.agents/skills/commitecho/SKILL.md` | Verified | Tested with MCP SDK 2.2+. Native rule in `.agents/rules/commitecho.md`. Stdio handshake verified. |
| `codex` | Codex (local) | Windows / POSIX | `.codex/config.toml` (`mcp_servers`) | `.agents/skills/commitecho/SKILL.md` | Verified | Folder-based skill in `.agents/skills`. Project instructions in root `AGENTS.md`. Stdio handshake verified. |
| `copilot_vscode` | GitHub Copilot in VS Code | Windows / POSIX | `.vscode/mcp.json` (`servers`) | `.agents/skills/commitecho/SKILL.md` | Untested | Config generator implemented; live session acceptance pending Copilot environment. |
| `claude_code` | Claude Code CLI | Windows / POSIX | `.mcp.json` (`mcpServers`) | `.claude/skills/commitecho/SKILL.md` | Pending Phase 1 | Supports `CLAUDE_PROJECT_DIR`. Implementation targeted for Phase 1. |

## Notes on Native Integration and Hook Contracts

- **Git Message Enforcement**: Use repository Git `commit-msg` hooks for universal message validation across all clients. Native tool-interception hooks are optional reminders/automation only.
- **Client Identification**: Each client passes its active profile ID (`antigravity`, `codex`, `copilot_vscode`, `claude_code`) in `client` during `begin_change`.
- **Status Accounting**: Clients without verified live runtime tests are marked as **Untested** or **Pending**, never claimed as validated through static SDK checks alone.
