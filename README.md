# CommitEcho

Preserve the decisions behind code changes and recall them through your coding agent.

CommitEcho is a local MCP server. During development, your coding agent records the problem, choices, alternatives, and reasons discussed with you. Selected records travel with the resulting Git commits, so another agent can explain a change months later.

**Status: v0.1.0 implementation in progress.** The local MCP server, CLI, storage, Git adapter, fixtures, and automated tests exist. Real client workflow validation and release gates are still pending.

## Install

```bash
pip install .
```

Or, with [uv](https://github.com/astral-sh/uv) (recommended):

```bash
uv pip install .
```

Requires Python 3.12+ and Git 2.34+. No external service or model API is needed.

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

Walks commits reachable from `HEAD`, reads records referenced by `CommitEcho-Record` trailers, and populates the search index. Run after cloning or pulling new commits.

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
# dry-run (shows what would be written):
commitecho setup --client codex --dry-run
```

Without `--client`, setup configures all three profiles. It writes the MCP server config and shared skill; Codex and Copilot receive an activation instruction block, and Antigravity receives a persistent activation rule (`trigger: always_on`). Dry-run lists planned changes rather than a file diff. Test the generated configuration in your client before relying on automatic capture.

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
| `.codex/skills/commitecho.md` | Shared capture/recall skill |
| `.codex/AGENTS.md` | Activation instruction block |

Codex loads project-local configuration only after the project is trusted. Setup does not change
the user's global trust settings.

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
| `.agents/skills/commitecho.md` | Shared capture/recall skill |
| `.github/copilot-instructions.md` | Activation instruction block (appended) |

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

# 4. Developer commits (includes record file + trailer)
git add .commitecho/records/<uuid>.json
git commit -m "fix: content hash dedup

CommitEcho-Record: <uuid>"

# 5. Months later, in a different session or clone:
commitecho index       # rebuild search index
search_history(question="content hash")
# → returns matching decision summaries; call get_evidence(record_id=...) for the full record and alternatives
```

Portable records are limited to 64 KiB, with 4 KiB of inline content per evidence item. Preparation rejects likely credentials and private home paths before writing JSON; edit the draft and retry. This check is best effort, so review the record before committing it.

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

---

## Release gates

These are target release gates, not a claim that the current build has passed them:

1. **Zero false `exact` results in fixtures** — `commitecho verify` on the `stale_preparation` fixture returns `declared_changed`, not `exact`.
2. **All records recover in a fresh full clone** — `commitecho index` on a clone of any fixture repo populates the search index and `search_history` returns the expected decisions.
3. **No branch/future-decision leakage** — `search_history` at a given `at_ref` does not surface decisions from commits unreachable from that ref.
4. **All three client workflows pass with recorded versions** — `commitecho setup --client <client>` for each of `codex`, `antigravity`, `copilot_vscode` produces valid config files and the 7-step acceptance scenario passes.
