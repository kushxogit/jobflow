from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Iterable

from .models import JobListing, JobScore, Profile, ScoreSignal
from .utils import tokenize

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_PRIORS: dict[str, float] = {
    "linkedin jobs": 1.00,
    "linkedin": 1.00,
    "instahyre": 0.95,
    "wellfound jobs": 0.92,
    "wellfound": 0.92,
    "cutshort": 0.90,
    "naukri jobs": 0.88,
    "naukri": 0.88,
    "hirist": 0.86,
    "surelyremote jobs": 0.82,
    "surelyremote": 0.82,
    "indeed jobs": 0.78,
    "indeed": 0.78,
}

TITLE_FAMILIES: dict[str, list[str]] = {
    "software_engineer": [
        "software engineer", "software developer", "application engineer",
        "sde", "sde 1", "sde 2", "sde1", "sde2", "member of technical staff",
    ],
    "backend_engineer": [
        "backend engineer", "backend developer", "python developer",
        "node js developer", "nodejs developer", "node.js developer",
        "api engineer", "server side engineer", "server-side engineer",
    ],
    "full_stack_engineer": [
        "full stack engineer", "full stack developer", "fullstack engineer",
        "fullstack developer", "mern developer", "mean developer",
        "mern stack", "mean stack",
    ],
    "integration_engineer": [
        "integration engineer", "implementation engineer", "solutions engineer",
        "technical consultant", "api integration engineer", "enterprise engineer",
    ],
    "product_engineer": [
        "product engineer", "product developer", "founding engineer",
    ],
    "platform_engineer": [
        "platform engineer", "infrastructure engineer", "devops engineer",
        "site reliability engineer", "sre",
    ],
    "solutions_engineer": [
        "solutions engineer", "solution architect", "pre-sales engineer",
    ],
    "implementation_engineer": [
        "implementation engineer", "onboarding engineer", "customer engineer",
    ],
}

PRIMARY_FAMILIES = {"software_engineer", "backend_engineer", "full_stack_engineer", "integration_engineer"}
SECONDARY_FAMILIES = {"product_engineer", "platform_engineer", "solutions_engineer", "implementation_engineer"}

REMOTE_PATTERNS = [
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\banywhere in india\b",
    r"\bremote[- ]first\b",
    r"\bfully remote\b",
    r"\bremote within india\b",
]

HYBRID_PATTERNS = [
    r"\bhybrid\b",
    r"\b\d+\s*days?\s*(?:a\s*week\s*)?(?:in\s*)?office\b",
    r"\bflexible work\b",
    r"\bflexible model\b",
]

ONSITE_PATTERNS = [
    r"\bon[- ]?site\b",
    r"\bin[- ]office\b",
    r"\bin office\b",
    r"\bon campus\b",
    r"\brelocation required\b",
    r"\bmust be in\b",
    r"\bwork from office\b",
    r"\bwfo\b",
]

_STOPWORDS = {
    "and", "or", "the", "to", "a", "of", "for", "in", "with",
    "on", "at", "by", "from", "is", "are", "as", "an", "be",
    "this", "that", "we", "you", "your", "our",
}

TIER_WEIGHTS = {"tier_1": 1.0, "tier_2": 0.65, "tier_3": 0.35}


# ---------------------------------------------------------------------------
# Work mode detection
# ---------------------------------------------------------------------------

class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


def detect_work_mode(job: JobListing) -> WorkMode:
    """Parse job text to determine canonical work mode."""
    haystack = " ".join([
        job.title, job.location, job.description,
        " ".join(job.tags),
    ]).lower()

    if any(re.search(p, haystack) for p in ONSITE_PATTERNS):
        # Still check for remote/hybrid override to catch mixed signals
        remote_hit = any(re.search(p, haystack) for p in REMOTE_PATTERNS)
        hybrid_hit = any(re.search(p, haystack) for p in HYBRID_PATTERNS)
        if remote_hit:
            return WorkMode.REMOTE
        if hybrid_hit:
            return WorkMode.HYBRID
        return WorkMode.ONSITE

    if any(re.search(p, haystack) for p in REMOTE_PATTERNS):
        return WorkMode.REMOTE

    if any(re.search(p, haystack) for p in HYBRID_PATTERNS):
        return WorkMode.HYBRID

    # Use the job.remote flag as a fallback
    if job.remote:
        return WorkMode.REMOTE

    return WorkMode.UNKNOWN


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower().strip())


def resolve_title_family(title: str) -> str | None:
    normalized = normalize_title(title)
    for family, variants in TITLE_FAMILIES.items():
        for variant in variants:
            if variant in normalized:
                return family
    return None


# ---------------------------------------------------------------------------
# Salary normalization
# ---------------------------------------------------------------------------

def normalize_salary_to_monthly_inr(
    text: str,
    salary_min: float,
    salary_max: float,
    currency: str,
) -> tuple[int | None, int | None, float]:
    """
    Returns (min_monthly_inr, max_monthly_inr, confidence).
    confidence = 0.0 means inferred/no data, 1.0 means explicit & clear.
    """
    # Already parsed as numeric values
    if salary_max > 0:
        # Detect LPA (Indian lakhs per annum) — values in range 1–100
        if 1 <= salary_max <= 100 and ("lpa" in text.lower() or "lac" in text.lower() or "lakh" in text.lower() or currency in ("", "INR")):
            return (
                int((salary_min or salary_max * 0.85) * 100000 / 12),
                int(salary_max * 100000 / 12),
                0.9,
            )
        # Monthly INR (values 10k–500k)
        if 10000 <= salary_max <= 1000000:
            return int(salary_min or 0), int(salary_max), 0.9
        # Annual INR (values > 500k)
        if salary_max > 500000:
            return int((salary_min or salary_max * 0.85) / 12), int(salary_max / 12), 0.85

    return None, None, 0.0


# ---------------------------------------------------------------------------
# Experience extraction
# ---------------------------------------------------------------------------

def extract_experience_range(text: str) -> tuple[float | None, float | None]:
    """Extract (min_years, max_years) from job description."""
    # Patterns like "3-5 years", "2+ years", "minimum 2 years", "3+ yrs", "3 to 5 yrs"
    patterns = [
        r"(\d+)\s*[-–to]+\s*(\d+)\s*(?:years?|yrs?)",
        r"(\d+)\+\s*(?:years?|yrs?)",
        r"minimum\s+(\d+)\s*(?:years?|yrs?)",
        r"at\s+least\s+(\d+)\s*(?:years?|yrs?)",
        r"(\d+)\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+)?experience",
        r"experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return float(groups[0]), float(groups[1])
            return float(groups[0]), float(groups[0]) + 2
    return None, None


# ---------------------------------------------------------------------------
# Scoring result container
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ScoringResult:
    scores: list[JobScore]
    threshold: float

    @property
    def shortlisted(self) -> list[JobScore]:
        return [item for item in self.scores if not item.rejected]


SYNONYMS: dict[str, list[str]] = {
    "aws": ["amazon web services", "ec2", "s3", "rds", "lambda"],
    "gcp": ["google cloud", "google cloud platform", "bigquery", "gcs"],
    "azure": ["microsoft azure", "azure devops"],
    "js": ["javascript", "es6", "ecmascript"],
    "ts": ["typescript"],
    "python": ["django", "flask", "fastapi", "pandas", "numpy"],
    "kubernetes": ["k8s", "helm"],
    "ml": ["machine learning", "deep learning", "ai", "artificial intelligence"],
    "nlp": ["natural language processing", "llm", "large language model"],
    "react": ["reactjs", "react.js", "nextjs", "next.js"],
    "node": ["nodejs", "node.js", "expressjs", "express.js"],
    "postgres": ["postgresql", "postgres sql"],
    "sql": ["mysql", "sqlite", "oracle", "sql server"],
    "ci/cd": ["cicd", "github actions", "gitlab ci", "jenkins", "circleci"],
}


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

class RelevanceScorer:
    def __init__(self, profile: Profile, threshold: float = 0.10):
        self.profile = profile
        self.threshold = threshold

        # Build tiered skill sets
        self._tier1 = {s.lower() for s in getattr(profile, "skills_tier_1", []) or profile.skills[:14]}
        self._tier2 = {s.lower() for s in getattr(profile, "skills_tier_2", []) or profile.skills[14:21]}
        self._tier3 = {s.lower() for s in getattr(profile, "skills_tier_3", []) or profile.skills[21:]}

        # Work mode config
        self._wm_prefs = getattr(profile, "work_mode_preferences", {}) or {}
        self._allowed_modes = {m.lower() for m in self._wm_prefs.get("allowed", ["remote", "hybrid"])}
        self._remote_score = float(self._wm_prefs.get("remote_score", 1.0))
        self._hybrid_score = float(self._wm_prefs.get("hybrid_score", 0.45))

        # Salary config
        self._salary_cfg = getattr(profile, "salary_constraints", {}) or {}
        self._salary_floor = int(self._salary_cfg.get("minimum_monthly_inr", 50000))
        self._salary_cap = int(self._salary_cfg.get("stretch_monthly_inr", 150000))
        self._infer_salary = bool(self._salary_cfg.get("infer_if_missing", True))

        # Experience config
        self._exp_cfg = getattr(profile, "experience_constraints", {}) or {}
        self._exp_ideal_min = float(self._exp_cfg.get("ideal_min_years", 1))
        self._exp_ideal_max = float(self._exp_cfg.get("ideal_max_years", 4))
        self._exp_soft_max = float(self._exp_cfg.get("soft_max_years", 5))

        # Freshness config
        self._fresh_cfg = getattr(profile, "freshness_constraints", {}) or {}
        self._hard_max_age = int(self._fresh_cfg.get("hard_max_age_days", 21))
        self._half_life = float(self._fresh_cfg.get("half_life_days", 5))

        # Semantic terms from profile
        self._profile_terms = self._build_profile_terms()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_many(self, jobs: list[JobListing]) -> ScoringResult:
        # Build IDF corpus
        corpus = [self._job_text_tokens(job) for job in jobs]
        corpus.append(list(self._profile_terms))
        from collections import Counter
        doc_freq: Counter[str] = Counter()
        for doc in corpus:
            doc_freq.update(set(doc))
        doc_count = len(corpus)

        results = [self.score(job, doc_freq, doc_count) for job in jobs]
        results.sort(key=lambda s: s.score, reverse=True)
        return ScoringResult(scores=results, threshold=self.threshold)

    def score(
        self,
        job: JobListing,
        doc_freq: "Counter[str] | None" = None,
        doc_count: int = 0,
    ) -> JobScore:
        from collections import Counter as _Counter
        if doc_freq is None:
            doc_freq = _Counter()

        work_mode = detect_work_mode(job)
        rejection_reasons = self._check_hard_filters(job, work_mode)

        # Compute all sub-scores
        s_title = self._title_score(job)
        s_skill = self._skill_score(job)
        s_fresh = self._freshness_score(job)
        s_mode = self._work_mode_score(work_mode)
        s_salary = self._salary_score(job)
        s_exp = self._experience_score(job)
        s_sem = self._semantic_score(job, doc_freq, doc_count)
        s_source = SOURCE_PRIORS.get(job.source.lower(), 0.75)
        s_velocity = self._company_velocity_score(job)

        base = (
            0.18 * s_title
            + 0.18 * s_skill
            + 0.18 * s_fresh
            + 0.14 * s_mode
            + 0.12 * s_salary
            + 0.08 * s_exp
            + 0.07 * s_sem
            + 0.03 * s_source
            + 0.02 * s_velocity
        )

        # Urgency multipliers
        age = self._job_age_days(job)
        fast_hire_mult = 1.15 if age is not None and age <= 3 else (1.05 if age is not None and age <= 7 else 1.0)
        remote_mult = 1.10 if work_mode == WorkMode.REMOTE else 1.0

        raw_score = base * fast_hire_mult * remote_mult
        score = round(min(max(raw_score, 0.0), 1.0), 4)
        rejected = score < self.threshold or bool(rejection_reasons)

        signals = [
            ScoreSignal("title", s_title, []),
            ScoreSignal("skills", s_skill, []),
            ScoreSignal("freshness", s_fresh, []),
            ScoreSignal("work_mode", s_mode, [work_mode.value]),
            ScoreSignal("salary", s_salary, []),
            ScoreSignal("experience", s_exp, []),
            ScoreSignal("semantic", s_sem, []),
            ScoreSignal("source", s_source, []),
            ScoreSignal("velocity", s_velocity, []),
        ]

        # Compute matched terms
        job_text = " ".join([job.title, job.description, " ".join(job.tags)]).lower()
        matched_terms = []
        for tier in ["tier_1", "tier_2", "tier_3"]:
            skill_set = self._tier1 if tier == "tier_1" else (self._tier2 if tier == "tier_2" else self._tier3)
            for skill in skill_set:
                if self._check_skill_match_isolated(skill, job_text):
                    matched_terms.append(skill)

        return JobScore(
            job=job,
            score=score,
            signals=signals,
            matched_terms=matched_terms,
            rejected=rejected,
            rejection_reasons=rejection_reasons,
            match_percent=int(round(score * 100)),
        )

    # ------------------------------------------------------------------
    # Hard filters
    # ------------------------------------------------------------------

    def _check_hard_filters(self, job: JobListing, work_mode: WorkMode) -> list[str]:
        reasons: list[str] = []

        # Strict Work Mode: Must be Remote
        if work_mode != WorkMode.REMOTE:
            reasons.append("must_be_remote")

        # Freshness
        age = self._job_age_days(job)
        if age is not None and age > self._hard_max_age:
            reasons.append("posted_too_old")

        # Explicit salary check only
        min_inr, max_inr, confidence = normalize_salary_to_monthly_inr(
            job.description, job.salary_min, job.salary_max, job.salary_currency
        )
        if max_inr is not None and confidence >= 0.8 and max_inr < self._salary_floor:
            reasons.append("salary_below_floor")

        # Strict Seniority Check
        job_title_lower = normalize_title(job.title)
        senior_keywords = ["senior", "sr", "lead", "manager", "sde 3", "sde iii", "staff", "principal"]
        if any(keyword in job_title_lower for keyword in senior_keywords) or re.search(r"\b3\b", job_title_lower):
            reasons.append("seniority_not_allowed")

        # Strict Experience Check
        exp_min, exp_max = extract_experience_range(job.description)
        if exp_min is not None and exp_min > 2.0:
            reasons.append("experience_too_high")

        return reasons

    # ------------------------------------------------------------------
    # Sub-scorers
    # ------------------------------------------------------------------

    def _title_score(self, job: JobListing) -> float:
        family = resolve_title_family(job.title)
        if family in PRIMARY_FAMILIES:
            return 1.0
        if family in SECONDARY_FAMILIES:
            return 0.7
        # Partial raw match fallback
        job_title_lower = normalize_title(job.title)
        for role in self.profile.target_roles:
            if role.lower() in job_title_lower:
                return 0.6
        return 0.0

    def _check_skill_match_isolated(self, skill: str, text: str) -> bool:
        s_clean = skill.lower().strip()
        skill_variants = {s_clean, s_clean.replace(".", ""), s_clean.replace(".js", " js")}
        if any(v in text for v in skill_variants):
            return True
        for canonical, syns in SYNONYMS.items():
            if s_clean == canonical or s_clean in syns:
                all_variants = [canonical] + syns
                if any(v in text for v in all_variants):
                    return True
        return False

    def _skill_score(self, job: JobListing) -> float:
        job_text = " ".join([job.title, job.description, " ".join(job.tags)]).lower()
        matched = 0.0
        total = 0.0
        for tier, weight in [("tier_1", 1.0), ("tier_2", 0.65), ("tier_3", 0.35)]:
            skill_set = self._tier1 if tier == "tier_1" else (self._tier2 if tier == "tier_2" else self._tier3)
            for skill in skill_set:
                total += weight
                if self._check_skill_match_isolated(skill, job_text):
                    matched += weight
        return round(matched / total, 4) if total > 0 else 0.0

    def _freshness_score(self, job: JobListing) -> float:
        age = self._job_age_days(job)
        if age is None:
            return 0.5  # Unknown freshness — neutral
        # Exponential decay with configurable half-life
        return round(0.5 ** (age / self._half_life), 4)

    def _work_mode_score(self, work_mode: WorkMode) -> float:
        if work_mode == WorkMode.REMOTE:
            return self._remote_score
        if work_mode == WorkMode.HYBRID:
            return self._hybrid_score
        if work_mode == WorkMode.UNKNOWN:
            return 0.25  # Benefit of the doubt, but penalised
        return 0.0  # ONSITE

    def _salary_score(self, job: JobListing) -> float:
        min_inr, max_inr, confidence = normalize_salary_to_monthly_inr(
            job.description, job.salary_min, job.salary_max, job.salary_currency
        )

        if max_inr is not None and confidence >= 0.8:
            # Explicit salary present
            x = max(self._salary_floor, min(max_inr, self._salary_cap))
            return round((x - self._salary_floor) / max(self._salary_cap - self._salary_floor, 1), 4)

        if not self._infer_salary:
            return 0.5

        # Inferred salary score
        return self._inferred_salary_score(job)

    def _inferred_salary_score(self, job: JobListing) -> float:
        score = 0.0
        family = resolve_title_family(job.title)
        if family in PRIMARY_FAMILIES:
            score += 0.30
        source_name = job.source.lower()
        if any(name in source_name for name in ["linkedin", "instahyre", "wellfound", "cutshort"]):
            score += 0.20
        exp_min, exp_max = extract_experience_range(job.description)
        if exp_min is not None and exp_max is not None:
            if exp_min <= 3 <= exp_max or (1 <= exp_min <= 4):
                score += 0.20
        job_text_lower = " ".join([job.title, job.description]).lower()
        tier1_hits = sum(1 for s in self._tier1 if s in job_text_lower)
        if tier1_hits >= 3:
            score += 0.15
        if any(stage in job_text_lower for stage in ["startup", "series a", "series b", "product"]):
            score += 0.10
        if any(w in job.title.lower() for w in ["intern", "trainee", "fresher"]):
            score -= 0.50
        return 0.65 * round(max(0.0, min(score, 1.0)), 4)

    def _experience_score(self, job: JobListing) -> float:
        exp_min, exp_max = extract_experience_range(job.description)
        if exp_min is None:
            return 0.6  # No info — moderate neutral
        ideal_min, ideal_max = self._exp_ideal_min, self._exp_ideal_max
        soft_max = self._exp_soft_max
        # Check overlap
        if exp_min <= ideal_max and (exp_max or exp_min) >= ideal_min:
            return 1.0
        if exp_min <= soft_max and (exp_max or exp_min) >= ideal_min:
            return 0.7
        return 0.2

    def _semantic_score(self, job: JobListing, doc_freq: "Counter[str]", doc_count: int) -> float:
        doc_count = max(doc_count, 1)
        # Field-weighted document for IDF scoring
        job_terms_weighted = (
            self._keywords(job.title) * 2
            + self._keywords(job.description[:3000])
        )
        from collections import Counter
        term_weights = Counter(job_terms_weighted)
        profile_terms = self._profile_terms

        def idf(term: str) -> float:
            return math.log((doc_count + 1) / (1 + doc_freq.get(term, 0))) + 1.0

        tf_idf = sum(term_weights[t] * idf(t) for t in profile_terms & set(term_weights))
        tf_idf /= max(len(profile_terms), 1)
        return round(min(tf_idf, 1.0), 4)

    def _company_velocity_score(self, job: JobListing) -> float:
        text = job.description.lower()
        signals = [
            "recently funded", "series a", "series b", "series c",
            "hiring fast", "fast-growing", "hypergrowth", "scaling team",
            "growing team", "expanding",
        ]
        hits = sum(1 for s in signals if s in text)
        return min(hits / 3, 1.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _job_age_days(self, job: JobListing) -> int | None:
        if not job.posted_at:
            return None
        posted = _parse_date(job.posted_at)
        if posted is None:
            return None
        return max((date.today() - posted).days, 0)

    def _build_profile_terms(self) -> set[str]:
        profile_text = " ".join([
            self.profile.name,
            self.profile.headline,
            self.profile.location,
            self.profile.seniority,
            self.profile.summary,
            " ".join(self.profile.target_roles),
            " ".join(self.profile.skills),
            " ".join(self.profile.keywords),
        ])
        return set(self._keywords(profile_text))

    def _keywords(self, text: str) -> list[str]:
        return [t for t in tokenize(text) if t not in _STOPWORDS and len(t) > 1]

    def _job_text_tokens(self, job: JobListing) -> list[str]:
        text = " ".join([job.title, job.company, job.location, job.description])
        return self._keywords(text)


# ---------------------------------------------------------------------------
# Lane-based reranker
# ---------------------------------------------------------------------------

class LaneReranker:
    """
    Splits scored jobs into Remote and Hybrid lanes, ranks each independently,
    then merges with a configurable quota.
    """

    def __init__(self, remote_quota: int = 120, hybrid_quota: int = 30):
        self.remote_quota = remote_quota
        self.hybrid_quota = hybrid_quota

    def rerank(self, scores: list[JobScore]) -> list[JobScore]:
        shortlisted = [s for s in scores if not s.rejected]

        remote_lane: list[JobScore] = []
        hybrid_lane: list[JobScore] = []

        for score in shortlisted:
            wm = detect_work_mode(score.job)
            if wm == WorkMode.REMOTE:
                remote_lane.append(score)
            elif wm == WorkMode.HYBRID:
                hybrid_lane.append(score)
            else:
                # UNKNOWN jobs go to remote lane with lower effective score
                remote_lane.append(score)

        # Sort each lane by score desc
        remote_lane.sort(key=lambda s: s.score, reverse=True)
        hybrid_lane.sort(key=lambda s: s.score, reverse=True)

        merged = remote_lane[: self.remote_quota] + hybrid_lane[: self.hybrid_quota]
        return merged


# ---------------------------------------------------------------------------
# Date parser
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    parsers = (
        lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")).date(),
        lambda item: datetime.strptime(item[:10], "%Y-%m-%d").date(),
    )
    for parser in parsers:
        try:
            return parser(text)
        except ValueError:
            continue
    return None
