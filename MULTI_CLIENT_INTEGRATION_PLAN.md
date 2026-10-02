# CommitEcho multi-client integration plan — reviewed handoff

Reviewed: 2026-10-02. Code baseline: `69df403`.
Implementation owner: Antigravity. This document revises the supplied plan; it does not claim that the proposed features are implemented or client-tested.

The direction is sound: fix shared setup, add Claude Code, then enhance automation and distribution. The main correction is to distinguish **configuration generated**, **MCP connection tested**, **workflow tested in the actual client**, and **hook behavior tested**. None implies the next.

## Corrections to the original plan

| Priority | Finding | Required change |
| --- | --- | --- |
| P1 | Checking whether shell text contains `git commit` or `CommitEcho-Record:` cannot validate the resulting message. It misses `git -C`, aliases, `-F`, editors, amend/reuse-message modes, and compound commands; unrelated quoted text can also satisfy the check. | Use Git's `commit-msg` input for message enforcement. Treat native tool hooks as optional reminders/automation with explicit coverage limits. |
| P1 | The proposed Codex hook file has the wrong structure. | Use the documented `hooks` → event → matcher group → handlers structure. Do not reuse another client's serializer or assume a minimum version from the original plan. |
| P1 | Antigravity is described as lacking pre-tool interception, and `postCommit` is presented as an event. | Current documentation describes `PreToolUse` and `PostToolUse`, with a different schema and payload. Replace the example; prove behavior separately on the installed IDE and CLI. |
| P1 | `verify HEAD` in background automation can verify a later commit, and successful verification can close a prepared change by default. | Prefer explicit `verify_commit` with the actual commit OID. Defer automatic post-commit verification until OID selection and change lifecycle are designed and tested. |
| P1 | Existing Codex and Copilot profile skill paths do not match the documented directory-based discovery convention; Codex instructions target `.codex/AGENTS.md`. | Install a shared folder-based skill and put repository activation instructions in root `AGENTS.md`, accounting for overrides. Test discovery, not just file existence. |
| P1 | Adding per-client skill substitution breaks doctor's exact comparison with `_SKILL_TEMPLATE`, and shared skill discovery can make another client's rendered identity visible. | Prefer one client-neutral skill. If templating is used later, setup and doctor must share rendering logic and avoid collisions. |
| P2 | `--repo .` defeats environment fallback; Click currently defaults `serve --repo` to `.`. `CODEX_PROJECT_DIR` is assumed without evidence. | Resolve repository selection at the CLI boundary with an unset default; use only documented host variables. |
| P2 | `doctor` does not perform a live handshake. Proposed `tests/test_profiles.py` and `tests/test_mcp_handshake.py` do not exist. | Keep static diagnostics explicit; extend `tests/integration/test_setup.py`, which already has real stdio handshake and restart tests. |
| P2 | A plugin running `uvx` is neither self-contained nor usable without runtime/package availability. Its hooks using bare `commitecho` need a separate PATH installation. | Choose and test one consistent runtime policy for MCP and hooks; gate registry execution on a published, pinned package. |
| P2 | Windows support, offline startup, configuration preservation, and version gates are deferred despite being prerequisites. | Include them in each feature's acceptance criteria. |

Codex's nested schema and trust requirements are documented in [Codex hooks](https://learn.chatgpt.com/docs/hooks). Antigravity's named hook definitions, pre/post events, and `toolCall` payload are documented in [Antigravity hooks](https://antigravity.google/docs/hooks). These are documentation findings, not proof of support in the installed versions.

## Scope and invariants

- Preserve the existing capture/prepare/verify/recall semantics, provenance boundary, revision checks, and idempotency rules. No database or record-schema migration is needed merely to add a client; `client` is already a string.
- Hooks do not create decisions, fabricate evidence, automatically stage files, or authorize commits. Record preparation and Git commits remain explicit agent/user workflow steps.
- Keep the eight MCP tools and current Python/MCP dependency requirements. No new dependency or generic hook framework is needed for this work.
- Keep machine-specific client configuration and private databases local. Portable examples and distributable templates must contain no checkout-specific paths or credentials.
- Every phase includes its own tests and acceptance gate. Final validation consolidates results; it is not the first time testing happens.

## Phase 0 — verify capabilities and fix shared setup

### 0.1 Establish a small capability ledger

Before implementing each native integration, record exact client version, surface/harness, OS, documented schema, and an observed discovery result. Start with Antigravity IDE and local Codex; add Claude Code and Copilot VS Code as those clients become available. IDE, CLI, desktop, Agent Host, and cloud are separate validation surfaces.

Record unavailable clients as **not tested**, never as passed through an SDK handshake. Remove the unverified `Codex v0.117.0+` minimum and the fixed per-turn token estimates. Establish the minimum supported versions from observed tests. Skill descriptions are loaded metadata; this does not establish a constant token cost every turn.

### 0.2 Make the shared skill client-neutral

In `src/commitecho/integrations/skill.md`:

- Replace both Antigravity defaults with instructions to identify the active agent: `codex`, `antigravity`, `copilot_vscode`, or `claude_code`. These are profile IDs, not a new closed server enum.
- Keep a concise description covering beginning/resuming meaningful coding work, recalling rationale, and preparing/verifying an authorized commit.
- Bump `version` from 2 to 3 when the workflow changes, and retain all existing provenance, UUID, revision, staging, and re-preparation instructions.
- Explain that unavailable tools must be reported, and that installing a skill does not grant commit permission.

Use the same bytes across clients. This avoids changes to doctor's template comparison and prevents sequential multi-client setup from replacing one client's identity with another's.

### 0.3 Repair discovery locations and migrate carefully

Recommended installed locations:

| Client | MCP configuration | Skill | Activation instructions |
| --- | --- | --- | --- |
| Codex, local | `.codex/config.toml` | `.agents/skills/commitecho/SKILL.md` | Root `AGENTS.md` |
| Antigravity | `.agents/mcp_config.json` | `.agents/skills/commitecho/SKILL.md` | `.agents/rules/commitecho.md` |
| Copilot VS Code | `.vscode/mcp.json` | `.agents/skills/commitecho/SKILL.md` | `.github/copilot-instructions.md` |
| Claude Code | `.mcp.json` | `.claude/skills/commitecho/SKILL.md` | Root `CLAUDE.md` |

Codex scans repository `.agents/skills`; VS Code supports folder-based skills there. Codex discovers project instructions along the root-to-working-directory path, so `.codex/AGENTS.md` does not serve as root guidance in a normal root-launched session. An `AGENTS.override.md` can take precedence and needs a diagnostic/manual activation path. Sources: [Codex skills](https://learn.chatgpt.com/docs/build-skills), [Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [VS Code skills](https://code.visualstudio.com/docs/agent-customization/agent-skills).

Update profile paths and deduplicate shared installations. For old `.codex/skills/commitecho.md` and `.agents/skills/commitecho.md`, migrate/remove only files positively identified as known generated assets. Preserve custom files and report manual migration. Do not delete a customized `.codex/AGENTS.md` or move unrelated instructions into root `AGENTS.md`.

### 0.4 Preserve local launch reliability; add portability only with a proved root

Keep the current default: `[sys.executable, '-m', 'commitecho', 'serve', '--repo', absolute_worktree]`. Absolute local paths are intentional and already tested; do not replace that default.

An optional `--portable` may select `commitecho serve`, with installation on PATH documented. Do not add a per-profile `portable_command` field unless actual supported profiles require different executable forms. Existing `--server-cmd` remains the customization mechanism; define its relationship to `--portable` and reject conflicting input before writing anything.

Repository resolution contract for commands that need it:

1. Explicit `--repo` wins, including explicit `--repo .`.
2. A supplied `COMMITECHO_REPO` wins when the argument is omitted.
3. For the validated Claude integration, use documented `CLAUDE_PROJECT_DIR` when the above are absent.
4. Otherwise use the process working directory and the existing Git discovery routine.

Implement this at the CLI resolution boundary used by `serve`, not by adding an argument parser to `mcp_server.py`. Pass the resolved path to `run_server`. Validate the selected Git worktree before opening private stores; an invalid explicit path must fail rather than fall through to another repository. Do not introduce `CODEX_PROJECT_DIR` without an authoritative runtime contract.

Claude documents `CLAUDE_PROJECT_DIR` in spawned stdio servers. Project config interpolation and plugin interpolation have different timing; reading it in Python avoids depending on that difference. [Claude MCP documentation](https://code.claude.com/docs/en/mcp).

Portable output must omit `--repo .` when relying on that fallback. For clients without a documented project-root mechanism or verified launch cwd, do not label a relative configuration portable: retain local setup or document an explicit launcher requirement. Test launching from an unrelated repository as well as from a subdirectory.

### 0.5 Configuration ownership and dry-run behavior

- Merge the CommitEcho server entry while preserving unrelated servers/settings; retain TOML comments through `tomlkit`.
- Preserve user overrides inside an existing CommitEcho entry unless the user explicitly requests regeneration. Define which fields setup owns and show changes in dry-run.
- Preflight selected profiles, existing file formats, and command input before writes. Unknown clients, empty commands, malformed JSON/TOML, or structurally invalid server maps must return an actionable failure.
- A true dry-run must not create private databases. Currently `setup` calls `_get_git_and_dbs` first; use Git discovery alone where setup needs only the worktree.
- Do not silently overwrite a customized installed skill; update positively identified generated content, otherwise show a conflict and preserve the file. Keep activation insertion idempotent and preserve unrelated instructions.
- Keep this revision at repository root: this checkout ignores `docs/`. Do not change that ignore policy or force-add generated configuration as part of implementation without a separate reason.

**Acceptance:** all selected profiles install the expected assets; repeated setup makes no changes; dry-run writes nothing; custom/invalid files are preserved; root discovery and launch commands work with Windows paths containing spaces; existing tests still pass.

## Phase 1 — Claude Code baseline profile

Add `CLAUDE_CODE` to `ALL_PROFILES` using `.mcp.json`, `mcpServers`, `.claude/skills/commitecho/SKILL.md`, and `CLAUDE.md`. No plugin or native hook is required for baseline support. Reuse the generator's plain activation block; add a skill-path reference only if actual discovery needs it.

Update CLI help, examples, tool schema descriptions, and the domain comment listing client examples. Do not add validation that breaks existing arbitrary client identifiers. Remember that no-argument `setup` currently configures every profile: retain and document that behavior, or deliberately change and test it rather than accidentally expanding its side effects.

Extend the existing profile parameterizations in `tests/integration/test_setup.py`. The live launch test currently names only Codex and Antigravity explicitly; extend it to Claude Code and Copilot configuration commands where applicable. Verify all eight tools, the actual target worktree, and a full capture/prepare/commit/verify/recall lifecycle in fixtures.

`doctor` remains static by default: detect the new profile and skill, distinguish absent optional clients from invalid installed configuration, and never print a handshake success based on importing `mcp`. A live mode is optional future work, not a prerequisite for a working Claude profile.

Document Claude's project MCP approval/loading step and a new-session/reload check. Project `.mcp.json` is shareable only when its contents are portable; file location alone does not make the current default absolute command safe to commit. [Claude MCP configuration](https://code.claude.com/docs/en/mcp).

**Acceptance:** generated configuration passes a real stdio handshake, Claude actually discovers the tools and skill, setup preserves existing `.mcp.json` and `CLAUDE.md`, and a new Claude conversation retrieves evidence from the fixture commit. Without the client run, label this phase configuration/protocol support only.

## Phase 2 — universal Git message validation, explicitly enabled

### 2.1 Replace command-string `check-trailer` with a message-file check

Proposed CLI interface: `commitecho check-message MESSAGE_FILE [--repo PATH] [--strict]`. This receives the actual message file from Git rather than a client-specific stdin tool payload.

Use `git interpret-trailers --parse`, consistent with `GitAdapter.read_commit_trailers`, instead of substring searches or `grep`. Reuse the existing parser pattern; extract a tiny shared helper only if both call sites need it. Require one valid canonical record UUID and report duplicate/invalid declarations distinctly.

To call this a record-validating gate, also inspect the referenced record from the **index**, validate its schema/identity, and compare its preparation against the staged code manifest using existing manifest helpers. A trailer-only gate must be labeled trailer-only. Do not reuse `VerifyService.verify_commit(HEAD)` for a prospective commit: HEAD is the previous commit.

Default advisory mode prints an actionable warning without blocking. Explicit strict mode rejects missing/invalid required records and validation failures. State what strict mode applies to: every commit in an opted-in repository, including manual commits; merge/amend/empty commits must have a tested policy. Avoid silently exempting cases under an enforcement claim.

### 2.2 Safe hook installation

Proposed CLI: `commitecho hook install --git [--strict] [--dry-run]`, with a documented uninstall path for CommitEcho-owned content.

- Locate the effective hook directory through Git, respecting `core.hooksPath` and linked worktrees; do not assume `.git` is a directory.
- Install only in the repository-local effective location. If configuration resolves to a shared/global hook directory, report the target and require a deliberate separate installation choice rather than modifying it incidentally.
- Preserve existing hooks. Do not append after an arbitrary `exit`, rewrite another tool's hook, or replace a hook manager. If occupied, print the exact integration command/instructions and leave it unchanged.
- Use a marked, idempotent launcher with argument/path quoting appropriate for Git on Windows and POSIX. Ensure it works when a GUI or agent launches Git with a different PATH.
- Define reinstall/strict-toggle and uninstall behavior, retain other hooks, and preserve executable permissions where relevant.
- Document bypass: Git's `--no-verify` skips `commit-msg`; hooks are local and are not installed by cloning. Mandatory organization policy would need separate CI/server-side enforcement, outside this plan.

Git documents `commit-msg`'s message-file argument, nonzero rejection, hook locations, and bypass. [Git hooks](https://git-scm.com/docs/githooks), [Git configuration](https://git-scm.com/docs/git-config).

**Acceptance:** actual `git commit` fixture tests cover `-m`, `-F`, amend, missing/fake/duplicate trailers, unstaged records, stale preparation, root commit, a linked worktree, `core.hooksPath`, an existing hook, advisory/strict modes, and uninstall. Strict failure must leave HEAD unchanged; advisory failure must permit the commit with a diagnostic.

## Phase 3 — optional native lifecycle enhancements

Do not install native hooks silently during normal `setup`. Introduce an explicit opt-in only once a client adapter has passed the capability ledger and runtime tests. Keep serialization and payload handling small and client-specific; there is no universal hook wire format.

### 3.1 Schema corrections and coverage

| Client | Documented shape / behavior | Implementation gate |
| --- | --- | --- |
| Claude Code | Nested `hooks` event groups. Current docs support exec-form `command` plus `args`; `if` belongs on the handler, not the matcher group. | Pin/test a minimum version supporting fields used; include Bash and PowerShell coverage where available. |
| Codex | Nested `hooks` event/matcher/handler groups. Current docs use a command string, with optional `commandWindows`; non-managed hooks require review/trust. | Test the installed runtime, actual tool name/input, quoting, and trust. Do not copy Claude's exec-form `args` without explicit support. |
| Antigravity | Top-level named hook definitions, each containing events such as `PreToolUse`/`PostToolUse`. Input uses `toolCall.name` and `toolCall.args`; deny output uses `decision`/`reason`. | Test IDE and CLI independently. Remove the unsupported `postCommit` example and assumption of Claude/Codex payload parity. |
| Copilot VS Code | Hook schema is owned by the selected session harness; current Local hooks include pre/post events. | Record Local versus Copilot Agent Host or another provider; optional adapter only after that harness is tested. |

Sources: [Claude hooks](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [Antigravity hooks](https://antigravity.google/docs/hooks), [VS Code hook selection](https://code.visualstudio.com/docs/agent-customization/hooks).

Use the universal Git hook for message gating across these clients. Native pre-tool checks may remind the agent to prepare a record, but must not claim to parse arbitrary shell commands or cover commits outside the intercepted tools.

### 3.2 Start with bounded session indexing

For a client with a validated session-start event, reuse `commitecho index` with the correct worktree and a bounded timeout. Cover startup/resume as supported. Antigravity's documented invocation events are not automatically session-start equivalents; avoid indexing on every model invocation.

If indexing is asynchronous, the agent may search before it finishes. Do not promise immediate complete searchability. Keep the existing explicit indexing/coverage diagnostic path, test concurrent processes, and make failures visible without blocking ordinary work. Use plain status/context output only where the client's event contract supports injection.

### 3.3 Keep explicit verification authoritative

The current verifier persists bindings and may change the latest prepared change to committed when `keep_open=False`. Automatic verification is therefore a state mutation, not a read-only health check.

Initially retain the shared skill's explicit `verify_commit(commit_oid=actual_oid, keep_open=...)`. If automatic verification is later implemented, it must determine the actual successful commit, account for multiple commits/amends and asynchronous shell completion, and define how it interacts with multi-commit open changes. `--keep-open` alone is not a universal solution because it also changes state. Test races with explicit agent verification and database contention.

### 3.4 Failure and output contract

- Index/context/reminder failures are advisory and observable; malformed stdin must not crash or block unrelated tools.
- The strict Git gate rejects inability to validate. Do not turn a promised strict policy into silent fail-open behavior through a blanket `except`.
- For native blocking where explicitly required, use the destination client's documented decision output. Claude/Codex can use exit 2 plus stderr, or structured denial with successful process exit; Antigravity has its own JSON contract. Test the exact selected form.
- Opt-in handlers must preserve unrelated hook definitions/settings and remain idempotent. Do not broadly auto-approve tools merely because a CommitEcho check succeeded.

**Acceptance:** actual client event tests prove loading, opt-in/trust, event filtering, unrelated tool behavior, failure diagnostics, cwd handling, Windows invocation, and disable/re-enable. Passing generated-JSON tests alone is insufficient.

## Phase 4 — Claude plugin packaging and consolidated release validation

### 4.1 Ship the smallest usable plugin first

Begin with:

```text
commitecho-plugin/
├── .claude-plugin/plugin.json
├── .mcp.json
└── skills/commitecho/SKILL.md
```

Keep components outside `.claude-plugin`. Reuse the canonical skill and current package version; document one installation route and validate with `claude plugin validate ./commitecho-plugin`. Manifest validation does not prove MCP startup or hook execution. [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference).

Prefer an installed package for initial local validation. Before publishing a registry-backed plugin, verify that the intended CommitEcho release and dependencies exist on the intended index, then pin the package version. `uvx` must be installed, supports a separate runtime environment, and needs network/cache availability; do not call this a self-contained plugin. Smoke-test from outside this source checkout without `PYTHONPATH`, including cached offline startup. Ensure hooks, if bundled, use the same supported runtime policy.

Avoid enabling the same MCP server through both project setup and a plugin in the same validation session. Test migration/disable instructions and tool namespace discovery; otherwise duplicate skill/server registration may hide failures.

### 4.2 Optional expansion after the baseline passes

Retain these from the original proposal as separate follow-ups:

- `/commitecho:why`: use the question/path arguments, search, fetch evidence, compare ranges, and state missing evidence.
- `/commitecho:commit`: explicit invocation only; include `operation_id` for mutations, correct revisions and selected decision IDs, staging/re-preparation, exact returned trailer, actual OID, and `keep_open`. Invocation does not authorize a push or unrelated changes.
- Historian: if added, use subagent frontmatter `tools`, not the skill field `allowed-tools`; allow only the observed read-only MCP names and prove write tools are unavailable. [Claude subagents](https://code.claude.com/docs/en/sub-agents).
- Plugin hooks: include only validated Phase 3 adapters. Avoid duplicating identical hook definitions through automatic discovery and explicit manifest configuration.
- `commitecho plugin --output-dir ...`: add a minimal deterministic generator once the package layout is validated. Reuse templates/rendering; reject output into a nonempty unrelated directory, preserve custom content, and test repeat generation. No plugin framework is needed.

Antigravity plugin parity, dynamic shell context injection, session transcript imports, and new database-path/monorepo behavior stay deferred. Existing stores deliberately use the Git common directory with worktree identities; changing that is a separate storage design, not an integration fix.

### 4.3 Test matrix and release evidence

| Check | Location / execution | Pass condition |
| --- | --- | --- |
| Setup/profile regressions | Extend `tests/integration/test_setup.py` | Discovery paths, all client IDs, neutral skill, idempotency, migration, preservation, true dry-run |
| Repository resolution | Small CLI-focused tests in the existing setup tests, or one new focused module | Explicit/env/cwd precedence, invalid roots, subdirectories, unrelated cwd, linked worktrees |
| Real MCP stdio | Existing live handshake/restart tests, expanded for generated commands | Initialize, all eight tools, intended worktree, lifecycle survives restart without `PYTHONPATH` |
| Git message gate | One focused integration module using real Git | Strict rejects before commit; advisory warns; staged record/manifest checks and hook coexistence |
| Native hooks | Payload fixtures plus actual client runs | Correct runtime decisions, version/OS/trust and observed events; no unexpected mutations |
| Plugin | Manifest validation plus actual plugin-loaded Claude session | Discovery, runtime/dependency availability, capture/recall, duplicate-install handling |
| Full regression suite | Project virtual environment | All tests pass, including live stdio tests; no timeout increase or skips to hide transport failures |
| Cross-client acceptance | Same Git fixture and fresh sessions/clone | Captured decisions are prepared/verified and retrieved with real evidence in another client |

Use the project's environment. On this Windows checkout the existing interpreter is `.venv/Scripts/python.exe`; the project's POSIX instructions use `.venv/bin/python`:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_setup.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

For environment creation/install, follow `AGENTS.md` with the OS-appropriate interpreter path. Live stdio/server and Git remote commands need the network/socket permissions required there; use the permissions supported by the execution environment. Preserve proxy/TLS/outbound policy. Do not use a larger handshake timeout as a permission workaround.

Record client surface/version, OS, Python/MCP version, model/harness, startup command, resolved worktree, observed tools/events, and outcome. Include partial staging, changing the index after preparation, multi-commit work, pending-change recovery, and fresh-clone index rebuild. Separate **protocol**, **workflow**, and **lifecycle** support in release notes.

The old Antigravity report records SDK 1.30.0 validation; current `pyproject.toml` requires MCP 2.2+. Rerun actual client acceptance for the current SDK rather than inheriting that report. This review did not run the test suite because it changes only this plan.

## Execution order for Antigravity

1. Implement Phase 0 shared skill/discovery and setup corrections; run the full suite.
2. Add the Claude baseline profile; run generated-command tests and actual Claude acceptance when available.
3. Implement the opt-in Git message gate independently; keep native shell-command parsing out of its scope.
4. Add one validated native enhancement at a time, starting with bounded session indexing on a supported client.
5. Validate the minimal Claude plugin, then add only the optional components needed for the release.

Each step is independently reviewable. Retain baseline support when a native feature cannot be validated. Re-estimate effort after the capability checks; the original 23-hour total excludes migration, runtime compatibility, hook coexistence, and real-client acceptance work.

First handoff target: a tested shared setup correction plus a Claude profile. Finish those before building the historian, specialized slash skills, automatic commit interception, or a plugin-generation command.
