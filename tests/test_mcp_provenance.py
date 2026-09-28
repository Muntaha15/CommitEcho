"""MCP callers must not assign trusted provenance to their own evidence."""

import asyncio
import importlib
import sys
from types import ModuleType

import pytest


def test_mcp_caller_cannot_self_assert_provenance(monkeypatch):
    # Keep this boundary test runnable even when the optional MCP SDK is absent.
    try:
        import mcp  # noqa: F401
    except ModuleNotFoundError:
        for name in ("mcp", "mcp.server", "mcp.server.stdio", "mcp.types"):
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
        sys.modules["mcp.server"].Server = object
        sys.modules["mcp.server.stdio"].stdio_server = object()
        sys.modules["mcp.types"].Tool = lambda **kwargs: kwargs
        sys.modules["mcp.types"].TextContent = object
        sys.modules["mcp.types"].CallToolResult = object

    dispatch = importlib.import_module("commitecho.transports.mcp_server")._dispatch

    class Capture:
        calls = 0

        def record_decisions(self, **kwargs):
            self.calls += 1
            return kwargs

    capture = Capture()
    args = {"change_id": "change", "expected_revision": 0, "operation_id": "op",
            "decisions": [], "evidence": [{"kind": "test_result", "content": "claimed"}]}
    for claim in ({"origin": "developer_confirmed"}, {"origin": "source_adapter"},
                  {"origin": "independent_artifact"}, {"kind": "developer_attestation"}):
        args["evidence"][0] = {"kind": "test_result", "content": "claimed", **claim}
        with pytest.raises(ValueError, match="cannot claim"):
            asyncio.run(dispatch("record_decisions", args, capture, None, None, None))
    assert capture.calls == 0

    args["evidence"][0] = {"kind": "test_result", "origin": "agent_reported"}
    asyncio.run(dispatch("record_decisions", args, capture, None, None, None))
    assert capture.calls == 1
    monkeypatch.delitem(sys.modules, "commitecho.transports.mcp_server", raising=False)
