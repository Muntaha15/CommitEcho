# v0.2.0 candidate UAT: Antigravity and Claude Code

Test a fresh clone of `multi-client-integration` after the candidate commits
are available remotely. Record the exact Git commit, dirty state, package/skill
versions, OS, client/model, Python/MCP/Git versions, and installation mode.
Use disposable fixture repositories for commits and hooks. Keep raw transcripts,
credentials, databases, and machine-specific configuration private.

The candidate is `0.2.0.dev0` with skill v6. These checks need the actual clients;
the local automated suite and protocol tests are recorded separately.

## Antigravity IDE

- [ ] Fresh installation and setup discover the intended repository, all eight
  MCP tools, shared skill v6, and persistent activation rule.
- [ ] An ordinary coding task activates capture without CommitEcho hints.
  The chosen approach, a discussed rejected alternative, its reason, and
  evidence/client attribution are preserved accurately.
- [ ] Capture, partial staging, preparation, fixture commit, exact verification,
  and indexing complete. Changes staged after preparation are detected.
- [ ] Restart recovers open work; a fresh chat recalls committed choices,
  alternatives, reasons, and evidence. A Git-only clone recalls them after indexing.
- [ ] Setup reruns/upgrades preserve custom configuration and skills. Git hook
  install/remove preserves foreign content; strict validation rejects bad commits.
- [ ] Exercise a fixture path with spaces and a linked worktree. Confirm the
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

Project v6 capture and plugin v6 capture are required before release sign-off.
Native SessionStart installation remains gated; no native-event pass is expected
from these fixes. Unavailable platforms or surfaces remain explicitly untested.

## Return report

For each item: pass, fail, or untested, with a short observed result. Include
fixture commit/record IDs, missed captures, exact errors, and relevant evidence
locations. Report full-suite counts and named skips separately from isolated
reruns. Do not infer an untested client/platform pass from another surface.
