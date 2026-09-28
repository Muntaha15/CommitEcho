"""CommitEcho MCP server – all 8 tools exposed over local stdio.

Launch via: python -m commitecho serve --repo /path/to/repo
or configured as an MCP stdio server in client config.

stdout is reserved for the MCP protocol; all logging goes to stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, Tool, TextContent
from pydantic import BaseModel, Field

from commitecho.git.adapter import GitAdapter, GitError
from commitecho.storage.db import open_drafts_db, open_index_db
from commitecho.application.capture import CaptureService
from commitecho.application.prepare import PrepareService
from commitecho.application.verify import VerifyService
from commitecho.application.retrieve import RetrieveService


# ---------------------------------------------------------------------------
# Tool input schemas (Pydantic models used for validation)
# ---------------------------------------------------------------------------


class BeginChangeInput(BaseModel):
    title: str = Field(description="Short description of the work being started.")
    client: str = Field(description="Client identifier, e.g. 'codex', 'antigravity', 'copilot_vscode'.")
    operation_id: str = Field(description="Caller-generated idempotency key (UUID recommended).")
    client_version: str | None = Field(default=None, description="Client version string.")
    native_session_id: str | None = Field(default=None, description="Opaque native session ID from the client.")
    prior_change_id: str | None = Field(default=None, description="Resume an existing open change.")


class DecisionInput(BaseModel):
    problem: str
    choice: str
    rationale: str
    decision_id: str | None = None
    predecessor_revision_ids: list[str] = Field(default_factory=list)
    disposition: Literal["proposed", "selected", "rejected", "withdrawn"] = "proposed"
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    code_scope: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class RecordDecisionsInput(BaseModel):
    change_id: str = Field(description="The change ID returned by begin_change.")
    expected_revision: int = Field(description="Current revision_counter; prevents blind overwrites.")
    operation_id: str = Field(description="Caller-generated idempotency key.")
    decisions: list[DecisionInput] = Field(
        description=(
            "List of decision objects. Each must have: problem, choice, rationale. "
            "Optional: decision_id, predecessor_revision_ids, disposition, alternatives, "
            "code_scope {paths, symbol_label}, evidence_ids."
        )
    )
    evidence: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Evidence items to persist. Each must have: kind, origin, content or locator. "
            "Optional evidence_id lets decisions and alternatives reference same-call evidence; "
            "the response returns every generated evidence ID. "
            "Kinds: discussion_summary, test_result, code_observation, source_excerpt, "
            "external_artifact. Agent submissions use origin: agent_reported; "
            "developer_attestation and stronger origins require independent confirmation."
        ),
    )


class PrepareCommitInput(BaseModel):
    change_id: str = Field(description="The change ID.")
    expected_revision: int = Field(description="Current revision_counter.")
    selected_revision_ids: list[str] = Field(
        description="Revision IDs (from record_decisions) relevant to this commit."
    )
    summary: str = Field(description="One-sentence summary of what this commit does.")
    operation_id: str = Field(description="Caller-generated idempotency key.")


class VerifyCommitInput(BaseModel):
    commit_oid: str = Field(description="Full or resolvable Git commit OID.")
    record_id: str | None = Field(default=None, description="Expected record UUID (optional).")
    keep_open: bool = Field(default=False, description="Keep this change open for another commit.")


class SearchHistoryInput(BaseModel):
    question: str | None = Field(default=None, description="Natural-language words matched literally with AND; punctuation is ignored.")
    path: str | None = Field(default=None, description="Repository-relative file path.")
    line: int | None = Field(default=None, description="Positive line number; requires path and matches explicit line ranges.")
    at_ref: str | None = Field(default=None, description="Git ref to scope results to (default: HEAD).")
    from_ref: str | None = Field(default=None, description="Range start, excluded; requires to_ref and cannot be combined with at_ref.")
    to_ref: str | None = Field(default=None, description="Range end, included; requires from_ref and cannot be combined with at_ref.")
    page_size: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, description="Result offset, up to 10000; page_size is 1-100.")


class GetEvidenceInput(BaseModel):
    evidence_id: str | None = Field(default=None)
    record_id: str | None = Field(default=None)


class CompareHistoryInput(BaseModel):
    from_ref: str = Field(description="Base Git ref (excluded from range).")
    to_ref: str = Field(description="Target Git ref (included in range).")
    path: str | None = Field(default=None, description="Limit to decisions touching this path.")


class GetStatusInput(BaseModel):
    change_id: str | None = Field(default=None, description="Specific change to inspect.")


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(repo_path: str | Path) -> Server:
    """Instantiate and configure the CommitEcho MCP server for *repo_path*."""

    git = GitAdapter.from_path(repo_path)
    repo_info = git.repo_info

    drafts_conn = open_drafts_db(repo_info.common_dir)
    index_conn = open_index_db(repo_info.common_dir)

    capture = CaptureService(drafts_conn, git)
    prepare = PrepareService(drafts_conn, git)
    verify = VerifyService(drafts_conn, index_conn, git)
    retrieve = RetrieveService(drafts_conn, index_conn, git)

    # ------------------------------------------------------------------
    # Tool: begin_change
    # ------------------------------------------------------------------

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=_TOOL_DEFINITIONS)

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        from commitecho.application.prepare import IndexChangedError
        try:
            result = await _dispatch(params.name, params.arguments or {}, capture, prepare, verify, retrieve)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(result, default=str))])
        except IndexChangedError as exc:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": str(exc), "error_code": "INDEX_CHANGED"}))], is_error=True)
        except (ValueError, TypeError) as exc:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": str(exc)}))], is_error=True)
        except Exception as exc:
            print(f"[commitecho] Unexpected error in {params.name}: {exc}", file=sys.stderr)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": str(exc)}))], is_error=True)

    return Server("commitecho", on_list_tools=list_tools, on_call_tool=call_tool)


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


async def _dispatch(
    name: str,
    args: dict[str, Any],
    capture: CaptureService,
    prepare: PrepareService,
    verify: VerifyService,
    retrieve: RetrieveService,
) -> Any:
    if name == "begin_change":
        inp = BeginChangeInput.model_validate(args, strict=True)
        return capture.begin_change(
            title=inp.title,
            client=inp.client,
            client_version=inp.client_version,
            native_session_id=inp.native_session_id,
            operation_id=inp.operation_id,
            prior_change_id=inp.prior_change_id,
        )

    if name == "record_decisions":
        inp = RecordDecisionsInput.model_validate(args, strict=True)
        for item in inp.evidence or []:
            if item.get("kind") == "developer_attestation" or item.get("origin", "agent_reported") != "agent_reported":
                raise ValueError("MCP evidence cannot claim developer confirmation or independent provenance.")
        return capture.record_decisions(
            change_id=inp.change_id,
            expected_revision=inp.expected_revision,
            operation_id=inp.operation_id,
            decisions=[decision.model_dump(exclude_unset=True) for decision in inp.decisions],
            evidence=inp.evidence,
        )

    if name == "prepare_commit":
        inp = PrepareCommitInput.model_validate(args, strict=True)
        return prepare.prepare_commit(
            change_id=inp.change_id,
            expected_revision=inp.expected_revision,
            selected_revision_ids=inp.selected_revision_ids,
            summary=inp.summary,
            operation_id=inp.operation_id,
        )

    if name == "verify_commit":
        inp = VerifyCommitInput.model_validate(args, strict=True)
        return verify.verify_commit(
            commit_oid=inp.commit_oid,
            record_id=inp.record_id,
            keep_open=inp.keep_open,
        )

    if name == "search_history":
        inp = SearchHistoryInput.model_validate(args, strict=True)
        return retrieve.search_history(
            question=inp.question,
            path=inp.path,
            line=inp.line,
            at_ref=inp.at_ref,
            from_ref=inp.from_ref,
            to_ref=inp.to_ref,
            page_size=inp.page_size,
            cursor=inp.cursor,
        )

    if name == "get_evidence":
        inp = GetEvidenceInput.model_validate(args, strict=True)
        return retrieve.get_evidence(
            evidence_id=inp.evidence_id,
            record_id=inp.record_id,
        )

    if name == "compare_history":
        inp = CompareHistoryInput.model_validate(args, strict=True)
        return retrieve.compare_history(
            from_ref=inp.from_ref,
            to_ref=inp.to_ref,
            path=inp.path,
        )

    if name == "get_status":
        inp = GetStatusInput.model_validate(args, strict=True)
        return retrieve.get_status(change_id=inp.change_id)

    raise ValueError(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Tool definitions (returned to the client on list_tools)
# ---------------------------------------------------------------------------


_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="begin_change",
        description=(
            "Open or resume a CommitEcho change for the current worktree. "
            "Call this at the start of any meaningful code/design task. "
            "Returns change_id, session_id, base Git OID, and revision counter."
        ),
        input_schema=BeginChangeInput.model_json_schema(),
    ),
    Tool(
        name="record_decisions",
        description=(
            "Persist one or more decision checkpoints for an open change. "
            "Call whenever an approach is chosen, rejected, or revised. "
            "Record only information present in visible context. "
            "Returns persisted revision_ids and updated revision_counter."
        ),
        input_schema=RecordDecisionsInput.model_json_schema(),
    ),
    Tool(
        name="prepare_commit",
        description=(
            "Prepare a CommitEcho record for the currently staged changes. "
            "Writes .commitecho/records/<uuid>.json and returns the trailer to include in the commit. "
            "Does NOT stage or commit files. "
            "Call after staging code changes but before committing."
        ),
        input_schema=PrepareCommitInput.model_json_schema(),
    ),
    Tool(
        name="verify_commit",
        description=(
            "Verify that a Git commit correctly carries its CommitEcho record. "
            "Checks three independent facts: trailer presence, record integrity, and code-change match. "
            "Returns binding outcome: exact | declared_changed | contained_only | unverifiable | invalid."
        ),
        input_schema=VerifyCommitInput.model_json_schema(),
    ),
    Tool(
        name="search_history",
        description=(
            "Search committed CommitEcho records by natural-language question and/or file path. "
            "Scoped to the ancestry of at_ref (default: HEAD). "
            "Returns ranked decision records with evidence IDs and coverage information."
        ),
        input_schema=SearchHistoryInput.model_json_schema(),
    ),
    Tool(
        name="get_evidence",
        description=(
            "Retrieve bounded source material and provenance for an evidence_id or record_id. "
            "Use after search_history to expand a specific evidence item."
        ),
        input_schema=GetEvidenceInput.model_json_schema(),
    ),
    Tool(
        name="compare_history",
        description=(
            "Return decision revisions introduced between from_ref and to_ref (A..B range). "
            "Excludes commits reachable from from_ref. "
            "Reports branch divergence and merge-base when applicable."
        ),
        input_schema=CompareHistoryInput.model_json_schema(),
    ),
    Tool(
        name="get_status",
        description=(
            "Return pending changes, stale preparations, indexing coverage, and setup capability. "
            "Use to check server health and see what work is in progress."
        ),
        input_schema=GetStatusInput.model_json_schema(),
    ),
]


# ---------------------------------------------------------------------------
# Entry point for direct launch
# ---------------------------------------------------------------------------


async def run_server(repo_path: str | Path) -> None:
    """Run the CommitEcho MCP server on stdio for *repo_path*."""
    server = create_server(repo_path)
    print(f"[commitecho] MCP server starting for {repo_path}", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
