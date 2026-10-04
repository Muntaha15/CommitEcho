# v0.2.0 integration checks: Codex, Antigravity, and Claude Code

These are developer-run integration tests of the client setup, MCP tools,
capture workflow, and history retrieval.

Test a fresh clone of `multi-client-integration` after the candidate commits
are available remotely. Record the exact Git commit, dirty state, package/skill
versions, OS, client/model, Python/MCP/Git versions, and installation mode.
Use disposable fixture repositories for commits and hooks. Keep raw transcripts,
credentials, databases, and machine-specific configuration private.

The candidate is `0.2.0.dev0` with skill v6. These checks need the actual clients;
the local automated suite and protocol tests are recorded separately.
Completed runs retain their recorded dates and client versions; remaining
checks use the current candidate.

## Codex

**Recorded integration checks passed on 2026-10-03** using Codex CLI
`0.159.0-alpha.12.1` in an interactive Windows session with normal project
trust and tool approvals. This completion covers that recorded workflow.
Results are summarized in the [release notes](RELEASE_NOTES.md#client-integration-testing).

- [x] Native `get_status` identifies the intended fixture repository and seed HEAD.
- [x] Native capture, decision recording, and preparation complete for the
  order-preserving deduplication task. Assertions for duplicates and empty input pass.
- [x] The fixture commit contains the prepared record and its exact trailer;
  native `verify_commit` returns `exact` with no reasons.
- [x] After restarting the client process, explicit indexing scans the fixture
  history and indexes the committed record.
- [x] Fresh-process search, record retrieval, and range comparison recover the
  recorded rationale with full history coverage.

Fixture commit: `5b3e0a23879cfcd2084d333b63c3e62edd09e544`.
Record: `aef2831c-aeec-43ce-8b8c-c629b352fce0`.

## Antigravity IDE

**Developer integration checks accepted on 2026-10-04** for this candidate.
The scope below reflects the developer's accepted results from live IDE
Phases 1 and 2 plus the earlier automated fixture checks. Results are summarized
in the [release notes](RELEASE_NOTES.md#client-integration-testing).

- [x] Fresh installation and setup discover the intended repository, all eight
  MCP tools, shared skill v6, and persistent activation rule.
- [x] An ordinary coding task activates capture without CommitEcho hints.
  The chosen approach, rationale, and evidence/client attribution are
  preserved accurately.
- [x] Capture, partial staging, preparation, fixture commit, exact verification,
  and indexing complete. Changes staged after preparation are detected.
- [x] Restart recovers open work; a fresh chat recalls committed choices,
  rationale, and evidence accurately through native IDE MCP tools.
- [x] Setup reruns preserve custom configuration and skills. Git hook
  install/remove preserves foreign content; strict validation rejects bad commits.
- [x] Exercise a fixture path with spaces and a linked worktree. Confirm the
  client stays bound to the intended repository.

Report IDE results separately from Antigravity CLI; qualify CLI only if tested.

## Claude Code

- [ ] Fresh project setup loads the intended repository and skill v6 through
  normal trust/approval. Actual tool calls work, regardless of a misleading
  startup `pending` display. Record print and interactive modes separately.
- [ ] An ordinary task organically captures the chosen approach and discussed
  rejected alternative. Its structured rejection reason, evidence references,
  client attribution, and known session metadata remain accurate.
- [ ] Project capture -> prepare -> fixture commit -> exact verification ->
  index -> restart/recall succeeds. A Git-only clone retrieves the same
  structured alternatives and linked evidence without originating drafts.
- [ ] Validate and load the generated plugin by itself. Repeat organic capture
  and restart/clone recall without duplicate project server/skill registrations.
- [ ] Try stock plugin upgrades across versions and preserve custom plugin
  assets. Test the portable PATH launcher separately from the pinned interpreter.
- [ ] Confirm malformed alternatives fail without partial capture, subsequent
  corrected calls work, and redirected Windows help remains readable.
- [ ] Exercise paths with spaces, open-change restart/resume, and interactive
  approval. Optional cross-client handoff should retain each client's attribution.

Project v6 capture and plugin v6 capture are required before release.
Native SessionStart installation remains gated; no native-event pass is expected
from these fixes. Unavailable platforms or surfaces remain explicitly untested.

## Return report

For each item: pass, fail, or untested, with a short observed result. Include
fixture commit/record IDs, missed captures, exact errors, and relevant evidence
locations. Report full-suite counts and named skips separately from isolated
reruns. Do not infer an untested client/platform pass from another surface.
