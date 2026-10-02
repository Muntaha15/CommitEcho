---
name: commitecho
version: 3
description: Capture decisions made during coding tasks, recall rationale from Git history, and prepare verified commit records.
---

# CommitEcho capture and recall workflow

## When to activate
- You begin or resume a task involving meaningful code or design work.
- You need to explain why committed code exists or how decisions evolved.
- If CommitEcho MCP tools are unavailable in your environment, report this to the user rather than inventing successful capture.

## Core concepts and parameters
- **Mutating operations** (`begin_change`, `record_decisions`, `prepare_commit`) require a caller-generated `operation_id`. Use a new UUID for each distinct operation. Reuse the identical `operation_id` only when retrying an identical payload after a transport failure.
- **Client identification**: Pass your active client ID in `client` (`"codex"`, `"antigravity"`, `"copilot_vscode"`, or `"claude_code"`). Record actual surface and version separately in `client_version` and `native_session_id`.
- **Revision tracking**: `expected_revision` must strictly match the server's current `revision_counter` (initially returned by `begin_change` as 0, updated by each successful `record_decisions`).
- **Provenance and evidence**: Any agent-authored summary must specify `origin="agent_reported"`. Never invent unstated alternatives or claim developer confirmation (`developer_confirmed`, `developer_attestation`, and `independent_artifact` origins are rejected at the MCP boundary).
- **Authorization**: Installing or loading this skill does not imply permission to make Git commits; follow normal project authorization.

## Capture workflow

1. **Open or resume change**:
   - Call `begin_change` with `title`, `client` set to your active agent identifier (`"codex"`, `"antigravity"`, `"copilot_vscode"`, or `"claude_code"`), and a new UUID `operation_id`.
   - Save the returned `change_id`, `session_id`, and `revision_counter`.

2. **Record decisions and alternatives**:
   - Whenever an approach is selected, rejected, or revised, call `record_decisions`.
   - Pass `change_id`, `expected_revision` (matching current `revision_counter`), and a new UUID `operation_id`.
   - For each decision, provide `problem`, `choice`, `rationale`, and optional `predecessor_revision_ids`, `code_scope`, and `disposition` (`"selected"`, `"rejected"`, `"proposed"`).
   - Only list alternatives that were actually discussed.
   - For agent-generated evidence items, set `origin="agent_reported"`.
   - Save the returned `revision_ids` and `evidence_ids`, and update `expected_revision` to the returned `revision_counter`.

3. **Stage code, prepare, commit, and verify**:
   a. Stage intended code changes first (`git add <files>`).
   b. Call `prepare_commit` with `change_id`, `expected_revision`, `selected_revision_ids`, `summary`, and a new UUID `operation_id`.
   c. Note the returned `record_id`, `record_path` (e.g. `.commitecho/records/<uuid>.json`), and `trailer` (e.g. `CommitEcho-Record: <uuid>`).
   d. If the staged tree is modified after preparation, re-preparation is required before committing (otherwise verification will detect `declared_changed` or prepare will fail).
   e. Stage the returned record: `git add <record_path>`.
   f. Commit with git, appending the exact returned `trailer` to the commit message:
      ```text
      CommitEcho-Record: <record_id>
      ```
   g. Call `verify_commit` with the resulting commit OID. Pass `keep_open=True` only if additional commits will follow for this change.

## Recall workflow

1. Call `search_history` with the user's question, file `path`, or revision scoping (`at_ref`, or `from_ref` and `to_ref`).
2. Call `get_evidence` with the returned `evidence_id` or `record_id` to inspect full details and alternatives.
3. Compose answers strictly from retrieved evidence and cite records. If history or rationale is missing from evidence, explicitly state that it is unrecorded rather than speculating.
4. For range-based comparisons across commits/branches, call `compare_history`.

## Invariants (never violate)
- Record only information present in visible context. Never fabricate discussions or developer intent.
- Preserve the distinction between user statements, agent summaries, hypotheses, and observed artifacts.
- A proposal, a selected approach, and observed implementation are distinct states.
- Do not infer decisions from time proximity or filename matches.
- A code match does not prove an explanation is true.
