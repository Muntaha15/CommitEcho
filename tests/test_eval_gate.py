"""Run the fixture evaluations in the ordinary pytest gate."""

from tests.evals import baseline_comparison, eval_runner
from tests.fixtures import build_fixtures


def test_fixture_evaluations(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    manifest = tmp_path / "fixture_manifest.json"
    monkeypatch.setattr(build_fixtures, "FIXTURES_DIR", repos)
    build_fixtures.main()
    for module in (eval_runner, baseline_comparison):
        monkeypatch.setattr(module, "_FIXTURES_DIR", repos)
        monkeypatch.setattr(module, "_MANIFEST_PATH", manifest)

    scenarios = eval_runner.run_all()
    assert all(result.passed for result in scenarios), scenarios
    comparisons = baseline_comparison.run_all()
    for question, comparison in zip(baseline_comparison.QUESTIONS, comparisons):
        actual = next(result for result in comparison.results if result.strategy == "commitecho")
        assert actual.contains_rationale == (question["expected_rationale_fragment"] is not None)
