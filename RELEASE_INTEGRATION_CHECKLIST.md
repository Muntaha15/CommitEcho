# v0.2.0 integration checks: Codex, Antigravity, and Claude Code

These are developer-run integration tests of the client setup, MCP tools,
capture workflow, and history retrieval.

Test a fresh clone of `multi-client-integration` after the candidate commits
are available remotely. Record the exact Git commit, dirty state, package/skill
versions, OS, client/model, Python/MCP/Git versions, and installation mode.
Use disposable fixture repositories for commits and hooks. Keep raw transcripts,
credentials, databases, and machine-specific configuration private.

The current candidate is `0.2.0.dev0` with skill v7. These checks need the actual clients;
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

**Reported Windows print-mode results received on 2026-10-04:** Claude Code
CLI 2.1.286, model `claude-opus-5-5`, candidate `01c1eaf`, skill v6. Project and
plugin-only capture/recall passed. The resume/runtime follow-up is implemented;
repeat the affected native checks with skill v7 before release (F-1/F-2). These are the supplied run's
results; consolidation did not rerun the client.

- [x] Fresh project setup loads the intended repository and skill v6 through
  normal trust/approval. Actual tool calls work, regardless of a misleading
  startup `pending` display. Record print and interactive modes separately.
  Print mode passed; the interactive approval dialog was not tested.
- [ ] An ordinary task organically captures the chosen approach and discussed
  rejected alternative. Its structured rejection reason, evidence references,
  client attribution, and known session metadata remain accurate.
  Single-session capture passed; the reported resume omission (F-1) is fixed in
  the automated regression. The native repeat is pending. Known session metadata
  was supplied inconsistently in the earlier run.
- [x] Project capture -> prepare -> fixture commit -> exact verification ->
  index -> restart/recall succeeds. A Git-only clone retrieves the same
  structured alternatives and linked evidence without originating drafts.
- [x] Validate and load the generated plugin by itself. Repeat organic capture
  and restart/clone recall without duplicate project server/skill registrations.
  Plugin indexing used another checkout's interpreter. Runtime discovery (F-2)
  now returns the server's index argument list and passes two-environment protocol
  checks; repeat its use through the native plugin.
- [x] Try stock plugin upgrades across versions and preserve custom plugin
  assets. Test the portable PATH launcher separately from the pinned interpreter.
- [x] Confirm malformed alternatives fail without partial capture, subsequent
  corrected calls work, and redirected Windows help remains readable.
- [ ] Exercise paths with spaces, open-change restart/resume, and interactive
  approval. Optional cross-client handoff should retain each client's attribution.
  Spaced paths passed. Resume omitted the earlier decision from the commit
  while retaining it in drafts (F-1); interactive approval and handoff were untested.

Project v6 capture and plugin v6 capture passed in the reported run. F-1/F-2
are implemented and covered by automated restart, partial-commit, clone-recall,
and runtime checks. Repeat the affected native capture, indexing, and recall
checks before release. Skill v7 also adds generated-ID guidance (F-3), and plugin
regeneration distinguishes a pinned-runtime mismatch (F-4) while preserving
customized files.
The follow-up full automated suite passed **403 tests, with no skips**, on
2026-10-04. This establishes server/protocol behavior; native Claude retesting
remains pending because the client is unavailable on the follow-up host.
Native SessionStart installation remains gated; no native-event pass is expected
from these fixes. Unavailable platforms or surfaces remain explicitly untested.

## Return report

For each item: pass, fail, or untested, with a short observed result. Include
fixture commit/record IDs, missed captures, exact errors, and relevant evidence
locations. Report full-suite counts and named skips separately from isolated
reruns. Do not infer an untested client/platform pass from another surface.
