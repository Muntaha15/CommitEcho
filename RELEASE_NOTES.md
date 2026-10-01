# CommitEcho v0.1.0

Initial release, 2026-10-01. The core implementation is complete. Live session
checks are complete in Codex and Antigravity; Copilot in VS Code
live acceptance remains pending.

## Included

- Local stdio MCP server exposing eight capture, preparation, verification, and recall tools.
- CLI, private SQLite drafts, portable committed JSON records, and rebuildable FTS5 index.
- Git binding checks, revision-scoped retrieval, evidence provenance, and idempotent retries.
- Setup profiles and shared instructions for Codex, Antigravity, and Copilot in VS Code.

## Validation evidence

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

## Remaining qualification and limits

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
