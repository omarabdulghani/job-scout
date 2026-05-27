import asyncio
import re
import urllib.parse

from agent.browser import BrowserController


class IndeedScraper:
    """Scrapes normally accessible Indeed Netherlands job listings."""

    BASE_URL = "https://nl.indeed.com"
    HOME_URL = f"{BASE_URL}/"
    JOBS_URL = f"{BASE_URL}/jobs"
    RESULTS_PER_PAGE = 10
    SEARCH_SCROLL_ROUNDS = 3
    MAX_CARDS_PER_SEARCH = 25

    # Indeed search-result cards change class names often. Prefer stable data
    # attributes first, then fall back to the common beacon/result containers.
    CARD_SELECTORS = [
        "[data-jk]",
        '[data-testid="slider_item"]',
        ".job_seen_beacon",
        "li:has(a.jcs-JobTitle)",
        "li:has(h2.jobTitle)",
    ]
    LINK_SELECTORS = [
        'a[data-testid="job-title"]',
        "a.jcs-JobTitle",
        "h2.jobTitle a",
        'a[href*="/viewjob"]',
        'a[href*="jk="]',
    ]
    TITLE_SELECTORS = [
        '[data-testid="jobTitle"] span[title]',
        '[data-testid="jobTitle"]',
        'a[data-testid="job-title"] span[title]',
        'a[data-testid="job-title"]',
        "a.jcs-JobTitle span[title]",
        "a.jcs-JobTitle",
        "h2.jobTitle span[title]",
        "h2.jobTitle",
    ]
    COMPANY_SELECTORS = [
        '[data-testid="company-name"]',
        '[data-testid="companyName"]',
        ".companyName",
        '[class*="companyName"]',
    ]
    LOCATION_SELECTORS = [
        '[data-testid="text-location"]',
        '[data-testid="job-location"]',
        ".companyLocation",
        '[class*="companyLocation"]',
    ]
    SALARY_SELECTORS = [
        '[data-testid="attribute_snippet_testid"]',
        ".salary-snippet-container",
        ".estimated-salary",
        '[aria-label*="salary"]',
    ]

    # Indeed job pages can render either a standalone detail page or a split
    # pane. Keep this list intentionally plain: no anti-bot behavior, only DOM
    # locations where an already visible description normally appears.
    DESCRIPTION_SELECTORS = [
        "#jobDescriptionText",
        '[data-testid="jobsearch-JobComponent-description"]',
        ".jobsearch-JobComponent-description",
        '[data-testid="jobDescriptionText"]',
        "section:has(#jobDescriptionText)",
    ]
    DESCRIPTION_EXPAND_SELECTORS = [
        "button",
        "a",
        'span[role="button"]',
        'div[role="button"]',
    ]
    DESCRIPTION_EXPAND_LABELS = [
        "show more",
        "read more",
        "more",
        "meer weergeven",
        "meer lezen",
        "meer",
    ]
    DESCRIPTION_STOP_MARKERS = [
        "Report job",
        "Job activity",
        "Hiring insights",
        "Solliciteer nu",
        "Apply now",
        "Indeed",
    ]
    MANUAL_ACTION_TEXT_MARKERS = [
        "captcha",
        "verify you are human",
        "security verification",
        "additional verification",
        "we need to verify",
        "unusual traffic",
        "access denied",
        "too many requests",
        "controleer dat u een mens bent",
        "beveiligingscontrole",
    ]
    GOOGLE_SIGN_IN_BLOCKED_TEXT_MARKERS = [
        "couldn't sign you in",
        "couldn\u2019t sign you in",
        "this browser or app may not be secure",
        "try using a different browser",
    ]
    MANUAL_ACTION_URL_MARKERS = [
        "/account/login",
        "/challenge",
        "/verify",
        "/captcha",
    ]
    GOOGLE_SIGN_IN_URL_MARKERS = [
        "accounts.google.com",
        "google.com/signin",
    ]

    def __init__(self, browser: BrowserController | None):
        self.browser = browser
        self._initial_manual_access_confirmed = False

    async def ensure_manual_access(self, preferences: dict | None = None) -> bool:
        """Open Indeed and let the user complete any manual login/setup."""
        await self.browser.goto(self.HOME_URL)
        await self.browser.human_delay(1.0, 2.0)
        print(
            "Indeed: Description extraction can usually continue without logging in. "
            "If a sign-in prompt appears, skip it unless Indeed requires it."
        )
        await self._pause_if_manual_action_required("home page")
        indeed_prefs = (preferences or {}).get("job_boards", {}).get("indeed", {})
        if (
            not self._initial_manual_access_confirmed
            and indeed_prefs.get("manual_login_pause", True)
        ):
            print(
                "Indeed: The browser is ready. Log in manually now if you want this "
                "dedicated browser profile to remember your Indeed session."
            )
            input("Indeed: Press Enter only after you are logged in, or ready to continue: ")
            self._initial_manual_access_confirmed = True
            await self.browser.human_delay(1.0, 2.0)
        return True

    async def search_jobs(self, preferences: dict) -> list:
        jobs = []
        seen_ids = set()
        indeed_prefs = preferences.get("job_boards", {}).get("indeed", {})
        max_titles = int(indeed_prefs.get("max_titles_per_search", 2) or 0)
        max_jobs_to_collect = int(indeed_prefs.get("max_jobs_to_collect", 25) or 0)
        search_titles = preferences.get("job_titles", [])
        if max_titles > 0:
            search_titles = search_titles[:max_titles]

        await self.ensure_manual_access(preferences)
        for title in search_titles:
            for location in preferences.get("locations", ["Remote"])[:2]:
                page_jobs = await self._search_once(title, location, preferences)
                for job in page_jobs:
                    if job.get("id") and job["id"] not in seen_ids:
                        job["source"] = "indeed"
                        jobs.append(job)
                        seen_ids.add(job["id"])
                        if max_jobs_to_collect > 0 and len(jobs) >= max_jobs_to_collect:
                            print(f"Indeed: Found {len(jobs)} jobs")
                            return jobs

                await self.browser.human_delay(2, 4)

        print(f"Indeed: Found {len(jobs)} jobs")
        return jobs

    async def validate_search(self, preferences: dict) -> dict:
        await self.ensure_manual_access(preferences)
        title = preferences.get("job_titles", [""])[0]
        location = preferences.get("locations", ["Remote"])[0]
        url = self._build_url(title, location, preferences)
        print(f"Indeed: Validating '{title}' in '{location}'")
        await self.browser.goto(url)
        await self._pause_if_manual_action_required("search results")
        await asyncio.sleep(3)

        cards, card_selector = await self._find_cards()
        jobs = await self._extract_jobs()
        note = f"card_selector={card_selector or 'none'}"
        sample = jobs[0]["title"] if jobs else ""

        if jobs:
            details = await self.get_job_details(dict(jobs[0]))
            note += f"; description_chars={len(details.get('description', ''))}"

        return {
            "board": "Indeed",
            "status": "ok" if jobs else "needs_review",
            "cards_seen": len(cards),
            "jobs_extracted": len(jobs),
            "sample": sample,
            "notes": note,
        }

    def _build_url(self, title: str, location: str, preferences: dict, start: int = 0) -> str:
        indeed_prefs = preferences.get("job_boards", {}).get("indeed", {})
        configured_url = (
            indeed_prefs.get("search_url")
            or indeed_prefs.get("search_url_template")
            or ""
        )
        posted_within_days = max(
            1,
            int(preferences.get("filters", {}).get("posted_within_days", 7)),
        )
        radius_km = indeed_prefs.get("radius_km", indeed_prefs.get("radius", 25))

        if configured_url:
            absolute_url = urllib.parse.urljoin(self.BASE_URL, configured_url)
            parsed = urllib.parse.urlparse(absolute_url)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            query["q"] = [title or ""]
            query["l"] = [location or ""]
            if start > 0:
                query["start"] = [str(start)]
            else:
                query.pop("start", None)
            if radius_km is not None and "radius" not in query:
                query["radius"] = [str(radius_km)]

            return urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
            )

        params = {
            "q": title,
            "l": location,
            "radius": str(radius_km),
            "sort": "date",
            "fromage": str(posted_within_days),
        }
        if start > 0:
            params["start"] = str(start)
        if "remote" in (location or "").lower():
            params["remotejob"] = "032b3046-06a3-4876-8dfd-474eb5e7ed11"
        return f"{self.JOBS_URL}?{urllib.parse.urlencode(params)}"

    async def _search_once(self, title: str, location: str, preferences: dict) -> list:
        url = self._build_url(title, location, preferences)
        print(f"Indeed: Searching '{title}' in '{location}'")
        await self.browser.goto(url)
        await self._pause_if_manual_action_required("search results")
        await asyncio.sleep(3)
        for _ in range(self.SEARCH_SCROLL_ROUNDS):
            await self.scroll_results()
        return await self._extract_jobs()

    async def _find_cards(self):
        for selector in self.CARD_SELECTORS:
            try:
                cards = await self.browser.page.query_selector_all(selector)
            except Exception:
                continue
            if cards:
                return cards, selector
        return [], None

    async def _extract_jobs(self) -> list:
        jobs = []
        try:
            cards, card_selector = await self._find_cards()
            for card in cards[:self.MAX_CARDS_PER_SEARCH]:
                try:
                    href, link_selector = await self._first_attribute_with_selector(
                        card,
                        self.LINK_SELECTORS,
                        "href",
                    )
                    title = await self._first_text(card, self.TITLE_SELECTORS)
                    company = await self._first_text(card, self.COMPANY_SELECTORS)
                    location = await self._first_text(card, self.LOCATION_SELECTORS)
                    salary = await self._first_text(card, self.SALARY_SELECTORS)
                    preview_text = await self._safe_inner_text(card)

                    job_id = (
                        await card.get_attribute("data-jk")
                        or await self._first_attribute(card, ["[data-jk]"], "data-jk")
                        or self._extract_job_id(href)
                        or self._extract_job_id(await card.get_attribute("id") or "")
                    )
                    canonical_url = self.canonical_job_url(job_id) if job_id else self._absolute_url(href)

                    if title and job_id and canonical_url:
                        jobs.append({
                            "id": f"indeed_{job_id}",
                            "job_id": job_id,
                            "title": self._clean_text(title),
                            "company": self._clean_text(company),
                            "location": self._clean_text(location),
                            "salary": self._clean_text(salary),
                            "url": canonical_url,
                            "preview_text": preview_text[:1200],
                            "source": "indeed",
                            "_raw_url": href,
                            "_card_selector": card_selector or "",
                            "_link_selector": link_selector or "",
                        })
                except Exception:
                    continue
        except Exception as exc:
            print(f"   Warning: Could not extract Indeed cards: {exc}")
        return jobs

    async def get_job_details(self, job: dict) -> dict:
        """Open a normally accessible Indeed job page and extract the description."""
        job_id = (job.get("job_id") or self._extract_job_id(job.get("url", ""))).strip()
        if job_id:
            job["job_id"] = job_id
            job["url"] = self.canonical_job_url(job_id)

        await self.browser.goto(job["url"])
        await self._pause_if_manual_action_required("job detail page")
        await asyncio.sleep(2)
        extraction = await self._extract_job_description()
        job["description"] = extraction.get("text", "")[:6000]
        job["description_debug"] = {
            key: value
            for key, value in extraction.items()
            if key != "text"
        }
        return job

    async def scroll_results(self) -> None:
        await self.browser.page.evaluate(
            "window.scrollBy(0, Math.max(500, Math.floor(window.innerHeight * 0.8)))"
        )
        await self.browser.human_delay(0.7, 1.5)

    async def has_next_page(self) -> bool:
        try:
            return bool(
                await self.browser.page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.visibility !== "hidden" &&
                                style.display !== "none" &&
                                rect.width > 0 &&
                                rect.height > 0;
                        };
                        const controls = Array.from(document.querySelectorAll("a, button")).filter(visible);
                        return controls.some((control) => {
                            const label = [
                                control.innerText || "",
                                control.textContent || "",
                                control.getAttribute("aria-label") || "",
                                control.getAttribute("title") || "",
                            ].join(" ").replace(/\\s+/g, " ").trim().toLowerCase();
                            const href = control.getAttribute("href") || "";
                            return (
                                label === "next" ||
                                label.includes("next page") ||
                                label.includes("volgende") ||
                                /[?&]start=\\d+/i.test(href)
                            );
                        });
                    }"""
                )
            )
        except Exception:
            return False

    async def _extract_job_description(self) -> dict:
        payload = {
            "selectors": self.DESCRIPTION_SELECTORS,
            "expandSelectors": self.DESCRIPTION_EXPAND_SELECTORS,
            "expandLabels": self.DESCRIPTION_EXPAND_LABELS,
            "stopMarkers": self.DESCRIPTION_STOP_MARKERS,
        }
        extraction = await self.browser.page.evaluate(
            """async (payload) => {
                const result = {
                    text: "",
                    selector_matched: "",
                    source: "",
                    container_found: false,
                    expand_clicked: false,
                    scrolled: false,
                    text_length: 0,
                    notes: [],
                };
                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const expandTerms = payload.expandLabels.map((term) => normalize(term).toLowerCase());
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const textOf = (el) => normalize(el?.innerText || el?.textContent || "");
                const trimAtStopMarkers = (text) => {
                    let output = normalize(text);
                    let cutIndex = -1;
                    for (const marker of payload.stopMarkers) {
                        const index = output.toLowerCase().indexOf(marker.toLowerCase());
                        if (index > 120 && (cutIndex === -1 || index < cutIndex)) {
                            cutIndex = index;
                        }
                    }
                    return normalize(cutIndex > -1 ? output.slice(0, cutIndex) : output);
                };

                for (const selector of payload.expandSelectors) {
                    const button = Array.from(document.querySelectorAll(selector)).filter(visible).find((candidate) => {
                        const label = normalize([
                            textOf(candidate),
                            candidate.getAttribute("aria-label") || "",
                            candidate.getAttribute("title") || "",
                        ].join(" ")).toLowerCase();
                        return expandTerms.some((term) => label.includes(term));
                    });
                    if (!button) continue;
                    try {
                        button.click();
                        result.expand_clicked = true;
                        await sleep(400);
                        break;
                    } catch (error) {
                        result.notes.push("expand_click_failed");
                    }
                }

                for (const selector of payload.selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector)).filter(visible);
                    for (const node of nodes) {
                        const text = trimAtStopMarkers(textOf(node));
                        if (text.length < 80) continue;
                        result.text = text;
                        result.selector_matched = selector;
                        result.source = "indeed_description_container";
                        result.container_found = true;
                        result.text_length = text.length;
                        return result;
                    }
                }

                window.scrollBy(0, Math.max(450, Math.floor(window.innerHeight * 0.7)));
                result.scrolled = true;
                await sleep(300);

                for (const selector of payload.selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector)).filter(visible);
                    for (const node of nodes) {
                        const text = trimAtStopMarkers(textOf(node));
                        if (text.length < 80) continue;
                        result.text = text;
                        result.selector_matched = selector;
                        result.source = "indeed_description_container_after_scroll";
                        result.container_found = true;
                        result.text_length = text.length;
                        return result;
                    }
                }

                result.notes.push("description_container_not_found");
                result.text_length = result.text.length;
                return result;
            }""",
            payload,
        )
        description = self._clean_description(extraction.get("text", ""))
        extraction["text"] = description
        extraction["text_length"] = len(description)
        extraction["preview"] = description[:280]
        return extraction

    async def _pause_if_manual_action_required(self, context: str) -> bool:
        if await self._google_sign_in_blocked():
            print(
                "Indeed: Google sign-in is blocked in this controlled browser. "
                "Do not try to bypass it. Go back to Indeed and continue as a guest, "
                "or use a non-Google Indeed login method manually if Indeed offers one."
            )
            input("Indeed: Press Enter here when you are back on Indeed or ready to continue as guest: ")
            await self.browser.human_delay(1.0, 2.0)
            return True

        if not await self._manual_action_required():
            return False

        print(
            "Indeed: Manual action required on the "
            f"{context}. If this is optional login, skip it and continue as a guest. "
            "If Indeed requires CAPTCHA or verification, complete it manually in the browser."
        )
        input("Indeed: Press Enter here after you have completed the manual step: ")
        await self.browser.human_delay(1.0, 2.0)
        return True

    async def _google_sign_in_blocked(self) -> bool:
        try:
            current_url = (await self.browser.get_current_url()).lower()
            page_text = (await self.browser.get_page_text()).lower()
            return (
                any(marker in current_url for marker in self.GOOGLE_SIGN_IN_URL_MARKERS)
                and any(marker in page_text for marker in self.GOOGLE_SIGN_IN_BLOCKED_TEXT_MARKERS)
            )
        except Exception:
            return False

    async def _manual_action_required(self) -> bool:
        try:
            current_url = (await self.browser.get_current_url()).lower()
            if any(marker in current_url for marker in self.MANUAL_ACTION_URL_MARKERS):
                return True
            page_text = (await self.browser.get_page_text()).lower()
            return any(marker in page_text for marker in self.MANUAL_ACTION_TEXT_MARKERS)
        except Exception:
            return False

    async def _safe_inner_text(self, root) -> str:
        try:
            return self._clean_text(await root.inner_text())
        except Exception:
            return ""

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
        value, _ = await self._first_attribute_with_selector(root, selectors, attribute)
        return value

    async def _first_attribute_with_selector(self, root, selectors, attribute: str) -> tuple[str, str]:
        for selector in selectors:
            try:
                element = await root.query_selector(selector)
                if not element:
                    continue
                value = await element.get_attribute(attribute)
                if value:
                    return value.strip(), selector
            except Exception:
                continue
        return "", ""

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

    def canonical_job_url(self, job_id: str) -> str:
        return f"{self.BASE_URL}/viewjob?jk={urllib.parse.quote(str(job_id or '').strip())}"

    def _absolute_url(self, href: str) -> str:
        return urllib.parse.urljoin(self.BASE_URL, href or "")

    def _extract_job_id(self, text: str) -> str:
        if not text:
            return ""
        for pattern in (
            r"[?&]jk=([A-Za-z0-9]+)",
            r"[?&]vjk=([A-Za-z0-9]+)",
            r"data-jk=[\"']?([A-Za-z0-9]+)",
            r"\bjob_([A-Za-z0-9]+)",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    def _clean_description(self, text: str) -> str:
        cleaned = self._clean_text(text)
        cleaned = re.sub(r"^(Job description|Full job description|Vacatureomschrijving)\s*", "", cleaned, flags=re.I)
        return cleaned
