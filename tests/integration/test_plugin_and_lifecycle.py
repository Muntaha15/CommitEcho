"""Integration tests for bounded session indexing hooks and Claude plugin packaging."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from commitecho.transports.cli import hook, main, plugin, rebuild_index


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="Git executable not available")


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
    def test_install_claude_hook(self, test_repo):
        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[add]" in res.output

        settings_file = test_repo / ".claude" / "settings.json"
        assert settings_file.exists()
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "hooks" in data
        assert "SessionStart" in data["hooks"]
        assert len(data["hooks"]["SessionStart"]) == 1
        entry = data["hooks"]["SessionStart"][0]
        assert entry["matcher"] == "startup|resume"
        sub = entry["hooks"][0]
        assert "commitecho" in (sub["command"] + " " + " ".join(sub["args"]))

    def test_install_claude_hook_idempotent(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo)])
        res = runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[skip]" in res.output
        assert "already up to date" in res.output

    def test_install_claude_hook_update_timeout(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo), "--timeout", "5.0"])
        res = runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo), "--timeout", "10.0"])
        assert res.exit_code == 0
        assert "[update]" in res.output

        settings_file = test_repo / ".claude" / "settings.json"
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        sub = data["hooks"]["SessionStart"][0]["hooks"][0]
        assert "10.0" in sub["args"]

    def test_install_claude_hook_preserves_foreign_settings(self, test_repo):
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        initial = {
            "model": "claude-3-5-sonnet",
            "hooks": {
                "UserPrompt": [{"matcher": ".*", "hooks": [{"type": "command", "command": "echo"}]}]
            }
        }
        settings_file.write_text(json.dumps(initial, indent=2), encoding="utf-8")

        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo)])
        assert res.exit_code == 0

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["model"] == "claude-3-5-sonnet"
        assert "UserPrompt" in data["hooks"]
        assert "SessionStart" in data["hooks"]

    def test_install_claude_hook_dry_run(self, test_repo):
        runner = CliRunner()
        res = runner.invoke(hook, ["install", "--client", "claude_code", "--dry-run", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "(dry-run: no files were written)" in res.output
        assert not (test_repo / ".claude" / "settings.json").exists()

    def test_uninstall_claude_hook_empty_removes_file(self, test_repo):
        runner = CliRunner()
        runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo)])
        settings_file = test_repo / ".claude" / "settings.json"
        assert settings_file.exists()

        res = runner.invoke(hook, ["uninstall", "--client", "claude_code", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[remove]" in res.output
        assert not settings_file.exists()

    def test_uninstall_claude_hook_preserves_other_settings(self, test_repo):
        settings_file = test_repo / ".claude" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        initial = {"model": "claude-3-opus"}
        settings_file.write_text(json.dumps(initial), encoding="utf-8")

        runner = CliRunner()
        runner.invoke(hook, ["install", "--client", "claude_code", "--repo", str(test_repo)])
        res = runner.invoke(hook, ["uninstall", "--client", "claude_code", "--repo", str(test_repo)])
        assert res.exit_code == 0
        assert "[update]" in res.output
        assert settings_file.exists()
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data == {"model": "claude-3-opus"}


class TestPluginGenerator:
    def test_generate_default_plugin(self, test_repo):
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
        assert "version" in data

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
