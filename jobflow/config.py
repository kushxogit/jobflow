from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Profile
from .utils import env_flag, env_text, ensure_dir, read_text


@dataclass(slots=True)
class SourceSpec:
    kind: str
    name: str
    enabled: bool = True
    search_queries: list[str] = field(default_factory=list)
    start_urls: list[str] = field(default_factory=list)
    search_template: str = ""
    job_link_pattern: str = ""
    fixture_path: str = ""
    board: str = ""
    company: str = ""
    search_url: str = ""
    api_url: str = ""
    board_url: str = ""
    max_results: int = 25
    pages: int = 3          # how many result pages to crawl per query
    location_hint: str = ""
    remote_filter: bool = False


@dataclass(slots=True)
class AppConfig:
    root_dir: Path
    profile_path: Path
    sources_path: Path
    db_path: Path
    output_dir: Path
    telegram_dry_run: bool = True
    notion_dry_run: bool = True
    llm_dry_run: bool = True
    scoring_threshold: float = 0.38
    posted_within_days_default: int = 3
    review_limit: int = 10
    approved_limit: int = 10
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notion_api_key: str = ""
    notion_database_id: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    openrouter_api_key: str = ""
    playwright_headless: bool = True
    playwright_user_data_dir: Path = field(default_factory=Path)
    linkedin_username: str = ""
    linkedin_password: str = ""
    naukri_username: str = ""
    naukri_password: str = ""
    wellfound_username: str = ""
    wellfound_password: str = ""
    indeed_username: str = ""
    indeed_password: str = ""
    remote_review_quota: int = 120
    hybrid_review_quota: int = 30
    urgent_half_life_days: int = 5


def load_profile(path: str | Path) -> Profile:
    data = load_data_file(path)
    return Profile(
        name=str(data.get("name", "JobFlow User")),
        headline=str(data.get("headline", "")),
        location=str(data.get("location", "")),
        target_roles=[str(item) for item in data.get("target_roles", [])],
        skills=[str(item) for item in data.get("skills", [])],
        keywords=[str(item) for item in data.get("keywords", [])],
        seniority=str(data.get("seniority", "")),
        company_stage_preferences=[str(item) for item in data.get("company_stage_preferences", [])],
        industries=[str(item) for item in data.get("industries", [])],
        locations=[str(item) for item in data.get("locations", [])],
        resume_path=str(data.get("resume_path", "")),
        resume_base_path=str(data.get("resume_base_path", "")),
        summary=str(data.get("summary", "")),
        desired_salary_min=float(data.get("desired_salary_min", 0) or 0),
        desired_salary_currency=str(data.get("desired_salary_currency", "USD")),
        remote_preference=str(data.get("remote_preference", "either")),
        posted_within_days=int(data.get("posted_within_days", 3) or 3),
        target_job_count=int(data.get("target_job_count", 25) or 25),
        # New extended fields
        skills_tier_1=[str(s) for s in data.get("skills_tier_1", [])],
        skills_tier_2=[str(s) for s in data.get("skills_tier_2", [])],
        skills_tier_3=[str(s) for s in data.get("skills_tier_3", [])],
        work_mode_preferences=dict(data.get("work_mode_preferences", {})),
        salary_constraints=dict(data.get("salary_constraints", {})),
        experience_constraints=dict(data.get("experience_constraints", {})),
        freshness_constraints=dict(data.get("freshness_constraints", {})),
        target_role_families=dict(data.get("target_role_families", {})),
        experience_years=int(data.get("experience_years", 0) or 0),
    )


def load_source_specs(path: str | Path) -> list[SourceSpec]:
    data = load_data_file(path)
    specs = []
    for item in data.get("sources", []):
        specs.append(
            SourceSpec(
                kind=str(item.get("kind", "fixture")),
                name=str(item.get("name", item.get("kind", "source"))),
                enabled=bool(item.get("enabled", True)),
                search_queries=[str(q) for q in item.get("search_queries", [])],
                start_urls=[str(url) for url in item.get("start_urls", [])],
                search_template=str(item.get("search_template", "")),
                job_link_pattern=str(item.get("job_link_pattern", "")),
                fixture_path=str(item.get("fixture_path", "")),
                board=str(item.get("board", "")),
                company=str(item.get("company", "")),
                search_url=str(item.get("search_url", "")),
                api_url=str(item.get("api_url", "")),
                board_url=str(item.get("board_url", "")),
                max_results=int(item.get("max_results", 25)),
                pages=int(item.get("pages", 3)),
                location_hint=str(item.get("location_hint", "")),
                remote_filter=bool(item.get("remote_filter", False)),
            )
        )
    return specs


def load_app_config(root_dir: str | Path | None = None) -> AppConfig:
    root = Path(root_dir or Path.cwd())
    load_env_file(root / ".env")
    config_dir = root / "config"
    data_dir = root / "data"
    output_dir = ensure_dir(root / "outputs")
    profile_path = config_dir / "profile.yaml"
    sources_path = config_dir / "sources.yaml"

    playwright_dir = data_dir / "playwright_profile"
    env_dir = env_text("PLAYWRIGHT_USER_DATA_DIR", "")
    if env_dir:
        playwright_dir = root / env_dir if not Path(env_dir).is_absolute() else Path(env_dir)
    ensure_dir(playwright_dir)

    return AppConfig(
        root_dir=root,
        profile_path=profile_path,
        sources_path=sources_path,
        db_path=data_dir / "jobflow.db",
        output_dir=output_dir,
        telegram_dry_run=env_flag("JOBFLOW_TELEGRAM_DRY_RUN", True),
        notion_dry_run=env_flag("JOBFLOW_NOTION_DRY_RUN", True),
        llm_dry_run=env_flag("JOBFLOW_LLM_DRY_RUN", True),
        scoring_threshold=float(env_text("JOBFLOW_SCORING_THRESHOLD", "0.15")),
        posted_within_days_default=int(env_text("JOBFLOW_POSTED_WITHIN_DAYS", "3")),
        review_limit=int(env_text("JOBFLOW_REVIEW_LIMIT", "10")),
        approved_limit=int(env_text("JOBFLOW_APPROVED_LIMIT", "10")),
        telegram_bot_token=env_text("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env_text("TELEGRAM_CHAT_ID", ""),
        notion_api_key=env_text("NOTION_API_KEY", ""),
        notion_database_id=env_text("NOTION_DATABASE_ID", ""),
        anthropic_api_key=env_text("ANTHROPIC_API_KEY", ""),
        anthropic_model=env_text("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
        deepseek_api_key=env_text("DEEPSEEK_API_KEY", ""),
        deepseek_model=env_text("DEEPSEEK_MODEL", "deepseek-chat"),
        openrouter_api_key=env_text("OPENROUTER_API_KEY", ""),
        playwright_headless=env_flag("PLAYWRIGHT_HEADLESS", True),
        playwright_user_data_dir=playwright_dir,
        linkedin_username=env_text("LINKEDIN_USERNAME", ""),
        linkedin_password=env_text("LINKEDIN_PASSWORD", ""),
        naukri_username=env_text("NAUKRI_USERNAME", ""),
        naukri_password=env_text("NAUKRI_PASSWORD", ""),
        wellfound_username=env_text("WELLFOUND_USERNAME", ""),
        wellfound_password=env_text("WELLFOUND_PASSWORD", ""),
        indeed_username=env_text("INDEED_USERNAME", ""),
        indeed_password=env_text("INDEED_PASSWORD", ""),
        remote_review_quota=int(env_text("JOBFLOW_REMOTE_REVIEW_QUOTA", "120")),
        hybrid_review_quota=int(env_text("JOBFLOW_HYBRID_REVIEW_QUOTA", "30")),
        urgent_half_life_days=int(env_text("JOBFLOW_URGENT_HALF_LIFE_DAYS", "5")),
    )


def load_data_file(path: str | Path) -> dict[str, Any]:
    raw = read_text(path)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Expected a top-level mapping")
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} must contain JSON-compatible YAML. "
            "This project ships sample configs that are valid JSON."
        ) from exc


def load_env_file(path: str | Path) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in __import__("os").environ:
            __import__("os").environ[key] = value
