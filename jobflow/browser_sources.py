from __future__ import annotations

import json
import re
import urllib.parse
from datetime import date as _date
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
                print(f"  [{index}/{total}] {spec.name}: no login page known - skipping.")
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
                print(f"  !  Still on login page ({current_url}).")
                print("  If you pressed ENTER without logging in, re-run 'python -m jobflow login'.")
            else:
                print(f"  OK Session saved for {name} (current page: {current_url[:60]})")

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
                try:
                    # Give slow sites like LinkedIn more time to respond
                    context.set_default_timeout(60000)
                    context.set_default_navigation_timeout(60000)
                    page = context.new_page()
                    listings = self._crawl(page)
                finally:
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
                "[LinkedIn] !  Not logged in or session expired. "
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

                        easy_apply_button = page.locator(".jobs-apply-button, button:has-text('Easy Apply'), span:has-text('Easy Apply')").first
                        is_easy_apply = False
                        try:
                            if easy_apply_button.is_visible():
                                btn_text = easy_apply_button.inner_text().lower()
                                if "easy apply" in btn_text or "easy" in btn_text:
                                    is_easy_apply = True
                        except Exception:
                            pass

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
                                is_direct_apply=is_easy_apply,
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
                "[Naukri] !  Not logged in. "
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
    # -- Broad fallback selectors for job cards on the listing page ----------
    _CARD_SELECTORS = [
        "[data-test='StartupResult'] [data-test='JobResult']",
        "[data-test='JobResult']",
        "[class*='styles_jobCard']",
        "[class*='JobListItem']",
        "[class*='job-card']",
        "li[class*='listing']",
    ]

    def _query_to_slug(self, query: str) -> str:
        """Convert a search query string to a Wellfound URL-friendly role slug."""
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower().strip())
        return slug.strip("-")

    def _try_extract_next_data(self, page: Any) -> tuple[list[dict], dict]:
        """
        Attempt to extract job listings from Wellfound's embedded __NEXT_DATA__
        JSON blob. Returns (list_of_job_dicts, apollo_cache).
        This avoids CSS-selector brittleness entirely.
        """
        try:
            raw = page.locator("script#__NEXT_DATA__").first.inner_text()
            data = json.loads(raw)
            apollo: dict = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("apolloState", {})
            )
            # Apollo state is a flat normalized cache: {"JobListing:123": {...}, ...}
            results = []
            for key, value in apollo.items():
                if not any(key.startswith(p) for p in ["JobListing:", "Job:", "StartupJob:", "JobPosting:"]):
                    continue
                if not isinstance(value, dict):
                    continue
                results.append(value)
            return results, apollo
        except Exception:
            return [], {}

    def _resolve_apollo_ref(self, apollo: dict, ref_obj: object) -> dict:
        """Resolve an Apollo cache reference like {'__ref': 'Company:123'} → dict."""
        if isinstance(ref_obj, dict) and "__ref" in ref_obj:
            return apollo.get(ref_obj["__ref"], {})
        return ref_obj if isinstance(ref_obj, dict) else {}

    # Maximum number of days old a job can be before we stop scrolling.
    # Enforced at 14 days minimum; falls back to config's posted_within_days_default.
    _MAX_AGE_DAYS = 14

    def _crawl(self, page: Any) -> list[JobListing]:
        # Session should already be cached via `py -m jobflow login`.
        page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        print(f"[Wellfound] Landed on: {page.url} | Title: {page.title()}")

        if "login" in page.url or "sign_in" in page.url:
            print(
                "[Wellfound] !  Not logged in. "
                "Run 'py -m jobflow login' first to save your session."
            )
            return []

        jobs: list[JobListing] = []
        seen_urls: set[str] = set()
        queries = self.spec.search_queries or ["software engineer"]
        location_hint = self.spec.location_hint or ""
        use_remote_filter = True  # Wellfound: always filter for remote-open roles
        max_age_days = max(self._MAX_AGE_DAYS, getattr(self.config, "posted_within_days_default", 14))

        for query in queries:
            if len(jobs) >= self.spec.max_results:
                break

            print(f"[Wellfound] -- Query: '{query}' --")

            # Step 1: Navigate to base page and use UI to type query (avoids saved-search override)
            page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            # Step 2: Set query, location, and remote filters via UI
            self._apply_search_filters(page, query, location_hint, use_remote_filter)

            job_count = self._count_job_links(page)
            print(f"[Wellfound] Initial job links found: {job_count}")

            # Step 3: Sort by most recent first
            self._sort_by_date(page)

            # Step 4: Scroll and collect, then fetch descriptions
            page_jobs = self._scroll_until_stale_or_old(page, seen_urls, max_age_days)
            jobs.extend(page_jobs)
            for j in page_jobs:
                seen_urls.add(j.url)

        return jobs

    def _count_job_links(self, page: Any) -> int:
        """Count job-looking links on the current page via JavaScript."""
        try:
            return page.evaluate(
                """
                () => {
                    const hrefs = Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => (h.includes('/jobs/') || h.includes('/role/')) && /\\d{4,}/.test(h));
                    return new Set(hrefs).size;
                }
                """
            )
        except Exception:
            return 0

    def _extract_job_links_js(self, page: Any) -> list[dict]:
        """
        Use JavaScript to extract ALL job links + surrounding text from the current page.
        Returns list of {url, surrounding_text} dicts.
        Completely immune to CSS class name changes.
        """
        try:
            return page.evaluate(
                """
                () => {
                    const seen = new Set();
                    const results = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        const h = a.href || '';
                        const isJob = (h.includes('/jobs/') || h.includes('/role/')) && /\\d{4,}/.test(h);
                        if (!isJob || seen.has(h)) return;
                        seen.add(h);

                        // Walk up to find the best container for metadata
                        let container = a;
                        for (let i = 0; i < 5; i++) {
                            if (!container.parentElement) break;
                            container = container.parentElement;
                            // Stop at a natural card boundary
                            const tag = container.tagName.toLowerCase();
                            if (tag === 'li' || tag === 'article' || tag === 'section') break;
                            const text = container.innerText || '';
                            if (text.length > 80 && text.length < 1000) break;
                        }

                        results.push({
                            url: h,
                            text: (container.innerText || a.innerText || '').slice(0, 800)
                        });
                    });
                    return results;
                }
                """
            ) or []
        except Exception as e:
            print(f"[Wellfound] JS link extraction error: {e}")
            return []

    def _apply_search_filters(
        self,
        page: Any,
        query: str,
        location_hint: str,
        use_remote_filter: bool,
    ) -> bool:
        """
        Interact with Wellfound's real search UI to apply query, location + remote filter.
        """
        try:
            url_before = page.url
            
            # -- Search Query --------------------------------------------------
            search_input = None
            # Scope search explicitly to the job search area, avoiding the global nav bar 
            # which has placeholder="Search" and navigates to the wrong page.
            for sel in [
                "input[placeholder*='role']",
                "input[placeholder*='Job title']",
                "input[placeholder*='keyword']",
                "main input[type='text']",
                "div[class*='jobSearch'] input[type='text']",
            ]:
                el = page.locator(sel).first
                if el.is_visible():
                    search_input = el
                    break
            
            if search_input:
                # Use force=True to bypass overlapping SVGs (like the user/magnifying glass icons)
                search_input.fill(query, force=True)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                page.wait_for_timeout(2500)

            # -- Location / Remote filter --------------------------------------
            is_remote_hint = location_hint.lower().strip() in (
                "remote", "remote only", "fully remote", ""
            )

            if use_remote_filter or is_remote_hint:
                remote_toggled = False
                for remote_sel in [
                    "button:has-text('Open to remote')",
                    "label:has-text('Open to remote')",
                    "[data-test*='remote']",
                    "[aria-label*='remote' i]",
                ]:
                    el = page.locator(remote_sel).first
                    try:
                        if el.is_visible():
                            el.click()
                            remote_toggled = True
                            print("[Wellfound] Toggled 'Open to remote' filter.")
                            page.wait_for_timeout(1000)
                            break
                    except Exception:
                        continue

            elif location_hint:
                loc_input = None
                for loc_sel in [
                    "input[placeholder*='Location']",
                    "input[placeholder*='City']",
                    "input[name='location']",
                ]:
                    el = page.locator(loc_sel).first
                    if el.is_visible():
                        loc_input = el
                        break
                if loc_input:
                    loc_input.click()
                    loc_input.triple_click()
                    loc_input.type(location_hint, delay=60)
                    page.wait_for_timeout(500)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                    print(f"[Wellfound] Location set to '{location_hint}'")

            return True

        except Exception as exc:
            print(f"[Wellfound] Filter application error: {exc}")
            return False

    def _sort_by_date(self, page: Any) -> None:
        """
        Click the sort dropdown and select 'Date posted' (newest first).
        Gracefully skips if the control can't be found.
        """
        try:
            sort_dropdown = None
            for sel in [
                "button:has-text('Recommended')",
                "button:has-text('Sort by')",
                "button:has-text('Sort')",
                "[data-test*='sort']",
                "[aria-label*='sort' i]",
                "select[name*='sort']",
            ]:
                el = page.locator(sel).first
                if el.is_visible():
                    sort_dropdown = el
                    break

            if sort_dropdown is None:
                print("[Wellfound] Sort control not found - results will be in default order.")
                return

            sort_dropdown.click()
            page.wait_for_timeout(800)

            # Click the 'Date posted' option in the dropdown
            for opt_sel in [
                "li:has-text('Date posted')",
                "option:has-text('Date posted')",
                "[role='option']:has-text('Date')",
                "a:has-text('Newest')",
                "button:has-text('Most recent')",
            ]:
                el = page.locator(opt_sel).first
                try:
                    if el.is_visible():
                        el.click()
                        page.wait_for_timeout(2500)
                        print("[Wellfound] OK Sorted by date posted (newest first).")
                        return
                except Exception:
                    continue

            print("[Wellfound] Could not find 'Date posted' option in sort dropdown.")
            # Close dropdown if open
            page.keyboard.press("Escape")
        except Exception as exc:
            print(f"[Wellfound] Sort error: {exc}")

    def _scroll_until_stale_or_old(
        self,
        page: Any,
        seen_urls: set,
        max_age_days: int,
    ) -> list[JobListing]:
        """
        TWO-PHASE approach:

        Phase 1 - Scroll & collect job link metadata using JavaScript
                   (no CSS selectors, no page navigation).
          Stops when:
            - A job's posted date is older than max_age_days
            - No new links after 3 scroll rounds
            - max_results links collected

        Phase 2 - Visit each URL for the full description.
        """
        from datetime import timedelta
        cutoff = _date.today() - timedelta(days=max_age_days)

        # -- PHASE 1: Scroll & collect links via JS --------------------------─
        card_data: list[dict] = []
        processed_hrefs: set[str] = set()
        last_link_count = 0
        stale_attempts = 0
        MAX_STALE = 3

        while len(card_data) < self.spec.max_results:
            raw_links = self._extract_job_links_js(page)
            current_count = len(raw_links)
            print(
                f"[Wellfound] [Phase 1] Page links: {current_count} | "
                f"Collected: {len(card_data)} | Cutoff: >{max_age_days}d"
            )

            if current_count > last_link_count:
                stale_attempts = 0
                hit_cutoff = False

                for link in raw_links[last_link_count:]:
                    if len(card_data) >= self.spec.max_results:
                        break

                    job_url = link.get("url", "").strip()
                    if not job_url:
                        continue
                    if job_url in seen_urls or job_url in processed_hrefs:
                        continue

                    card_text = link.get("text", "")

                    # Date guard - stop when we hit old jobs (sorted newest-first)
                    rel_match = re.search(
                        r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago",
                        card_text, re.I,
                    )
                    posted_at_str = rel_match.group(0) if rel_match else ""
                    if posted_at_str:
                        iso = self._posted_at_iso(posted_at_str)
                        if iso:
                            try:
                                if _date.fromisoformat(iso) < cutoff:
                                    print(f"[Wellfound] Job at {posted_at_str} > {max_age_days}d - stopping.")
                                    hit_cutoff = True
                                    break
                            except ValueError:
                                pass

                    processed_hrefs.add(job_url)

                    # Parse lightweight metadata from surrounding text
                    lines = [l.strip() for l in card_text.splitlines() if l.strip()]
                    title = lines[0] if lines else f"Wellfound Job {len(card_data) + 1}"
                    company = lines[1] if len(lines) > 1 else "Wellfound Company"

                    seniority = ""
                    for level in ["Intern", "Junior", "Mid-level", "Senior", "Lead", "Principal", "Staff"]:
                        if level.lower() in card_text.lower():
                            seniority = level
                            break

                    location_text = ""
                    for line in lines:
                        if any(kw in line.lower() for kw in ["remote", "hybrid", "onsite", "us", "uk", "india", "worldwide"]):
                            location_text = line
                            break

                    card_data.append({
                        "url": job_url,
                        "title": title,
                        "company": company,
                        "location_text": location_text,
                        "card_text": card_text,
                        "posted_at_str": posted_at_str,
                        "seniority": seniority,
                        "source_job_id": self._extract_job_id(job_url) or str(abs(hash(job_url))),
                    })

                if hit_cutoff:
                    break
                last_link_count = current_count

            else:
                stale_attempts += 1
                if stale_attempts >= MAX_STALE:
                    print("[Wellfound] No new links after 3 scrolls - end of results.")
                    break

            # Try pagination Next button first
            paginated = False
            for next_sel in [
                "a[aria-label='Next page']",
                "a:has-text('Next')",
                "button:has-text('Next')",
                "[data-test='pagination-next']",
            ]:
                try:
                    btn = page.locator(next_sel).first
                    if btn.is_visible() and btn.is_enabled():
                        btn.click()
                        page.wait_for_timeout(3000)
                        last_link_count = 0  # New page - reset
                        paginated = True
                        print("[Wellfound] Clicked 'Next page'.")
                        break
                except Exception:
                    continue

            if not paginated:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2500)
                try:
                    lm = page.locator(
                        "button:has-text('Load more'), button:has-text('Show more'), "
                        "button:has-text('See more jobs'), button:has-text('Load More')"
                    ).first
                    if lm.is_visible():
                        lm.click()
                        page.wait_for_timeout(2500)
                        print("[Wellfound] Clicked 'Load more'.")
                except Exception:
                    pass

        # -- PHASE 2: Visit each URL for the full description -----------------
        print(f"[Wellfound] [Phase 2] Fetching descriptions for {len(card_data)} jobs...")
        jobs: list[JobListing] = []
        for cd in card_data:
            if len(jobs) >= self.spec.max_results:
                break
            try:
                job_url = cd["url"]
                page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)

                description = ""
                tags: list[str] = []

                # __NEXT_DATA__ is the most reliable source
                detail_jobs, apollo = self._try_extract_next_data(page)
                
                # Check if we can build a perfect JobListing directly from Apollo
                matched_job = None
                for raw in detail_jobs:
                    j_url = raw.get("jobUrl") or raw.get("url") or ""
                    # Match by URL or by Job ID
                    if j_url and (j_url in job_url or job_url in j_url):
                        matched_job = self._job_from_apollo(raw, apollo)
                        break
                    elif str(raw.get("id")) == cd["source_job_id"]:
                        matched_job = self._job_from_apollo(raw, apollo)
                        break
                
                if matched_job:
                    jobs.append(matched_job)
                    print(f"[Wellfound] OK {matched_job.title} @ {matched_job.company}")
                    continue

                # Fallback to DOM parsing if Apollo failed
                for raw in detail_jobs:
                    candidate = re.sub(
                        r"<[^>]+>", " ",
                        str(raw.get("description") or raw.get("jobDescription") or "")
                    ).strip()
                    if len(candidate) > len(description):
                        description = candidate

                if not description:
                    for sel in [
                        "[class*='Description']", "[class*='description']",
                        "[class*='JobDetails']", "article", "main",
                    ]:
                        desc_el = page.locator(sel).first
                        if desc_el.is_visible():
                            candidate = desc_el.inner_text().strip()
                            if len(candidate) > 100:
                                description = candidate
                                break

                for tag_el in page.locator(
                    "[class*='tag'], [class*='Tag'], [class*='skill'], [class*='Skill']"
                ).all()[:20]:
                    try:
                        t = tag_el.inner_text().strip()
                        if t and len(t) < 40:
                            tags.append(t)
                    except Exception:
                        pass
                
                # Fallback company extraction from page title if needed
                page_title = page.title()
                if " at " in page_title and " | " in page_title:
                    extracted_company = page_title.split(" at ")[-1].split(" | ")[0].strip()
                    if extracted_company:
                        cd["company"] = extracted_company

                description = description or cd["card_text"][:2000]
                salary_min, salary_max, salary_currency = self._parse_salary(description)
                is_remote = "remote" in cd["location_text"].lower() or "remote" in description.lower()

                jobs.append(JobListing(
                    source=self.spec.name,
                    title=cd["title"],
                    company=cd["company"],
                    location=cd["location_text"] or ("Remote" if is_remote else ""),
                    url=job_url,
                    description=description or "See job URL for details",
                    apply_url=job_url,
                    source_job_id=cd["source_job_id"],
                    posted_at=self._posted_at_iso(cd["posted_at_str"]),
                    remote=is_remote,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_currency,
                    seniority=cd["seniority"],
                    tags=tags,
                    raw_payload={"source": "wellfound_dom"},
                ))
                print(f"[Wellfound] OK {cd['title']} @ {cd['company']}")
            except Exception as e:
                print(f"[Wellfound] Detail fetch failed for {cd.get('url', '?')}: {e}")

        return jobs

    def _job_from_apollo(self, raw: dict, apollo: dict) -> "JobListing | None":
        """Build a JobListing from an Apollo-state job node."""
        title = str(raw.get("title") or raw.get("jobType") or "").strip()
        if not title:
            return None

        company_ref = raw.get("startup") or raw.get("company") or {}
        company_obj = self._resolve_apollo_ref(apollo, company_ref)
        company = str(company_obj.get("name") or company_obj.get("companyName") or "Wellfound Company").strip()

        job_url = str(raw.get("jobUrl") or raw.get("url") or "").strip()
        if job_url.startswith("/"):
            job_url = f"https://wellfound.com{job_url}"
        source_job_id = self._extract_job_id(job_url) or str(raw.get("id") or raw.get("jobId") or "")

        remote_ok = bool(raw.get("remote") or raw.get("allowsRemote"))
        location_data = raw.get("locationNames") or raw.get("locations") or []
        if isinstance(location_data, list):
            location = ", ".join(str(loc) for loc in location_data if loc) or ("Remote" if remote_ok else "")
        else:
            location = str(location_data) or ("Remote" if remote_ok else "")

        try:
            salary_min = float(raw.get("salaryMin") or raw.get("minSalary") or 0)
            salary_max = float(raw.get("salaryMax") or raw.get("maxSalary") or 0)
        except (ValueError, TypeError):
            salary_min, salary_max = 0.0, 0.0
        salary_currency = str(raw.get("currency") or "USD")

        description = str(raw.get("description") or raw.get("jobDescription") or "").strip()
        description = re.sub(r"<[^>]+>", " ", description)

        posted_at = self._posted_at_iso(
            raw.get("createdAt") or raw.get("publishedAt") or raw.get("postedAt") or ""
        )

        seniority = str(raw.get("seniority") or raw.get("seniorityLevel") or raw.get("experienceLevel") or "").strip()
        tags_raw = raw.get("skills") or raw.get("tags") or raw.get("roleTypes") or []
        tags: list[str] = []
        for tag in tags_raw:
            if isinstance(tag, dict):
                tag_name = tag.get("name") or ""
                if not tag_name and tag.get("__ref"):
                    skill_obj = apollo.get(str(tag["__ref"]), {})
                    tag_name = skill_obj.get("name") or skill_obj.get("displayName") or ""
                if tag_name:
                    tags.append(str(tag_name))
            elif tag:
                tags.append(str(tag))

        return JobListing(
            source=self.spec.name,
            title=title,
            company=company,
            location=location or ("Remote" if remote_ok else ""),
            url=job_url,
            description=description or "See job URL for details",
            apply_url=job_url,
            source_job_id=source_job_id,
            posted_at=posted_at,
            remote=remote_ok,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            seniority=seniority,
            tags=tags,
            raw_payload={"source": "wellfound_apollo"},
        )

    def _extract_job_id(self, url: str) -> str:
        """Extract a stable numeric job ID from a Wellfound job URL."""
        match = re.search(r"/jobs?/([\w-]+)", url)
        if match:
            # Pull out just the leading digit segment
            part = match.group(1)
            digits = re.match(r"(\d+)", part)
            if digits:
                return digits.group(1)
        match = re.search(r"/(\d{6,})", url)
        if match:
            return match.group(1)
        return ""

    def _extract_card_dom(self, page: Any, card: Any, index: int, seen_urls: set) -> "JobListing | None":
        """DOM fallback: navigate to the job detail page for full description."""
        title_el = card.locator("h2, h3, h4, [class*='title'], [class*='Title']").first
        title = title_el.inner_text().strip() if title_el.is_visible() else f"Wellfound Job {index + 1}"

        company_el = card.locator("[class*='company'], [class*='Company'], [class*='startup']").first
        company = company_el.inner_text().strip() if company_el.is_visible() else "Wellfound Company"

        href = ""
        for link_sel in ["a[href*='/jobs/']", "a[href*='/role/']", "a[href]"]:
            link_el = card.locator(link_sel).first
            if link_el.is_visible():
                href = link_el.get_attribute("href") or ""
                if href:
                    break
        if not href:
            return None
        job_url = href if href.startswith("http") else f"https://wellfound.com{href}"
        if job_url in seen_urls:
            return None

        source_job_id = self._extract_job_id(job_url) or str(abs(hash(job_url)))

        loc_el = card.locator("[class*='location'], [class*='Location'], [class*='remote']").first
        location_text = loc_el.inner_text().strip() if loc_el.is_visible() else ""
        is_remote = "remote" in location_text.lower() or "remote" in card.inner_text().lower()
        location = location_text or ("Remote" if is_remote else "")

        card_text = card.inner_text()
        rel_match = re.search(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", card_text, re.I)
        posted_at = self._posted_at_iso(rel_match.group(0) if rel_match else "")

        seniority = ""
        for level in ["Intern", "Junior", "Mid-level", "Senior", "Lead", "Principal", "Staff"]:
            if level.lower() in card_text.lower():
                seniority = level
                break

        description = ""
        tags: list[str] = []
        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)

            # Try __NEXT_DATA__ on the detail page first
            detail_next_data = self._try_extract_next_data(page)
            if detail_next_data:
                for raw in detail_next_data:
                    desc_candidate = re.sub(r"<[^>]+>", " ", str(raw.get("description") or raw.get("jobDescription") or "")).strip()
                    if len(desc_candidate) > len(description):
                        description = desc_candidate

            if not description:
                for sel in ["[class*='Description']", "[class*='description']", "[class*='JobDetails']", "article", "main"]:
                    desc_el = page.locator(sel).first
                    if desc_el.is_visible():
                        candidate = desc_el.inner_text().strip()
                        if len(candidate) > 100:
                            description = candidate
                            break

            tag_els = page.locator("[class*='tag'], [class*='Tag'], [class*='skill'], [class*='Skill']").all()
            for tag_el in tag_els[:20]:
                tag_text = tag_el.inner_text().strip()
                if tag_text and len(tag_text) < 40:
                    tags.append(tag_text)

            page.go_back()
            page.wait_for_timeout(1500)
        except Exception as detail_exc:
            print(f"[Wellfound] Detail fetch failed for {job_url}: {detail_exc}")
            description = card_text[:2000]

        salary_min, salary_max, salary_currency = self._parse_salary(description)

        return JobListing(
            source=self.spec.name,
            title=title,
            company=company,
            location=location,
            url=job_url,
            description=description or "See job URL for details",
            apply_url=job_url,
            source_job_id=source_job_id,
            posted_at=posted_at,
            remote=is_remote,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            seniority=seniority,
            tags=tags,
            raw_payload={"source": "wellfound_dom"},
        )


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

                        indeed_apply_button = page.locator("#indeedApplyButton, .indeed-apply-button, button:has-text('Apply now')").first
                        is_indeed_apply = False
                        try:
                            if indeed_apply_button.is_visible():
                                is_indeed_apply = True
                        except Exception:
                            pass

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
                                is_direct_apply=is_indeed_apply,
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
