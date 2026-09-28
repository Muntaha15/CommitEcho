# CommitEcho technical notes

Reviewed against the v0.1.0 source on 2026-09-28. This is an implementation guide, not a promise that every item in [architecture](architecture.md) is complete.

## 1. What the program does

CommitEcho is a local Python package with a Click CLI and an MCP stdio server. An agent supplies concise decision summaries; CommitEcho stores drafts privately, prepares a JSON record for a staged Git change, and uses a commit trailer to point back to that record. Another session can index records from Git history and search them. It does not read hidden model reasoning or automatically capture every conversation.

The package needs Python 3.12+, Git, `mcp`, `pydantic`, and `click`. `pyproject.toml` defines the `commitecho` entry point. `python -m commitecho serve --repo .` starts the MCP server; `python -m commitecho` alone enters the CLI.

## 2. Source map

| Path | Responsibility |
| --- | --- |
| `src/commitecho/transports/mcp_server.py` | Eight MCP tool schemas, validation, dispatch, stdio process |
| `src/commitecho/transports/cli.py` | Repository setup, diagnostics, indexing, inspection, comparison, export, client setup |
| `src/commitecho/application/capture.py` | Create/resume changes; persist decisions and evidence |
| `src/commitecho/application/prepare.py` | Inspect staged code, make a portable record and suggested trailer |
| `src/commitecho/application/verify.py` | Compare the declared record's prepared parent and code digest with a commit |
| `src/commitecho/application/retrieve.py` | Search, evidence lookup, range comparison, status |
| `src/commitecho/git/adapter.py` | Git discovery, index and commit inspection, canonical manifest |
| `src/commitecho/storage/` | SQLite connection, schema migration, draft persistence |
| `src/commitecho/integrations/` | Three client profiles and the shared agent instructions |

The CLI and MCP transport instantiate the application services. MCP calls are serialized as JSON text on stdio; stdout is reserved for the protocol.

## 3. Identity and storage

Repository discovery uses `git rev-parse --show-toplevel` and `--git-common-dir`, so linked worktrees can share the Git common directory. The private store is `<git-common-dir>/commitecho/`:

- `drafts.sqlite` contains repositories, sessions, changes, evidence, decision revisions, prepared record metadata, and operation IDs. It is authoritative local state and cannot be recreated from a clone.
- `index.sqlite` contains committed records and decisions, paths, FTS5 text, scanned commits, and binding results. It can be rebuilt from reachable Git objects by `commitecho index`.

Both databases use SQLite foreign keys, WAL, and a five-second busy timeout. They sit under Git metadata and should not be committed. `commitecho init` creates `.commitecho/config.json` and `.commitecho/records/` in the worktree. Those files are meant to be tracked: records are the portable part of the system. No `docs/` ignore rule is appropriate.

A normal clone receives committed record files and trailers, but not uncommitted drafts or the local index. After cloning, run `commitecho index`. The current index command scans commits reachable from `HEAD`; other branches require indexing while reachable from the selected HEAD.

## 4. Capture and record lifecycle

1. `begin_change` accepts a title, client, and caller-generated `operation_id`. It creates a local change and session, returning `change_id`, `session_id`, base commit OID, and `revision_counter`. A prior change can be resumed.
2. `record_decisions` accepts the change ID, `expected_revision`, a new operation ID, decisions, and optional evidence. Each decision has `problem`, `choice`, and `rationale`; optional fields include disposition, alternatives, and code scope. The revision counter prevents blind concurrent updates.
3. The developer or agent stages intended code. `prepare_commit` receives selected revision IDs, the current counter, summary, and operation ID. It reads `HEAD` and the staged index, computes a digest, checks that the snapshot did not move, writes `.commitecho/records/<record-id>.json`, and returns the path, trailer, staged paths, and uncovered paths. It neither stages nor commits.
4. The normal Git workflow stages the record file and commits with `CommitEcho-Record: <record-id>` in the message.
5. `verify_commit` checks the commit. `commitecho index` later reads committed record blobs and populates the search index.

An agent instruction in `src/commitecho/integrations/skill.md` asks clients to perform these steps. The server does not know whether the agent faithfully summarized the conversation, and the instruction cannot guarantee automatic capture.

## 5. The Git fingerprint

`GitAdapter.staged_changes()` reads the Git index with `git diff-index --cached --raw -z`. For an unborn branch it compares against the empty tree. Each entry has path, old and new blob OIDs, and old and new modes. The manifest sorts entries by path, includes object format and manifest version, and excludes generated `.commitecho/records/` paths. `fingerprint_manifest()` hashes compact, sorted-key JSON with SHA-256.

The prepared record stores the digest and expected parent commit OID. Verification recomputes the manifest from the committed change. A matching parent and digest yields `exact`. A changed parent or code digest yields `declared_changed`. Other outcomes are `contained_only`, `unverifiable`, and `invalid`. An exact code match says the record was prepared for those code bytes; it does not prove the rationale is true.

## 6. Indexing and retrieval

`commitecho index` walks commits reachable from `HEAD`. It validates each referenced record and writes all associations and the completed commit marker in one transaction. Invalid records leave diagnostics and are retried on the next run.

`search_history` resolves `at_ref` or defaults to `HEAD`, enumerates reachable commits, and reports partial coverage when reachable commits have not been indexed or Git history is shallow. Text queries use SQLite FTS5; path queries use exact repository-relative paths. Text and path filters intersect. A line filter requires a path and matches recorded line ranges. `from_ref` and `to_ref` select a commit range, while `at_ref` selects reachable history; invalid combinations are rejected. Results use bounded, stable pagination.

`compare_history(A, B)` returns decisions in commits reachable from B and not A. It reports whether A is an ancestor of B and provides a merge base on divergence. `get_evidence` retrieves a local draft evidence item or committed evidence by ID, and can return an indexed full record by record ID. `commitecho show` reads a record from the index or local prepared record metadata.

## 7. Setup and operational commands

`commitecho setup --client codex`, `--client antigravity`, and `--client copilot_vscode` write per-client MCP JSON and a copy of the shared skill. The option can be repeated; omitting it selects all three. Codex and Copilot receive an activation instruction block. Antigravity does not yet receive a persistent rule. `--dry-run` lists planned file actions and does not write.

`commitecho doctor` checks Git discovery, Python version, FTS5, MCP package import, both databases, skill copies, and presence of client config entries. It does not establish a live MCP handshake. `commitecho status` shows pending changes and whether HEAD has been indexed. `commitecho verify <oid>` exits nonzero unless the result is `exact`. `commitecho diff <from-ref> <to-ref>` compares decision history. `commitecho export <change-id>` exports a readable draft snapshot with parsed decisions, predecessor links, and referenced evidence; it is not a restorable database backup.

## 8. Current limits and risks

- A fresh clone can verify a self-consistent committed record and code binding, but cannot authenticate the original local preparation without its draft database.
- Portable records are limited to 64 KiB and inline evidence to 4 KiB each. The credential and private-path screen is best effort; review the JSON before committing it.
- Search is lexical FTS5 with literal word matching. There is no semantic search or line-specific blame.
- Deterministic fixtures run in the pytest gate, but a live acceptance pass across all three clients has not been recorded. The baseline comparison checks stored context, not answer quality.
- Client setup writes project files. Review them before committing, especially existing instructions and machine-specific server paths.

These are implementation observations. [Product scope and delivery](product-and-delivery.md) keeps the release gates and proposed follow-up work separate from what the current source proves.
## 9. Maintenance checklist

When changing the wire schema, update `domain/models.py`, the SQLite migrations, the indexer, and any fixture records together. When changing Git linkage, run the root-commit, partial-staging, stale-preparation, and fresh-clone scenarios. When changing a client profile, inspect its generated JSON and instruction file, then test a real MCP handshake in that client. Keep the README commands aligned with Click's `--help` output.
