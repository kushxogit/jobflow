import sys
from unittest.mock import Mock
from jobflow.validator import verify_job_with_ai
from jobflow.config import load_app_config

config = load_app_config()

job = Mock()
job.title = "Software Engineer - Remote"
job.company = "Test Co"
job.location = "Remote"
job.description = "Looking for a software engineer with 2 years of experience. Must be fully remote. We build cool stuff."

approved, reason = verify_job_with_ai(job, config.deepseek_api_key, config.deepseek_model)
print(f"Test 1 (Valid): Approved={approved}, Reason={reason}")

job2 = Mock()
job2.title = "Senior Software Engineer"
job2.company = "Test Co"
job2.location = "Hybrid"
job2.description = "Looking for a senior engineer with 5 years experience. Must come to office."

approved, reason = verify_job_with_ai(job2, config.deepseek_api_key, config.deepseek_model)
print(f"Test 2 (Invalid): Approved={approved}, Reason={reason}")
