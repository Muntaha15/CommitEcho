# Codex live test — 2026-10-03

Outcome: **interactive CLI capture and fresh-process recall passed**.
Earlier non-interactive attempts below remain failed; they used a different approval policy.

## Interactive follow-up

The later 2026-10-03 fixture run used Codex CLI `0.159.0-alpha.12.1`, its
interactive TUI, `on-request` approvals, `workspace-write`, and `--no-daemon`.
The operator accepted normal fixture trust and MCP/Git approval prompts.
`required = true` was added to the fixture's generated configuration.

- Native `get_status` matched the seed HEAD
  `1cb66d65e89eb6e5a1d607845c15cc68f664a208`.
- Assertions for order-preserving deduplication and empty input passed.
- Capture, decision recording, and preparation succeeded through native tools.
  Commit `5b3e0a23879cfcd2084d333b63c3e62edd09e544` contained the code and
  record `aef2831c-aeec-43ce-8b8c-c629b352fce0`, with its exact trailer.
- Native `verify_commit` returned `exact` with no reasons.
- The capture process shut down. A fresh process initially reported empty
  recall and two unindexed commits. Explicit `commitecho index` scanned both
  commits and indexed one record; retried search, evidence retrieval, and
  range comparison recovered the selected rationale with full coverage.
- The recalled record contained rationale but no attached evidence items.
  Automatic skill discovery was not separately established by this report.

Indexing occurred after restart in this run. The canonical skill is now version
4 and requires indexing after verification, before restart/recall. Verification
alone does not populate the search index. The observed success qualifies this
interactive Windows workflow; unattended execution and other surfaces remain
separate. Raw transcripts, harnesses, and fixture repositories stay local under
the ignored `.commitecho/codex-live-20261003/` directory.

The sections below retain the earlier attempts and their diagnostic evidence.

## Environment and scope

Windows, Python 3.12.14, MCP SDK 2.2.0, Git 2.49.0.windows.1, and installed
Codex CLI `0.159.0-alpha.12.1`. CLI sign-in status reported ChatGPT login.
The exact desktop app build and CLI-selected model were not recorded.
Fixture path contained spaces; commands used the current project interpreter
and generated Codex server entry. `PYTHONPATH` was removed for fixture launches.

No main-repository commit, push, global trust change, execution-rule change,
or safeguard bypass was performed. The disposable fixture received a seed
commit from the harness; neither live CLI session created a test commit.

## Observed desktop connection

This actual Codex chat exposed all eight CommitEcho tool definitions. Calls
to `get_status`, `begin_change` (resume), `record_decisions`, `search_history`,
`get_evidence`, `compare_history`, and `verify_commit` succeeded.
The installed neutral skill was read from `.agents/skills/commitecho/SKILL.md`.

- Status resolved the current worktree and HEAD
  `1763d0d4a48d5ae5444ac79afcc3558e316b5f0b`, with full history coverage.
- Resume returned the existing review change and its revision counter; recording
  the observed test outcome advanced that counter successfully.
- History/evidence/range comparison returned actual committed decision records.
- Verification of existing commit
  `eb44a048ffea455a80ed8082d3ed9353d1578f23` returned `exact`, with
  `local_preparation_verified: true`.

`prepare_commit` was not called against the user's real checkout: its review
changes remain uncommitted, and this live test did not alter their staged index.
Existing-commit verification does not prove a new native capture/commit cycle.

## Fresh CLI attempts

Both runs used `codex exec`, ephemeral sessions, the standard workspace-write
sandbox, and unchanged execution rules. They were actual model sessions,
not SDK simulations.

1. **Project configuration/discovery attempt.** Session
   `01a0fea4-b9ca-7683-90f0-ecf25dea55ae` received a disposable implementation/
   commit task. Codex reported that the per-run `projects.<path>` trust setting
   was unrecognized/ignored. Its shell read of AGENTS/skill/code was rejected
   by runtime policy. It reported no CommitEcho tools and stopped without edits
   or a workflow commit. The harness assertion correctly failed.
2. **Explicit generated server-command attempt.** `codex mcp list` with the
   generated command/args reported CommitEcho `enabled: true` and the intended
   fixture repository. Session `01a0fea7-ac12-79f3-8a50-2e2ac50fd13e` was asked
   to use only CommitEcho tools; fixture code/testing/staging were performed by
   the harness to avoid the blocked shell path. The canonical skill was supplied
   in the prompt, so this attempt cannot prove native skill discovery. Codex
   again reported that CommitEcho tools were unavailable. No record was prepared
   and no workflow commit occurred. The harness assertion correctly failed.

A CLI exit code of zero meant the model finished its turn, not that acceptance
passed. Transcript inspection and harness assertions established these failures.
The exact cause of missing tool exposure in these spawned sessions is unresolved;
an enabled configuration listing alone does not establish connection/loading.

## Follow-up required

### Focused diagnosis after the initial attempts

A read-only fresh CLI probe with the same explicit generated server command,
`required = true`, and a prompt allowing tool discovery exposed CommitEcho and
attempted an actual `get_status` call. Session
`01a0feb0-900a-78f2-be60-3142f25f1b97` returned this client-side error:

```text
MCP tool call requires approval, but approval policy is never
```

A second probe added the documented per-tool
`mcp_servers.commitecho.tools.get_status.approval_mode = "auto"` override.
It exposed the tool but returned the same approval error. Neither probe
returned status data or performed a workflow commit. No execution rules,
global configuration, or safeguards were changed. The initial missing-tool
reports do not establish a server startup defect; startup was required and
tool discovery was explicitly allowed in these later probes.

The demonstrated blocker is now native CLI approval handling. Repeat the
full workflow in a normal trusted interactive Codex session that can approve
the authorized MCP calls, or a supported automation environment with effective
tool approval settings. Use `required = true` in the acceptance launcher so
initialization failures cannot silently pass. The attempted per-tool override
has not been shown effective in this installed runtime. A CommitEcho server
code change is not established by these results.

Official [MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp)
defines required startup and tool approval settings. The observed runtime
rejection remains the deciding evidence for this run.

The focused generated-Codex stdio lifecycle regression passed separately:

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/integration/test_setup.py::test_stdio_code_change_lifecycle_survives_restart -q --basetemp .test-tmp-codex-live-protocol -p no:cacheprovider
```

**1 passed in 10.26 seconds**, with the required shell network/local-socket
permission. This test completed capture/prepare/commit/`exact` verification,
server restart, indexing, and evidence recall through a real stdio connection.
It establishes server/protocol functionality, not fresh Codex CLI tool loading.

Run the generated configuration in a normal fresh Codex session with the project
trusted through its supported loading path. Confirm actual tool exposure and
skill discovery, then perform capture/prepare/commit/verify and fresh-session
recall in a disposable fixture. Do not suppress execution rules or increase
MCP timeouts to classify the current run as passed.

Official [project configuration documentation](https://learn.chatgpt.com/docs/config-file/config-advanced)
states that project-local configuration is loaded only for trusted projects;
[non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
describes `codex exec`. These contracts guided the test but do not establish
which loading restriction caused this particular CLI result.

Raw fixture logs and harness scripts remain local in ignored
`.commitecho/codex-live-20261003/` for diagnosis. They are not release assets.
