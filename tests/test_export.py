"""Draft export is a readable snapshot with linked material."""

import json
import subprocess

from click.testing import CliRunner

from commitecho.application.capture import CaptureService
from commitecho.git.adapter import GitAdapter
from commitecho.storage.db import open_drafts_db
from commitecho.transports.cli import main


def test_export_contains_parsed_links(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    git = GitAdapter.from_path(tmp_path)
    capture = CaptureService(open_drafts_db(git.repo_info.common_dir), git)
    change_id = capture.begin_change(title="export", client="test", operation_id="begin")["change_id"]
    first = capture.record_decisions(
        change_id=change_id, expected_revision=0, operation_id="first",
        decisions=[{"problem": "p", "choice": "a", "rationale": "r"}],
    )["revision_ids"][0]
    evidence_id = "evidence-1"
    capture.record_decisions(
        change_id=change_id, expected_revision=1, operation_id="second",
        evidence=[{"evidence_id": evidence_id, "kind": "test_result", "content": "passed"}],
        decisions=[{"problem": "p", "choice": "b", "rationale": "r",
                    "predecessor_revision_ids": [first], "evidence_ids": [evidence_id]}],
    )
    result = CliRunner().invoke(main, ["export", change_id, "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["format"] == "commitecho-draft-snapshot-v1"
    assert data["decisions"][1]["predecessor_revision_ids"] == [first]
    assert data["decisions"][1]["evidence_ids"] == [evidence_id]
    assert data["evidence"][0]["evidence_id"] == evidence_id
    assert isinstance(data["decisions"][1]["code_scope"], dict)
