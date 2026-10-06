# v0.2.0 integration checks: Codex, Antigravity, and Claude Code

These are developer-run integration tests of the client setup, MCP tools,
capture workflow, and history retrieval.

Test a fresh clone of `multi-client-integration` after the candidate commits
are available remotely. Record the exact Git commit, dirty state, package/skill
versions, OS, client/model, Python/MCP/Git versions, and installation mode.
Use disposable fixture repositories for commits and hooks. Keep raw transcripts,
credentials, databases, and machine-specific configuration private.

The final release artifact is `0.2.0` with skill v7. These checks need the actual clients;
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

**Supplied round 4 Windows print-mode results received on 2026-10-04:** Claude Code CLI 2.1.286, model `claude-opus-5-5`, clean fresh clone at `a9650c5`, `0.2.0.dev0`, skill v7. All **22/22 acceptance checks passed**, including native retests of F-1 through F-4; no new defects. These results belong to the supplied run; consolidation did not rerun the client.

- [x] Fresh project setup and doctor install/check skill v7 and bind to the intended fixture with spaces. Fixture-local approval allowed real calls; `init` reported connected while `claude mcp get` still showed Pending approval.
- [x] Organic project/plugin capture preserves structured rejected alternatives, reasons, evidence IDs and `agent_reported` / `claude_code` attribution. A1 correctly left work open without committing.
- [x] F-1 native resume: A2 found the earlier revision and selected both decisions. `omitted_revision_ids: []`, exact verification, `remaining_revision_ids: []`; project new-process and Git-only clone recall recovered all four decisions and both alternatives.
- [x] Single-session project capture -> prepare -> commit -> exact verification -> index -> restart/clone recall passed.
- [x] Plugin validates and loads alone with one server/skill, no duplicates; organic capture, exact verification and fresh-process/clone recall passed.
- [x] F-2 native indexing uses the server interpreter advertised by `get_status.runtime`.
- [x] F-3: all 19 client-supplied operation/evidence IDs were generated with `uuid.uuid4()`.
- [x] F-4: runtime mismatch names the pinned/current interpreters and remedy, preserving files. Stock 0.1.1 pinned/portable upgrades and custom skill/manifest preservation passed.
- [x] Portable plugin connects on PATH with the expected HEAD; absent PATH yields CONNECTION_CLOSED and an honest connection-failure report.
- [x] Malformed alternatives fail atomically, corrected calls succeed, and root/plugin/setup/hook help exits 0 under cp1252 with ASCII output.
- [ ] Interactive approval dialog and cross-client handoff: untested.
- [ ] Deliberate partial decision selection in a native Claude session: not exercised by round 4; automated coverage remains separate.
- [ ] Broader portable project capture/restart qualification, SessionStart hooks, Linux/macOS and Claude IDE/desktop: untested.

Round 4 observations: the resumed call omitted `client_version` (attribution remained correct); a co-author line after the record trailer still verified exact. No new defect was reported.

Fixture commits/records: project `3101fb2` / `eb78d6d8…` and `cbb62e0` / `569628e6…`; plugin `767607b` / `b0c2102a…`. Raw transcripts/harness are reported under private `.commitecho/claude-live-r4-20261004/` on the reporting checkout, absent here; detailed supplied results are retained in the existing local Claude reports.

Reported fresh-clone full suite at `a9650c5`: **412 passed, 9 skipped in 340.8 seconds**, Python 3.12.10, MCP 2.3.0. Skips: `tests/integration/test_setup.py::test_all_client_preflight_rejects_symlink_escaping_repository` and eight parameterized `test_setup_rejects_external_legacy_file_symlink_before_writes` cases (two legacy paths, four flag combinations), all due to WinError 1314 creating symlinks. Enable Developer Mode or run elevated, then rerun those nine checks. The earlier isolated pass does not change this count.

Separate earlier supplied suite at `800a65d`: **394 passed, 9 skipped**, same privilege reason/remedy. Independent implementation full suite: **403 passed, 0 skipped**. Independent recovery full suite: **421 passed, 0 skipped in 705.55 seconds**, including real MCP stdio checks with a short Windows temporary root. Preserve these distinct environments and counts.

Publication recovery includes shallow-history commits, index rebuilds and partial commits verified in either order; draft schema v5 preserves local verification proof. Restart MCP servers after upgrading. Native SessionStart installation remains gated.

## Return report

For each item: pass, fail, or untested, with a short observed result. Include
fixture commit/record IDs, missed captures, exact errors, and relevant evidence
locations. Report full-suite counts and named skips separately from isolated
reruns. Do not infer an untested client/platform pass from another surface.

## Final v0.2.0 artifact and publication checks

- [x] Package/source version and tracked portable plugin are `0.2.0`; skill v7 is unchanged.
- [x] Final project suite: 421 passed, zero skips in 969.64 seconds on Windows/Python 3.12.14/MCP 2.2.0; includes fixture evals and real MCP stdio.
- [x] Wheel/source archive build; strict Twine checks and packaged MIT license/skill/private-file audit pass.
- [x] Fresh installed wheel on MCP 2.3.0: 15 checks passed, zero skips in 86.81 seconds; all client/plugin launches, restart/clone lifecycles, and final-version upgrades. CLI smoke checks pass.
- [x] Visible MIT license, CI badge, and PR/push workflow for Windows/Linux with minimum/latest MCP are prepared.
- [ ] Hosted GitHub CI: run after authorized branch push; no remote pass is claimed.
- [ ] Final-version native Claude plugin loading: CLI unavailable here; supplied round 4 covers unchanged product code/skill.
- [ ] PyPI upload, clean public installation, release tag, and GitHub release: publication remains pending.
