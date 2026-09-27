"""Unit tests for CommitEcho domain models."""

from __future__ import annotations

import pytest
from commitecho.domain.models import (
    Alternative,
    Binding,
    BindingOutcome,
    Change,
    ChangeStatus,
    CodeScope,
    CommitRecord,
    DecisionDisposition,
    DecisionRevision,
    Evidence,
    EvidenceKind,
    EvidenceOrigin,
    PreparedFor,
    Repository,
    Session,
)


class TestDecisionRevision:
    def test_immutable(self):
        rev = DecisionRevision(
            problem="p", choice="c", rationale="r"
        )
        with pytest.raises(Exception):
            rev.problem = "x"  # type: ignore[misc]

    def test_defaults(self):
        rev = DecisionRevision(problem="p", choice="c", rationale="r")
        assert rev.disposition == DecisionDisposition.PROPOSED
        assert rev.alternatives == []
        assert rev.evidence_ids == []

    def test_alternative(self):
        alt = Alternative(
            choice="filename dedup",
            disposition=DecisionDisposition.REJECTED,
            reason="renames bypass it",
        )
        rev = DecisionRevision(
            problem="duplicate uploads",
            choice="content hash dedup",
            rationale="same content = one job",
            alternatives=[alt],
        )
        assert rev.alternatives[0].disposition == DecisionDisposition.REJECTED


class TestEvidence:
    def test_content_size_limit(self):
        with pytest.raises(ValueError, match="64 KiB"):
            Evidence(
                kind=EvidenceKind.DISCUSSION_SUMMARY,
                origin=EvidenceOrigin.AGENT_REPORTED,
                content="x" * 70_000,
            )

    def test_valid_evidence(self):
        ev = Evidence(
            kind=EvidenceKind.TEST_RESULT,
            origin=EvidenceOrigin.INDEPENDENT_ARTIFACT,
            content="tests passed",
        )
        assert ev.origin == EvidenceOrigin.INDEPENDENT_ARTIFACT


class TestCommitRecord:
    def test_trailer(self):
        record = CommitRecord(
            record_id="3ef6b6f8-a1de-4b82-bb32-6356df4daa51",
            change_id="some-change",
            summary="prevent dup uploads",
            prepared_for=PreparedFor(
                parent_oid="a" * 40,
                code_manifest_sha256="b" * 64,
            ),
        )
        assert record.trailer() == "CommitEcho-Record: 3ef6b6f8-a1de-4b82-bb32-6356df4daa51"

    def test_record_path(self):
        record = CommitRecord(
            record_id="3ef6b6f8-a1de-4b82-bb32-6356df4daa51",
            change_id="some-change",
            summary="s",
            prepared_for=PreparedFor(
                parent_oid="a" * 40,
                code_manifest_sha256="b" * 64,
            ),
        )
        assert record.record_path() == ".commitecho/records/3ef6b6f8-a1de-4b82-bb32-6356df4daa51.json"


class TestChange:
    def test_mutable(self):
        c = Change(title="add feature", worktree_id="main")
        c.status = ChangeStatus.PREPARED
        assert c.status == ChangeStatus.PREPARED
