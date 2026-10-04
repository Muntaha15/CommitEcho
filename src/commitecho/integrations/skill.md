---
name: commitecho
version: 7
description: Capture decisions made during coding tasks, recall rationale from Git history, and prepare verified commit records.
---

# CommitEcho capture and recall workflow

## When to activate
- You begin or resume a task involving meaningful code or design work.
- You need to explain why committed code exists or how decisions evolved.
- If CommitEcho MCP tools are unavailable in your environment, report this to the user rather than inventing successful capture.

## Core concepts and parameters
- **Mutating operations** (`begin_change`, `record_decisions`, `prepare_commit`) require a caller-generated `operation_id`. Generate a new UUID for each distinct operation using a UUID library or shell tool, such as Python `uuid.uuid4()` or PowerShell `[guid]::NewGuid().ToString()`; do not invent patterned IDs. Generate evidence IDs the same way. Reuse the identical `operation_id` only when retrying an identical payload after a transport failure.
- **Client identification**: Pass your active client ID in `client` (`"codex"`, `"antigravity"`, `"copilot_vscode"`, or `"claude_code"`). Session metadata and each evidence item's `client` are independent; neither is filled from the other.
- **Revision tracking**: `expected_revision` must strictly match the server's current `revision_counter` (initially returned by `begin_change` as 0, updated by each successful `record_decisions`).
- **Provenance and evidence**: Any agent-authored summary must specify `origin="agent_reported"`. Never invent unstated alternatives or claim developer confirmation (`developer_confirmed`, `developer_attestation`, and `independent_artifact` origins are rejected at the MCP boundary).
- **Authorization**: Installing or loading this skill does not imply permission to make Git commits; follow normal project authorization.

## Capture workflow

1. **Open or resume change**:
   - Call `get_status` to inspect open changes and save its `runtime.index_argv` for indexing. On restart, inspect the intended change with `get_status(change_id=...)` or resume with `begin_change(prior_change_id=...)`. Review its `decision_revisions` and `unpublished_revision_ids`; preserve earlier decisions and evidence rather than recording only the new session's work.
   - Call `begin_change` with `title`, `client` set to your active agent identifier (`"codex"`, `"antigravity"`, `"copilot_vscode"`, or `"claude_code"`), and a new UUID `operation_id`.
   - Include the actual `client_version` and `native_session_id` when available; omit unknown values or use null. The native ID belongs to the client session, not the CommitEcho `session_id` returned by this call. Never guess these values or put a surface name in either field.
   - Example (substitute your active client and observed values): `begin_change(title="Fix duplicate requests", client="claude_code", client_version="<observed-version>", native_session_id="<known-native-session-id>", operation_id="<new-uuid>")`. Omit the two optional metadata fields when unavailable.
   - Save the returned `change_id`, `session_id`, and `revision_counter`, plus any existing decision revision IDs when resuming.

2. **Record decisions and alternatives**:
   - Whenever an approach is selected, rejected, or revised, call `record_decisions`.
   - Pass `change_id`, `expected_revision` (matching current `revision_counter`), and a new UUID `operation_id`.
   - For each decision, provide `problem`, `choice`, `rationale`, and optional `predecessor_revision_ids`, `code_scope`, and `disposition` (`"selected"`, `"rejected"`, `"proposed"`).
   - Only list alternatives that were actually discussed.
   - Alternatives require `choice`; accepted optional fields are `disposition` (default `"rejected"`), `reason`, and `evidence_ids`. Unknown fields are rejected. The decision's `rationale` explains the chosen approach; an alternative's `reason` explains its rejection. Omit an unrecorded reason rather than inventing one.
   - Example rejected alternative inside a decision's `alternatives`: `{"choice":"Add a cache dependency", "disposition":"rejected", "reason":"The existing standard library solution meets the requirement", "evidence_ids":["<supporting-evidence-id>"]}`. Use only alternatives and reasons present in the conversation, and reference evidence belonging to this change.
   - For evidence you author, set `origin="agent_reported"` and `client` to your active client ID, even when resuming a change started by another client. Preserve the original client when referencing existing evidence.
   - Example evidence item for `record_decisions`: `{"evidence_id":"<new-uuid>", "kind":"test_result", "origin":"agent_reported", "client":"claude_code", "content":"<actual observed test result>"}`. Reference its `evidence_id` in the relevant decision's or alternative's `evidence_ids` so preparation includes it.
   - Save the returned `revision_ids` and `evidence_ids`, and update `expected_revision` to the returned `revision_counter`.

3. **Stage code, prepare, commit, and verify**:
   a. Stage intended code changes first (`git add <files>`).
   b. Call `prepare_commit` with `change_id`, `expected_revision`, `selected_revision_ids`, `summary`, and a new UUID `operation_id`.
      Select the intended unpublished revisions from all sessions. If `omitted_revision_ids` is nonempty, review those decisions and re-prepare with any that belong in this commit; a deliberate partial commit leaves the remaining decisions open.
   c. Note the returned `record_id`, `record_path` (e.g. `.commitecho/records/<uuid>.json`), and `trailer` (e.g. `CommitEcho-Record: <uuid>`).
   d. If the staged tree is modified after preparation, re-preparation is required before committing (otherwise verification will detect `declared_changed` or prepare will fail).
   e. Stage the returned record: `git add <record_path>`.
   f. Commit with git, appending the exact returned `trailer` to the commit message:
      ```text
      CommitEcho-Record: <record_id>
      ```
   g. Call `verify_commit` with the resulting commit OID. Pass `keep_open=True` if additional commits will follow for this change. Check `details.remaining_revision_ids` and `details.change_status`; exact verification can leave a partial change open until its unpublished decisions are committed.
   h. After successful verification, execute the `runtime.index_argv` returned by `get_status`, preserving each argument and using quoting appropriate to the active shell. It supplies the MCP server's Python executable and repository path; do not substitute another checkout's environment or assume plugin variables exist in the shell. Verification does not populate searchable history; index before restarting for recall.

## Recall workflow

1. Call `search_history` with the user's question, file `path`, or revision scoping (`at_ref`, or `from_ref` and `to_ref`).
   - If coverage notes report commits not yet indexed (for example after cloning, pulling, or committing), call `get_status` and execute its `runtime.index_argv`, then retry the query. Preserve the argument list and use the active shell's quoting rules, including paths with spaces. Indexing is a CLI command, not an MCP tool. If shell access or indexing is unavailable, report incomplete coverage; do not treat an empty result as proof that rationale is unrecorded.
2. Call `get_evidence` with the returned `evidence_id` or `record_id` to inspect full details and alternatives.
3. Compose answers strictly from retrieved evidence and cite records. If history or rationale is missing from evidence, explicitly state that it is unrecorded rather than speculating.
4. For range-based comparisons across commits/branches, call `compare_history`.

## Invariants (never violate)
- Record only information present in visible context. Never fabricate discussions or developer intent.
- Preserve the distinction between user statements, agent summaries, hypotheses, and observed artifacts.
- A proposal, a selected approach, and observed implementation are distinct states.
- Do not infer decisions from time proximity or filename matches.
- A code match does not prove an explanation is true.
