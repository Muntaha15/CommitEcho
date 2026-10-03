# Antigravity IDE live test - 2026-10-03

Outcome: **native capture, commit, verification, indexing, and recall reported passed**.
The saved report does not document a process restart, so fresh-process recall
remains unqualified by this run.

The run report identifies Antigravity IDE 1.107.0, Windows 10 x64, Python
3.12.14, Git 2.49.0.windows.1, and Gemini 3.8 Flash (High). It used a separate
disposable repository with spaces in its path and the existing project runtime.
This is a summary of the saved agent report, not a new independent client run.

- The report records discovery of all eight native MCP tools, shared skill v4,
  and the activation rule. The generated server arguments targeted the fixture.
- Native `get_status` matched seed HEAD
  `a2f18e5ae3caf8a4aba7bfe5d2feda7e9bf5f893` before mutations.
- The fixture implementation used `list(dict.fromkeys(values))` for
  order-preserving deduplication. Assertions covered duplicates and empty input.
  The decision referenced the submitted assertion evidence as `agent_reported`.
- Commit `4f29b531a019c7c198fe7ec61e0851ea54ef9f98` contained `dedupe.py`
  and record `6647d739-e6a7-4a3d-bdda-e40664486fc3`, with its exact trailer.
- Native verification returned `exact`, `local_preparation_verified: true`,
  and no reasons. Explicit indexing scanned two commits and indexed one record.
- Search, record/evidence retrieval, and range comparison recovered the selected
  decision and linked assertion evidence. Final status reported full coverage
  with no open changes or diagnostics.

The report's overall PASS applies to these recorded checkpoints. Restart,
cross-client handoff, Antigravity CLI, POSIX, and native lifecycle hooks require
separate evidence. Raw reports, machine paths, configuration, databases, and
fixture Git history remain in the ignored `.commitecho/` run directory.
