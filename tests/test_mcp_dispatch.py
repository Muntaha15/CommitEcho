"""Actual low-level MCP call dispatch, including the wire error flag."""

import asyncio
import json
import os
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path
from uuid import uuid4

import pytest

from mcp.client import Client

from commitecho.transports import mcp_server


@pytest.mark.parametrize("alternate_environment", [False, True])
def test_plugin_status_identifies_index_runtime(tmp_path, alternate_environment):
    """A plugin server supplies runnable indexing argv even with another venv nearby."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = tmp_path / "project with spaces"
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    executable = sys.executable
    if alternate_environment:
        environment = tmp_path / "other runtime with spaces"
        venv.EnvBuilder(with_pip=False).create(environment)
        executable = str(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        # Reuse installed dependencies offline; the process still has its own venv runtime.
        libraries = environment / ("Lib/site-packages" if os.name == "nt" else
                                   f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
        (libraries / "test-dependencies.pth").write_text(
            f"import site; site.addsitedir({sysconfig.get_path('purelib')!r})\n"
            + str(Path(__file__).resolve().parents[1] / "src") + "\n",
            encoding="utf-8")
    plugin_dir = tmp_path / "generated plugin"
    subprocess.run([executable, "-m", "commitecho", "plugin", "--repo", str(repo),
                    "--output-dir", str(plugin_dir)], capture_output=True, check=True)
    entry = json.loads((plugin_dir / ".mcp.json").read_text())["mcpServers"]["commitecho"]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    env.pop("COMMITECHO_REPO", None)
    env.pop("PYTHONPATH", None)

    async def check():
        params = StdioServerParameters(**entry, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 10)
                result = await asyncio.wait_for(session.call_tool("get_status", {}), 10)
                assert not result.is_error, result.content
                runtime = json.loads(result.content[0].text)["runtime"]
                assert Path(runtime["python_executable"]).absolute() == Path(executable).absolute()
                assert runtime["index_argv"] == [runtime["python_executable"], "-m", "commitecho",
                                                 "index", "--repo", str(repo.resolve())]
                indexed = subprocess.run(runtime["index_argv"], cwd=tmp_path, env=env,
                                         capture_output=True, text=True, timeout=30)
                assert indexed.returncode == 0, indexed.stderr
    asyncio.run(check())


@pytest.mark.parametrize("partial_commit", [False, True])
def test_stdio_resumed_decisions_reach_git_only_clone(tmp_path, partial_commit):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = tmp_path / "resumed work with spaces"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "CommitEcho Test")
    git("config", "user.email", "test@commitecho.test")
    (repo / "helper.py").write_text("# initial\n", encoding="utf-8")
    git("add", "helper.py")
    git("commit", "-m", "initial")
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "commitecho", "serve", "--repo", str(repo)])

    async def call(session, name, **args):
        result = await asyncio.wait_for(session.call_tool(name, args), 10)
        assert not result.is_error, result.content
        return json.loads(result.content[0].text)

    async def record(session, change, choice, client):
        evidence_id = str(uuid4())
        result = await call(session, "record_decisions", change_id=change["change_id"],
                            expected_revision=change["revision_counter"], operation_id=str(uuid4()),
                            decisions=[{"problem": "Preserve decisions across restart", "choice": choice,
                                        "rationale": "Keep the recorded explanation", "disposition": "selected",
                                        "code_scope": {"paths": ["helper.py"]},
                                        "alternatives": [{"choice": "Discard prior context", "reason": "Earlier rationale is needed",
                                                          "evidence_ids": [evidence_id]}]}],
                            evidence=[{"evidence_id": evidence_id, "kind": "discussion_summary",
                                       "origin": "agent_reported", "client": client, "content": choice}])
        return result, evidence_id

    async def commit(session, change_id, counter, revisions, content):
        (repo / "helper.py").write_text(content, encoding="utf-8")
        git("add", "helper.py")
        prepared = await call(session, "prepare_commit", change_id=change_id, expected_revision=counter,
                              selected_revision_ids=revisions, summary="Preserve recorded rationale",
                              operation_id=str(uuid4()))
        git("add", prepared["record_path"])
        git("commit", "-m", "Preserve rationale\n\n" + prepared["trailer"])
        verified = await call(session, "verify_commit", commit_oid=git("rev-parse", "HEAD"))
        assert verified["outcome"] == "exact", verified
        return prepared, verified

    async def check():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 10)
                change = await call(session, "begin_change", title="first session", client="codex",
                                    operation_id=str(uuid4()))
                first, first_evidence = await record(session, change, "Original implementation", "codex")
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 10)
                resumed = await call(session, "begin_change", title="review session", client="claude_code",
                                     prior_change_id=change["change_id"], operation_id=str(uuid4()))
                assert resumed["unpublished_revision_ids"] == first["revision_ids"]
                assert resumed["decision_revisions"][0]["choice"] == "Original implementation"
                second, second_evidence = await record(session, resumed, "Review decision", "claude_code")
                selected = second["revision_ids"] if partial_commit else first["revision_ids"] + second["revision_ids"]
                prepared, verified = await commit(session, change["change_id"], second["revision_counter"],
                                                   selected, "# first commit\n")
                assert prepared["omitted_revision_ids"] == (first["revision_ids"] if partial_commit else [])
                status = await call(session, "get_status", change_id=change["change_id"])
                if partial_commit:
                    assert status["open_changes"][0]["unpublished_revision_ids"] == first["revision_ids"]
                else:
                    assert status["open_changes"] == []
        if partial_commit:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), 10)
                    status = await call(session, "get_status", change_id=change["change_id"])
                    remaining = status["open_changes"][0]
                    await commit(session, change["change_id"], remaining["revision_counter"],
                                 remaining["unpublished_revision_ids"], "# remaining explanation\n")
                    assert (await call(session, "get_status", change_id=change["change_id"]))["open_changes"] == []
        clone = tmp_path / "git only clone"
        git("clone", str(repo), str(clone))
        clone_params = StdioServerParameters(command=sys.executable,
                                            args=["-m", "commitecho", "serve", "--repo", str(clone)])
        async with stdio_client(clone_params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 10)
                status = await call(session, "get_status")
                subprocess.run(status["runtime"]["index_argv"], check=True, capture_output=True)
                history = await call(session, "search_history", path="helper.py")
                assert history["coverage"] == "full"
                assert {r["revision_id"] for r in history["results"]} == set(first["revision_ids"] + second["revision_ids"])
                for evidence_id, client in [(first_evidence, "codex"), (second_evidence, "claude_code")]:
                    evidence = await call(session, "get_evidence", evidence_id=evidence_id)
                    assert evidence["source"] == "index" and evidence["client"] == client
                    assert evidence["origin"] == "agent_reported"
                for record_id in {r["record_id"] for r in history["results"]}:
                    recalled = await call(session, "get_evidence", record_id=record_id)
                    assert recalled["source"] == "index"
                    assert all(d["alternatives"][0]["reason"] == "Earlier rationale is needed"
                               for d in recalled["record"]["decisions"])
    asyncio.run(check())


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
