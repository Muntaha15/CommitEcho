# Product scope and delivery

Status: product plan reviewed against the v0.1.0 source on 2026-09-27. Estimates are planning judgments, not measured implementation results. The server, CLI, setup profiles, fixtures, and automated tests exist; live three-client acceptance and release evaluation remain open.

## Purpose and positioning

CommitEcho records the decisions made during a code change, preserves them with the resulting Git history, and helps another coding agent explain how those decisions evolved.

The project should be judged by whether a developer can recover the actual recorded rationale six months later, including after switching agents or cloning onto another machine.

## Existing work and our intended contribution

These descriptions reflect project documentation, not independent performance evaluations. Feature overlap is real; CommitEcho must not claim to invent coding-agent memory or commit reasoning.

| Project | Documented focus | CommitEcho design implication |
| --- | --- | --- |
| [sessions](https://github.com/nicknisi/sessions) | Searches local coding transcripts and correlates sessions with code using file/time evidence | Explicitly attach selected decision records when code is committed; measure linkage accuracy separately from search |
| [agit](https://github.com/agit-stuff/agit) | Agents push context through MCP; context is linked to Git changes | Proactive capture alone is not novel; evaluate the full persistence and retrieval contract |
| [varve](https://github.com/varve-sh/varve) | Decision memory, scope/provenance/lifecycle, and commit attribution | Structured decisions and supersession already exist; avoid presenting those features as unique |
| [Spelungit](https://github.com/haacked/spelungit) | Natural-language search over Git history | Semantic search is a retrieval option rather than the project's main contribution |

Our chosen engineering emphasis is the combination of:

- **Explicit change linkage:** selected discussion is prepared for the staged code and validated against the resulting commit.
- **Portable published memory:** a normal repository clone reconstructs committed records without access to the original chat store.
- **Revision-scoped explanations:** answers distinguish the decision at revision A from the decision at revision B, including branch divergence.
- **Honest provenance:** a code match, an agent report, a source artifact, and developer confirmation remain different facts.
- **Tested handoff:** Codex, Antigravity IDE, and Copilot in VS Code can capture and retrieve the same record format.

This is an implementation focus, not a claim that no existing tool offers similar behavior. The portfolio should publish the schema, failure cases, evaluation fixtures, and results. Credit relevant projects and preserve licenses if any code is reused. A feature checklist or a renamed chat archive would not establish a contribution.

## First-release scope

| Include | Defer |
| --- | --- |
| Local stdio MCP server and matching CLI | Hosted service, accounts, team administration |
| Three supported local client workflows | Every client, cloud coding environments |
| Incremental decision capture | Automatic ingestion of all chat transcripts |
| Draft persistence and committed records | Background transcript summarization service |
| Ordinary/root commit preparation and validation | Exact rewrite/squash reconciliation and merge-resolution capture |
| Commit/path/line/range retrieval | Arbitrary-language symbol identity tracking |
| Lexical search plus exact Git filters | Vector database, rerankers, knowledge graph service |
| Recorded alternatives and decision revisions | Reconstructed undocumented historical intent |

## Recommended implementation order

| Milestone | Deliverable | Exit condition |
| --- | --- | --- |
| M0: compatibility and format spike | Minimal stdio tool + instruction in all three clients; record/fingerprint prototype | Each client sends one structured checkpoint; one record survives commit and fresh clone; Windows path behavior checked |
| M1: capture and commit lifecycle | Domain models, local drafts, prepare/verify, CLI | Real Git fixtures pass for root/ordinary commits, partial staging, retries, mismatches, and crash recovery |
| M2: recall and temporal correctness | History index, evidence fetch, range comparison, decision revisions | Queries at A and B use the correct records; branch conflicts and incomplete clones are reported |
| M3: three-client workflow | Setup profiles, shared skill, doctor, cross-client scenarios | End-to-end capture/recall passes in Codex, Antigravity IDE, and Copilot VS Code |
| M4: evaluation and release | Fixtures, measured results, documented limitations, short demo | A new user reproduces the handoff demo; no unsupported compatibility claims |

M0 must validate all three clients early. Subsequent implementation can use one client for iteration, then run the common scenario across all three. If proactive skill use is unreliable, improve activation and expose an explicit checkpoint command; do not hide capture gaps behind search quality.

## Effort and running cost

For one developer comfortable with Python, Git, and MCP, allow approximately **20–35 focused engineering days** for a tested v0.1. A rough allocation is 2–3 days for M0, 6–10 for M1, 5–8 for M2, 4–7 for M3, and 3–7 for evaluation/polish. Those ranges sum to 20–35 days. Learning the tools, client incompatibilities, and publication requirements can extend the schedule.

After the common core works, a new local MCP-and-skills client is tentatively **1–3 days for setup and a smoke path**, followed by broader compatibility testing. A transcript parser or reliable lifecycle automation is a separate feature and may take substantially longer. "All coding agents" is an ongoing compatibility commitment, not a finite initial feature.

v0.1 requires no hosted infrastructure, paid vector database, or separate model API key. The user's existing coding agent performs summaries and answers, which consumes its normal tokens/usage. CommitEcho itself performs deterministic storage, Git inspection, and retrieval. Benchmark checkpoint frequency and returned context size before quoting a per-session model cost.

## Evaluation that makes the portfolio credible

Create a small repository with deliberate, reviewable discussion scripts and expected decisions. Include a chosen/rejected alternative, a later reversal, two branches that disagree, partial staging, a stale preparation, a rewritten commit, and a question whose reason was never recorded.

Compare three approaches under the same host model, question set, and context budget:

1. Git history/diff/blame with no captured conversation.
2. Search over stored conversation excerpts without explicit commit linkage.
3. CommitEcho's selected records and verified bindings.

If another open-source tool can be installed and configured fairly, include a separate reproducible comparison. Do not use a hand-built baseline as evidence that CommitEcho beats named projects.

| Measurement | What to record |
| --- | --- |
| Capture completeness | Expected decisions recorded / decisions deliberately discussed; split automatic vs explicitly invoked |
| Capture fidelity | Unsupported rationale or invented alternatives per record, manually checked against the script |
| Linkage correctness | Correct commit associations and false exact labels, especially after staged changes and rewrites |
| Retrieval | Relevant decision recall@k, with exact Git filters and paraphrased questions measured separately |
| Answer grounding | Factual claims supported by supplied evidence; citations point to the right version |
| Unknown handling | Missing rationale remains unknown instead of receiving a plausible invented answer |
| Portability | Fresh clone + empty history index + different agent recovers the committed explanation |
| Cost and usability | Tool calls, context size, wall time, summary burden, and failures per task |

Initial release gates: zero false `exact` results in the deterministic Git fixtures; all published records recover in a fresh full clone; no branch/future-decision leakage in temporal fixtures; all three client workflows pass with recorded versions. Capture and answer quality results must be reported numerically, including failures, rather than described as perfect from a small sample.

## Design decisions and outstanding spikes

| Decision | Proposed baseline | Reason / remaining validation |
| --- | --- | --- |
| Capture location | Current agent summarizes visible discussion | Portable without private transcript access; measure instruction adherence |
| Core transport | Local MCP stdio | All target clients document a path; validate exact versions |
| Runtime | Python 3.12+ and official MCP SDK | Small deployment and SQLite integration; verify packaged installs on supported OSes |
| Storage | Private draft DB + committed JSON records + derived index | Explicit durability boundary and ordinary Git portability |
| Commit pointer | Git trailer referencing a record UUID | Avoid a self-referential SHA; validate against actual objects |
| Retrieval | SQLite FTS5 plus Git ancestry/path filters | Simple first baseline; measure before adding embeddings |
| Rewrite handling | Detect and downgrade uncertain links | Correctness before automatic reconciliation |
| Hooks | Optional per-client enhancement | No shared reliable lifecycle contract assumed |

The source now defines a JSON-based canonical manifest and a versioned Pydantic record export. Precise client versions, live MCP handshakes, installed executable discovery across supported operating systems, and the full acceptance scenario still need validation. See [technical notes](technical-notes.md) for implementation limits.
