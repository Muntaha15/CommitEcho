"""Integration tests for bounded session indexing hooks and Claude plugin packaging."""

from __future__ import annotations

import json
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from commitecho.transports.cli import hook, plugin, rebuild_index


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="Git executable not available")


@pytest.mark.parametrize("args,expected", [
    (["--help"], "preserve and recall"),
    (["plugin", "--help"], "skills/commitecho/SKILL.md"),
])
def test_redirected_help_cp1252(args, expected):
    result = subprocess.run(
        [sys.executable, "-m", "commitecho", *args], capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"}, timeout=30)
    assert result.returncode == 0, result.stderr.decode("cp1252")
    assert expected in result.stdout.decode("cp1252")
    assert b"Traceback" not in result.stderr


@pytest.fixture
def test_repo(tmp_path: Path):
    """Create a temporary Git repository with multiple commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo), check=True, capture_output=True)

    for i in range(5):
        f = repo / f"file_{i}.txt"
        f.write_text(f"content {i}\n", encoding="utf-8")
        subprocess.run(["git", "add", f.name], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=str(repo), check=True, capture_output=True)

    return repo


class TestBoundedIndex:
    @pytest.mark.parametrize("seconds", ["0", "-1", "nan", "inf", "-inf"])
    def test_invalid_timeout_writes_nothing(self, tmp_path, seconds):
        res = CliRunner().invoke(rebuild_index, ["--repo", str(tmp_path), "--timeout", seconds])
        assert res.exit_code == 2
        assert "finite positive" in res.output
        assert not (tmp_path / ".git").exists()

    def test_timeout_covers_worker_before_git_discovery(self, tmp_path, monkeypatch):
        import commitecho.transports.cli as cli
        original = subprocess.run
        def slow_worker(command, **kwargs):
            assert command[:4] == [sys.executable, "-m", "commitecho", "index"]
            assert "--timeout" not in command
            return original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        monkeypatch.setattr(cli.subprocess, "run", slow_worker)
        started = time.monotonic()
        res = CliRunner().invoke(rebuild_index, ["--repo", str(tmp_path), "--timeout", "0.1"])
        assert res.exit_code == 0
        assert "coverage may be incomplete" in res.output
        assert time.monotonic() - started < 3

    def test_worker_reports_invalid_repo(self, tmp_path):
        res = CliRunner().invoke(rebuild_index, ["--repo", str(tmp_path / "missing"), "--timeout", "10"])
        assert res.exit_code != 0
        assert "Error:" in res.output

    def test_index_quiet(self, test_repo):
        runner = CliRunner()
        res = runner.invoke(rebuild_index, ["--repo", str(test_repo), "--quiet"])
        assert res.exit_code == 0
        assert "Scanning" not in res.output
        assert "Indexed" not in res.output

    def test_index_timeout_stops_gracefully(self, test_repo):
        runner = CliRunner()
        # Set a near-zero timeout to trigger the timeout limit
        res = runner.invoke(rebuild_index, ["--repo", str(test_repo), "--timeout", "0.0000001"])
        assert res.exit_code == 0
        assert "Indexing stopped after reaching timeout" in res.output


class TestClaudeCodeSessionHook:
    @staticmethod
    def generated_settings():
        return {"hooks": {"SessionStart": [{"matcher": "startup|resume", "hooks": [{
            "type": "command", "command": "commitecho",
            "args": ["index", "--timeout", "5.0", "--quiet"],
        }]}]}}

    @pytest.mark.parametrize("foreign_settings", [False, True])
    @pytest.mark.parametrize("combined", [False, True])
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_external_claude_directory_link_preserves_both_targets(
        self, test_repo, tmp_path, directory_link, foreign_settings, combined, dry_run,
    ):
        runner = CliRunner()
        assert runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)]).exit_code == 0
        git_hook = test_repo / ".git" / "hooks" / "commit-msg"
        git_before = git_hook.read_bytes()
        external = tmp_path / "shared-claude"
        external.mkdir()
        settings = self.generated_settings()
        if foreign_settings:
            settings["model"] = "retain"
        settings_file = external / "settings.json"
        settings_file.write_text(json.dumps(settings), encoding="utf-8")
        before = settings_file.read_bytes()
        link = directory_link(test_repo / ".claude", external)
        args = ["uninstall", "--client", "claude_code", "--repo", str(test_repo)]
        result = runner.invoke(hook, args + (["--git"] if combined else []) + (["--dry-run"] if dry_run else []))
        assert result.exit_code == 1, result.output
        assert "outside the repository" in result.output
        assert settings_file.read_bytes() == before
        assert git_hook.read_bytes() == git_before
        assert link.is_dir()

    @pytest.mark.parametrize("invalid", [b"{invalid", b"[]", b"\xff", None])
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_combined_invalid_claude_settings_preserve_git_hook(self, test_repo, invalid, dry_run):
        runner = CliRunner()
        assert runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)]).exit_code == 0
        git_hook = test_repo / ".git" / "hooks" / "commit-msg"
        git_before = git_hook.read_bytes()
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir()
        if invalid is None:
            settings_file.mkdir()
        else:
            settings_file.write_bytes(invalid)
        args = ["uninstall", "--git", "--client", "claude_code", "--repo", str(test_repo)]
        result = runner.invoke(hook, args + (["--dry-run"] if dry_run else []))
        assert result.exit_code == 1, result.output
        assert "settings.json" in result.output
        assert git_hook.read_bytes() == git_before
        if invalid is None:
            assert settings_file.is_dir()
        else:
            assert settings_file.read_bytes() == invalid

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_combined_invalid_claude_parent_preserves_git_hook(self, test_repo, dry_run):
        runner = CliRunner()
        assert runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)]).exit_code == 0
        git_hook = test_repo / ".git" / "hooks" / "commit-msg"
        before = git_hook.read_bytes()
        claude_path = test_repo / ".claude"
        claude_path.write_bytes(b"foreign file")
        args = ["uninstall", "--git", "--client", "claude_code", "--repo", str(test_repo)]
        result = runner.invoke(hook, args + (["--dry-run"] if dry_run else []))
        assert result.exit_code == 1, result.output
        assert "must be a directory" in result.output
        assert git_hook.read_bytes() == before
        assert claude_path.read_bytes() == b"foreign file"

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_combined_external_git_hook_preserves_claude_settings(self, test_repo, tmp_path, dry_run):
        from commitecho.transports.cli import _generate_hook_block

        external = tmp_path / "shared-hooks"
        external.mkdir()
        git_hook = external / "commit-msg"
        git_before = b"#!/bin/sh\n" + _generate_hook_block(False).encode()
        git_hook.write_bytes(git_before)
        subprocess.run(["git", "config", "core.hooksPath", str(external)], cwd=test_repo, check=True)
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir()
        settings_file.write_text(json.dumps(self.generated_settings()), encoding="utf-8")
        before = settings_file.read_bytes()
        args = ["uninstall", "--git", "--client", "claude_code", "--repo", str(test_repo)]
        result = CliRunner().invoke(hook, args + (["--dry-run"] if dry_run else []))
        assert result.exit_code == 1, result.output
        assert "external/global" in result.output
        assert git_hook.read_bytes() == git_before
        assert settings_file.read_bytes() == before

    @pytest.mark.parametrize("unreadable", ["git", "claude"])
    def test_combined_unreadable_target_preserves_both(self, test_repo, monkeypatch, unreadable):
        runner = CliRunner()
        assert runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)]).exit_code == 0
        git_hook = test_repo / ".git" / "hooks" / "commit-msg"
        git_before = git_hook.read_bytes()
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir()
        settings_file.write_text(json.dumps(self.generated_settings()), encoding="utf-8")
        settings_before = settings_file.read_bytes()
        read = Path.read_bytes if unreadable == "git" else Path.read_text
        target = git_hook if unreadable == "git" else settings_file
        def deny_target(path, *args, **kwargs):
            if path == target:
                raise PermissionError(f"Access denied: {path}")
            return read(path, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes" if unreadable == "git" else "read_text", deny_target)
            result = runner.invoke(hook, ["uninstall", "--git", "--client", "claude_code", "--repo", str(test_repo)])
        assert result.exit_code == 1, result.output
        assert "Access denied" in result.output
        assert git_hook.read_bytes() == git_before
        assert settings_file.read_bytes() == settings_before

    @pytest.mark.parametrize("settings_present", [False, True])
    def test_combined_cleanup_dry_run_success_and_repeat(self, test_repo, settings_present):
        runner = CliRunner()
        assert runner.invoke(hook, ["install", "--git", "--repo", str(test_repo)]).exit_code == 0
        git_hook = test_repo / ".git" / "hooks" / "commit-msg"
        before = git_hook.read_bytes()
        settings_file = test_repo / ".claude" / "settings.json"
        if settings_present:
            settings_file.parent.mkdir()
            settings_file.write_text(json.dumps(self.generated_settings()), encoding="utf-8")
        settings_before = settings_file.read_bytes() if settings_present else None
        args = ["uninstall", "--git", "--client", "claude_code", "--repo", str(test_repo)]
        result = runner.invoke(hook, args + ["--dry-run"])
        assert result.exit_code == 0, result.output
        assert git_hook.read_bytes() == before
        assert (settings_file.read_bytes() if settings_file.exists() else None) == settings_before
        result = runner.invoke(hook, args)
        assert result.exit_code == 0, result.output
        assert not git_hook.exists()
        assert not settings_file.exists()
        assert runner.invoke(hook, args).exit_code == 0

    @pytest.mark.parametrize("flags", [[], ["--dry-run"], ["--git"]])
    def test_unqualified_install_preserves_everything(self, test_repo, flags):
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir()
        settings_file.write_text('{"model": "custom"}', encoding="utf-8")
        before = settings_file.read_bytes()
        res = CliRunner().invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo), *flags])
        assert res.exit_code != 0
        assert "not qualified" in res.output
        assert "commitecho index --timeout 5" in res.output
        assert settings_file.read_bytes() == before
        assert not (test_repo / ".git" / "hooks" / "commit-msg").exists()

    @pytest.mark.parametrize("portable", [False, True])
    def test_uninstall_only_generated_handlers(self, test_repo, portable):
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir()
        generated = {
            "type": "command", "command": "commitecho" if portable else Path(sys.executable).as_posix(),
            "args": ([] if portable else ["-m", "commitecho"]) + ["index", "--timeout", "5.0", "--quiet"],
        }
        foreign = {"type": "command", "command": "echo commitecho-status"}
        customized = {**generated, "timeout": 12}
        initial = {"model": "custom", "hooks": {"SessionStart": [
            {"matcher": "startup|resume", "hooks": [generated, foreign, customized]},
            {"matcher": "startup", "hooks": None},
            {"matcher": "custom", "hooks": [generated], "description": "retain this metadata"},
        ]}}
        settings_file.write_text(json.dumps(initial), encoding="utf-8")
        runner = CliRunner()
        command = ["uninstall", "--client", "claude_code", "--repo", str(test_repo)]
        before = settings_file.read_bytes()
        dry = runner.invoke(hook, command + ["--dry-run"])
        assert dry.exit_code == 0
        assert settings_file.read_bytes() == before
        result = runner.invoke(hook, command)
        assert result.exit_code == 0, result.output
        initial["hooks"]["SessionStart"][0]["hooks"] = [foreign, customized]
        initial["hooks"]["SessionStart"][2]["hooks"] = []
        assert json.loads(settings_file.read_text()) == initial
        retained = settings_file.read_bytes()
        repeated = runner.invoke(hook, command)
        assert repeated.exit_code == 0
        assert settings_file.read_bytes() == retained


class TestPluginGenerator:
    @pytest.mark.parametrize("portable", [False, True])
    @pytest.mark.parametrize("old_version,new_version", [
        ("0.1.0", "0.2.0.dev0"),
        ("0.1.1.dev0", "0.2.0.dev0"),
        ("0.2.0.dev0", "0.2.0"),
    ])
    def test_stock_manifest_cross_version_upgrade(self, test_repo, tmp_path, monkeypatch, portable, old_version, new_version):
        runner = CliRunner()
        out = tmp_path / "plugin outside repository"
        args = ["--repo", str(test_repo), "--output-dir", str(out), *(["--portable"] if portable else [])]
        monkeypatch.setattr("importlib.metadata.version", lambda name: old_version)
        assert runner.invoke(plugin, args).exit_code == 0
        manifest = out / ".claude-plugin" / "plugin.json"
        # Keep the existing universal-newline recognition on Windows/POSIX.
        manifest.write_bytes(manifest.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        monkeypatch.setattr("importlib.metadata.version", lambda name: new_version)
        dry = runner.invoke(plugin, args + ["--dry-run"])
        assert dry.exit_code == 0, dry.output
        assert "[update]" in dry.output
        assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == before
        result = runner.invoke(plugin, args)
        assert result.exit_code == 0, result.output
        assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == new_version.replace(".dev", "-dev.")
        after = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        assert all(p == manifest or after[p] == content for p, content in before.items())
        repeated = runner.invoke(plugin, args)
        assert repeated.exit_code == 0, repeated.output
        assert repeated.output.count("[skip]") == 3
        assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == after

    @pytest.mark.parametrize("version", [4, 5])
    @pytest.mark.parametrize("customized", [False, True])
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_stock_skill_upgrade_preserves_custom_content(self, test_repo, monkeypatch, customized, dry_run, version):
        from commitecho.integrations.profiles import SKILL_TEMPLATE

        runner = CliRunner()
        args = ["--repo", str(test_repo)]
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.1.1.dev0")
        assert runner.invoke(plugin, args).exit_code == 0
        out = test_repo / "commitecho-plugin"
        skill = out / "skills" / "commitecho" / "SKILL.md"
        old = (Path(__file__).parents[1] / "fixtures" / f"skill-v{version}.md").read_text(encoding="utf-8")
        skill.write_text(old + ("\nTeam customization.\n" if customized else ""), encoding="utf-8")
        before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.2.0.dev0")
        result = runner.invoke(plugin, args + ["--portable"] + (["--dry-run"] if dry_run else []))
        assert (result.exit_code == 0) == (not customized), result.output
        if customized or dry_run:
            assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == before
        else:
            assert skill.read_text(encoding="utf-8") == SKILL_TEMPLATE
            assert json.loads((out / ".claude-plugin" / "plugin.json").read_text())["version"] == "0.2.0-dev.0"

    @pytest.mark.parametrize("mutation", [
        {"version": None}, {"version": 1}, {"version": ""}, {"version": "0.1"},
        {"version": "01.1.0"}, {"version": "0.1.1.dev0"}, {"version": "0.1.1-dev.01"},
        {"version": "0.1.1-rc.1"}, {"version": "0.1.1+custom"}, {"name": "foreign"},
        {"description": "Team description"}, {"author": {"name": "Custom author"}},
        {"homepage": "https://example.com"}, {"repository": "https://example.com"},
        {"extra": True}, "missing-version", "formatting", "missing-newline",
    ])
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_manifest_upgrade_preserves_custom_metadata(self, test_repo, monkeypatch, mutation, dry_run):
        runner = CliRunner()
        args = ["--repo", str(test_repo)]
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.1.1.dev0")
        assert runner.invoke(plugin, args).exit_code == 0
        out = test_repo / "commitecho-plugin"
        manifest = out / ".claude-plugin" / "plugin.json"
        content = manifest.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(mutation, dict):
            data.update(mutation)
            content = json.dumps(data, indent=2) + "\n"
        elif mutation == "missing-version":
            del data["version"]
            content = json.dumps(data, indent=2) + "\n"
        elif mutation == "formatting":
            content = json.dumps(data) + "\n"
        else:
            content = content.rstrip("\n")
        manifest.write_text(content, encoding="utf-8")
        (out / ".mcp.json").unlink()
        before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.2.0.dev0")
        result = runner.invoke(plugin, args + (["--dry-run"] if dry_run else []))
        assert result.exit_code != 0, result.output
        assert "Preserving all files" in result.output
        assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == before

    @pytest.mark.parametrize("asset", [".claude-plugin/plugin.json", ".mcp.json", "skills/commitecho/SKILL.md"])
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_custom_asset_preflight_preserves_all_files(self, test_repo, monkeypatch, asset, dry_run):
        runner = CliRunner()
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.1.1.dev0")
        assert runner.invoke(plugin, ["--repo", str(test_repo)]).exit_code == 0
        out = test_repo / "commitecho-plugin"
        (out / asset).write_text("customized content", encoding="utf-8")
        # A missing earlier asset must not be written before discovering a later conflict.
        if asset == "skills/commitecho/SKILL.md":
            (out / ".mcp.json").unlink()
        before = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.2.0.dev0")
        res = runner.invoke(plugin, ["--repo", str(test_repo), "--portable", *(["--dry-run"] if dry_run else [])])
        assert res.exit_code != 0
        after = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        assert after == before

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_upgrade_preserves_different_local_runtime(self, test_repo, monkeypatch, dry_run):
        runner = CliRunner()
        args = ["--repo", str(test_repo)]
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.1.1.dev0")
        assert runner.invoke(plugin, args).exit_code == 0
        out = test_repo / "commitecho-plugin"
        mcp = out / ".mcp.json"
        data = json.loads(mcp.read_text(encoding="utf-8"))
        data["mcpServers"]["commitecho"]["command"] = "/another/runtime/python"
        mcp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        monkeypatch.setattr("importlib.metadata.version", lambda name: "0.2.0.dev0")
        result = runner.invoke(plugin, args + (["--dry-run"] if dry_run else []))
        assert result.exit_code != 0, result.output
        assert "choose an empty output directory" in result.output
        assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == before

    def test_foreign_plugin_manifest_is_preserved(self, test_repo):
        out = test_repo / "commitecho-plugin"
        (out / ".claude-plugin").mkdir(parents=True)
        manifest = out / ".claude-plugin" / "plugin.json"
        manifest.write_text('{"name":"foreign-plugin"}', encoding="utf-8")
        res = CliRunner().invoke(plugin, ["--repo", str(test_repo)])
        assert res.exit_code != 0
        assert manifest.read_text() == '{"name":"foreign-plugin"}'
        assert not (out / ".mcp.json").exists()

    def test_invalid_asset_parent_preflight_writes_nothing(self, test_repo):
        runner = CliRunner()
        assert runner.invoke(plugin, ["--repo", str(test_repo)]).exit_code == 0
        out = test_repo / "commitecho-plugin"
        skill_dir = out / "skills" / "commitecho"
        (skill_dir / "SKILL.md").unlink()
        skill_dir.rmdir()
        skill_dir.write_text("custom file", encoding="utf-8")
        (out / ".mcp.json").unlink()
        res = runner.invoke(plugin, ["--repo", str(test_repo)])
        assert res.exit_code != 0
        assert "Expected a directory" in res.output
        assert not (out / ".mcp.json").exists()
        assert skill_dir.read_text() == "custom file"

    def test_regeneration_is_idempotent_and_skill_is_canonical(self, test_repo):
        from commitecho.integrations.profiles import SKILL_TEMPLATE
        runner = CliRunner()
        args = ["--repo", str(test_repo)]
        assert runner.invoke(plugin, args).exit_code == 0
        repeated = runner.invoke(plugin, args)
        assert repeated.exit_code == 0
        assert repeated.output.count("[skip]") == 3
        assert (test_repo / "commitecho-plugin" / "skills" / "commitecho" / "SKILL.md").read_text(encoding="utf-8") == SKILL_TEMPLATE

    @pytest.mark.parametrize("portable", [False, True])
    def test_generated_plugin_mcp_launch_from_unrelated_cwd(self, test_repo, tmp_path, portable, monkeypatch):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from commitecho.git.adapter import GitAdapter
        result = CliRunner().invoke(plugin, ["--repo", str(test_repo), *(["--portable"] if portable else [])])
        assert result.exit_code == 0, result.output
        entry = json.loads((test_repo / "commitecho-plugin" / ".mcp.json").read_text())["mcpServers"]["commitecho"]
        unrelated = tmp_path / "unrelated cwd"
        unrelated.mkdir()
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("COMMITECHO_REPO", None)
        env["CLAUDE_PROJECT_DIR"] = str(test_repo)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        monkeypatch.setenv("PATH", env["PATH"])
        params = StdioServerParameters(command=entry["command"], args=entry["args"], env=env, cwd=str(unrelated))
        async def handshake():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=10)
                    tools = await asyncio.wait_for(session.list_tools(), timeout=10)
                    status = await asyncio.wait_for(session.call_tool("get_status", {}), timeout=10)
                    assert not status.is_error
                    return {tool.name for tool in tools.tools}, json.loads(status.content[0].text)
        tools, status = asyncio.run(handshake())
        assert tools == {"begin_change", "record_decisions", "prepare_commit", "verify_commit", "search_history", "get_evidence", "compare_history", "get_status"}
        assert status["worktree"] == GitAdapter.from_path(test_repo).repo_info.worktree_id
        assert not (unrelated / ".commitecho").exists()

    @pytest.mark.parametrize("package_version,plugin_version", [
        ("0.1.0", "0.1.0"),
        ("0.1.1.dev0", "0.1.1-dev.0"),
    ])
    def test_generate_default_plugin(self, test_repo, monkeypatch, package_version, plugin_version):
        monkeypatch.setattr("importlib.metadata.version", lambda name: package_version)
        runner = CliRunner()
        res = runner.invoke(plugin, ["--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "Plugin generated successfully." in res.output

        plugin_dir = test_repo / "commitecho-plugin"
        manifest = plugin_dir / ".claude-plugin" / "plugin.json"
        mcp_conf = plugin_dir / ".mcp.json"
        skill = plugin_dir / "skills" / "commitecho" / "SKILL.md"

        assert manifest.exists()
        assert mcp_conf.exists()
        assert skill.exists()

        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["name"] == "commitecho"
        assert data["version"] == plugin_version

    def test_generate_plugin_custom_output_dir(self, test_repo, tmp_path):
        custom_out = tmp_path / "my-custom-plugin"
        runner = CliRunner()
        res = runner.invoke(plugin, ["--repo", str(test_repo), "--output-dir", str(custom_out)])
        assert res.exit_code == 0
        assert (custom_out / ".claude-plugin" / "plugin.json").exists()

    def test_generate_plugin_portable(self, test_repo, tmp_path):
        out = tmp_path / "portable-plugin"
        runner = CliRunner()
        res = runner.invoke(plugin, ["--repo", str(test_repo), "--output-dir", str(out), "--portable"])
        assert res.exit_code == 0

        mcp_data = json.loads((out / ".mcp.json").read_text(encoding="utf-8"))
        srv = mcp_data["mcpServers"]["commitecho"]
        assert srv["command"] == "commitecho"
        assert srv["args"] == ["serve"]

    def test_generate_plugin_dry_run(self, test_repo, tmp_path):
        out = tmp_path / "dry-plugin"
        runner = CliRunner()
        res = runner.invoke(plugin, ["--repo", str(test_repo), "--output-dir", str(out), "--dry-run"])
        assert res.exit_code == 0
        assert "(dry-run: no files were written)" in res.output
        assert not out.exists()

    def test_generate_plugin_refuses_unrelated_nonempty_dir(self, test_repo, tmp_path):
        unrelated = tmp_path / "unrelated_dir"
        unrelated.mkdir()
        (unrelated / "important_file.txt").write_text("critical data", encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(plugin, ["--repo", str(test_repo), "--output-dir", str(unrelated)])
        assert res.exit_code != 0
        assert "is not a CommitEcho plugin directory" in res.output
