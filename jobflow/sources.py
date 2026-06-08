from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .config import SourceSpec
from .models import JobListing
from .utils import read_text, tokenize


class JobSource(Protocol):
    name: str

    def fetch_jobs(self) -> list[JobListing]:
        ...


def create_source(spec: SourceSpec, root_dir: str | Path, config: Any = None) -> JobSource:
    kind = spec.kind.lower().strip()
    if kind == "fixture":
        return FixtureSource(spec, root_dir)
    if kind == "greenhouse":
        return GreenhouseSource(spec)
    if kind == "lever":
        return LeverSource(spec)
    if kind == "html":
        return GenericHtmlSource(spec)

    # Playwright crawlers
    if "playwright" in kind:
        from .browser_sources import (
            LinkedInPlaywrightSource,
            NaukriPlaywrightSource,
            WellfoundPlaywrightSource,
            IndeedPlaywrightSource,
            SurelyRemotePlaywrightSource,
        )
        if config is None:
            raise ValueError(f"AppConfig is required for Playwright sources, kind: {kind}")
        if kind == "linkedin_playwright":
            return LinkedInPlaywrightSource(spec, config)
        if kind == "naukri_playwright":
            return NaukriPlaywrightSource(spec, config)
        if kind == "wellfound_playwright":
            return WellfoundPlaywrightSource(spec, config)
        if kind == "indeed_playwright":
            return IndeedPlaywrightSource(spec, config)
        if kind == "surely_remote_playwright":
            return SurelyRemotePlaywrightSource(spec, config)
        if kind == "workday_playwright":
            from .browser_sources import WorkdayPlaywrightSource
            return WorkdayPlaywrightSource(spec, config)

    return FixtureSource(spec, root_dir)


class BaseSource:
    def __init__(self, spec: SourceSpec):
        self.spec = spec
        self.name = spec.name

    def _request_text(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "JobFlow/0.1",
                "Accept": "application/json,text/html,*/*",
            },
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.read().decode("utf-8", errors="replace")

    def _request_json(self, url: str) -> object:
        return json.loads(self._request_text(url))

    def _matches_query(self, job: JobListing) -> bool:
        queries = [query.strip().lower() for query in self.spec.search_queries if query.strip()]
        if not queries:
            return True
        haystack = " ".join(
            [
                job.title,
                job.company,
                job.location,
                job.description,
                " ".join(job.tags),
            ]
        ).lower()
        for query in queries:
            tokens = [token for token in tokenize(query) if token]
            if tokens and all(token in haystack for token in tokens):
                return True
        return False

    def _limit(self, jobs: list[JobListing]) -> list[JobListing]:
        filtered = [job for job in jobs if self._matches_query(job)]
        return filtered[: self.spec.max_results]

    def _parse_salary(self, text: str) -> tuple[float, float, str]:
        matches = re.findall(r"([$€£]|usd|inr|eur|gbp)?\s*([\d,]+(?:\.\d+)?)\s*(k|lpa|lac|lakhs?|lakh)?", text, re.I)
        values: list[float] = []
        currency = ""
        for symbol, number, suffix in matches:
            if not symbol and not suffix:
                continue
            try:
                value = float(number.replace(",", ""))
            except ValueError:
                continue
            suffix_lower = suffix.lower() if suffix else ""
            if suffix_lower == "k":
                value *= 1000.0
            elif suffix_lower in {"lpa", "lac", "lakhs", "lakh"}:
                value *= 100000.0
            values.append(value)
            if symbol:
                currency = symbol.upper()
        if not values:
            return 0.0, 0.0, currency
        return min(values), max(values), currency

    def _posted_at_iso(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
            
        text_lower = text.lower()
        from datetime import timedelta
        rel_match = re.search(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", text_lower)
        if rel_match:
            amount = int(rel_match.group(1))
            unit = rel_match.group(2)
            days = 0
            if unit == "day": days = amount
            elif unit == "week": days = amount * 7
            elif unit == "month": days = amount * 30
            elif unit == "year": days = amount * 365
            
            if unit in ("minute", "hour"):
                return datetime.now(timezone.utc).date().isoformat()
            return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
            
        if text_lower in ("today", "just now"):
            return datetime.now(timezone.utc).date().isoformat()
        if text_lower == "yesterday":
            return (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

        parsers = (
            lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")),
            lambda item: datetime.strptime(item[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc),
        )
        for parser in parsers:
            try:
                parsed = parser(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).date().isoformat()
            except ValueError:
                continue
        return text


class FixtureSource(BaseSource):
    def __init__(self, spec: SourceSpec, root_dir: str | Path):
        super().__init__(spec)
        self.root_dir = Path(root_dir)

    def fetch_jobs(self) -> list[JobListing]:
        if not self.spec.fixture_path:
            return []
        path = Path(self.spec.fixture_path)
        if not path.is_absolute():
            path = self.root_dir / path
        if not path.exists():
            return []
        payload = json.loads(read_text(path))
        listings: list[JobListing] = []
        for item in payload:
            listings.append(self._from_dict(item))
        return self._limit(listings)

    def _from_dict(self, item: dict[str, object]) -> JobListing:
        salary_min, salary_max, salary_currency = self._parse_salary(
            " ".join([str(item.get("salary", "")), str(item.get("description", ""))])
        )
        return JobListing(
            source=self.spec.name,
            title=str(item.get("title", "")),
            company=str(item.get("company", "")),
            location=str(item.get("location", "")),
            url=str(item.get("url", "")),
            description=str(item.get("description", "")),
            apply_url=str(item.get("apply_url", item.get("url", ""))),
            source_job_id=str(item.get("source_job_id", "")),
            posted_at=self._posted_at_iso(item.get("posted_at", "")),
            remote=bool(item.get("remote", False)),
            salary_min=float(item.get("salary_min", salary_min) or 0),
            salary_max=float(item.get("salary_max", salary_max) or 0),
            salary_currency=str(item.get("salary_currency", salary_currency)),
            seniority=str(item.get("seniority", "")),
            tags=[str(tag) for tag in item.get("tags", [])],
            raw_payload=dict(item),
        )


class GreenhouseSource(BaseSource):
    def fetch_jobs(self) -> list[JobListing]:
        endpoint = self.spec.api_url or self.spec.board_url
        if not endpoint and self.spec.board:
            endpoint = f"https://boards-api.greenhouse.io/v1/boards/{self.spec.board}/jobs?content=true"
        if not endpoint:
            return []
        payload = self._request_json(endpoint)
        jobs = []
        for item in payload.get("jobs", []):
            salary_min, salary_max, salary_currency = self._parse_salary(
                " ".join(
                    [
                        str(item.get("pay_input_ranges", "")),
                        str(item.get("content", "")),
                        str(item.get("metadata", "")),
                    ]
                )
            )
            jobs.append(
                JobListing(
                    source=self.spec.name,
                    title=str(item.get("title", "")),
                    company=self.spec.company or self.spec.board or "Greenhouse",
                    location=str((item.get("location") or {}).get("name", "")),
                    url=str(item.get("absolute_url", "")),
                    description=str(item.get("content", "")),
                    apply_url=str(item.get("absolute_url", "")),
                    source_job_id=str(item.get("id", "")),
                    posted_at=self._posted_at_iso(item.get("updated_at", "")),
                    remote="remote" in str((item.get("location") or {}).get("name", "")).lower(),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_currency,
                    tags=[str(department.get("name", "")) for department in item.get("departments", []) if department],
                    raw_payload=dict(item),
                )
            )
        return self._limit(jobs)


class LeverSource(BaseSource):
    def fetch_jobs(self) -> list[JobListing]:
        endpoint = self.spec.api_url
        if not endpoint and self.spec.company:
            endpoint = f"https://api.lever.co/v0/postings/{self.spec.company}?mode=json"
        if not endpoint:
            return []
        payload = self._request_json(endpoint)
        jobs = []
        for item in payload:
            cats = item.get("categories", {})
            tags = [str(value) for value in cats.values() if value]
            salary_min, salary_max, salary_currency = self._parse_salary(
                " ".join([str(item.get("salaryRange", "")), str(item.get("description", ""))])
            )
            jobs.append(
                JobListing(
                    source=self.spec.name,
                    title=str(item.get("text", "")),
                    company=self.spec.company or str(item.get("hostedUrl", "")).split("/")[-2] or "Lever",
                    location=str(cats.get("location", "")),
                    url=str(item.get("hostedUrl", "")),
                    apply_url=str(item.get("applyUrl", item.get("hostedUrl", ""))),
                    description=str(item.get("description", "")),
                    source_job_id=str(item.get("id", "")),
                    posted_at=self._posted_at_iso(item.get("createdAt", "")),
                    remote="remote" in " ".join(tags).lower(),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_currency,
                    tags=tags,
                    raw_payload=dict(item),
                )
            )
        return self._limit(jobs)


class GenericHtmlSource(BaseSource):
    def fetch_jobs(self) -> list[JobListing]:
        start_urls = self._build_start_urls()
        if not start_urls:
            return []
        jobs: list[JobListing] = []
        seen_urls: set[str] = set()
        for start_url in start_urls:
            try:
                html = self._request_text(start_url)
            except Exception:
                continue
            job_links = self._extract_job_links(start_url, html)
            for index, job_url in enumerate(job_links, start=1):
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                job = self._fetch_job_page(job_url, index)
                if job is not None:
                    jobs.append(job)
                if len(jobs) >= self.spec.max_results:
                    return self._limit(jobs)
        return self._limit(jobs)

    def _build_start_urls(self) -> list[str]:
        urls = [url for url in self.spec.start_urls if url]
        if urls:
            return urls
        if self.spec.search_template and self.spec.search_queries:
            rendered = []
            for query in self.spec.search_queries:
                rendered.append(
                    self.spec.search_template.format(
                        query=urllib.parse.quote_plus(query),
                        location=urllib.parse.quote_plus(self.spec.location_hint or ""),
                    )
                )
            return rendered
        if self.spec.search_url:
            return [self.spec.search_url]
        return []

    def _extract_job_links(self, base_url: str, html: str) -> list[str]:
        href_pattern = re.compile(r'href="(?P<url>[^"]+)"', re.I)
        compiled = re.compile(self.spec.job_link_pattern, re.I) if self.spec.job_link_pattern else None
        links: list[str] = []
        for match in href_pattern.finditer(html):
            href = urllib.parse.urljoin(base_url, match.group("url"))
            href_lower = href.lower()
            if compiled is not None:
                if compiled.search(href):
                    links.append(href)
                continue
            if any(token in href_lower for token in ("/jobs/", "/job/", "viewjob", "jk=", "jobid", "/positions/")):
                links.append(href)
        deduped: list[str] = []
        seen: set[str] = set()
        for link in links:
            if link in seen:
                continue
            seen.add(link)
            deduped.append(link)
        return deduped[: self.spec.max_results * 2]

    def _fetch_job_page(self, job_url: str, index: int) -> JobListing | None:
        try:
            html = self._request_text(job_url)
        except Exception:
            return None
        payload = self._extract_job_payload(job_url, html)
        if payload is None:
            return None
        salary_min, salary_max, salary_currency = self._parse_salary(
            " ".join([payload.get("salary", ""), payload.get("description", "")])
        )
        return JobListing(
            source=self.spec.name,
            title=payload.get("title", "") or f"Job {index}",
            company=payload.get("company", "") or self.spec.company or self.spec.name,
            location=payload.get("location", ""),
            url=job_url,
            apply_url=payload.get("apply_url", "") or job_url,
            description=payload.get("description", "")[:20000],
            source_job_id=payload.get("source_job_id", "") or f"{self.spec.name}-{index}",
            posted_at=self._posted_at_iso(payload.get("posted_at", "")),
            remote=payload.get("remote", False),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=payload.get("salary_currency", "") or salary_currency,
            seniority=payload.get("seniority", ""),
            tags=payload.get("tags", []),
            raw_payload={"url": job_url, "html_excerpt": html[:4000]},
        )

    def _extract_job_payload(self, job_url: str, html: str) -> dict[str, object] | None:
        structured = self._parse_json_ld(html)
        if structured is not None:
            return structured
        title_match = re.search(r"<title>(?P<title>.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group("title")).strip() if title_match else ""
        description = re.sub(r"<[^>]+>", " ", html)
        description = re.sub(r"\s+", " ", description).strip()
        if not title and not description:
            return None
        return {
            "title": title,
            "company": self.spec.company or self.spec.name,
            "location": self.spec.location_hint,
            "description": description[:20000],
            "apply_url": job_url,
            "posted_at": "",
            "remote": "remote" in description.lower() or "work from home" in description.lower(),
            "salary": description[:1000],
            "salary_currency": "",
            "seniority": "",
            "tags": [],
            "source_job_id": "",
        }

    def _parse_json_ld(self, html: str) -> dict[str, object] | None:
        pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(?P<payload>.*?)</script>',
            re.I | re.S,
        )
        for match in pattern.finditer(html):
            raw = match.group("payload").strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            blocks = data if isinstance(data, list) else [data]
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                type_name = str(block.get("@type", "")).lower()
                if type_name != "jobposting":
                    continue
                hiring_org = block.get("hiringOrganization") or {}
                job_location = block.get("jobLocation") or {}
                address = job_location.get("address") if isinstance(job_location, dict) else {}
                base_salary = block.get("baseSalary") or {}
                salary_value = ""
                if isinstance(base_salary, dict):
                    salary_value = json.dumps(base_salary)
                description = str(block.get("description", ""))
                return {
                    "title": str(block.get("title", "")),
                    "company": str(hiring_org.get("name", "")) if isinstance(hiring_org, dict) else "",
                    "location": str(address.get("addressLocality", "")) if isinstance(address, dict) else "",
                    "description": re.sub(r"<[^>]+>", " ", description),
                    "apply_url": str(block.get("url", "")),
                    "posted_at": str(block.get("datePosted", "")),
                    "remote": "remote" in description.lower() or "work from home" in description.lower(),
                    "salary": salary_value,
                    "salary_currency": str(base_salary.get("currency", "")) if isinstance(base_salary, dict) else "",
                    "seniority": "",
                    "tags": [],
                    "source_job_id": "",
                }
        return None
