# CommitEcho

Preserve the decisions behind code changes and recall them through your coding agent.

CommitEcho is a local MCP server. During development, your coding agent records the problem, choices, alternatives, and reasons discussed with you. Selected records travel with the resulting Git commits, so another agent can explain a change months later.

**Status: v0.2.0 in development (`0.2.0.dev0`); v0.1.0 is the published release.** This candidate adds Claude setup/plugin generation, an opt-in Git message gate, bounded indexing, and safer setup/cleanup and plugin upgrades. Four local client configuration profiles are available. Recorded Codex and Antigravity workflows and supplied Claude print-mode/plugin-loading results retain their original scope; revised skill v6 Claude project/plugin capture and the latest Antigravity IDE UAT are pending. See the [UAT checklist](RELEASE_UAT_CHECKLIST.md), [Codex results](CODEX_LIVE_TEST.md), [Antigravity results](ANTIGRAVITY_LIVE_TEST.md), [Claude Code report](CLAUDE_CODE_LIVE_TEST.md), and [capability ledger](CAPABILITY_LEDGER.md).

## Install

```bash
python -m pip install .
```

Or, with [uv](https://github.com/astral-sh/uv) (recommended):

```bash
uv venv .venv
uv pip install --python .venv .
```

Requires Python 3.12+, Git 2.34+, and MCP Python SDK 2.2+ (installed with the package). No external service or model API is needed.

Run commands in that environment: activate it with `source .venv/bin/activate` on POSIX or `./.venv/Scripts/Activate.ps1` in PowerShell. Without activation, use `.venv/bin/python -m commitecho` or `./.venv/Scripts/python.exe -m commitecho` in place of `commitecho`. Setup uses the interpreter that runs it.

These commands install the current development checkout. For the published v0.1.0 source, select its release tag before installing.

---

## CLI quick-start

### Initialise a repository

```bash
commitecho init
```

Creates `.commitecho/config.json` and `.commitecho/records/` in the worktree. Private `drafts.sqlite` and rebuildable `index.sqlite` live under the Git common directory's `commitecho/` folder. Run once per clone.

### Health check

```bash
commitecho doctor
```

Checks Git discovery, Python, SQLite FTS5, the MCP package, database access, and whether client skill/config files are present. It does not test a live client connection.

### Check status

```bash
commitecho status
# or for a specific change:
commitecho status --change-id <change_id>
```

### Index committed records

```bash
commitecho index
```

Walks commits reachable from `HEAD`, reads records referenced by `CommitEcho-Record` trailers, and populates the search index. Run after each verified commit and after cloning or pulling new commits, before recall. Verification does not update the search index. If a search reports partial coverage or unindexed commits, index and retry.

### Verify a commit binding

```bash
commitecho verify <commit_oid>
commitecho verify <commit_oid> --record-id <record_id>
commitecho verify <commit_oid> --keep-open  # another commit will follow for this change
```

Returns one of `exact`, `declared_changed`, `contained_only`, `unverifiable`, or `invalid` and explains why. `exact` means the committed record, trailer, parent, and code fingerprint agree. When the local draft exists, verification also compares the committed bytes with the prepared digest; `details.local_preparation_verified` reports that stronger check. A fresh clone can establish a self-consistent `exact` binding, but cannot authenticate the original preparation or the truth of the rationale.

An exact local verification closes the prepared change by default. Use `--keep-open` (or MCP `keep_open: true`) for an intermediate commit; it returns the change to `open` so the next commit can use the same change ID. Failed verification leaves it `prepared`. Status lists abandoned changes separately from open work.

### Show a record

```bash
commitecho show <record_id>
```

### Browse decision history across a range

```bash
commitecho diff main feature/my-branch
commitecho diff main feature/my-branch --path src/api_client.py
```

### Export draft decisions

`export` writes a readable JSON snapshot of a change's draft decisions, predecessor links, and referenced evidence. It is useful for review or handoff. It is not a restorable database backup and does not include sessions, operations, or prepared commit records. The snapshot may contain private evidence; review it before sharing.

```bash
commitecho export <change_id>
commitecho export <change_id> --output decisions.json
```

### Set up a client

```bash
commitecho setup --client codex
commitecho setup --client antigravity
commitecho setup --client copilot_vscode
commitecho setup --client claude_code
# dry-run (shows what would be written):
commitecho setup --client codex --dry-run
```

Without `--client`, setup configures all four profiles. It writes the MCP server config and shared skill; Codex, Copilot, and Claude receive activation instructions, and Antigravity receives a persistent activation rule (`trigger: always_on`). Dry-run writes no files or private databases and lists planned changes. Existing launch overrides and customized skills are preserved. Use `--regenerate-server` to explicitly refresh the managed launch fields while retaining other settings. Test discovery in your actual client before relying on automatic capture.

Setup also preflights legacy skill cleanup paths. If configuration, skill, instruction, or cleanup paths resolve outside the selected repository through a link or junction, setup rejects them before changing any selected profile. Move shared custom assets into an appropriate local layout or migrate them manually.

The default uses the active Python interpreter and absolute checkout path, so generated configuration stays local. `setup --client claude_code --portable` uses an installed `commitecho` on PATH and Claude's documented project-root environment. Other profiles reject `--portable`; use `--server-cmd` for an explicit launcher, and setup appends the repository argument. A custom command is an argv string, not a shell script; quote paths containing spaces and do not include pipes or shell expansion.


### Validate commit messages and manage Git hooks

CommitEcho provides an opt-in Git message gate that validates the actual message file and the current HEAD/index preparation.

```bash
# Check a commit message file (advisory warning by default):
commitecho check-message .git/COMMIT_EDITMSG

# Check strictly (exits with error and rejection if trailer/record/manifest mismatch):
commitecho check-message .git/COMMIT_EDITMSG --strict

# Safely install the Git commit-msg hook:
commitecho hook install --git
# or install in strict mode:
commitecho hook install --git --strict

# Preview hook installation:
commitecho hook install --git --dry-run

# Uninstall the hook (removes CommitEcho block, preserving other hook contents):
commitecho hook uninstall
```

The validation hook checks that:

- Every commit, including empty and merge commits, carries exactly one canonical `CommitEcho-Record: <lowercase-uuid>` trailer.
- The referenced record is present in the Git index, has a supported schema and identity, and was prepared for current `HEAD` (or the root marker).
- The staged code manifest matches the preparation digest.
- Existing foreign hooks are left intact, with manual integration instructions. Installation and removal refuse shared/external hook directories.

Advisory mode warns and permits validation failures; strict mode rejects them, including missing runtime or unreadable records. The gate checks schema and preparation consistency; it does not authenticate the truth of recorded evidence or replace explicit `verify_commit` on the resulting OID. Git's `commit-msg` event does not identify amend operations. Reusing a HEAD record for an amend is rejected; automatic amend preparation is not supported. Use a new ordinary commit for the supported prepare/commit/verify workflow. Hooks are local, are not installed by cloning, and can be bypassed with `git commit --no-verify`. See [Git's hook contract](https://git-scm.com/docs/githooks).

Explicit indexing can be bounded with `commitecho index --timeout 5 --quiet`; the deadline covers the indexing process, including repository discovery, database access, and history traversal. A deadline leaves completed index transactions reusable and reports incomplete work. Native `hook install --client claude_code` remains gated until an actual supported Claude runtime has been qualified; JSON generation alone does not establish event behavior.

Cleanup of earlier generated Claude hooks refuses settings paths outside the repository. Combined Git/Claude cleanup validates both targets before making changes; predictable path or configuration errors preserve both. This does not provide a transaction across files if the operating system fails during a write.


### Generate Claude Code plugin

Generate a local Claude Code plugin artifact containing the MCP server definition, canonical skill, and manifest:

```bash
# Generate a local plugin without changing this checkout's portable example:
commitecho plugin --output-dir local-commitecho-plugin

# Generate a portable artifact in a separate directory, requiring commitecho on PATH:
commitecho plugin --portable --output-dir portable-commitecho-plugin

# Generate to a custom directory:
commitecho plugin --output-dir path/to/plugin

# Preview plugin generation without writing files:
commitecho plugin --output-dir local-commitecho-plugin --dry-run
```

Without `--output-dir`, generation targets `commitecho-plugin/`. This checkout tracks a portable example there; local generation replaces its launch fields with your interpreter path, so use a separate output directory. The default pins the current interpreter and requires CommitEcho installed in that environment. The portable example also requires Python, Git, CommitEcho, and its dependencies installed on PATH; it performs no registry download. Regeneration refuses customized or unrelated assets before writing. This is an installed-runtime plugin, not a bundled Python runtime.

Stock plugin manifests can regenerate across package versions, including development-to-release upgrades; customized metadata, skills, and launch definitions stay protected. If an older local plugin points to a different Python installation, generate into a fresh output directory and validate it before switching the client.

When Claude is available, run `claude plugin validate ./local-commitecho-plugin`, then test a plugin-loaded project session for tools, skill discovery, and capture/recall. Manifest validation alone does not prove startup. For local testing use `claude --plugin-dir ./local-commitecho-plugin` as described in the [official plugin reference](https://code.claude.com/docs/en/plugins-reference). Disable the project `.mcp.json` CommitEcho entry while enabling the plugin, or use a clean fixture project, so the same server and skill are not registered twice. Restore project setup when disabling the plugin. No native hooks ship with this artifact.

---

## MCP server (agent transport)

Start the server so your coding agent can connect to it:

```bash
python -m commitecho serve --repo .
```

Or, when invoked by a client that manages its own process lifecycle:

```bash
commitecho setup --client codex   # writes the correct command into .codex/config.toml
```

The server exposes eight MCP tools:

| Tool | Description |
|---|---|
| `begin_change` | Open or resume a Change for the current worktree |
| `record_decisions` | Persist one or more decision revisions for a Change |
| `prepare_commit` | Snapshot staged changes and write a CommitRecord to `.commitecho/records/` |
| `search_history` | Retrieve decisions by question or file path |
| `verify_commit` | Check a commit's declared record binding |
| `get_evidence` | Fetch a stored evidence item or indexed record |
| `compare_history` | Compare decisions introduced between two Git refs |
| `get_status` | Inspect open changes and index coverage |

---

## Client setup

### Codex (local)

After running `commitecho setup --client codex` the following files are written (or merged):

| File | Purpose |
|---|---|
| `.codex/config.toml` | Registers the `commitecho` MCP server entry for trusted Codex projects |
| `.agents/skills/commitecho/SKILL.md` | Shared capture/recall skill |
| `AGENTS.md` | Activation instruction block |

Codex loads project-local configuration only after the project is trusted. Setup does not change
the user's global trust settings.

Start a fresh trusted session or reload the server after setup; generating files does not attach tools to an existing chat. Confirm the eight tools and call `get_status` before capture. The tested interactive session used normal tool approvals. Its earlier non-interactive run rejected MCP calls under approval policy `never`; an enabled server listing alone did not prove callable tools. If `AGENTS.override.md` exists, add the activation instructions there because it takes precedence over `AGENTS.md`.

### Antigravity IDE

```bash
commitecho setup --client antigravity
```

| File | Purpose |
|---|---|
| `.agents/mcp_config.json` | Registers the `commitecho` MCP server entry under `mcpServers` |
| `.agents/skills/commitecho/SKILL.md` | Shared capture/recall skill (folder-based) |
| `.agents/rules/commitecho.md` | Persistent activation rule (`trigger: always_on`) |

After running setup, reload MCP servers using the Antigravity UI (**Additional Options (...) > MCP Servers** or `/mcp` in chat) or start a new session with the repository. Always install CommitEcho into the same Python environment that launches the server.

### GitHub Copilot in VS Code

```bash
commitecho setup --client copilot_vscode
```

| File | Purpose |
|---|---|
| `.vscode/mcp.json` | Registers the `commitecho` MCP server entry |
| `.agents/skills/commitecho/SKILL.md` | Shared capture/recall skill |
| `.github/copilot-instructions.md` | Activation instruction block (appended) |

Current [VS Code MCP documentation](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
prefers portable `.mcp.json` and retains `.vscode/mcp.json` for compatibility.
This profile keeps its existing local location; migrate deliberately to avoid
duplicate server registration or overwriting another client's configuration.

### Claude Code

```bash
commitecho setup --client claude_code
```

| File | Purpose |
|---|---|
| `.mcp.json` | Registers the `commitecho` MCP server entry under `mcpServers` |
| `.claude/skills/commitecho/SKILL.md` | Shared capture/recall skill |
| `CLAUDE.md` | Activation instruction block (appended) |

Interactive Claude project sessions ask for approval of project-local MCP servers; unattended and SDK hosts have different loading controls. After setup, approve the server, start a fresh session/reload, and check tools and skill discovery. For shared configurations, use `commitecho setup --client claude_code --portable` with the package installed on PATH. File location alone does not make absolute launch paths portable. See [Claude MCP documentation](https://code.claude.com/docs/en/mcp).

For an unattended run in a trusted workspace, explicitly opt in to this server
by merging the following into your untracked `.claude/settings.local.json`,
preserving other settings and existing server entries:

```json
{"enabledMcpjsonServers": ["commitecho"]}
```

This local file does not bypass workspace trust. Complete Claude's trust dialog
first; a `disabledMcpjsonServers` entry can still reject the server. Setup prints
guidance but never writes approval settings. See Claude's
[approval and trust rules](https://code.claude.com/docs/en/mcp#project-server-approvals-and-workspace-trust).

The [supplied UAT report](CLAUDE_CODE_UAT_REPORT.md) observed Claude CLI 2.1.286
reporting `pending` after local approval even though tools worked later in the
session. Check the effective server binding and make a real `get_status` call;
compare `head_oid` with `git rev-parse HEAD` in the intended repository. A startup
status alone is insufficient. If the call fails, inspect trust, approval, and
launch errors. `doctor` checks static configuration, not live client connectivity.

Shared skill v6 asks agents to supply known client session metadata and to label
each evidence item they author with their active client. Unknown metadata stays
unset. Setup upgrades exact generated older skills and preserves custom content;
the plugin generator uses the same recognition rule for its skill asset.

Alternatives require `choice` and accept `disposition` (default `rejected`),
`reason`, and `evidence_ids`. Use decision `rationale` for the selected approach
and alternative `reason` for its rejection; unknown alternative fields are
rejected. An omitted reason remains null. Stock v5 skills upgrade to v6;
customized skills remain protected.

---

## Typical workflow

```
# 1. Agent begins a change
begin_change(title="fix retry storms", client="codex", operation_id="<new-uuid>")
# → returns change_id, session_id

# 2. Agent records the chosen approach + rejected alternatives
record_decisions(change_id=..., expected_revision=0, operation_id="<new-uuid>", decisions=[
  { problem: "duplicate uploads on retry",
    choice: "content hash deduplication",
    rationale: "same bytes → same job ID; rename-safe",
    disposition: "selected",
    alternatives: [{ choice: "filename dedup", disposition: "rejected",
                     reason: "renames bypass it" }] }
])

# 3. Agent stages files, then prepares a record
prepare_commit(change_id=..., expected_revision=1, operation_id="<new-uuid>", selected_revision_ids=[...],
               summary="Deduplicate by content hash")
# → writes .commitecho/records/<uuid>.json
# → returns trailer: "CommitEcho-Record: <uuid>"

# If the staged code changes after preparation, prepare again before committing.
# 4. Commit the staged code, record file, and exact returned trailer
git add .commitecho/records/<uuid>.json
git commit -m "fix: content hash dedup

CommitEcho-Record: <uuid>"

# 5. Verify the actual commit, then index before ending the session
verify_commit(commit_oid="<actual-git-commit-oid>")
# → require outcome="exact"; otherwise inspect the reported reasons
commitecho index

# 6. In a fresh session or clone, index new history and retrieve evidence
commitecho index
search_history(question="content hash")
# → returns matching decision summaries; call get_evidence(record_id=...) for the full record and alternatives
```

Portable records are limited to 64 KiB, with 4 KiB of inline content per evidence item. Preparation rejects likely credentials and private home paths before writing JSON; edit the draft and retry. This check is best effort, so review the record before committing it.

---

## CommitEcho in this repository

This repository uses CommitEcho to preserve its own development decisions. For example, [commit bf162c5](https://github.com/Muntaha15/CommitEcho/commit/bf162c52e3adacf3f654e49e483eee967f3197f5) includes a [decision record](.commitecho/records/1e604be7-d723-47e0-949c-08d13f1b14fe.json) explaining why we added a complete MCP stdio lifecycle test: existing transport tests checked startup and status, while lifecycle tests called services directly.

After cloning this repository and installing CommitEcho, inspect the recorded decision and evidence:

```bash
commitecho index
commitecho show 1e604be7-d723-47e0-949c-08d13f1b14fe
```

With CommitEcho connected to your coding agent, recall the decision through MCP:

```text
search_history(path="tests/integration/test_setup.py")
get_evidence(record_id="1e604be7-d723-47e0-949c-08d13f1b14fe")
```

The record includes agent-reported evidence of 120 passing tests on MCP SDK 2.2.0. It preserves the reported result; it does not independently certify it. Review records for private context before committing them. Published `.commitecho/records/` files stay trackable; local `.commitecho/config.json` and generated client configuration stay ignored.

---

## Evaluation

### Build fixture repos

```bash
python tests/fixtures/build_fixtures.py
```

Creates six tiny Git repos under `tests/fixtures/repos/` covering: chosen/rejected decision, later reversal, branch conflict, partial staging, stale preparation, and never-recorded rationale.

### Run the eval suite

```bash
python tests/evals/eval_runner.py
```

Reports three fixture metrics per scenario: **capture completeness**, **linkage correctness**, and **retrieval recall@5**. These deterministic fixtures do not measure live agent capture fidelity.

### Run the three-baseline comparison

```bash
python tests/evals/baseline_comparison.py
```

Compares the information present in git diff/blame, stored excerpts, and CommitEcho structured recall on the same question set. It does not invoke an LLM or measure answer quality.

### Run all tests (including fixture evaluations)

```bash
python -m pip install -e ".[test]"
python -m pytest
```

Pytest builds isolated fixture repositories and runs both deterministic evaluation modules. The baseline comparison checks recorded context, not answer quality.

Use the project environment for development (`uv pip install --python .venv -e ".[test]"`). The suite includes real MCP stdio handshakes; restricted command sandboxes need local-socket/network permission as described in [AGENTS.md](AGENTS.md).

---

## Validation targets

The initial v0.1.0 release includes automated fixture validation and limited live-client evidence. These targets describe full client qualification; the revised integrations do not claim all four interactive workflows have passed:

1. **Zero false `exact` results in fixtures** — `commitecho verify` on the `stale_preparation` fixture returns `declared_changed`, not `exact`.
2. **All records recover in a fresh full clone** — `commitecho index` on a clone of any fixture repo populates the search index and `search_history` returns the expected decisions.
3. **No branch/future-decision leakage** — `search_history` at a given `at_ref` does not surface decisions from commits unreachable from that ref.
4. **All four client workflows pass with recorded versions** — `commitecho setup --client <client>` for each of `codex`, `antigravity`, `copilot_vscode`, `claude_code` produces valid configuration and the acceptance scenario passes in the actual client. Service-layer client-ID tests and MCP protocol tests establish separate, narrower facts.
