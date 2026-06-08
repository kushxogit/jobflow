from __future__ import annotations

import unittest
from pathlib import Path

from jobflow.config import SourceSpec, load_profile
from jobflow.scoring import RelevanceScorer
from jobflow.sources import FixtureSource


class ScoringTests(unittest.TestCase):
    def test_python_jobs_rank_above_off_role(self) -> None:
        root = Path.cwd()
        profile = load_profile(root / "config" / "profile.yaml")
        fixture_source = FixtureSource(
            SourceSpec(
                kind="fixture",
                name="Demo",
                fixture_path="data/fixtures/sample_jobs.json",
                search_queries=[],
                max_results=10,
            ),
            root,
        )
        jobs = fixture_source.fetch_jobs()

        scorer = RelevanceScorer(profile, threshold=0.1)
        result = scorer.score_many(jobs)

        self.assertGreater(result.scores[0].score, result.scores[-1].score)
        self.assertEqual(result.scores[0].job.title, "Python Automation Engineer")
        self.assertTrue(any("python" in term for term in result.scores[0].matched_terms))
        self.assertFalse(result.scores[0].rejected)
        self.assertIn("not_remote", result.scores[1].rejection_reasons)
