# CommitEcho development

Use the project's Python environment for commands:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest -q
```

The test suite includes real MCP stdio handshakes, not just in-process tool
calls. Run the full suite before considering a transport or setup change ready.

## Codex cloud command permissions

Run live MCP tests, the MCP server, and Git remote operations with network access
enabled for the shell command. With the Codex `exec_command` tool, use:

```json
{
  "sandbox_permissions": "with_additional_permissions",
  "additional_permissions": {"network": {"enabled": true}}
}
```

This permission is also required for local socket sends in the current command
sandbox. Python's asyncio event loop uses a local socket to wake up after AnyIO
reads stdin in a worker thread. Denying that send can make a healthy stdio MCP
server time out during initialization. Increasing the handshake timeout or
skipping live tests does not fix the blocked wake-up.

Keep the cloud's outbound destination policy, proxy settings, and TLS
verification in place. Command network access does not override those controls.

## Local client setup

```bash
.venv/bin/python -m commitecho setup --client codex
.venv/bin/python -m commitecho doctor
```

Generated `.codex/config.toml` contains absolute paths for this checkout. Keep
machine-specific client configuration local. Codex must load the configuration
in a trusted project before automatically exposing its MCP tools; generating
the file does not attach tools to an already-running chat.

## Git workflow

Inspect the working tree and stage intended files explicitly. Keep private
CommitEcho databases, credentials, and machine-specific configuration out of
commits. Use the configured `origin` remote and check remote access with:

```bash
git ls-remote origin HEAD
```

When a push is requested, push the intended branch normally. Do not force-push
or modify shared branches unless the user authorizes it. A push dry run checks
remote access without publishing a branch, but branch rules may still affect
an actual push.
