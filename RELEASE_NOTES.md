# CommitEcho release notes

## v0.1.1 - in development

Package version: `0.1.1.dev0`. This work has not been released; v0.1.0 remains
the published release. The portable plugin uses SemVer `0.1.1-dev.0`.

The 2026-10-03 multi-client review repairs setup preservation, strict Git gate behavior, indexing deadlines,
and plugin ownership; it does not extend those earlier sessions to revised
discovery paths or native hooks. Four configuration profiles now include
Claude Code. Revised qualification is tracked in [CAPABILITY_LEDGER.md](CAPABILITY_LEDGER.md)
and findings/repairs in [MULTI_CLIENT_INTEGRATION_REVIEW.md](MULTI_CLIENT_INTEGRATION_REVIEW.md).
Claude interactive/plugin validation and native event tests remain pending.
The repaired full suite passed 238 tests in 341.08 seconds; one new directory-
symlink test skipped because this Windows account lacks creation permission.
All live MCP tests ran. No new dependency or storage migration was introduced.

Later 2026-10-03 fixture runs add versioned evidence: interactive Codex CLI
and Antigravity IDE completed capture, exact verification, process restart,
and fresh-process recall after explicit indexing. See [Codex results](CODEX_LIVE_TEST.md)
and [Antigravity results](ANTIGRAVITY_LIVE_TEST.md). The canonical skill at that point was
version 4 and required indexing before recall; the portable plugin example used
the same skill. Raw sessions and fixture repositories remain local.

Prior development-checkout validation: **241 passed, 1 skipped in 362.22
seconds** using the project Python with all live MCP checks enabled, including
the parametrized restart lifecycle test for Codex and Antigravity. The skip
requires Windows directory-symlink permission. Package/CLI version metadata,
portable plugin generation, canonical skill content, and ignore rules also
passed their checks.

The supplied [Claude Code UAT report](CLAUDE_CODE_UAT_REPORT.md) records 12
passing Windows CLI 2.1.286 print-mode checks with skill v4 and local approval,
including organic activation and fresh-process recall. Its reported 242-test
result and source baseline have not been independently reproduced here; see
the capability ledger for scope and the baseline discrepancy.

Our independent follow-up adds Claude to the generic stdio restart regression,
documents the observed `pending` status, and prints setup approval guidance
without editing approval settings. Shared skill v5 clarifies known session
metadata and explicit evidence client attribution. Setup and plugin regeneration
recognize exact older skill templates while preserving custom content. The
fresh-clone evidence regression now checks index fallback and retained provenance.
No storage migration or dependency was added. Live skill v5 adherence,
interactive approval, cross-client handoff, plugin loading, and hooks remain
pending; Claude is not on PATH in this follow-up environment.

Independent follow-up validation on `703387e` plus working-tree changes:
**269 passed, 1 skipped in 366.47 seconds**, using Windows, Python 3.12.14,
MCP SDK 2.2.0, and Git 2.49.0.windows.1. All live MCP handshakes ran. The skip
is the existing Windows directory-symlink permission test. These automated
results do not qualify the pending native client scenarios.

Windows symlink follow-up (2026-10-03): the user enabled Developer Mode and
reran `test_all_client_preflight_rejects_symlink_escaping_repository` in Git Bash,
reporting **1 passed in 6.00 seconds**. The earlier skip resulted from missing
symlink-creation privilege (WinError 1314). This is a separate targeted result;
the full suite has not been rerun since enabling Developer Mode.

## v0.1.0 - 2026-10-01

Initial release. The core implementation is complete. Live session checks are
complete in Codex and Antigravity; Copilot in VS Code live acceptance remains
pending. The following evidence describes that original release.

### Included

- Local stdio MCP server exposing eight capture, preparation, verification, and recall tools.
- CLI, private SQLite drafts, portable committed JSON records, and rebuildable FTS5 index.
- Git binding checks, revision-scoped retrieval, evidence provenance, and idempotent retries.
- Setup profiles and shared instructions for Codex, Antigravity, and Copilot in VS Code.

### Validation evidence

- Windows, Python 3.12.14, MCP SDK 2.2.0: 120 tests passed in 201.68 seconds
  in the release-preparation Codex chat. Tests include real stdio handshakes,
  capture/commit/verify/restart/recall, fresh clones, stale preparation, branch
  isolation, retry recovery, and deterministic fixture evaluations.
- Codex desktop: connected MCP tools were called in this chat for status,
  change creation, and decision capture. The release commit carries a decision
  record so its binding and recall can also be checked through this connection.
- Codex release preparation independently built the wheel and installed it with
  resolved runtime dependencies in a fresh Python 3.12 environment outside the
  checkout. The installed entry point passed help/init/Codex setup/doctor, and
  its generated server command passed initialize, discovery of all eight tools,
  and get_status on MCP SDK 2.2.0. Package imports resolved inside that environment.
- Antigravity: clean wheel build and installation in an isolated environment
  outside the checkout, CLI init/setup/doctor, and stdio initialize/list_tools/get_status
  with all eight tools passed.
- Live session checks in Codex and Antigravity are complete.
- Client application versions are not recorded. Separate Codex CLI qualification
  and Copilot live model-session acceptance remain pending.

### Remaining qualification and limits

Complete the documented seven-step acceptance scenario in Copilot and retain
versioned results for the Codex/Antigravity runs, including missed captures,
restart recovery, new-chat recall, and cross-client clone handoff. Synthetic
service-layer client variants and protocol tests do not establish instruction
adherence in those apps.

Fixture evaluations measure stored context and linkage, not model answer quality
or automatic capture fidelity. Search is lexical. Credential/private-path checks
are best effort; review records before committing. Fresh-clone verification checks
self-consistent bindings, not the truth of a rationale or original local preparation.

The ignored `docs/` folder is not part of the published release. Client configuration
and private databases remain local. No PyPI publication is included in this release.
