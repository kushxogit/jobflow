from __future__ import annotations

import unittest
from pathlib import Path

from jobflow.config import SourceSpec
from jobflow.sources import FixtureSource


class SourceFilteringTests(unittest.TestCase):
    def test_fixture_source_respects_search_queries(self) -> None:
        spec = SourceSpec(
            kind="fixture",
            name="Demo",
            fixture_path="data/fixtures/sample_jobs.json",
            search_queries=["python automation"],
            max_results=10,
        )
        source = FixtureSource(spec, Path.cwd())
        jobs = source.fetch_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Python Automation Engineer")
