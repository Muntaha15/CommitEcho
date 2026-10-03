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
completed capture, exact verification, and fresh-process recall after explicit
indexing; Antigravity IDE reported native capture and linked-evidence recall,
without a documented process restart. See [Codex results](CODEX_LIVE_TEST.md)
and [Antigravity results](ANTIGRAVITY_LIVE_TEST.md). The canonical skill is now
version 4 and requires indexing before recall; the portable plugin example uses
the same skill. Raw sessions and fixture repositories remain local.

Final development-checkout validation: **240 passed, 1 skipped in 350.41
seconds** using the project Python with all live MCP checks enabled. The skip
requires Windows directory-symlink permission. Package/CLI version metadata,
portable plugin generation, canonical skill content, and ignore rules also
passed their checks.

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
