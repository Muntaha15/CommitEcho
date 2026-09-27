---
name: commitecho
version: 1
description: Capture decisions made during coding tasks and recall them from Git history.
---

# CommitEcho capture and recall workflow

## When to activate
- You begin or resume a task involving meaningful code or design work.
- You need to explain why committed code exists or how decisions evolved.

## Capture workflow

1. Call `begin_change` with the task title and your client identifier.
   Save the returned `change_id` and `revision_counter`.

2. Whenever an approach is chosen, rejected, or revised, call `record_decisions`.
   - Include `problem`, `choice`, and `rationale` for each decision.
   - List only alternatives that were actually discussed.
   - Use `evidence` items with `origin: agent_reported` for anything you summarized.
   - Update `expected_revision` to the current `revision_counter`.

3. Before committing:
   a. Stage your code changes (`git add …`).
   b. Call `prepare_commit` with the relevant `selected_revision_ids` and a one-sentence `summary`.
   c. Stage the returned record file: `git add <record_path>`.
   d. Commit with the returned trailer appended to the commit message.
   e. Call `verify_commit` with the resulting commit OID.

## Recall workflow

1. Call `search_history` with the user's question and/or the relevant file path.
2. Call `get_evidence` for any evidence IDs in the results.
3. Compose a cited answer from the returned evidence. State missing history explicitly.
4. For range questions, use `compare_history` with `from_ref` and `to_ref`.

## Invariants (never violate)
- Record only information present in visible context.
- Preserve the distinction: user statements, agent summaries, hypotheses, observed artifacts.
- A proposal, a selected approach, and observed implementation are distinct states.
- Do not infer decisions from time proximity or filename matches.
- A code match does not prove an explanation is true.
