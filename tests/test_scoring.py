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
        python_job_score = next(s for s in result.scores if s.job.title == "Python Automation Engineer")
        self.assertTrue(any("python" in term for term in python_job_score.matched_terms))
        self.assertFalse(python_job_score.rejected)
        
        # Check that Growth Marketing Manager is rejected because it is too old
        old_job_score = next(s for s in result.scores if s.job.title == "Growth Marketing Manager")
        self.assertTrue(old_job_score.rejected)
        self.assertIn("posted_too_old", old_job_score.rejection_reasons)
