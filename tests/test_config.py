from __future__ import annotations

import unittest
from pathlib import Path

from jobflow.config import load_app_config, load_profile, load_source_specs


class ConfigTests(unittest.TestCase):
    def test_load_profile_and_sources(self) -> None:
        root = Path.cwd()
        profile = load_profile(root / "config" / "profile.yaml")
        sources = load_source_specs(root / "config" / "sources.yaml")

        self.assertEqual(profile.name, "Sample Candidate")
        self.assertIn("Python", profile.skills)
        self.assertEqual(len(sources), 4)
        self.assertTrue(any(spec.kind == "fixture" for spec in sources))

    def test_load_app_config(self) -> None:
        config = load_app_config(Path.cwd())
        self.assertTrue(config.profile_path.exists())
        self.assertTrue(config.sources_path.exists())

