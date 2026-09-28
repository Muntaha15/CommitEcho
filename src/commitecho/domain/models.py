"""Core domain entities for CommitEcho.

These are immutable value objects and plain data containers.  No persistence
or Git logic lives here – only the essential fields defined by the architecture.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DecisionDisposition(str, Enum):
    """Lifecycle state of a decision."""

    PROPOSED = "proposed"
    SELECTED = "selected"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class EvidenceKind(str, Enum):
    """Category of an evidence item."""

    DISCUSSION_SUMMARY = "discussion_summary"
    TEST_RESULT = "test_result"
    CODE_OBSERVATION = "code_observation"
    DEVELOPER_ATTESTATION = "developer_attestation"
    SOURCE_EXCERPT = "source_excerpt"
    EXTERNAL_ARTIFACT = "external_artifact"


class EvidenceOrigin(str, Enum):
    """How an evidence item was obtained or verified."""

    AGENT_REPORTED = "agent_reported"
    DEVELOPER_CONFIRMED = "developer_confirmed"
    SOURCE_ADAPTER = "source_adapter"
    INDEPENDENT_ARTIFACT = "independent_artifact"


class ChangeStatus(str, Enum):
    """Lifecycle state of a Change."""

    OPEN = "open"
    PREPARED = "prepared"
    COMMITTED = "committed"
    ABANDONED = "abandoned"


class BindingOutcome(str, Enum):
    """Result of linking a CommitRecord to an actual Git commit."""

    EXACT = "exact"
    DECLARED_CHANGED = "declared_changed"
    CONTAINED_ONLY = "contained_only"
    UNVERIFIABLE = "unverifiable"
    INVALID = "invalid"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Repository(BaseModel):
    """Local installation identity for a Git repository."""

    installation_id: str = Field(default_factory=_new_uuid)
    common_dir: str  # absolute path to the Git common directory
    portable_project_id: str | None = None  # optional cross-machine identifier

    model_config = {"frozen": True}


class Session(BaseModel):
    """A single client session contributing to one or more Changes."""

    session_id: str = Field(default_factory=_new_uuid)
    client: str  # e.g. "codex", "antigravity", "copilot_vscode"
    client_version: str | None = None
    native_session_id: str | None = None  # opaque; client-supplied
    worktree_id: str  # repository-relative worktree identifier
    created_at: datetime = Field(default_factory=_now)

    model_config = {"frozen": True}


class Change(BaseModel):
    """Unit of ongoing work that may result in several commits."""

    change_id: str = Field(default_factory=_new_uuid)
    title: str
    status: ChangeStatus = ChangeStatus.OPEN
    worktree_id: str
    starting_revision: str | None = None  # HEAD OID when change was opened
    contributing_session_ids: list[str] = Field(default_factory=list)
    revision_counter: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    model_config = {"frozen": False}


class Evidence(BaseModel):
    """A single piece of supporting material for a decision statement."""

    evidence_id: str = Field(default_factory=_new_uuid)
    kind: EvidenceKind
    origin: EvidenceOrigin
    content: str | None = None  # inline text
    locator: str | None = None  # URI / path for external artifacts
    client: str | None = None
    observed_at: datetime = Field(default_factory=_now)
    verification_method: str | None = None
    max_content_bytes: ClassVar[int] = 4096

    model_config = {"frozen": True}

    @field_validator("content")
    @classmethod
    def _cap_content(cls, v: str | None) -> str | None:
        if v is not None and len(v.encode("utf-8")) > cls.max_content_bytes:
            raise ValueError("Evidence content exceeds 4 KiB limit")
        return v


class Alternative(BaseModel):
    """A considered-but-not-chosen approach within a decision."""

    choice: str
    disposition: DecisionDisposition
    reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class CodeScope(BaseModel):
    """File/line scope for a decision statement (not causal proof)."""

    paths: list[str] = Field(default_factory=list)
    base_blob_oid: str | None = None
    line_ranges: list[tuple[int, int]] | None = None  # [(start, end), ...]
    symbol_label: str | None = None  # agent-supplied hint, not guaranteed

    model_config = {"frozen": True}


class DecisionRevision(BaseModel):
    """One immutable revision of a decision record."""

    decision_id: str = Field(default_factory=_new_uuid)
    revision_id: str = Field(default_factory=_new_uuid)
    predecessor_revision_ids: list[str] = Field(default_factory=list)
    disposition: DecisionDisposition = DecisionDisposition.PROPOSED
    problem: str
    choice: str
    rationale: str
    alternatives: list[Alternative] = Field(default_factory=list)
    code_scope: CodeScope = Field(default_factory=CodeScope)
    evidence_ids: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=_now)

    model_config = {"frozen": True}


class CommitRecord(BaseModel):
    """Portable snapshot prepared for one code commit, written to .commitecho/records/."""

    schema_version: int = 1
    record_id: str = Field(default_factory=_new_uuid)
    change_id: str
    summary: str
    prepared_for: PreparedFor
    decisions: list[DecisionRevision] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    model_config = {"frozen": True}

    def trailer(self) -> str:
        """Return the Git commit trailer line for this record."""
        return f"CommitEcho-Record: {self.record_id}"

    def record_path(self) -> str:
        """Repository-relative path where this record should be written."""
        return f".commitecho/records/{self.record_id}.json"


class PreparedFor(BaseModel):
    """Fingerprint of the staged change this record was prepared against."""

    parent_oid: str  # full SHA; use explicit root-commit marker for root commits
    object_format: str = "sha1"  # "sha1" | "sha256"
    manifest_version: int = 1
    code_manifest_sha256: str  # hex digest

    model_config = {"frozen": True}


# Fix forward reference
CommitRecord.model_rebuild()


class Binding(BaseModel):
    """Result of linking a CommitRecord to an actual Git commit."""

    binding_id: str = Field(default_factory=_new_uuid)
    record_id: str
    commit_oid: str  # full OID
    outcome: BindingOutcome
    validation_details: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=_now)

    model_config = {"frozen": True}
