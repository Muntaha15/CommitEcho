# CommitEcho v0.2.0 implementation and release plan

Prepared 2026-10-04 against `94ec480a5c5f1fe7ea43a9117d7a16fa3a503644`.
Status: local implementation and automated validation complete; native UAT pending.

Target v0.2.0. The changes since v0.1.0 introduce Claude setup/plugin generation,
Git message validation/hooks, and bounded indexing. These are a feature release.
Use `0.2.0.dev0` during remediation and `0.2.0` for the final candidate. The
portable plugin equivalents are `0.2.0-dev.0` and `0.2.0`.

The local scope is the ownership/upgrade repairs, automated validation,
development candidate, and verified milestone commits. The user delegated live
Claude qualification to a friend testing a fresh clone; local completion does
not depend on running that client here. Antigravity and Claude testers use
[the concise UAT checklist](RELEASE_UAT_CHECKLIST.md). Live gates remain open
and the candidate remains unreleased until the qualification evidence returns.

Local closure on 2026-10-04:

- R1/R2/R4 now validate cleanup paths and every lexical parent before mutation;
  combined uninstall preflights both targets. Independent review also caught
  external-parent links back into the repository; both new junction regressions
  failed before the repair and pass afterward. Linked worktree roots remain valid.
- R3 recognizes exact stock manifests across versions and preserves customized
  assets. No dependency, framework, storage migration, or native installer was added.
- Final full suite: **377 passed, 9 skipped in 526.09 seconds**, MCP 2.2.0,
  Python 3.12.14, Windows. All stdio and junction tests ran. Named symlink skips
  and their WinError 1314 remedy are recorded in the release notes and ledger.
- Fresh installed wheel with MCP 2.3.0: CLI checks and **9 launch/lifecycle tests
  passed in 80.71 seconds** outside the checkout without `PYTHONPATH`. This is
  separate from the full suite. Metadata, portable assets, skill consistency,
  public local links, whitespace, and independent final review passed.
- The local ignored stock v4 skill was refreshed to v6 without changing launch
  overrides or project instructions. A new native session must verify discovery.
- Ownership, plugin-upgrade, and candidate/documentation milestones use separate
  CommitEcho stage/prepare/commit/verify/index records. The checklist is ready
  for testers after the commits become available remotely.

Implementation commits: `21f2f8f` (ownership and combined cleanup) and
`45d96b2` (stock plugin upgrades), each verified `exact` and indexed. Candidate
metadata, final validation evidence, and this handoff are the following milestone.

The remaining sections retain the accepted implementation and release gates;
sections 2-5 are locally complete. Sections 6-7 require the indicated actual
clients or remain explicitly deferred; the final version/tag/publication steps
in section 8 follow successful UAT.

## 1. Findings and closure requirements

| ID | Priority and verified behavior | Required closure |
| --- | --- | --- |
| R1 | P1: setup follows an external `.codex/skills` directory junction and deletes the recognized legacy `commitecho.md` there. Existing containment preflight covers new outputs but omits legacy cleanup inputs. | Validate every selected legacy path before any profile writes. External content and all selected profiles remain unchanged on rejection. |
| R2 | P1: Claude hook cleanup follows an external `.claude` junction and rewrites shared `settings.json`. Its empty-settings branch can also unlink a file through that parent. | Validate the settings path before reading or modifying it; enforce the same ownership rule for update, removal, and dry-run. |
| R3 | P2: a stock plugin generated under `0.1.1.dev0` cannot regenerate under `0.2.0`; the old manifest version makes it look customized. | Recognize stock manifests with a different managed version without accepting custom metadata or relaxing the other asset checks. |
| R4 | P2, confirmed during plan review: `hook uninstall --git --client claude_code` deletes the Git hook before rejecting malformed Claude settings. | Preflight both selected cleanup targets before either mutation. Predictable path, format, or ownership errors leave both targets unchanged. |

R1-R3 were reproduced in the release review. R4 was reproduced with a managed
Git hook and `.claude/settings.json` containing `[]`: exit 1 followed deletion
of the Git hook. Reproductions used disposable repositories and sibling target
directories beneath the ignored `.test-tmp-release-review/` folder.

## 2. Implement ownership repairs first

Primary files: `src/commitecho/integrations/profiles.py`,
`src/commitecho/transports/cli.py`, `tests/integration/test_setup.py`, and
`tests/integration/test_plugin_and_lifecycle.py`.

1. Extract the existing resolved-path containment check into one small helper
   in `integrations/profiles.py`, reused by setup and Claude cleanup. Resolve
   both the owning worktree and candidate path. Reject targets outside that
   worktree, including traversal through linked parents and dangling links
   whose resolved target is outside it. Retain existing parent-type checks.
   Convert failures into the existing CLI error style.
2. In `SetupGenerator.preflight`, include both legacy paths
   (`.codex/skills/commitecho.md` and `.agents/skills/commitecho.md`) whenever
   selected profiles use the shared replacement skill. Validate before reading
   their contents and before any selected profile writes. Reuse the same path
   list during cleanup so validation and deletion cannot diverge.
3. Preserve existing migration conditions: exact recognized stock content,
   successful replacement availability, no cleanup on a customized destination,
   no removal of the replacement itself, and no shared migration during
   Claude-only setup. Preserve custom legacy skills.
4. Validate `.claude/settings.json` in `_uninstall_claude_code_hook` before its
   existence/read/write/unlink branches. Preserve the exact generated-handler
   matcher and neighboring/custom handler behavior. Do not enable native hook
   installation as part of this repair.
5. Refactor `hook_uninstall` just enough to validate/read selected targets
   before applying changes. Preflight effective Git hook locality/readability
   and Claude path/JSON structure together. Reuse the validated Claude data
   during cleanup; avoid a generic transaction or hook framework. Unexpected
   operating-system failures after mutation begins must be reported honestly;
   this preflight does not promise crash-atomic changes across two files.

Keep ownership roots specific to each operation: setup and Claude settings use
the worktree; Git hooks retain the existing worktree/common-directory policy;
explicit plugin output may be outside the repository and remains confined to
its chosen output directory. Do not apply the new worktree restriction to
legitimate custom plugin output.

Regression matrix, implemented by extending existing fixtures/tests:

| Scenario | Assertion |
| --- | --- |
| Each legacy location through an external directory link; single-client and all-client setup; normal and dry-run | Nonzero result, external bytes preserved, no earlier profile/config/skill/instruction/database writes. |
| Stock local legacy skill, customized legacy skill, customized destination, Claude-only setup | Existing successful migration and preservation behavior remains intact. |
| Claude external parent directory link, with foreign settings retained or only generated settings present | Both update and unlink paths reject; external files and link remain unchanged. Dry-run also diagnoses the unsafe target. |
| Combined uninstall with external Claude path or invalid JSON/root | Git hook and settings remain byte-for-byte unchanged; error identifies the failing target. |
| Combined uninstall with unsafe Git hook path and valid Claude settings | Claude settings remain unchanged. |
| Valid local cleanup, missing settings, mixed handlers, repeated cleanup | Existing success, preservation, and idempotency still pass. |
| Terminal file symlink and dangling external link, on a host supporting their creation | Resolved containment rejects external targets; no output or external target is modified. |

Windows directory-link regressions must actually run. Use a real junction in
Windows fixtures and a directory symlink on POSIX, with one small reusable test
helper if needed by both suites. Name results as directory-link/junction tests,
not symbolic-link passes. Verify fixture cleanup removes only fixture links and
paths. Retain distinct symlink-specific checks where useful; report privilege
skips precisely rather than catching arbitrary setup errors as permission skips.

Exit gate: R1, R2, and R4 reproductions fail against the baseline and pass after
the repairs; existing locality and content-preservation tests remain green.

## 3. Repair plugin upgrades without broadening ownership

Primary files: `src/commitecho/transports/cli.py` and
`tests/integration/test_plugin_and_lifecycle.py`.

1. Use one small manifest renderer for output and stock-manifest recognition.
   Read the prior manifest version, require a supported normal or development
   SemVer string, render the stock manifest with that version, and compare it
   with the existing content using the current newline handling. Only the
   version is treated as replaceable managed metadata. Retain the conservative
   policy for altered formatting, extra fields, descriptions, authors, names,
   repository URLs, and other customizations.
2. Continue preflighting all three assets before any write. Keep exact current
   and historical skill recognition, customized skill/MCP preservation, path
   containment, and unrelated-directory refusal. An unchanged version remains
   idempotent; a stock older version can update together with the skill.
3. Test real two-step generation while changing installed package metadata:
   `0.1.0 -> 0.2.0.dev0`, `0.1.1.dev0 -> 0.2.0.dev0`, and
   `0.2.0.dev0 -> 0.2.0`. Cover local and portable output, dry-run, and repeat
   generation. Include a stock v4/v5 skill in an older-version plugin so the
   manifest cannot prevent the already-supported skill upgrade.
4. Add negative cases for invalid/missing version, foreign manifest, changed
   metadata, extra fields, and customized later assets. Snapshot all assets;
   rejection and dry-run must preserve every byte and avoid recreating missing
   earlier assets.

An old local plugin pointing to a different Python installation remains a
launch conflict: use a fresh output directory and validate it before switching
the client. Do not infer ownership of arbitrary launcher paths. Document this
recovery path alongside same-runtime version upgrades. Use the existing normal
and `.devN` package formats; adding rc/beta conversion is outside this release.

Exit gate: R3 closes with actual cross-version regeneration, including the
development-to-final transition, while foreign/custom assets remain protected.

## 4. Reconcile every earlier finding

Earlier fixes are retained and regression-checked, not reimplemented. This table
is the current disposition; historical reports keep their original results.

| Earlier finding group | Current disposition and required follow-through |
| --- | --- |
| Original audit P0/P1: launch, committed-record verification, transactions/idempotency, history scope, recoverable indexing, evidence identities/provenance, revision links, ownership, SHA-256/Git errors, portable-content limits | Implemented before this release review. Preserve their full-suite regressions. No new storage/schema/dependency work. |
| Original audit contract fixes: completion, search/ranges/pagination/conflicts, literal FTS queries, Git executable override, MCP error signaling, export, eval collection, generated tool schemas | Implemented; retain existing tests and documented limits. |
| Multi-client review: exact skill ownership, malformed-config preflight, TOML/comments/launch overrides, Windows argv, doctor, portable root contract | Implemented. Extend the remaining legacy cleanup boundary through R1; preserve existing assertions. |
| Multi-client review: full strict record validation, stale-parent/amend policy, canonical trailers, empty/merge commits, runtime failures, Git cwd, hook locality and foreign-byte preservation | Implemented. R4 adds combined-command preflight; run `test_hooks.py` after that change. Automatic amend preparation stays unsupported. |
| Multi-client review: generated native-handler ownership, native installation gate, complete-process indexing deadline and timeout validation | Implemented. R2 closes settings-path containment. Native installation remains gated. |
| Multi-client review: foreign plugin protection, all-assets preflight, local/portable runtime smoke tests | Implemented. R3 closes version migration. Keep changed-interpreter conflict recovery explicit. |
| Claude O-1/O-4: pending/approval display and unattended setup | Guidance exists; actual `get_status` and repository binding establish connectivity. Setup must not edit trust or approval settings. Interactive behavior remains a separate live test. |
| Claude O-2/O-3: attribution and evidence-ID index lookup | Remediated and reported working in round 2. Preserve explicit per-evidence client attribution, unknown metadata handling, and index-only clone checks. |
| Claude D-1: unknown alternative fields and lost rejection reasons | Fixed in `bfa2b5a`, with atomic validation and lifecycle/clone tests. Historical null reasons stay unchanged. Revised organic v6 capture is still open, covered below. |
| Claude D-2/D-3: unexpected MCP error context and redirected cp1252 help | Fixed with regressions. Keep error signaling/continued usability and redirected root/plugin help tests in the final suite. |
| Original audit item 14: live acceptance in every client | Codex/Antigravity have bounded recorded evidence; Claude v6 project/plugin capture and Copilot interactive acceptance are still distinct open items. Do not turn service or protocol tests into live qualification. |
| Original audit item 23: ignored design documents | Keep the existing decision to leave `docs/` local. Put release-critical instructions and acceptance criteria in tracked root documents. Check all release-facing local links against tracked files; do not publish local plans/transcripts wholesale. |
| Supplied Claude round-1 source revision/version discrepancy | Retain its attribution and unresolved baseline caveat. New runs must record source OID, dirty state and artifact version; do not invent or retroactively repair the external baseline. |

## 5. Version, documentation, and automated release validation

1. After the repairs, update `pyproject.toml` and
   `src/commitecho/__init__.py` to `0.2.0.dev0`; reinstall the editable project
   so `importlib.metadata`, CLI version, and generated manifests agree.
   Regenerate the tracked portable plugin with the repaired generator. Its
   `.mcp.json` must remain portable and its skill must match canonical v6.
   These path/manifest fixes do not require a skill-version bump.
   The operator checkout began with stock shared skill v4 in `.agents/`.
   During implementation, inspect setup dry-run and refresh that recognized
   generated skill through setup while preserving launch overrides and custom
   content. Start a fresh client session and verify it loads v6. Keep these
   machine-local files out of the release diff; a canonical v6 file alone does
   not establish which skill a running client has loaded.
2. Update current status in `README.md`, `RELEASE_NOTES.md`, and
   `CAPABILITY_LEDGER.md`. Preserve dated historical evidence. Specifically
   remove the current plugin-section contradiction claiming no plugin testing:
   round 2 established loading and index-only recall, while v6 capture and
   validator/native qualification remain separate. Replace blanket success
   output in the plugin CLI with a factual generation/runtime message and a
   direction to validate in the actual client.
3. Document the ownership refusal behavior and plugin upgrade/recovery paths.
   Review hook help so the unavailable native installer is explicitly gated.
   Keep broad platform/client claims aligned with observed surfaces.
4. Run focused setup/plugin/hook tests, then the full project-environment suite
   on the final implementation, including real MCP stdio and deterministic
   evaluations. Re-run the full suite after any further product-code repair.
5. Build a wheel and install it, with resolved runtime dependencies, into a
   fresh environment. From outside the source checkout and without `PYTHONPATH`,
   verify imports resolve to that environment; run CLI version/help/init/setup/
   doctor; initialize all four generated profiles and local/portable plugin
   commands, list exactly eight tools, call `get_status`, and assert the intended
   worktree/HEAD. Extend the existing lifecycle test to run with the installed
   wheel interpreter for capture/commit/verify/index/restart/clone recall; reuse
   the current flow rather than writing another lifecycle implementation.
6. Record minimum supported MCP 2.2.0 regression evidence and the freshly
   resolved SDK smoke result separately. A smoke pass on a newer SDK is not a
   claim that its full suite ran. Preserve proxy/TLS/outbound controls and use
   the host's supported network/local-socket permission mechanism.
7. Check final metadata/portable assets/skill equality, tracked public links,
   sensitive/generated-file exclusions, and `git diff --check`. Remove the
   existing added blank line at EOF in `tests/integration/test_setup.py` while
   editing that file; the earlier release-range whitespace check found it.

Commands in PowerShell, using the existing project environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs tests/integration/test_setup.py tests/integration/test_plugin_and_lifecycle.py tests/integration/test_hooks.py
.\.venv\Scripts\python.exe -m pytest -q -rs
git diff --check
```

The existing review baseline is **285 passed, 1 skipped in 425.34 seconds** on
MCP 2.2.0. The skipped
`test_all_client_preflight_rejects_symlink_escaping_repository` encountered
missing Windows symlink privilege; a separate probe reproduced WinError 1314.
Developer Mode or an elevated shell is the remedy for that specific test.
Keep isolated reruns separate from full-suite counts. New Windows junction
regressions must execute even when symbolic-link creation is unavailable.

The review also built and installed the `0.1.1.dev0` wheel with MCP 2.3.0 and
passed init/setup/doctor plus initialize/eight-tools/status for all four profiles
and the local plugin. That is useful baseline evidence, not final v0.2.0 or a
portable-plugin/full-lifecycle qualification of the wheel.

## 6. Finish live Claude qualification on the candidate

Carry forward T7/T8 from the Claude UAT plan as explicit release gates. Confirm
client availability at execution time. Use a fixture with spaces in its path,
record actual client/model/OS/Python/MCP/Git versions, candidate OID and dirty
state, skill v6, launch mode, approval method, and fixture commit/record IDs.
Capture failures and missed activations as results. Keep raw transcripts and
machine-specific configuration local; publish sanitized summaries.

| Gate | Procedure and pass criterion |
| --- | --- |
| T7: project capture | Generate project setup, use the recorded approval method, verify actual tool connectivity/worktree, then give an ordinary coding task containing an explicit rejected alternative and reason. Authorize fixture commits, but give no CommitEcho hints. Require organic capture, correct evidence client, valid alternatives, exact commit verification and explicit indexing. |
| T7: restart and clone | Ask a fresh read-only process to retrieve choice, rejected alternative, exact structured reason and linked evidence. Repeat from a Git-only clone after indexing; prove originating draft evidence is absent and evidence comes from the index. |
| T8: plugin validation/capture | Run the actual client plugin validator. Use only the generated plugin in a separate fixture: no competing project MCP registration, project skill or activation instructions. Prove organic skill use and repository binding, then the same capture/commit/verify/index flow. |
| T8: plugin restart and clone | Repeat read-only recall in a fresh plugin-only process and Git-only clone. Require the same structured reason, disposition, evidence IDs, original client and origin. Loading/index-only recall alone does not close capture. |

Use normal trust/approval controls. Report the tested print/interactive surface
precisely. A supplied report may establish a pass only when it identifies the
candidate source/artifact and retains inspectable evidence for these criteria.
Current tool availability does not itself establish organic skill use.

## 7. Explicitly retained qualification backlog

These are tracked limits, not hidden blockers for the scoped Windows release:

| Item | Status and trigger for expanding the claim |
| --- | --- |
| T10: Claude native portable PATH launch | Protocol portable commands already have automated coverage. Qualify actual project and plugin portable launches in a fresh installed environment before calling the native path qualified. |
| T11: cross-client handoff | Test Codex capture -> Claude resume in the same repository with shared drafts; preserve both clients' evidence attribution. Then test committed-history recall from a clone. Open-change resume and Git-only recall are different cases. |
| T12: interactive Claude approval | Requires a fresh interactive fixture and normal trust/approval, restart/resume and recall. Print-mode opt-in results do not close it. |
| Copilot interactive acceptance | Requires actual VS Code client discovery/capture/commit/restart/clone recall with recorded versions. Keep configuration/protocol support distinct. |
| Codex automatic discovery; Antigravity CLI | Keep existing narrower reports. Qualify automatic discovery and the separate CLI surface before extending claims. |
| T13: Linux/macOS, Claude IDE/desktop, other harnesses/cloud | Run their own suite and relevant client scenarios when those deployments are targeted. |
| T13: SessionStart/native lifecycle | Keep installation disabled until actual event loading, execution, deadlines, diagnostics and trust/disable behavior pass. Explicit indexing remains supported. |
| Offline distribution, registry execution | No promise of bundled runtimes, dependency-free/offline installation, or PyPI availability. Test installed offline startup separately if that becomes a release claim. |
| Historian, extra slash skills, transcript import, automatic verification, new storage/monorepo semantics | Deferred product work; none is required to fix R1-R4 or ship the scoped release. |

## 8. Execution order and final decision

1. **Ownership repair:** R1/R2/R4, real directory-link regressions, and existing
   setup/hook preservation tests.
2. **Plugin upgrade repair:** R3, development-to-final upgrade regressions and
   custom-content protection.
3. **Candidate preparation:** development version/metadata alignment, current
   documentation cleanup, full suite and isolated wheel validation.
4. **Live qualification:** T7/T8 with evidence from the candidate. If a live
   result requires code changes, return to the applicable repair and repeat
   its automated and affected live gates.
5. **Final candidate:** set all release versions to `0.2.0`, reinstall, regenerate
   portable assets, rebuild the wheel, and repeat full-suite/installed-artifact
   checks. Run T7/T8 against the final artifact, or explicitly record that the
   already-qualified candidate differs only in release metadata and validate
   plugin loading/upgrade on the final artifact. Any behavioral change requires
   the affected live workflow again.
6. **Release decision:** all four defects closed, required checks passed,
   T7/T8 closed, remaining limits explicit, version/assets/docs consistent,
   and intended Git diff reviewed. Commit records, if commits are requested,
   use the existing stage/prepare/commit/verify/index workflow. Tagging,
   publication and remote push occur only as the subsequent release action.

This plan adds no dependency, storage migration, generic framework, new MCP
tool, or native-hook implementation. Its completion is a tested release
candidate with explicit evidence, not merely a larger passing test count.
