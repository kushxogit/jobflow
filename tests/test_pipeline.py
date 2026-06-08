from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from jobflow.config import AppConfig
from jobflow.pipeline import JobFlowPipeline


class PipelineTests(unittest.TestCase):
    def test_dry_run_pipeline_creates_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "data" / "fixtures").mkdir(parents=True, exist_ok=True)

            shutil.copy(Path.cwd() / "config" / "profile.yaml", root / "config" / "profile.yaml")
            shutil.copy(Path.cwd() / "config" / "sources.yaml", root / "config" / "sources.yaml")
            shutil.copy(
                Path.cwd() / "data" / "fixtures" / "sample_jobs.json",
                root / "data" / "fixtures" / "sample_jobs.json",
            )

            config = AppConfig(
                root_dir=root,
                profile_path=root / "config" / "profile.yaml",
                sources_path=root / "config" / "sources.yaml",
                db_path=root / "data" / "jobflow.db",
                output_dir=root / "outputs",
                telegram_dry_run=True,
                notion_dry_run=True,
                scoring_threshold=0.1,
                review_limit=3,
                approved_limit=3,
            )
            pipeline = JobFlowPipeline(config)
            result = pipeline.run()

            self.assertGreaterEqual(result.summary.discovered, 1)
            self.assertTrue((root / "outputs" / "telegram_outbox.jsonl").exists())
            self.assertTrue((root / "outputs" / "pipeline_events.jsonl").exists())
            self.assertGreaterEqual(result.summary.shortlisted, 1)

            packet = pipeline._build_packet(result.jobs[0])
            pipeline._write_packet(packet)
            self.assertTrue((root / "outputs" / "packets").exists())
            self.assertTrue(packet.cold_email_subject)
            self.assertIn("Minimum salary expectation", packet.form_answers)
