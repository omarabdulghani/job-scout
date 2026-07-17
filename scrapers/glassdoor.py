import asyncio
import re
import urllib.parse

from agent.browser import BrowserController


class GlassdoorScraper:
    """Scrapes job listings from Glassdoor."""

    CARD_SELECTORS = [
        '[data-test="job-card"]',
        'li[data-test="jobListing"]',
        'article[data-test="job-card"]',
    ]
    TITLE_SELECTORS = [
        '[data-test="job-title"]',
        'a[data-test="job-title"]',
        'a[href*="jobListing.htm"]',
    ]
    COMPANY_SELECTORS = [
        '[data-test="employer-short-name"]',
        '[data-test="employer-name"]',
        '[class*="EmployerProfile_compactEmployerName"]',
    ]
    LOCATION_SELECTORS = [
        '[data-test="emp-location"]',
        '[data-test="job-location"]',
        '[class*="JobCard_location"]',
    ]
    LINK_SELECTORS = [
        'a[data-test="job-title"]',
        'a[href*="jobListing.htm"]',
    ]
    DESCRIPTION_SELECTORS = [
        "[class*='JobDetails_jobDescription']",
        "[data-test='jobDescription']",
        "[class*='jobDescriptionContent']",
        ".desc",
    ]
    POPUP_SELECTORS = [
        '[alt="Close"]',
        'button[data-test="modal-close"]',
        'button[aria-label="Close"]',
    ]

    def __init__(self, browser: BrowserController):
        self.browser = browser

    async def search_jobs(self, preferences: dict) -> list:
        jobs = []
        seen_ids = set()

        for title in preferences.get("job_titles", [])[:2]:
            for location in preferences.get("locations", ["Remote"])[:2]:
                page_jobs = await self._search_once(title, location, preferences)
                for job in page_jobs:
                    if job.get("id") and job["id"] not in seen_ids:
                        job["source"] = "glassdoor"
                        jobs.append(job)
                        seen_ids.add(job["id"])

                await self.browser.human_delay(2, 5)

        print(f"Glassdoor: Found {len(jobs)} jobs")
        return jobs

    async def validate_search(self, preferences: dict) -> dict:
        title = preferences.get("job_titles", [""])[0]
        location = preferences.get("locations", ["Remote"])[0]
        url = self._build_url(title, location, preferences)
        print(f"Glassdoor: Validating '{title}' in '{location}'")
        await self.browser.goto(url)
        await asyncio.sleep(3)
        await self._dismiss_popup()

        cards, card_selector = await self._find_cards()
        jobs = await self._extract_jobs()
        note = f"card_selector={card_selector or 'none'}"
        sample = jobs[0]["title"] if jobs else ""

        if jobs:
            details = await self.get_job_details(dict(jobs[0]))
            note += f"; description_chars={len(details.get('description', ''))}"

        return {
            "board": "Glassdoor",
            "status": "ok" if jobs else "needs_review",
            "cards_seen": len(cards),
            "jobs_extracted": len(jobs),
            "sample": sample,
            "notes": note,
        }

    def _build_url(self, title: str, location: str, preferences: dict) -> str:
        posted_within_days = max(
            1,
            int(preferences.get("filters", {}).get("posted_within_days", 7)),
        )
        params = {
            "keyword": title,
            "locKeyword": location,
            "locT": "N",
            "fromAge": posted_within_days,
        }
        return f"https://www.glassdoor.com/Job/jobs.htm?{urllib.parse.urlencode(params)}"

    async def _search_once(self, title: str, location: str, preferences: dict) -> list:
        url = self._build_url(title, location, preferences)
        print(f"Glassdoor: Searching '{title}' in '{location}'")
        await self.browser.goto(url)
        await asyncio.sleep(3)
        await self._dismiss_popup()
        return await self._extract_jobs()

    async def _dismiss_popup(self):
        """Close the sign-in popup if it appears."""
        for selector in self.POPUP_SELECTORS:
            try:
                locator = self.browser.page.locator(selector).first
                if await locator.is_visible(timeout=2000):
                    await locator.click()
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue

    async def _find_cards(self):
        for selector in self.CARD_SELECTORS:
            cards = await self.browser.page.query_selector_all(selector)
            if cards:
                return cards, selector
        return [], None

    async def _extract_jobs(self) -> list:
        jobs = []
        try:
            cards, _ = await self._find_cards()
            for card in cards[:15]:
                try:
                    href = await self._first_attribute(card, self.LINK_SELECTORS, "href")
                    title = await self._first_text(card, self.TITLE_SELECTORS)
                    company = await self._first_text(card, self.COMPANY_SELECTORS)
                    location = await self._first_text(card, self.LOCATION_SELECTORS)
                    job_id = (
                        await card.get_attribute("data-id")
                        or self._extract_job_id(href)
                    )

                    if title and href:
                        jobs.append({
                            "id": f"glassdoor_{job_id}" if job_id else f"glassdoor_{href}",
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": self._absolute_url(href),
                        })
                except Exception:
                    continue
        except Exception as exc:
            print(f"   Warning: Could not extract Glassdoor cards: {exc}")
        return jobs

    async def get_job_details(self, job: dict) -> dict:
        if not job.get("url"):
            return job

        await self.browser.goto(job["url"])
        await asyncio.sleep(2)
        await self._dismiss_popup()
        try:
            description = await self._page_first_text(self.DESCRIPTION_SELECTORS)
            if description:
                job["description"] = description[:3000]
        except Exception:
            pass
        return job

    async def _first_text(self, root, selectors) -> str:
        for selector in selectors:
            try:
                element = await root.query_selector(selector)
                if not element:
                    continue
                text = (await element.inner_text()).strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    async def _first_attribute(self, root, selectors, attribute: str) -> str:
        for selector in selectors:
            try:
                element = await root.query_selector(selector)
                if not element:
                    continue
                value = await element.get_attribute(attribute)
                if value:
                    return value.strip()
            except Exception:
                continue
        return ""

    async def _page_first_text(self, selectors) -> str:
        for selector in selectors:
            try:
                element = await self.browser.page.query_selector(selector)
                if not element:
                    continue
                text = (await element.inner_text()).strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _extract_job_id(self, href: str) -> str:
        if not href:
            return ""
        match = re.search(r"jl=(\d+)", href)
        return match.group(1) if match else ""

    def _absolute_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("/"):
            return f"https://www.glassdoor.com{href}"
        return href
