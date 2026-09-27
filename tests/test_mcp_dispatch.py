"""Actual low-level MCP call dispatch, including the wire error flag."""

import asyncio
import json
import subprocess

from mcp.types import CallToolRequest, CallToolRequestParams

from commitecho.transports import mcp_server


def test_tool_result_error_flags(tmp_path, monkeypatch):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    server = mcp_server.create_server(tmp_path)
    handler = server.request_handlers[CallToolRequest]

    def call(name, arguments):
        request = CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
        return asyncio.run(handler(request)).root

    success = call("get_status", {})
    assert success.isError is False
    assert "open_changes" in json.loads(success.content[0].text)

    validation = call("begin_change", {})
    assert validation.isError is True
    assert "validation" in validation.content[0].text.lower()

    async def fail(*_args):
        raise RuntimeError("forced internal failure")

    monkeypatch.setattr(mcp_server, "_dispatch", fail)
    internal = call("get_status", {})
    assert internal.isError is True
    assert "forced internal failure" in internal.content[0].text
