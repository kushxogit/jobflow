from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobflow.models import JobListing
from jobflow.store import JobStore


class StoreTests(unittest.TestCase):
    def test_dedup_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobflow.db")
            job = JobListing(
                source="fixture",
                title="Python Automation Engineer",
                company="FlowOps",
                location="Remote",
                url="https://example.com/jobs/demo-001",
                description="Build internal automation tools using Python.",
                source_job_id="demo-001",
            )
            fingerprint = store.record_job(job, score=0.9)
            self.assertTrue(store.has_seen(job))
            loaded = store.load_job(fingerprint)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.title, job.title)

