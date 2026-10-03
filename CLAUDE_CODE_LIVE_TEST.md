# Claude Code live test - 2026-10-03

Outcome: **native discovery, organic skill activation, capture, commit,
verification, indexing, process restart, and fresh-process recall passed**.

The run used Claude Code CLI 2.1.286 in print mode (`claude -p`, stream-json
transcripts) with model `claude-opus-5-5` on Windows 11 x64 (10.0.26200),
Python 3.12.10, MCP SDK 2.3.0, and Git 2.42.0.windows.2. It used a separate
disposable repository with spaces in its path and this checkout's runtime.
The operator's normal user-level Claude Code settings and hooks stayed active.

## Setup and server approval

- `commitecho setup --client claude_code` generated `.mcp.json`,
  `.claude/skills/commitecho/SKILL.md` (skill v4), and the `CLAUDE.md`
  activation block. `commitecho doctor` reported the Claude Code entries as ok.
- `claude mcp list` discovered the project server but reported
  `Pending approval`, matching the profile's documented limitation.
- Approval was granted only in the fixture through
  `.claude/settings.local.json` with `"enabledMcpjsonServers": ["commitecho"]`.
  No global configuration, workspace trust, or safeguard was changed.
- After that approval, `claude mcp get` and the stream-json `init` event still
  showed the server as `pending`. The server connected during the session
  anyway, and its tools were callable. Do not use the `init` status alone as
  evidence that tools are unavailable.

## Probe session

Session `7a8516c7-c918-46e9-9eae-930a937a055c` loaded all eight tools through
`ToolSearch`. The skill appeared natively as the `commitecho` command. Native
`get_status` returned seed HEAD `1552e0eb6a3ef7a6a09d176e09b35d42fac43f6e`
with partial coverage and no open changes.

## Capture session

The prompt for session `23164178-d188-45bf-944c-615b1a0d5260` asked for an
order-preserving `dedupe(values)` with plain-assert tests and authorized a
commit. It **did not mention CommitEcho**. Claude Code invoked the skill on its
own and completed the workflow through native tools:

- `begin_change` used `client="claude_code"` and returned the seed HEAD as
  `base_oid`.
- Claude wrote a single-pass seen-set implementation and tests. `python
  test_dedupe.py` passed for duplicates, empty input, and new-list return.
- `record_decisions` recorded two selected decisions, one for the
  implementation and one for the tests. Alternatives were empty, and the
  rationale states that none were discussed. The test output was attached as
  `agent_reported` evidence.
- `prepare_commit` covered both staged paths and left no uncovered paths.
- Commit `60e133e04e584be2eaf1542770f51b0c3af97cdf` contained the code, the
  tests, and record `d0178861-69ea-4bc5-9880-f194962f02ef`, with its exact trailer.
- Native `verify_commit` returned `exact` with no reasons.
- Claude then ran `python -m commitecho index` with the server's interpreter,
  which it found in `.mcp.json`. The index scanned two commits and indexed one
  record, as skill v4 requires.

## Fresh-process recall

Session `9b21fcc3-e3ae-427f-972a-455ba8b634c3` was a new Claude Code process
with a new stdio server and read-only tools (no Write, Edit, or Bash). The
question did not mention CommitEcho. Claude invoked the skill and called
`search_history`, `compare_history` (seed to HEAD), and `get_evidence` (by
evidence and by record). With full coverage, it recovered the selected
rationale, the absence of alternatives, the `agent_reported` test evidence, and
the single-commit range. It labeled the agent-reported provenance and noted
that the hashable-values assumption is untested. It did not fabricate
developer intent.

## Observations

- Evidence items carried `client: null`. The session did not pass
  `client_version` or `native_session_id`, even though the skill asks for them.
- `get_evidence(evidence_id=...)` resolved from `source: "draft"`, while the
  record lookup resolved from `index`.
- The stdio lifecycle regression
  `test_stdio_code_change_lifecycle_survives_restart` now covers `claude_code`
  alongside `codex` and `antigravity` (3 passed).

The overall PASS applies to these checkpoints in print mode with fixture-local
approval. The interactive approval dialog, the Claude plugin
(`commitecho-plugin/`), the portable `--portable` launch, the SessionStart
hook adapter, POSIX, and cross-client handoff require separate evidence.
Raw transcripts, the inspection script, and fixture Git history stay in the
ignored `.commitecho/claude-live-20261003/` directory.
