# CommitEcho release notes

## v0.2.0 - release prepared 2026-10-04

Package version: `0.2.0`; portable plugin: `0.2.0`; shared skill v7.
Release artifacts are prepared locally; tagging and publication remain pending.
The final artifact changes release/package metadata from the Claude-qualified
`a9650c5` candidate and adds the MIT license and PR CI;
product behavior and skill content are unchanged. Dated validation
below retains the original candidate versions and environments.

The feature release includes Claude Code setup/plugin generation, opt-in Git
message validation and hook management, bounded indexing, and shared skill v7.
The prior `0.1.1.dev0` milestones below are included in this release.

PyPI distribution is prepared with SPDX MIT metadata, a packaged root license,
project URLs, and a public `pip install commitecho` installation path.
GitHub Actions CI is configured on pushes and pull requests for Windows/Linux
and minimum/latest MCP dependencies. Full pytest includes fixture evaluations
and live MCP stdio checks; hosted CI execution is pending a branch push.

Release-review repairs close R1-R4: legacy skill cleanup and Claude settings
cleanup reject paths outside the selected repository; combined hook uninstall
preflights both targets; stock plugin manifests upgrade across package versions
while customized assets remain protected. No dependency or storage migration
is added. Native lifecycle installation remains gated.

### Final release validation - 2026-10-04

The final `0.2.0` project environment passed **421 tests, 0 skipped in
969.64 seconds**, Windows, Python 3.12.14, pytest 9.1.1, MCP 2.2.0. This includes
fixture evaluations, real MCP stdio, setup ownership boundaries, plugin upgrades,
and publication recovery. No earlier isolated or supplied run is counted here.
The wheel and source archive build with Hatchling 1.32.4 and pass strict Twine
metadata/description validation. Their license, canonical skill v7, portable
plugin metadata, project URLs, and exclusion of private local files were checked.

Fresh installed-wheel validation on MCP **2.3.0** passed **15 tests, 0 skipped
in 86.81 seconds**, using imports from fresh environment site-packages outside
the source import path and without `PYTHONPATH`: four generated client launches,
three capture/commit/verify/index/restart/Git-only clone lifecycles, local/portable
plugin launches, and six stock-manifest upgrade cases including development to
`0.2.0`. CLI version/help/init/setup/doctor also passed. This is a focused artifact
run, not a full MCP 2.3.0 suite. The first concurrent artifact run had four MCP
initialization timeouts (5 passed, 4 failed); the separate rerun passed without
changing product code or handshake timeouts.
Native Claude loading of the final `0.2.0` metadata is untested on this host
because Claude CLI is unavailable. The supplied native round 4 qualification
covers the same product code and skill v7 at `a9650c5`; the release adds package
metadata, licensing, documentation, and CI. Hosted GitHub CI and actual PyPI
upload/install remain pending their external execution.

### Earlier candidate validation

Local candidate validation on 2026-10-04: **377 passed, 9 skipped in 526.09
seconds**, Windows, Python 3.12.14, MCP SDK 2.2.0. All real MCP stdio checks
and directory-junction regressions ran. The skips were
`test_all_client_preflight_rejects_symlink_escaping_repository` and eight
parameterizations of `test_setup_rejects_external_legacy_file_symlink_before_writes`;
each encountered WinError 1314 creating its symlink. Enable Windows Developer
Mode or use an elevated shell and rerun; earlier isolated passes do not alter
this full-suite count.

The rebuilt wheel installed into a fresh environment with MCP 2.3.0 and,
from outside the checkout without `PYTHONPATH`, passed CLI version/help/init/
setup/doctor and **9 installed-artifact tests in 80.71 seconds**: all four
generated client launches, three restart/clone capture lifecycles, and local/
portable plugin launches. Pytest reported one unused `asyncio_mode` config
warning because the isolated harness omitted pytest-asyncio; these synchronous
tests execute their live async flows directly. This is separate from the full
MCP 2.2.0 suite. Metadata, canonical/plugin skill equality, public local links,
and whitespace checks passed. The local ignored stock skill was refreshed to
v6; automatic loading is checked in a new native client session.

### Client integration testing

These are developer-run checks of client setup, MCP tools, capture, commit
verification, indexing, and history retrieval. Live client results and automated
server/protocol results retain their separate scopes.

| Client | Recorded integration results |
|---|---|
| Codex | Windows interactive CLI capture, fixture commit, exact verification, indexing, and fresh-process recall passed on 2026-10-03. |
| Antigravity IDE | The developer accepted the live Phase 1/2 results and automated fixture checks for this candidate on 2026-10-04, including capture, exact verification, indexing, restart recovery, fresh-chat recall, and a linked worktree with spaces. |
| Claude Code | Supplied round 4 on 2026-10-04 passed 22/22 checks at `a9650c5`, skill v7: Windows CLI 2.1.286 print-mode project/plugin capture, exact verification, server-runtime indexing, resume and fresh-process/Git-only clone recall. Native F-1 through F-4 retests passed; interactive approval, handoff, hooks and other surfaces remain untested. |
| Copilot VS Code | Generated configuration and protocol checks are covered; interactive client checks remain pending. |

The live Antigravity fixture commit is
`6ae2f52b2e14f25b5e235edeb11d2fbfb7297744`, carrying record
`b29a13ac-9e1e-4db3-a7d4-50fc6fc2a92f`. Its test evidence is attributed to
`client="antigravity"` and `origin="agent_reported"`. The reported IDE
verification returned `exact` and indexing completed. After IDE restart, open
change `58d1a1c6-8779-4ac7-aa95-9c4318c5d63b` was recovered and the committed
decision was recalled through native MCP tools.

The Claude run used CLI 2.1.286 and model `claude-opus-5-5` on a fresh clone at
`01c1eaf` (`0.2.0.dev0`, skill v6). Project commit
`b96a800a3d26c03ad64234bf11569c0bb69358c6` and plugin commit
`5a42674b67811597b93588f369c2e307f47e86d1` preserved structured alternatives,
reasons, and linked evidence through recall. Stock plugin upgrades, custom-asset
preservation, portable PATH connection, malformed-input rejection, and redirected
Windows help also passed. Open-change resume needs access to earlier revision
IDs and clear handling of decisions omitted from preparation; the earlier
decision remained in drafts after the partial record was committed. The follow-up
implementation below addresses this behavior and the smaller findings.

Resume/runtime follow-up (2026-10-04): existing resume and scoped status responses
expose current decisions and unpublished revision IDs. Preparation reports omitted
revisions; exact verification keeps unpublished work open, excluding superseded
and previously verified revisions. MCP status supplies the server's Python and
index argument list. Skill v7 covers resume selection, runtime use, and generated
UUIDs; stock v6 upgrades preserve custom skills. Plugin regeneration identifies
a different pinned runtime without modifying its files. No new tool, dependency,
or storage migration was added. Native Claude retesting remains pending because
the client is unavailable in this follow-up environment.

Follow-up validation on `66dafb6` plus these working-tree changes: **403 passed,
0 skipped in 731.65 seconds**, Windows 10 (10.0.19045), Python 3.12.14, MCP SDK
2.2.0, Git 2.49.0.windows.1. The full suite includes real stdio restart,
full/partial commits, Git-only clone recall, and generated-plugin indexing with
two Python environments. The independent review found no actionable issues;
canonical/plugin skill equality, local documentation links, and whitespace checks
passed. Earlier full-suite and isolated results above retain their original counts.

Antigravity CLI, other platforms, cross-client handoff, and native lifecycle
hooks are separate follow-up checks for the scoped Windows release. The
[remaining integration checklist](RELEASE_INTEGRATION_CHECKLIST.md) tracks
remaining client/platform qualification. Detailed reports and development
plans stay local; this summary and the checklist are the public status record.

Publication recovery follow-up (2026-10-04): exact local verification is now
stored in private drafts, preserving it when the disposable index is rebuilt.
Draft schema v5 imports authenticated results from an existing older index;
legacy hold intent remains unknown until the latest preparation is reverified.
Known reachable commits count in shallow history, and partial commits can finish
in either verification order. Newer unverified preparations, remaining decisions,
and the owner's `keep_open` choice remain protected. Restart MCP servers after
upgrading. No new dependency or MCP tool is added.

Recovery validation on `800a65d` plus these changes: **421 passed, 0 skipped in
705.55 seconds**, using the short Windows temporary root `.commitecho/r421`.
All real MCP stdio tests ran. The independent review found no additional
actionable issues. The earlier long-root run and its fixture failures are
recorded separately in the local Claude report.

### Claude Code round 4 acceptance - 2026-10-04

The final supplied run tested a clean fresh clone of `origin/multi-client-integration` at `a9650c5`, package `0.2.0.dev0`, skill v7, Claude CLI 2.1.286 / `claude-opus-5-5`, Windows 11 x64, Python 3.12.10, MCP 2.3.0 and Git 2.42.0.windows.2. All 22 checks passed across ten live print-mode sessions, with no new defects. This supersedes the historical native-retest pending statements above for that surface; consolidation did not rerun the client or suite.

F-1: the resumed process committed both decisions and retained the earlier rejected alternative, with no omitted/remaining revisions. Project new-process/clone recall returned all four decisions and both alternatives with reasons, evidence IDs and original provenance. F-2: plugin indexing used the server runtime. F-3: all 19 supplied IDs came from UUID generation. F-4: regeneration named both runtimes and the remedy while preserving files. Plugin validation, stock pinned/portable upgrades, custom-asset protection, PATH connection/failure handling, atomic malformed-input rejection and cp1252 help passed. Fixture commits: project `3101fb2`, `cbb62e0`; plugin `767607b`.

Reported fresh-clone full suite: **412 passed, 9 skipped in 340.8 seconds**. `tests/integration/test_setup.py::test_all_client_preflight_rejects_symlink_escaping_repository` and eight `test_setup_rejects_external_legacy_file_symlink_before_writes` cases (two paths, four flag combinations) skipped due to WinError 1314 creating symlinks. Enable Windows Developer Mode or use an elevated shell and rerun those nine tests. Earlier same-day supplied `800a65d` run: **394 passed, 9 skipped**, same reason/remedy. Neither count replaces the independent **421 passed, 0 skipped** recovery result or the earlier isolated symlink pass.

Remaining observations: resume omitted `client_version` while retaining correct attribution; a co-author line after the record trailer still verified exact. Interactive approval, cross-client handoff, deliberate native partial selection, broader portable project workflow, SessionStart, Linux/macOS and IDE/desktop remain untested. Raw evidence remains private on the reporting checkout; the detailed report and summary were consolidated locally. The candidate remains unreleased.

## v0.1.1 development milestones - superseded by v0.2.0

Package version: `0.1.1.dev0`. This work has not been released; v0.1.0 remains
the published release. The portable plugin uses SemVer `0.1.1-dev.0`.

Claude round 2 remediation (2026-10-03) fixes D-1-D-3: alternatives have a
published field schema and reject unknown keys atomically; valid reasons and
evidence links survive the commit/index/restart/clone lifecycle. Unexpected MCP
errors identify exception type and tool while retaining error signaling.
Root/plugin help works with redirected cp1252 output. Shared skill v6 adds a
rejected-alternative example; exact stock v5 skills upgrade safely and custom
skills stay protected. No dependency or storage migration is added.
Supplied round 2 evidence confirms skill v5 project capture and plugin loading
with index-only recall. Revised live v6 project/plugin capture remains pending
because Claude is unavailable locally.

Remediation implementation `bfa2b5a`: **285 passed, 1 skipped in 379.19 seconds**
on Windows with Python 3.12.14, MCP SDK 2.2.0, and Git 2.49.0.windows.1;
all real stdio handshakes ran. The skipped
`test_all_client_preflight_rejects_symlink_escaping_repository` lacked
directory-symlink permission; a separate probe reproduced WinError 1314.
Enable Developer Mode or use an elevated shell and rerun. Prior isolated
results do not change this full-suite count. Diff and skill consistency checks
passed, and the milestone's CommitEcho binding verified `exact`.

The 2026-10-03 multi-client review repairs setup preservation, strict Git gate behavior, indexing deadlines,
and plugin ownership; it does not extend those earlier sessions to revised
discovery paths or native hooks. Four configuration profiles now include
Claude Code. Current integration status is summarized above.
Claude interactive/plugin validation and native event tests remain pending.
The repaired full suite passed 238 tests in 341.08 seconds; one new directory-
symlink test skipped because this Windows account lacks creation permission.
All live MCP tests ran. No new dependency or storage migration was introduced.

Later 2026-10-03 fixture runs add versioned evidence: interactive Codex CLI
and Antigravity IDE completed capture, exact verification, process restart,
and fresh-process recall after explicit indexing. The canonical skill at that point was
version 4 and required indexing before recall; the portable plugin example used
the same skill. Raw sessions and fixture repositories remain local.

Prior development-checkout validation: **241 passed, 1 skipped in 362.22
seconds** using the project Python with all live MCP checks enabled, including
the parametrized restart lifecycle test for Codex and Antigravity. The skip
requires Windows directory-symlink permission. Package/CLI version metadata,
portable plugin generation, canonical skill content, and ignore rules also
passed their checks.

The supplied Claude Code integration test results record 12
passing Windows CLI 2.1.286 print-mode checks with skill v4 and local approval,
including organic activation and fresh-process recall. Its reported 242-test
result and source baseline have not been independently reproduced here. The
reported base `69df403` declares v0.1.0, so its exact tested working-tree state
remains unverified.

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
