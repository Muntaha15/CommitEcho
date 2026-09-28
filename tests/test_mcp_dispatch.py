"""Actual low-level MCP call dispatch, including the wire error flag."""

import asyncio
import json
import subprocess

from mcp.client import Client

from commitecho.transports import mcp_server


def test_tool_result_error_flags(tmp_path, monkeypatch):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    server = mcp_server.create_server(tmp_path)

    async def check():
        async with Client(server) as client:
            success = await client.call_tool("get_status", {})
            assert success.is_error is False
            assert "open_changes" in json.loads(success.content[0].text)

            validation = await client.call_tool("begin_change", {})
            assert validation.is_error is True
            assert "validation" in validation.content[0].text.lower()

            wrong_type = await client.call_tool(
                "begin_change", {"title": 123, "client": "codex", "operation_id": "op"}
            )
            assert wrong_type.is_error is True

            async def fail(*_args):
                raise RuntimeError("forced internal failure")

            monkeypatch.setattr(mcp_server, "_dispatch", fail)
            internal = await client.call_tool("get_status", {})
            assert internal.is_error is True
            assert "forced internal failure" in internal.content[0].text

    asyncio.run(check())


def test_client_sees_validation_schema(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    server = mcp_server.create_server(tmp_path)

    async def list_tools():
        async with Client(server) as client:
            return await client.list_tools()

    schemas = {tool.name: tool.input_schema for tool in asyncio.run(list_tools()).tools}
    assert set(schemas["begin_change"]["required"]) == {"title", "client", "operation_id"}
    assert set(schemas["record_decisions"]["required"]) == {
        "change_id", "expected_revision", "operation_id", "decisions"
    }
    decision = schemas["record_decisions"]["$defs"]["DecisionInput"]
    assert set(decision["required"]) == {"problem", "choice", "rationale"}
    assert schemas["search_history"]["properties"]["page_size"]["maximum"] == 100
