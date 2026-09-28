"""MCP callers must not assign trusted provenance to their own evidence."""

import asyncio

import pytest

from commitecho.transports.mcp_server import _dispatch


def test_mcp_caller_cannot_self_assert_provenance():
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
            asyncio.run(_dispatch("record_decisions", args, capture, None, None, None))
    assert capture.calls == 0

    args["evidence"][0] = {"kind": "test_result", "origin": "agent_reported"}
    asyncio.run(_dispatch("record_decisions", args, capture, None, None, None))
    assert capture.calls == 1
