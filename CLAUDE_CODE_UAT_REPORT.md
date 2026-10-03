# Claude Code UAT report: CommitEcho

| | |
|---|---|
| **Date** | 2026-10-03 |
| **Client under test** | Claude Code CLI 2.1.286 (print mode, `claude -p`) |
| **Model** | `claude-opus-5-5` |
| **CommitEcho version** | `0.1.1.dev0` (branch `main`, base commit `69df403`) |
| **Skill version** | 4 |
| **Overall result** | **PASS**: 12 of 12 acceptance checks passed, with 4 observations |
| **Short summary** | [CLAUDE_CODE_LIVE_TEST.md](CLAUDE_CODE_LIVE_TEST.md) |

---

## 1. Executive summary

CommitEcho works with Claude Code from start to finish. A real Claude Code
session was given a plain coding task that did not mention CommitEcho. It
loaded the CommitEcho skill on its own and recorded its decisions through the
MCP tools. It then made a commit with the record attached, verified the commit
(`exact`), and indexed the history. A separate, new Claude Code process with a
new MCP server then answered "why was this built this way?" from the recorded
history alone. Its answer was accurate and correctly attributed, and it
invented nothing.

The one setup gap is approval. Claude Code requires approval for project MCP
servers. Without the interactive dialog, approval was given through a
settings file local to the test repository. The approval status that Claude
Code reports is also misleading (see observation O-1).

The automated test suite still passes after this run: **242 passed, 1
skipped**. The stdio lifecycle regression test now also covers `claude_code`.

---

## 2. Scope

### In scope

- Running `commitecho setup` and `commitecho doctor` for the `claude_code`
  profile
- Claude Code finding the project `.mcp.json` server, the approval step, and
  whether the tools are exposed
- Claude finding the skill and using it unprompted (`.claude/skills/commitecho/SKILL.md`
  plus the `CLAUDE.md` activation block)
- The full capture workflow: `begin_change` → `record_decisions` →
  `prepare_commit` → `git commit` with the trailer → `verify_commit` → `commitecho index`
- Recall from a new process: `search_history`, `get_evidence`, `compare_history`
- Whether recorded content is accurate and correctly attributed (no invented
  alternatives or claims of developer confirmation)
- An automated stdio lifecycle regression test for `claude_code`

### Out of scope (not tested in this run)

| Item | Reason |
|---|---|
| Interactive project MCP approval dialog | This run had no interactive terminal; approval was given through a settings file instead |
| Claude plugin (`commitecho-plugin/`) loading | Separate surface; needs `claude plugin` install and a session with the plugin loaded |
| `--portable` setup (`commitecho serve` on PATH, `CLAUDE_PROJECT_DIR`) | Needs the runtime installed on PATH |
| SessionStart lifecycle hook adapter | Gated in the CLI as not yet qualified |
| POSIX (Linux/macOS) | Run on a Windows host only |
| Cross-client handoff (for example, a Codex capture recalled in Claude) | Needs a separate scenario |
| Claude Code IDE extension / desktop surfaces | Only the CLI was tested |

---

## 3. Test environment

| Component | Version / value |
|---|---|
| OS | Windows 11 Home Single Language, 10.0.26200, x64 |
| Claude Code | 2.1.286 (CLI) |
| Model | `claude-opus-5-5` |
| Python | 3.12.10 (project `.venv`) |
| MCP SDK | 2.3.0 |
| Git | 2.42.0.windows.2 |
| Shell used by Claude | Git Bash |
| Fixture location | Ignored folder `.commitecho/claude-live-20261003/fixture repo/` (path contains a space) |
| User-level Claude settings | Left active (the operator's normal SessionStart hooks also ran) |

**Environment setup note:** `uv` (named in AGENTS.md) is not installed on this
host. The environment was built with `py -3.12 -m venv .venv` and
`pip install -e '.[test]'`. The earlier Codex and Antigravity runs used
Python 3.12.14 and Git 2.49.

---

## 4. Method

1. **Baseline.** The full suite was run before any changes:
   `241 passed, 1 skipped in 291 s`.
2. **Fixture.** A new Git repository was created with one seed commit
   (`README.md`). Seed HEAD: `1552e0eb6a3ef7a6a09d176e09b35d42fac43f6e`.
3. **Setup.** `python -m commitecho setup --client claude_code --repo "<fixture>"`
   was run, followed by `doctor`.
4. **Approval.** A fixture-only file, `.claude/settings.local.json`, was created
   containing `{"enabledMcpjsonServers": ["commitecho"]}`.
5. **Live sessions.** Three separate `claude -p` processes were run with
   `--output-format stream-json --verbose`, so every tool call and tool result
   was recorded. Each verdict below is based on the **recorded tool events**,
   not on what the model said it did.
6. **No prompt hints.** The capture and recall prompts never mentioned
   CommitEcho. This tests whether Claude activates it from `CLAUDE.md` and the
   skill alone.
7. **Least privilege.** Tool permissions were set with `--allowedTools`. The
   recall session was read-only (`Write`, `Edit` and `Bash` disallowed). The
   capture session could not run `git push`.
8. **Regression.** The stdio lifecycle test was extended to `claude_code` and
   the full suite was run again.

### Session log

| Session | Session ID | Purpose | Turns | Duration | Cost (USD) | Result |
|---|---|---|---|---|---|---|
| Probe | `7a8516c7-c918-46e9-9eae-930a937a055c` | Check tool exposure (read-only) | 3 | 7.6 s | 0.27 | success |
| A: capture | `23164178-d188-45bf-944c-615b1a0d5260` | Implement, record, commit, verify, index | 15 | 62.5 s | 0.64 | success |
| B: recall | `9b21fcc3-e3ae-427f-972a-455ba8b634c3` | Recall from a new process (read-only) | 8 | 19.0 s | 0.50 | success |

All three sessions exited with code 0 and wrote nothing to stderr.

---

## 5. Acceptance test cases

| ID | Test case | Expected | Actual | Status |
|---|---|---|---|---|
| UAT-01 | `setup --client claude_code` creates the client files | `.mcp.json`, skill file and `CLAUDE.md` block created | `[add] .mcp.json`, `[add] .claude/skills/commitecho/SKILL.md`, `[create] CLAUDE.md` | PASS |
| UAT-02 | `doctor` validates the Claude profile | Claude entries reported as ok | Skill v4 matches; activation block present; `.mcp.json` entry present; core checks passed | PASS |
| UAT-03 | Server launch arguments point at the fixture, including the path with a space | The `--repo` argument is the fixture's absolute path, passed as a single element | Correct; the JSON array form preserves the space | PASS |
| UAT-04 | Claude Code finds the project server | Server listed with scope "Project config" | Listed as `commitecho` (stdio, project scope), status "Pending approval" | PASS (see O-1) |
| UAT-05 | All 8 MCP tools are exposed after approval | 8 `mcp__commitecho__*` tools available | `ToolSearch` returned all 8: `begin_change`, `record_decisions`, `prepare_commit`, `verify_commit`, `search_history`, `compare_history`, `get_evidence`, `get_status` | PASS |
| UAT-06 | Native `get_status` reports the correct repository state | `head_oid` = seed; no open changes | `head_oid` `1552e0eb…`, `open_changes: []`, coverage `partial` (1 unindexed commit), as expected | PASS |
| UAT-07 | Claude finds and uses the skill without being prompted | Skill used for a coding task that does not mention CommitEcho | `Skill("commitecho")` was the **first** tool call in sessions A and B; it also appeared in `commands_changed` | PASS |
| UAT-08 | Capture: begin and record decisions | Change opened with `client="claude_code"`; decisions recorded at revision 0 → 1 | `change_id d86439a9…`, `base_oid` = seed; 2 decisions recorded; `revision_counter` 1 | PASS |
| UAT-09 | Prepare and commit with the trailer | Record covers all staged paths; commit holds the code, the record and the exact trailer | `uncovered_paths: []`; commit `60e133e0…` contains `dedupe.py`, `test_dedupe.py` and the record JSON; trailer `CommitEcho-Record: d0178861-…` | PASS |
| UAT-10 | Verify the commit | `exact` with no reasons | `outcome: exact`, `reasons: []`, expected parent = actual parent = seed, manifest hashes match | PASS |
| UAT-11 | Index after verification (skill v4 rule) | Indexed with the server's Python before recall | Claude read the interpreter path from `.mcp.json` and ran `python -m commitecho index --repo …`, which printed "Scanning 2 commits... Indexed 1 new records." | PASS |
| UAT-12 | Recall from a new process: accurate, correctly attributed, nothing invented | Rationale, alternatives and evidence recovered with full coverage; agent-reported content labelled as such | New process and new server; `search_history`, `compare_history` and `get_evidence` all succeeded; coverage full; answer matched the record exactly (see §7) | PASS |

---

## 6. Capture details (session A)

### Prompt (CommitEcho not mentioned)

> Implement dedupe(values) in dedupe.py: return a new list with duplicates
> removed, preserving first-occurrence order. Add a test_dedupe.py using plain
> assert statements covering duplicates and empty input, and run it. You are
> authorized to commit the change to the current branch of this repository when
> done (no push). Follow this repository's project instructions.

### Tool calls in order (from the transcript)

| # | Tool | Key input / output |
|---|---|---|
| 1 | `Skill` | `commitecho` |
| 2 | `ToolSearch` | Loaded `begin_change`, `record_decisions`, `prepare_commit`, `verify_commit` |
| 3 | `Bash` | Read `.mcp.json`; generated 4 UUIDs for `operation_id` values |
| 4 | `begin_change` | `client="claude_code"` → `change_id d86439a9-8173-42ee-b1c7-dbf9b3c38da2`, `revision_counter 0` |
| 5 | `Write` | `dedupe.py` |
| 6 | `Write` | `test_dedupe.py` |
| 7 | `Bash` | `python test_dedupe.py` → `All tests passed.` |
| 8 | `record_decisions` | 2 decisions plus evidence `ev-test` (`agent_reported`) → `revision_counter 1` |
| 9 | `Bash` | `git add dedupe.py test_dedupe.py` (staged only the intended files; left `.claude/`, `.mcp.json`, `CLAUDE.md` and `__pycache__/` unstaged) |
| 10 | `prepare_commit` | → record `d0178861-69ea-4bc5-9880-f194962f02ef`, `uncovered_paths: []` |
| 11 | `Bash` | `git add <record>`; `git commit` with the trailer → `60e133e04e584be2eaf1542770f51b0c3af97cdf` |
| 12 | `verify_commit` | → `exact`, no reasons |
| 13 | `Bash` | `python -m commitecho index` → 1 record indexed |

The order exactly matches skill v4 steps 1–3h. Claude staged files
explicitly and did not stage generated client configuration.

### Code produced

```python
def dedupe(values):
    """Return a new list with duplicates removed, preserving first-occurrence order."""
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
```

Tests: duplicates with order kept (`[3, 1, 3, 2, 1, 4]` → `[3, 1, 2, 4]`),
empty input, and a check that the function returns a new list without
changing the input. The tests are runnable directly and discoverable by pytest.

### Recorded decisions (from the committed record)

| Revision | Scope | Choice | Alternatives | Evidence |
|---|---|---|---|---|
| `ffe58583…` | `dedupe.py` (`dedupe`) | Single pass that tracks seen items in a set and appends unseen items to a new list | `[]`. The rationale says *"no alternatives were discussed with the user"* | none |
| `dfd0fbdd…` | `test_dedupe.py` | Plain-assert test functions plus a `__main__` runner | `[]` | `ev-test` |

**Accuracy and attribution check:**
- The rationale calls the implementation an *"Agent-chosen implementation"*
  and states its assumption that the values are hashable.
- No rejected alternatives were invented.
- Evidence uses `origin: agent_reported`.
- No developer-confirmation origins were used.

---

## 7. Recall details (session B)

### Prompt (CommitEcho not mentioned)

> Why was dedupe() implemented the way it is, were alternatives considered, and
> what evidence backs it? Also compare history from the seed commit 1552e0eb to
> HEAD. Answer only from recorded project history; do not modify any files.

### Tool calls in order

| # | Tool | Result |
|---|---|---|
| 1 | `Skill` | `commitecho` |
| 2 | `ToolSearch` | Loaded the 4 recall tools |
| 3 | `search_history("dedupe")` | Both revisions from record `d0178861…`, coverage full |
| 4 | `compare_history(1552e0eb → HEAD)` | `is_ancestor: true`, 1 commit, 2 decisions |
| 5 | `get_evidence(evidence_id="ev-test")` | found, `source: draft` |
| 6 | `get_evidence(record_id=…)` | found, `source: index`, full record |

### What the answer got right

- It explained the rationale (O(n) with a seen-set, keeps first-occurrence
  order, does not change the input) and said it was **"recorded as the agent's
  choice, not confirmed by the developer"**.
- It answered **"No"** to whether alternatives were considered, citing the
  empty `alternatives` list and the rationale text.
- It correctly said the implementation decision has **no evidence** and the
  test decision has one agent-reported item.
- It pointed out that the hashable-values assumption is stated but never tested.
- It said the seed commit has no record, so nothing explains why it was made.
- It cited the record ID and commit throughout, did not speculate, and changed
  no files.

---

## 8. Automated regression results

| Run | Command | Result |
|---|---|---|
| Baseline (before changes) | `.venv/Scripts/python.exe -m pytest -q` | **241 passed, 1 skipped** in 291.07 s |
| Focused lifecycle test | `pytest tests/integration/test_setup.py::test_stdio_code_change_lifecycle_survives_restart` | **3 passed** in 28.35 s (codex, antigravity, claude_code) |
| Final full suite | `.venv/Scripts/python.exe -m pytest -q` | **242 passed, 1 skipped** in 209.90 s |

The skipped test is the existing directory-symlink test, which needs a
Windows permission this account lacks. It is unrelated to this change. All
live MCP stdio handshakes ran, and no timeouts were raised.

---

## 9. Observations and findings

| ID | Severity | Finding | Impact | Recommendation |
|---|---|---|---|---|
| O-1 | Medium (UX/diagnostics) | After approval through `enabledMcpjsonServers`, `claude mcp get` and the stream-json `init` event **still report `pending`**, although the server connects later in the session and all tools work. | Users and harnesses may wrongly conclude the tools are unavailable. Automated acceptance checks that read `init.mcp_servers[].status` would report a false failure. | Document this in the README and the Claude troubleshooting guide. Base any automated check on a real tool call, not the reported status. |
| O-2 | Low | Neither `begin_change` nor the evidence items included `client_version` / `native_session_id`, so evidence has `client: null`. The skill asks for these. | Records are less traceable back to the session that wrote them. | Make the skill wording stronger or give an example, or have the server default `client` on evidence from the change's client. |
| O-3 | Informational | `get_evidence(evidence_id=…)` resolved from `source: draft`, while `get_evidence(record_id=…)` resolved from `index`. | None for correctness here. On a fresh clone without draft databases, the evidence-ID lookup would have to come from the index. | Add a test that looks up evidence by ID on a clone that has only the index. |
| O-4 | Informational | Project MCP servers need approval (a documented limitation). Print mode has no dialog, so a fixture-local settings file was needed. | Unattended or CI use needs an explicit opt-in. | Consider having `setup --client claude_code` print a hint about `enabledMcpjsonServers` and `settings.local.json`. Do not write the file automatically. |

No defects were found in CommitEcho's server, setup or skill logic.

---

## 10. Code and documentation changes from this UAT

| File | Change |
|---|---|
| [tests/integration/test_setup.py](tests/integration/test_setup.py#L247) | The `test_stdio_code_change_lifecycle_survives_restart` test cases now also cover `claude_code` |
| [CLAUDE_CODE_LIVE_TEST.md](CLAUDE_CODE_LIVE_TEST.md) | New short live-test summary in the same format as the Codex and Antigravity reports |
| [README.md](README.md) | Status line updated; link to the Claude Code results |
| [CAPABILITY_LEDGER.md](CAPABILITY_LEDGER.md) | Environment bullet added; Claude Code row in the matrix updated |
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | Claude Code result added |
| `CLAUDE_CODE_UAT_REPORT.md` | This report |

None of these changes are committed yet.

---

## 11. How to reproduce

```powershell
# 1. Environment
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"

# 2. Fixture (any new directory, ideally with a space in its path)
git init --initial-branch=main "<fixture>"
# ...add README.md and make the seed commit...
.venv\Scripts\python.exe -m commitecho setup --client claude_code --repo "<fixture>"
.venv\Scripts\python.exe -m commitecho doctor --repo "<fixture>"

# 3. Approve the project server (fixture only)
#    <fixture>\.claude\settings.local.json:
#    { "enabledMcpjsonServers": ["commitecho"] }

# 4. Capture session (run from inside <fixture>)
claude -p "<capture prompt from §6>" --permission-mode acceptEdits `
  --allowedTools "Read Write Edit Glob Grep Skill ToolSearch Bash mcp__commitecho" `
  --disallowedTools "Bash(git push:*)" --output-format stream-json --verbose

# 5. Recall session (new process, read-only)
claude -p "<recall prompt from §7>" `
  --allowedTools "Read Glob Grep Skill ToolSearch mcp__commitecho__get_status mcp__commitecho__search_history mcp__commitecho__get_evidence mcp__commitecho__compare_history" `
  --disallowedTools "Write Edit Bash" --output-format stream-json --verbose
```

Judge pass or fail from the `tool_use` and `tool_result` events in the
transcript, not from the model's final message.

---

## 12. Artifacts

All raw evidence is kept locally in the ignored folder
`.commitecho/claude-live-20261003/` and is not committed:

| File | Contents |
|---|---|
| `probe1.jsonl` / `.err` | Probe session transcript |
| `sessionA.jsonl` / `.err` | Capture session transcript |
| `sessionB.jsonl` / `.err` | Recall session transcript |
| `inspect.py` | Script that extracts the tool-call sequence from a transcript |
| `fixture repo/` | Fixture repository with its full Git history, draft and index databases, and generated config |

---

## 13. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| UAT executed by | Claude Code (automated operator) | PASS, with the scope limits in §2 | 2026-10-03 |
| Reviewed by | | | |
| Approved by | | | |
