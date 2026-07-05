from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Profile:
    name: str
    headline: str = ""
    location: str = ""
    target_roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    seniority: str = ""
    company_stage_preferences: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    resume_path: str = ""
    resume_base_path: str = ""
    summary: str = ""
    desired_salary_min: float = 0.0
    desired_salary_currency: str = "USD"
    remote_preference: str = "either"
    posted_within_days: int = 3
    target_job_count: int = 25
    # Extended fields for new scoring engine
    skills_tier_1: list[str] = field(default_factory=list)
    skills_tier_2: list[str] = field(default_factory=list)
    skills_tier_3: list[str] = field(default_factory=list)
    work_mode_preferences: dict[str, Any] = field(default_factory=dict)
    salary_constraints: dict[str, Any] = field(default_factory=dict)
    experience_constraints: dict[str, Any] = field(default_factory=dict)
    freshness_constraints: dict[str, Any] = field(default_factory=dict)
    target_role_families: dict[str, Any] = field(default_factory=dict)
    experience_years: int = 0


@dataclass(slots=True)
class JobListing:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str
    apply_url: str = ""
    source_job_id: str = ""
    posted_at: str = ""
    remote: bool = False
    salary_min: float = 0.0
    salary_max: float = 0.0
    salary_currency: str = ""
    seniority: str = ""
    tags: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    is_direct_apply: bool = False

    def short_summary(self) -> str:
        location = self.location or "Unknown location"
        company = self.company or "Unknown company"
        return f"{self.title} · {company} · {location}"


@dataclass(slots=True)
class ScoreSignal:
    name: str
    value: float
    details: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JobScore:
    job: JobListing
    score: float
    signals: list[ScoreSignal] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    rejected: bool = False
    rejection_reasons: list[str] = field(default_factory=list)
    match_percent: int = 0

    def explanation(self) -> str:
        if not self.signals:
            return "No scoring signals were produced."
        pieces = [f"{signal.name}:{signal.value:.2f}" for signal in self.signals if signal.value]
        return ", ".join(pieces) if pieces else "No positive signals."


@dataclass(slots=True)
class ApplicationPacket:
    job: JobListing
    score: JobScore
    resume_notes: list[str] = field(default_factory=list)
    tailored_resume_text: str = ""
    cover_letter: str = ""
    cold_email_subject: str = ""
    cold_email_body: str = ""
    form_answers: dict[str, str] = field(default_factory=dict)
    form_questions: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_markdown(self) -> str:
        answers = self.form_answers or {}
        answer_lines = "\n".join(f"- **{key}**: {value}" for key, value in answers.items()) or "- None"
        notes = "\n".join(f"- {note}" for note in self.resume_notes) or "- None"
        questions = "\n".join(f"- {question}" for question in self.form_questions) or "- None"
        return (
            f"# Application Packet\n\n"
            f"## Job\n"
            f"- Title: {self.job.title}\n"
            f"- Company: {self.job.company}\n"
            f"- Location: {self.job.location}\n"
            f"- URL: {self.job.url}\n"
            f"- Score: {self.score.score:.2f}\n\n"
            f"## Resume Notes\n{notes}\n\n"
            f"## Tailored Resume Draft\n{self.tailored_resume_text or 'Not generated yet.'}\n\n"
            f"## Cover Letter\n{self.cover_letter or 'Not generated yet.'}\n\n"
            f"## Cold Email Subject\n{self.cold_email_subject or 'Not generated yet.'}\n\n"
            f"## Cold Email Body\n{self.cold_email_body or 'Not generated yet.'}\n\n"
            f"## Form Questions\n{questions}\n\n"
            f"## Form Answers\n{answer_lines}\n"
        )


@dataclass(slots=True)
class PipelineSummary:
    discovered: int
    deduped: int
    scored: int
    shortlisted: int
    approved: int
    skipped: int
    sent_to_telegram: int
    logged_to_notion: int
    top_jobs: list[JobScore] = field(default_factory=list)
