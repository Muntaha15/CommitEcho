"""Evaluation fixtures – capture/recall tasks with expected evidence.

These definitions are keyed to the fixture repos built by
``tests/fixtures/build_fixtures.py``.  Each scenario dict describes:

  id:               unique scenario identifier
  description:      what the scenario tests
  expected_decisions: list of (problem, choice) tuples that MUST appear in
                    recall results after the fixture commit is indexed
  expected_gaps:    list of questions whose answer must NOT invent rationale
                    (search_history returns empty or coverage_notes indicate
                    no record was found)
  fixture_repo:     name of the repo under tests/fixtures/repos/
  gap_query:        optional question to fire at search_history for gap test
"""

from __future__ import annotations

# Each eval scenario is a dict with:
#   id:               unique scenario identifier
#   description:      what the scenario tests
#   expected_decisions: list of (problem, choice) tuples that must appear in recall
#   expected_gaps:    list of questions whose reason is expected to be "not recorded"

EVAL_SCENARIOS: list[dict] = [
    {
        "id": "chosen_and_rejected",
        "description": "Chosen approach and rejected alternative are both recallable.",
        "fixture_repo": "chosen_and_rejected",
        "expected_decisions": [
            ("duplicate uploads on retry", "content hash deduplication"),
        ],
        "expected_gaps": [],
        "gap_query": None,
        "linkage_check": "exact",   # verify_commit must return "exact"
    },
    {
        "id": "later_reversal",
        "description": "A decision recorded at commit A is superseded by a new decision at commit B; "
                       "both are recallable and the newer choice is returned first.",
        "fixture_repo": "later_reversal",
        "expected_decisions": [
            ("rapid input generates too many API calls", "debounce at 300 ms"),
            ("rapid input generates too many API calls", "reduce debounce to 150 ms after profiling"),
        ],
        "expected_gaps": [],
        "gap_query": None,
        "linkage_check": "exact",
    },
    {
        "id": "branch_conflict",
        "description": "Two branches have incompatible decisions; compare_history surfaces both. "
                       "Each decision is reachable only from its own branch HEAD.",
        "fixture_repo": "branch_conflict",
        # Each tuple: (problem_substr, choice_substr, commit_key_in_manifest)
        # For branch_conflict, recall is checked per-branch using at_ref.
        "expected_decisions": [],  # checked via branch-scoped expected_branch_decisions
        "expected_branch_decisions": [
            ("which backend to use for the async job queue", "PostgreSQL SKIP LOCKED", "main_commit_oid"),
            ("which backend to use for the async job queue", "Redis Streams", "branch_commit_oid"),
        ],
        "expected_gaps": [],
        "gap_query": None,
        "linkage_check": "exact",
        # The conflict is detected by verifying both decisions share a decision_id in the index.
        "conflict_check": True,
    },
    {
        "id": "partial_staging",
        "description": "Only staged paths are covered; unstaged paths are flagged as uncovered.",
        "fixture_repo": "partial_staging",
        "expected_decisions": [
            ("API endpoint hit too frequently by bots", "token bucket rate limiter at 100 req/min"),
        ],
        "expected_gaps": [],
        "gap_query": None,
        "linkage_check": "exact",
        # uncovered_paths in the prepare result must not be empty
        "uncovered_paths_nonempty": True,
    },
    {
        "id": "stale_preparation",
        "description": "Index changed after prepare_commit; record is not labeled exact.",
        "fixture_repo": "stale_preparation",
        "expected_decisions": [
            ("repeated DB reads for hot keys slow response time", "in-process LRU cache with 60 s TTL"),
        ],
        "expected_gaps": [],
        "gap_query": None,
        # Extra file was added after prepare; verify must NOT return "exact"
        "linkage_check": "declared_changed",
    },
    {
        "id": "never_recorded",
        "description": "A question whose rationale was never captured returns no results, not invented.",
        "fixture_repo": "never_recorded",
        "expected_decisions": [],
        "expected_gaps": ["Why was the queue size set to 100?"],
        "gap_query": "Why was the queue size set to 100?",
        "linkage_check": None,  # no CommitEcho record in this commit
    },
]
