# Agent integration plan

Status: setup profiles and a shared skill are implemented in v0.1.0; live end-to-end validation in Codex, Antigravity IDE, and Copilot in VS Code has not been recorded. Reviewed 2026-09-27.

Initial targets: local Codex sessions, Antigravity IDE, and **GitHub Copilot in VS Code**, as selected by the project owner. Copilot CLI and cloud agent are later targets.

## Support levels

| Level | Contract |
| --- | --- |
| Protocol compatible | Client can launch the stdio MCP server and call its tools |
| Workflow supported | Setup installs instructions/skill; capture, prepare, verify, and recall pass in that client |
| Lifecycle enhanced | Specific native hooks improve checkpoint reminders or verification, with tested fallback |

The first release requires the middle level for all three targets. It does not promise every MCP client can silently capture complete chat history. Each additional agent needs configuration, a usable instruction mechanism, and an integration test; most core logic is shared.

## Documented integration paths

| Client | Baseline connection | Workflow installation | Optional automation |
| --- | --- | --- | --- |
| Codex, local | Configured local stdio MCP command | Project instruction plus shared skill | Codex-specific lifecycle hooks after version/surface testing |
| Antigravity IDE | Custom MCP entry through raw configuration | Shared skill and a persistent rule | Do not assume IDE and CLI hook parity |
| Copilot in VS Code | Workspace MCP configuration | Shared skill and Copilot instructions | Hook behavior depends on the active harness and version |

[Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp) describes its server configuration. [Codex skills](https://learn.chatgpt.com/docs/build-skills) and [OpenAI's skill/MCP guidance](https://developers.openai.com/plugins/concepts/skills) support packaging a workflow around tools. [Codex hooks](https://learn.chatgpt.com/docs/hooks) offer lifecycle integration, but they are an optional adapter capability, not the portable capture mechanism.

Antigravity documents custom stdio MCP commands under `mcpServers`, including a workspace `.agents/mcp_config.json` path. Its skill documentation lists `.agents/skills/`, and persistent rules provide an activation path. Prefer skills to legacy Workflows, which have a documented migration. Sources: [MCP](https://www.antigravity.google/docs/mcp), [skills](https://www.antigravity.google/docs/skills?tab=ide), [rules](https://www.antigravity.google/docs/rules/), [workflow migration](https://www.antigravity.google/docs/migration/workflows-to-skills/).

VS Code documents `.vscode/mcp.json` with a `servers` map and a portable `.mcp.json` format. Its skill locations include `.agents/skills/`. Hook selection depends on the session harness, so record that in validation results. Sources: [MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration), [skills](https://code.visualstudio.com/docs/agent-customization/agent-skills), [hooks](https://code.visualstudio.com/docs/agent-customization/hooks).

## Shared instruction content

One canonical capture/recall workflow should be installed from templates, with a short client-specific activation instruction. It must say:

1. Begin or resume a CommitEcho change when the task involves meaningful code/design work.
2. Save decisions when an approach is chosen, rejected, or revised. Record only information present in visible context.
3. Preserve the distinction between user statements, agent summaries, hypotheses, and observed artifacts.
4. Before a commit, select decisions for the staged change and prepare its record.
5. Use the normal authorized Git commit workflow; include the prepared record and trailer.
6. Verify the resulting commit, and report any stale or missing linkage.
7. For historical questions, search CommitEcho and retrieve evidence before composing the answer. State missing history explicitly.

The shared instruction content is implemented in `src/commitecho/integrations/skill.md` and installed by `commitecho setup --client <id>`. It remains an agent instruction, so capture depends on the client following it.

## Setup behavior

The CLI implements `commitecho setup --client <id>` (repeatable; omitting it selects all profiles). It merges an MCP server entry into JSON configuration, installs the shared skill, and adds an activation block for Codex and Copilot. Antigravity has no generated persistent rule. `--dry-run` lists actions; it does not show a file diff. Removal and upgrade ownership tracking are not implemented.

Each stdio command launches an installed, pinned CommitEcho executable with an explicit repository/worktree path. Setup must handle Windows spaces and executable resolution. Do not rely on identical working-directory defaults, shell expansion, or environment-variable syntax across clients.

A client adapter records:

```text
client + surface + version
MCP configuration format and supported transport
instruction/skill locations and activation rules
native hook capabilities, if validated
how to run the common smoke scenario
known limitations
```

`commitecho doctor` checks Git discovery, Python version, SQLite FTS5, MCP package availability, database opening, installed skill content, and whether client configs contain a `commitecho` entry. It does not validate a client handshake or agent instruction adherence.

## Integration acceptance scenario

Run the same task from a fixture repository in each client:

1. Discuss two approaches to fixing duplicate requests and select one for a stated constraint.
2. Make a code change and stage only part of it.
3. Capture the chosen and rejected approaches, prepare memory, commit, and verify.
4. Start a new conversation and ask why the committed lines changed.
5. Change the index after preparation and confirm the record is not labeled an exact match.
6. Restart the client and recover a pending change.
7. Clone into a fresh directory, rebuild the index, and ask from a different supported agent.

Record client version, active harness, operating system, model, tool permissions, observed tool calls, missing captures, and the returned evidence. A successful MCP handshake alone does not pass this test.

## Extension boundary

A future client that can call tools but cannot discover skills can receive equivalent project instructions or a manual prompt. If it cannot access the local repository, it needs a separate remote deployment/storage design. If it cannot send structured tool calls, it does not meet the MCP support contract.

Transcript import can later add source excerpts and recover missed checkpoints, using explicit per-client adapters. Native session files and internal APIs are not a portable dependency. No claim of support for an untested agent or complete passive capture appears in the README.

Copilot cloud agent has distinct MCP constraints; its documentation currently describes tools support separately from resources/prompts. Evaluate it as its own surface rather than inheriting the VS Code result. [GitHub documentation](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/mcp-and-cloud-agent).
