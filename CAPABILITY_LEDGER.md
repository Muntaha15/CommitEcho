# CommitEcho client capability ledger

Updated 2026-10-03 after Claude UAT remediation on base `4a1478d`. Configuration, MCP
protocol, agent workflow, and native lifecycle qualification are separate.
See [the implementation review](MULTI_CLIENT_INTEGRATION_REVIEW.md).

## Recorded environment

- Independent remediation implementation `bfa2b5a`, skill v6,
  CommitEcho `0.1.1.dev0`: **285 passed, 1 skipped in 379.19 seconds** on
  Windows, Python 3.12.14, MCP SDK 2.2.0, Git 2.49.0.windows.1. All real MCP
  handshakes ran, including exact alternative-reason/evidence preservation
  through restart and Git-only clone index recall. D-1-D-3 are fixed with
  automated regressions; revised native Claude capture remains pending.
  `test_all_client_preflight_rejects_symlink_escaping_repository` skipped for
  directory-symlink privilege; a separate probe reproduced WinError 1314.
  Enable Developer Mode or use an elevated shell and rerun. Earlier isolated
  passes remain separate. Record `d1f82581-487e-4503-9919-e76603fb032e` verified
  `exact` and was indexed. Claude is unavailable on PATH and usual native/npm
  paths. The older environments and counts below retain their original scope.

- Review/test host: Windows, Python 3.12.14, MCP SDK 2.2.0, CommitEcho 0.1.0,
  Git 2.49.0.windows.1; Codex desktop chat using its local shell/MCP tools.
- Available Codex CLI reports `0.159.0-alpha.12.1`. This is an inventory
  observation, not a CLI workflow or native-hook acceptance run. No minimum
  supported client version is inferred from it.
- Claude Code executable was unavailable during the initial repair review. Copilot and Antigravity revised
  discovery/event acceptance were not run during the initial repair review. No POSIX runtime
  acceptance was performed.
- Follow-up [Codex live test](CODEX_LIVE_TEST.md): interactive CLI capture,
  commit, exact verification, and recall in a fresh process passed using normal
  approvals. Earlier non-interactive attempts failed under approval policy
  `never`. Explicit indexing recovered initially empty recall; the record's
  attached evidence was empty. Automatic skill discovery remains unqualified.
- Follow-up [Antigravity live test](ANTIGRAVITY_LIVE_TEST.md): native capture,
  exact verification, indexing, process restart, and fresh-process recall
  passed using the generated Antigravity profile in a separate fixture with
  spaces. Automated protocol restart tests pass for Antigravity alongside Codex.
- Supplied [Claude Code UAT report](CLAUDE_CODE_UAT_REPORT.md): CLI 2.1.286,
  model `claude-opus-5-5`, Windows 11 x64, Python 3.12.10, MCP SDK 2.3.0,
  Git 2.42.0.windows.2, skill v4. Reports 12 passing print-mode checks, organic
  skill activation, local approval, exact verification, indexing, and fresh-process
  recall. Its `242 passed, 1 skipped` result belongs to that external run; raw
  transcripts are not present here. The reported base `69df403` declares v0.1.0,
  so the exact tested working-tree state remains unverified. Only the two reports
  were transferred; our follow-up implementation is independent.
- Baseline full suite: 179 passed in 274.90 seconds, including real stdio tests.
  These passing tests did not cover the reproduced preservation/gate failures.
- Repaired full suite: **238 passed, 1 skipped in 341.08 seconds**. The skip is
  directory-symlink creation requiring unavailable Windows permission. All live
  MCP handshakes ran; no protocol timeout was increased. The run used the project
  environment with network/local-socket permission and isolated Git fixtures.
- Prior `0.1.1.dev0` checkout: **241 passed, 1 skipped in 362.22 seconds**,
  including the development-version plugin regression, parametrized restart
  lifecycle test across Codex and Antigravity, and all live MCP checks.
  The same Windows directory-symlink permission test skipped. Package/CLI
  metadata and portable plugin/skill consistency checks passed.

- Independent UAT follow-up on base `703387e` plus working-tree changes:
  **269 passed, 1 skipped in 366.47 seconds**, Windows, Python 3.12.14,
  MCP SDK 2.2.0, Git 2.49.0.windows.1, skill v5. All live MCP handshakes ran;
  the existing directory-symlink permission test skipped. This run includes
  Claude in the generic restart regression, exact skill upgrades, approval
  preservation, plugin skill migration, and fresh-clone evidence provenance.
  Claude is unavailable locally, so no revised native agent UAT is claimed.
- Windows symlink follow-up, 2026-10-03: the user enabled Developer Mode and
  reported **1 passed in 6.00 seconds** for
  `test_all_client_preflight_rejects_symlink_escaping_repository` in Git Bash.
  A prior isolated probe reproduced WinError 1314 (required privilege missing).
  Developer Mode allowed the fixture symlink to be created and the setup
  containment assertions to run. This resolves the skipped check in the user's
  environment; the earlier full-suite result remains 269 passed, 1 skipped.
  Git Bash command:
  `./.venv/Scripts/python.exe -m pytest -q -rs tests/integration/test_setup.py::test_all_client_preflight_rejects_symlink_escaping_repository`.

## Client matrix

| Client | Configuration / skill / activation | Protocol evidence | Actual revised client acceptance |
| --- | --- | --- | --- |
| Codex local | `.codex/config.toml`; `.agents/skills/commitecho/SKILL.md`; root `AGENTS.md` | Generated-command stdio tests; connected tools in this review chat | Interactive CLI 0.159.0-alpha.12.1 capture and fresh-process recall passed on Windows. Automatic skill discovery, unattended/cloud/native events, and cross-client handoff pending. `AGENTS.override.md` can mask activation. |
| Antigravity IDE | `.agents/mcp_config.json`; shared `.agents` skill; `.agents/rules/commitecho.md` | Generated-command stdio tests; live IDE 1.107.0 report | Native discovery, capture, verification, indexing, process restart, and fresh-process recall passed on Windows. CLI is a separate untested surface; native hooks/cross-client pending. |
| Copilot VS Code | `.vscode/mcp.json`; shared `.agents` skill; `.github/copilot-instructions.md` | Generated-command stdio tests | Interactive discovery/workflow pending. Local versus Agent Host/native harness not qualified. |
| Claude Code | `.mcp.json`; `.claude/skills/commitecho/SKILL.md`; `CLAUDE.md` | Generated-command stdio and restart tests; server reads documented `CLAUDE_PROJECT_DIR` | Supplied Windows CLI 2.1.286 round 2 print-mode report confirms skill v5 attribution, project capture/recall, and plugin loading/index-only clone recall. Round 2 found alternative-field loss. Remediated live skill v6 capture, plugin capture, interactive approval, portable PATH launch, POSIX, native events, and cross-client handoff remain pending. |

The suite asserts the eight tool names and intended worktree independently of
the client applications. It exercises capture/prepare/commit/verify/restart/
recall and isolated service-layer client identifiers. These tests do not prove
model adherence, automatic capture, or application skill loading.

## Setup ownership and runtime

Local defaults use the active interpreter and absolute worktree; machine paths
stay local. Existing user launch overrides, TOML comments, custom skills, and
instructions are preserved. Explicit server regeneration refreshes launch
fields. All selected configurations are preflighted; dry-run opens no stores.
Only exact recognized generated skill content is migrated.

Skill v6 retains explicit per-evidence client attribution and optional known native
session metadata, and documents typed alternatives with rejection `reason`.
Exact generated v4/v5 skills are recognized for setup and plugin
regeneration; custom skills stay protected. Evidence is not assigned a client
from a change's contributing sessions. Setup prints Claude approval guidance
without modifying approval settings; the README records the version-specific
`pending` observation and requires a callable `get_status` readiness check.

Automatic portable setup is limited to Claude's documented server project-root
contract. Other clients require an explicit launcher/root contract. Portable
commands require an installed package on PATH; no package registry or offline
runtime availability is implied by configuration generation.

## Git gate policy

`check-message` validates one canonical trailer, supported record/schema in the
Git index, preparation parent against HEAD (or root), and staged code manifest.
Strict mode requires records for every opted-in commit, including manual,
empty, and merge commits. Advisory mode warns without rejecting failures.
The gate checks consistency, not the truth of rationale or original authorship.

There is no guessed HEAD-parent/amend exemption. A `commit-msg` hook receives
only a message-file argument; the existing preparation workflow targets HEAD,
so automatic amend qualification remains unsupported. Explicit verification
of the resulting OID remains authoritative and owns change-lifecycle mutation.

Install/uninstall respect Git's effective hook path and refuse external/shared
locations. Foreign hooks are preserved. The launcher pins the installed Python
runtime and selects Git's actual working directory. Strict runtime failure
rejects. Hooks are local and bypassable with `--no-verify`.

## Native lifecycle and indexing

`index --timeout SECONDS` bounds the complete indexing process; completed
transactions remain reusable after interruption. Seconds must be finite and
positive. Explicit indexing and coverage diagnostics remain available.

Fresh Claude native-hook installation is gated pending observed client version,
event loading, output visibility, Windows invocation, and trust/disable tests.
Safe cleanup of previously generated hooks preserves foreign handlers and
settings. There is no automatic commit verification or shell interception.

## Claude plugin artifact

The minimal layout is `.claude-plugin/plugin.json`, `.mcp.json`, and
`skills/commitecho/SKILL.md`. Default generation is a local installed-runtime
artifact; the checked-in example uses `commitecho serve` and requires an
installed package and dependencies. Regeneration preflights ownership and
preserves customized/unrelated files. No hooks ship in the plugin.

Protocol smoke tests are separate from `claude plugin validate` and an actual
plugin-loaded project session, both still pending. Claude is not on PATH in the
local follow-up environment; the supplied external UAT did not test plugins.
The smoke tests use the installed editable package without `PYTHONPATH`;
revised standalone-wheel installation and offline distribution were not tested.
Disable project CommitEcho registration while enabling the plugin to avoid
duplicate server/skill discovery. Registry execution, bundled runtimes,
historian, and extra slash skills remain deferred.

## Official references

[Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[VS Code MCP](https://code.visualstudio.com/docs/agent-customization/mcp-servers),
[VS Code skills](https://code.visualstudio.com/docs/agent-customization/agent-skills),
[Antigravity MCP](https://antigravity.google/docs/mcp),
[Antigravity skills](https://antigravity.google/docs/skills),
[Claude MCP](https://code.claude.com/docs/en/mcp),
[Claude hooks](https://code.claude.com/docs/en/hooks),
[Claude plugins](https://code.claude.com/docs/en/plugins-reference),
[Git hooks](https://git-scm.com/docs/githooks).
