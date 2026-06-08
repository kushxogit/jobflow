from __future__ import annotations

import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from .config import AppConfig, SourceSpec
from .models import JobListing
from .sources import BaseSource


# Maps source kind → login URL for each site that requires authentication.
LOGIN_URLS: dict[str, str] = {
    "linkedin_playwright": "https://www.linkedin.com/login",
    "naukri_playwright": "https://www.naukri.com/nlogin/login",
    "indeed_playwright": "https://in.indeed.com/account/login",
    "wellfound_playwright": "https://wellfound.com/login",
}

# After login, we wait until we are NO LONGER on one of these URL prefixes.
POST_LOGIN_URL_PATTERNS: dict[str, str] = {
    "linkedin_playwright": "linkedin.com/login",
    "naukri_playwright": "naukri.com/nlogin",
    "indeed_playwright": "indeed.com/account",
    "wellfound_playwright": "wellfound.com/login",
}


class LoginManager:
    """
    Opens a real (headful) browser for each requested site and waits for
    the user to log in manually in the terminal. Once the user presses
    ENTER, the session is saved into the persistent user-data directory.
    Subsequent `run` calls reuse these cookies automatically.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def login_all(self, specs: list[SourceSpec]) -> None:
        total = len(specs)
        for index, spec in enumerate(specs, 1):
            kind = spec.kind.lower()
            login_url = LOGIN_URLS.get(kind, "")
            if not login_url:
                print(f"  [{index}/{total}] {spec.name}: no login page known — skipping.")
                continue
            self._login_one(index, total, spec.name, kind, login_url)

    def _login_one(self, index: int, total: int, name: str, kind: str, login_url: str) -> None:
        print(f"\n{'─' * 55}")
        print(f"  [{index}/{total}] {name}")
        print(f"  Opening: {login_url}")
        print(f"{'─' * 55}")

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=self.config.playwright_user_data_dir,
                headless=False,  # Always headful for login
                viewport={"width": 1280, "height": 850},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )
            page = context.new_page()
            page.goto(login_url)

            print(f"\n  ✋ A browser window is now open for {name}.")
            print("  Log in completely (handle any CAPTCHA or 2FA too).")
            print("  When you are fully logged in and see your home/dashboard,")
            print("  come back here and press ENTER ↵ to save the session...")

            input()

            # Verify we actually left the login page
            current_url = page.url
            stuck_pattern = POST_LOGIN_URL_PATTERNS.get(kind, "")
            if stuck_pattern and stuck_pattern in current_url:
                print(f"  ⚠️  Still on login page ({current_url}).")
                print("  If you pressed ENTER without logging in, re-run 'python -m jobflow login'.")
            else:
                print(f"  ✅ Session saved for {name} (current page: {current_url[:60]})")

            context.close()


class PlaywrightJobSource(BaseSource):
    def __init__(self, spec: Any, config: AppConfig):
        super().__init__(spec)
        self.config = config

    def fetch_jobs(self) -> list[JobListing]:
        listings: list[JobListing] = []
        with sync_playwright() as p:
            headless = self.config.playwright_headless
            user_data_dir = self.config.playwright_user_data_dir
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    viewport={"width": 1280, "height": 800},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--use-fake-ui-for-media-stream",
                    ],
                )
                # Give slow sites like LinkedIn more time to respond
                context.set_default_timeout(60000)
                context.set_default_navigation_timeout(60000)
                page = context.new_page()
                listings = self._crawl(page)
                context.close()
            except Exception as exc:
                print(f"[Playwright] Error in source {self.name}: {exc}")
        return self._limit(listings)

    def _crawl(self, page: Any) -> list[JobListing]:
        return []


class LinkedInPlaywrightSource(PlaywrightJobSource):
    def _crawl(self, page: Any) -> list[JobListing]:
        # Session should already be cached via `python -m jobflow login`.
        # We just verify we are logged in before starting to crawl.
        page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        if "feed" not in page.url and "login" in page.url or "authwall" in page.url:
            print(
                "[LinkedIn] ⚠️  Not logged in or session expired. "
                "The scraper will attempt to use the logged-out view, but results may be limited. "
                "Run 'python -m jobflow login' to save your session."
            )

        jobs: list[JobListing] = []
        queries = self.spec.search_queries or ["python developer"]
        location = self.spec.location_hint or "India"
        pages = max(1, self.spec.pages)
        per_page = 25  # LinkedIn shows 25 jobs per page

        for query in queries:
            encoded_query = urllib.parse.quote(query)
            encoded_loc = urllib.parse.quote(location)
            # posted_within_days default in seconds (e.g. 21 days = 1814400)
            posted_secs = self.config.posted_within_days_default * 86400
            time_filter = f"&f_TPR=r{posted_secs}" if posted_secs > 0 else ""
            remote_qs = "&f_WT=2" if self.spec.remote_filter else ""

            for page_num in range(pages):
                start_offset = page_num * per_page
                url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={encoded_query}&location={encoded_loc}"
                    f"&start={start_offset}{time_filter}{remote_qs}"
                )
                print(f"[LinkedIn] Fetching page {page_num + 1}/{pages} for '{query}'...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as nav_exc:
                    print(f"[LinkedIn] Navigation failed (page {page_num + 1}): {nav_exc}")
                    break
                page.wait_for_timeout(3000)

                # Scroll sidebar to trigger lazy loading
                try:
                    sidebar = page.locator(".jobs-search-results-list")
                    if sidebar.is_visible():
                        for _ in range(4):
                            sidebar.evaluate("el => el.scrollTop = el.scrollHeight")
                            page.wait_for_timeout(800)
                except Exception:
                    pass

                cards = page.locator(".jobs-search-results__list-item, li[data-occludable-job-id], .base-search-card").all()
                if not cards:
                    print(f"[LinkedIn] No cards found on page {page_num + 1}, stopping pagination.")
                    break

                for index, card in enumerate(cards):
                    if len(jobs) >= self.spec.max_results:
                        break
                    try:
                        card.click()
                        page.wait_for_timeout(1500)

                        title_el = (
                            page.locator(".job-details-jobs-unified-top-card__job-title")
                            .or_(page.locator(".jobs-unified-top-card__job-title"))
                            .or_(card.locator(".base-search-card__title"))
                            .first
                        )
                        title = title_el.inner_text().strip() if title_el.is_visible() else f"LinkedIn Job {index + 1}"

                        company_el = (
                            page.locator(".job-details-jobs-unified-top-card__company-name")
                            .or_(page.locator(".jobs-unified-top-card__company-name"))
                            .or_(card.locator(".base-search-card__subtitle"))
                            .first
                        )
                        company = company_el.inner_text().strip() if company_el.is_visible() else "LinkedIn Company"

                        loc_el = (
                            page.locator(".job-details-jobs-unified-top-card__bullet")
                            .or_(page.locator(".jobs-unified-top-card__bullet"))
                            .or_(card.locator(".job-search-card__location"))
                            .first
                        )
                        job_location = loc_el.inner_text().strip() if loc_el.is_visible() else location

                        desc_el = (
                            page.locator("#job-details")
                            .or_(page.locator(".jobs-description__content"))
                            .first
                        )
                        description = desc_el.inner_text().strip() if desc_el.is_visible() else ""
                        
                        card_text = card.inner_text()
                        rel_match = re.search(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", card_text, re.I)
                        posted_at = rel_match.group(0) if rel_match else ""

                        job_url = page.url
                        link_el = card.locator("a[href*='/jobs/view/'], a.base-card__full-link").first
                        if link_el.is_visible():
                            job_url = link_el.get_attribute("href") or page.url
                        
                        if job_url.startswith("/"):
                            job_url = f"https://www.linkedin.com{job_url}"
                            
                        # Clean up URL to remove noisy tracking params for cleaner Notion links
                        if "?" in job_url:
                            job_url = job_url.split("?")[0]

                        salary_min, salary_max, salary_currency = self._parse_salary(description)
                        jobs.append(
                            JobListing(
                                source=self.spec.name,
                                title=title,
                                company=company,
                                location=job_location,
                                url=job_url,
                                description=description or "See URL for details",
                                apply_url=job_url,
                                source_job_id=str(hash(job_url)),
                                posted_at=self._posted_at_iso(posted_at),
                                remote="remote" in description.lower() or "remote" in job_location.lower(),
                                salary_min=salary_min,
                                salary_max=salary_max,
                                salary_currency=salary_currency,
                            )
                        )
                    except Exception as card_exc:
                        print(f"[LinkedIn] Error on card {index} (page {page_num + 1}): {card_exc}")

                if len(jobs) >= self.spec.max_results:
                    break

        return jobs


class NaukriPlaywrightSource(PlaywrightJobSource):
    def _crawl(self, page: Any) -> list[JobListing]:
        # Session should already be cached via `python -m jobflow login`.
        page.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        if "nlogin" in page.url or "login" in page.url.lower():
            print(
                "[Naukri] ⚠️  Not logged in. "
                "Run 'python -m jobflow login' first to save your session."
            )
            return []

        jobs: list[JobListing] = []
        queries = self.spec.search_queries or ["python"]
        location = self.spec.location_hint or "india"
        pages = max(1, self.spec.pages)

        for query in queries:
            query_clean = re.sub(r"[^a-zA-Z0-9]+", "-", query.lower().strip())
            loc_clean = re.sub(r"[^a-zA-Z0-9]+", "-", location.lower().strip())

            for page_num in range(1, pages + 1):
                # Naukri paginates via suffix: -1 = page 1, -2 = page 2, etc.
                suffix = f"-{page_num}" if page_num > 1 else ""
                url = f"https://www.naukri.com/{query_clean}-jobs-in-{loc_clean}{suffix}"
                print(f"[Naukri] Fetching page {page_num}/{pages} for '{query}'...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as nav_exc:
                    print(f"[Naukri] Navigation failed (page {page_num}): {nav_exc}")
                    break
                page.wait_for_timeout(3000)

                card_locator = None
                for sel in [".srp-jobtuple-wrapper", "article.jobTuple"]:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        card_locator = loc
                        break

                if card_locator is None:
                    print(f"[Naukri] No cards on page {page_num}, stopping.")
                    break

                job_links: list[dict[str, str]] = []
                count = min(card_locator.count(), self.spec.max_results - len(jobs))
                for idx in range(count):
                    card = card_locator.nth(idx)
                    try:
                        title_el = card.locator("a.title, .title").first
                        title = title_el.inner_text().strip()
                        href = title_el.get_attribute("href") or ""
                        company_el = card.locator(".comp-name, a.comp-name").first
                        company = company_el.inner_text().strip() if company_el.is_visible() else "Naukri Company"
                        loc_el = card.locator(".loc-wrap, .location").first
                        job_loc = loc_el.inner_text().strip() if loc_el.is_visible() else location
                        if href:
                            job_links.append({"title": title, "url": href, "company": company, "location": job_loc})
                    except Exception as ce:
                        print(f"[Naukri] Card parse error idx {idx}: {ce}")

                for item in job_links:
                    try:
                        page.goto(item["url"], wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(2000)
                        description = ""
                        for sel in [".job-desc", ".job-description", "article", ".styles_job-desc__"]:
                            desc_el = page.locator(sel).first
                            if desc_el.is_visible():
                                description = desc_el.inner_text().strip()
                                break
                        if not description:
                            description = page.locator("body").inner_text()[:4000]
                        salary_min, salary_max, salary_currency = self._parse_salary(description)
                        jobs.append(
                            JobListing(
                                source=self.spec.name,
                                title=item["title"],
                                company=item["company"],
                                location=item["location"],
                                url=item["url"],
                                description=description,
                                apply_url=item["url"],
                                source_job_id=str(hash(item["url"])),
                                remote="remote" in description.lower() or "remote" in item["location"].lower(),
                                salary_min=salary_min,
                                salary_max=salary_max,
                                salary_currency=salary_currency,
                            )
                        )
                    except Exception as de:
                        print(f"[Naukri] Detail fetch error {item['url']}: {de}")

                if len(jobs) >= self.spec.max_results:
                    break

        return jobs


class WellfoundPlaywrightSource(PlaywrightJobSource):
    def _crawl(self, page: Any) -> list[JobListing]:
        # Session should already be cached via `python -m jobflow login`.
        page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        if "login" in page.url or "sign_in" in page.url:
            print(
                "[Wellfound] ⚠️  Not logged in. "
                "Run 'python -m jobflow login' first to save your session."
            )
            return []

        jobs: list[JobListing] = []
        queries = self.spec.search_queries or ["python"]
        pages = max(1, self.spec.pages)

        for query in queries:
            encoded_query = urllib.parse.quote(query)
            url = f"https://wellfound.com/jobs?query={encoded_query}"
            print(f"[Wellfound] Fetching '{query}' (will scroll {pages} times to load more)...")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as nav_exc:
                print(f"[Wellfound] Navigation failed for '{query}': {nav_exc}")
                continue
            page.wait_for_timeout(4000)

            # Wellfound uses infinite scroll — scroll `pages` times to load more results
            for scroll_round in range(pages):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                # Click "Load more" button if present
                try:
                    load_more = page.locator("button:has-text('Load more'), button:has-text('Show more')").first
                    if load_more.is_visible():
                        load_more.click()
                        page.wait_for_timeout(2000)
                except Exception:
                    pass

            cards = page.locator("[data-test='JobResult'], .styles_jobCard__").all()
            print(f"[Wellfound] Found {len(cards)} job cards for '{query}'")
            for index, card in enumerate(cards):
                if len(jobs) >= self.spec.max_results:
                    break
                try:
                    title_el = card.locator("h4, .styles_title__").first
                    title = title_el.inner_text().strip() if title_el.is_visible() else f"Wellfound Job {index + 1}"
                    company_el = card.locator("h3, .styles_companyName__").first
                    company = company_el.inner_text().strip() if company_el.is_visible() else "Wellfound Company"
                    desc_el = card.locator(".styles_description__").first
                    description = desc_el.inner_text().strip() if desc_el.is_visible() else card.inner_text()
                    job_url = page.url
                    link_el = card.locator("a[href*='/jobs/']").first
                    if link_el.is_visible():
                        job_url = link_el.get_attribute("href") or page.url
                    salary_min, salary_max, salary_currency = self._parse_salary(description)
                    jobs.append(
                        JobListing(
                            source=self.spec.name,
                            title=title,
                            company=company,
                            location="Remote",
                            url=job_url,
                            description=description,
                            apply_url=job_url,
                            source_job_id=str(hash(job_url)),
                            remote=True,
                            salary_min=salary_min,
                            salary_max=salary_max,
                            salary_currency=salary_currency,
                        )
                    )
                except Exception as card_exc:
                    print(f"[Wellfound] Error on card {index}: {card_exc}")

        return jobs


class IndeedPlaywrightSource(PlaywrightJobSource):
    def _crawl(self, page: Any) -> list[JobListing]:
        jobs: list[JobListing] = []
        queries = self.spec.search_queries or ["python"]
        location = self.spec.location_hint or "India"
        pages = max(1, self.spec.pages)
        per_page = 10  # Indeed shows 10–15 per page

        for query in queries:
            encoded_query = urllib.parse.quote(query)
            encoded_loc = urllib.parse.quote(location)

            for page_num in range(pages):
                start_offset = page_num * per_page
                url = f"https://in.indeed.com/jobs?q={encoded_query}&l={encoded_loc}&start={start_offset}&fromage=3"
                print(f"[Indeed] Fetching page {page_num + 1}/{pages} for '{query}'...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as nav_exc:
                    print(f"[Indeed] Navigation failed (page {page_num + 1}): {nav_exc}")
                    break
                page.wait_for_timeout(3000)

                cards = page.locator(".job_seen_beacon, td.resultContent").all()
                if not cards:
                    print(f"[Indeed] No cards on page {page_num + 1}, stopping.")
                    break

                for index, card in enumerate(cards):
                    if len(jobs) >= self.spec.max_results:
                        break
                    try:
                        title_el = card.locator("a.jcs-JobTitle, h2").first
                        title = title_el.inner_text().strip() if title_el.is_visible() else f"Indeed Job {index + 1}"
                        company_el = card.locator(".companyName, [data-testid='company-name']").first
                        company = company_el.inner_text().strip() if company_el.is_visible() else "Indeed Company"
                        loc_el = card.locator(".companyLocation, [data-testid='text-location']").first
                        job_loc = loc_el.inner_text().strip() if loc_el.is_visible() else location

                        title_el.click()
                        page.wait_for_timeout(2000)

                        desc_el = page.locator("#jobDescriptionText, .jobsearch-JobComponent-description").first
                        description = desc_el.inner_text().strip() if desc_el.is_visible() else ""

                        job_url = page.url
                        link_el = card.locator("a.jcs-JobTitle").first
                        if link_el.is_visible():
                            job_url = "https://in.indeed.com" + (link_el.get_attribute("href") or "")

                        salary_min, salary_max, salary_currency = self._parse_salary(description)
                        jobs.append(
                            JobListing(
                                source=self.spec.name,
                                title=title,
                                company=company,
                                location=job_loc,
                                url=job_url,
                                description=description,
                                apply_url=job_url,
                                source_job_id=str(hash(job_url)),
                                remote="remote" in description.lower() or "remote" in job_loc.lower(),
                                salary_min=salary_min,
                                salary_max=salary_max,
                                salary_currency=salary_currency,
                            )
                        )
                    except Exception as card_exc:
                        print(f"[Indeed] Error on card {index} (page {page_num + 1}): {card_exc}")

                if len(jobs) >= self.spec.max_results:
                    break

        return jobs


class SurelyRemotePlaywrightSource(PlaywrightJobSource):
    def _crawl(self, page: Any) -> list[JobListing]:
        jobs: list[JobListing] = []
        page.goto("https://surelyremote.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # Scrape SurelyRemote job links
        links = page.locator("a[href*='/job/'], a[href*='/jobs/']").all()
        job_urls: list[str] = []
        for link in links:
            href = link.get_attribute("href")
            if href:
                full_url = urllib.parse.urljoin("https://surelyremote.com/", href)
                if full_url not in job_urls:
                    job_urls.append(full_url)

        for index, url in enumerate(job_urls[: self.spec.max_results]):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)

                title_el = page.locator("h1").first
                title = title_el.inner_text().strip() if title_el.is_visible() else f"SurelyRemote Job {index+1}"
                
                desc_el = page.locator("main, article, .job-details").first
                description = desc_el.inner_text().strip() if desc_el.is_visible() else page.locator("body").inner_text()[:3000]

                salary_min, salary_max, salary_currency = self._parse_salary(description)

                jobs.append(
                    JobListing(
                        source=self.spec.name,
                        title=title,
                        company="Remote Partner",
                        location="Remote",
                        url=url,
                        description=description,
                        apply_url=url,
                        source_job_id=str(hash(url)),
                        remote=True,
                        salary_min=salary_min,
                        salary_max=salary_max,
                        salary_currency=salary_currency,
                    )
                )
            except Exception as card_exc:
                print(f"[SurelyRemote] Error parsing {url}: {card_exc}")

        return jobs


class WorkdayPlaywrightSource(PlaywrightJobSource):
    """
    Crawls Workday career portals.
    Configure in sources.yaml with kind=workday_playwright.
    Use board_url to specify the company's Workday portal, e.g.:
      board_url: "https://salesforce.wd1.myworkdayjobs.com/External_Career_Site"
    Use company to name the employer.
    """

    def _crawl(self, page: Any) -> list[JobListing]:
        jobs: list[JobListing] = []
        board_url = self.spec.board_url or self.spec.start_urls[0] if self.spec.start_urls else ""
        if not board_url:
            print(f"[Workday] No board_url or start_urls configured for {self.name}. Skipping.")
            return []

        queries = self.spec.search_queries or [""]

        for query in queries:
            try:
                # Workday search URL: append ?q= for keyword filtering
                search_url = board_url
                if query:
                    search_url = f"{board_url.rstrip('/')}?q={urllib.parse.quote(query)}"
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                except Exception as nav_exc:
                    print(f"[Workday] Navigation failed for query '{query}': {nav_exc}")
                    continue
                page.wait_for_timeout(4000)

                # Workday renders jobs in a list with data-automation-id="jobItem"
                # or li elements under a jobs grid
                job_items = page.locator(
                    "[data-automation-id='jobItem'], li[class*='job'], .job-listing-item"
                ).all()

                if not job_items:
                    # Try waiting for dynamic load and retry
                    page.wait_for_timeout(3000)
                    job_items = page.locator(
                        "[data-automation-id='jobItem'], li[class*='job'], .job-listing-item"
                    ).all()

                for index, item in enumerate(job_items[: self.spec.max_results]):
                    try:
                        # Extract title and link
                        link_el = item.locator("a").first
                        title = link_el.inner_text().strip() if link_el.is_visible() else f"Workday Job {index + 1}"
                        href = link_el.get_attribute("href") or ""
                        job_url = urllib.parse.urljoin(board_url, href) if href else board_url

                        # Location
                        loc_el = item.locator(
                            "[data-automation-id='locations'], .job-location, dd"
                        ).first
                        job_location = loc_el.inner_text().strip() if loc_el.is_visible() else self.spec.location_hint or ""

                        # Posted date
                        date_el = item.locator(
                            "[data-automation-id='postedOn'], .job-date, time"
                        ).first
                        posted_at = date_el.inner_text().strip() if date_el.is_visible() else ""

                        # Navigate to job detail page for description
                        if href:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_timeout(2500)
                            desc_el = page.locator(
                                "[data-automation-id='jobPostingDescription'], .job-description, article, main"
                            ).first
                            description = desc_el.inner_text().strip() if desc_el.is_visible() else page.locator("body").inner_text()[:5000]
                            page.go_back()
                            page.wait_for_timeout(1500)
                        else:
                            description = title

                        salary_min, salary_max, salary_currency = self._parse_salary(description)

                        jobs.append(
                            JobListing(
                                source=self.spec.name,
                                title=title,
                                company=self.spec.company or self.name,
                                location=job_location,
                                url=job_url,
                                description=description,
                                apply_url=job_url,
                                source_job_id=str(hash(job_url)),
                                posted_at=self._posted_at_iso(posted_at),
                                remote="remote" in description.lower() or "remote" in job_location.lower(),
                                salary_min=salary_min,
                                salary_max=salary_max,
                                salary_currency=salary_currency,
                            )
                        )
                    except Exception as item_exc:
                        print(f"[Workday] Error parsing job item {index} for {self.name}: {item_exc}")

            except Exception as query_exc:
                print(f"[Workday] Error running query '{query}' for {self.name}: {query_exc}")

        return jobs
