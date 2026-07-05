from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from pathlib import Path
from jobflow.models import ApplicationPacket, JobListing, Profile, JobScore
from jobflow.applier import JobApplier

class TestJobApplier(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(
            name="Kushagra",
            headline="SDE",
            location="India",
            target_roles=["Python Developer", "Software Engineer"],
            skills=["Python", "AWS", "SQL"],
            keywords=["https://linkedin.com/in/kushagra", "https://github.com/kushxogit", "https://kush.dev/portfolio"],
            experience_years=4,
            desired_salary_min=1200000.0,
            desired_salary_currency="INR"
        )
        self.job = JobListing(
            source="LinkedIn",
            title="Backend Developer",
            company="Awesome Startup",
            location="Bangalore",
            url="https://linkedin.com/jobs/view/123",
            description="Looking for a Python Developer with AWS experience.",
            is_direct_apply=True
        )
        self.score = JobScore(
            job=self.job,
            score=0.9,
            matched_terms=["Python", "AWS"]
        )
        self.packet = ApplicationPacket(
            job=self.job,
            score=self.score,
            form_answers={
                "years of experience with python": "4",
                "notice period": "15 days",
            }
        )
        # Mock Playwright Page
        self.page_mock = MagicMock()
        self.applier = JobApplier(
            page=self.page_mock,
            packet=self.packet,
            profile=self.profile,
            resume_path=Path("mock_resume.pdf")
        )

    def test_find_matching_answer_direct(self):
        self.assertEqual(self.applier._find_matching_answer("years of experience with python"), "4")
        self.assertEqual(self.applier._find_matching_answer("Notice Period"), "15 days")

    def test_find_matching_answer_heuristics(self):
        # Visa / Auth
        self.assertEqual(self.applier._find_matching_answer("Are you authorized to work in the US?"), "Yes")
        self.assertEqual(self.applier._find_matching_answer("Will you now or in the future require visa sponsorship?"), "No")
        
        # Experience
        self.assertEqual(self.applier._find_matching_answer("How many years of work experience do you have?"), "4")
        
        # Salary
        self.assertIn("INR", self.applier._find_matching_answer("What is your expected salary?"))
        self.assertIn("1,200,000", self.applier._find_matching_answer("What is your expected CTC?"))
        
        # Social links
        self.assertEqual(self.applier._find_matching_answer("LinkedIn Profile URL"), "https://linkedin.com/in/kushagra")
        self.assertEqual(self.applier._find_matching_answer("GitHub URL"), "https://github.com/kushxogit")
        self.assertEqual(self.applier._find_matching_answer("Portfolio / Personal Website"), "https://kush.dev/portfolio")

if __name__ == "__main__":
    unittest.main()
