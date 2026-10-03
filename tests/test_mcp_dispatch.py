"""Actual low-level MCP call dispatch, including the wire error flag."""

import asyncio
import json
import subprocess

import pytest

from mcp.client import Client

from commitecho.transports import mcp_server


def test_tool_result_error_flags(tmp_path, monkeypatch, capsys):
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

            original = mcp_server._dispatch
            monkeypatch.setattr(mcp_server, "_dispatch", fail)
            internal = await client.call_tool("get_status", {})
            assert internal.is_error is True
            assert "forced internal failure" in internal.content[0].text
            error = json.loads(internal.content[0].text)
            assert error["exception_type"] == "RuntimeError"
            assert error["tool"] == "get_status"
            monkeypatch.setattr(mcp_server, "_dispatch", original)
            assert (await client.call_tool("get_status", {})).is_error is False

    asyncio.run(check())
    diagnostic = capsys.readouterr().err
    assert "RuntimeError" in diagnostic and "get_status" in diagnostic


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
    alternative = schemas["record_decisions"]["$defs"]["AlternativeInput"]
    assert alternative["required"] == ["choice"]
    assert alternative["additionalProperties"] is False
    assert set(alternative["properties"]) == {"choice", "disposition", "reason", "evidence_ids"}
    assert schemas["search_history"]["properties"]["page_size"]["maximum"] == 100


@pytest.mark.parametrize("alternative,fields", [
    ({"description": "cache", "reason": "too complex"}, ["choice", "description"]),
    ({"choice": "cache", "rationale": "too complex"}, ["rationale"]),
    ({"choice": "cache", "reason": 123}, ["reason"]),
])
def test_mcp_rejects_malformed_alternatives(tmp_path, alternative, fields):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)

    async def check():
        async with Client(mcp_server.create_server(tmp_path)) as client:
            begin = await client.call_tool("begin_change", {
                "title": "alternatives", "client": "codex", "operation_id": "begin"})
            change_id = json.loads(begin.content[0].text)["change_id"]
            result = await client.call_tool("record_decisions", {
                "change_id": change_id, "expected_revision": 0, "operation_id": "record",
                "decisions": [{"problem": "p", "choice": "c", "rationale": "r",
                               "alternatives": [alternative]}]})
            assert result.is_error is True
            error = json.loads(result.content[0].text)["error"]
            assert "validation" in error.lower()
            for field in fields:
                assert field in error
            assert "KeyError" not in error

    asyncio.run(check())
