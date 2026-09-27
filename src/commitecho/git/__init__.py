"""Git adapter for CommitEcho – repository discovery, object reads, HEAD resolution."""

from commitecho.git.adapter import (
    GitAdapter,
    GitError,
    discover_repository,
    resolve_ref,
)

__all__ = [
    "GitAdapter",
    "GitError",
    "discover_repository",
    "resolve_ref",
]
