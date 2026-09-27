"""Package entry point – enables `python -m commitecho`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click


@click.group()
def _entry():
    pass


@click.command("serve")
@click.option(
    "--repo",
    default=".",
    show_default=True,
    help="Path to the Git repository to serve.",
)
def serve(repo: str) -> None:
    """Start the CommitEcho MCP server on stdio for REPO."""
    from commitecho.transports.mcp_server import run_server

    asyncio.run(run_server(Path(repo).resolve()))


if __name__ == "__main__":
    # When invoked as `python -m commitecho serve --repo .`
    # Also supports falling through to the CLI for other sub-commands.
    from commitecho.transports.cli import main as cli_main

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve(standalone_mode=True)
    else:
        cli_main(standalone_mode=True)
