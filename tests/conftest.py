"""Shared filesystem fixtures for ownership boundary regressions."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def directory_link():
    """Create real directory links without requiring Windows symlink privilege."""
    links = []

    def create(link: Path, target: Path) -> Path:
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            env = os.environ.copy()
            env["COMMITECHO_TEST_LINK"] = str(link)
            env["COMMITECHO_TEST_TARGET"] = str(target)
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 "$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
                 "-Path $env:COMMITECHO_TEST_LINK -Target $env:COMMITECHO_TEST_TARGET | Out-Null"],
                env=env, check=True, capture_output=True, text=True,
            )
            assert link.is_junction()
        else:
            link.symlink_to(target, target_is_directory=True)
            assert link.is_symlink()
        links.append(link)
        assert link.resolve() == target.resolve()
        return link

    yield create
    for link in reversed(links):
        if os.name == "nt":
            if link.is_junction():
                link.rmdir()  # Remove the junction itself, never recurse into its target.
        elif link.is_symlink():
            link.unlink()
