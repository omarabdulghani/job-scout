import asyncio
import random
import re
import urllib.parse

from agent.browser import BrowserController
from agent.search_scope import linkedin_workplace_type_codes


class LinkedInScraper:
    """
    Scrapes job listings from LinkedIn and handles Easy Apply.
    Requires you to be logged in.
    """

    BASE_URL = "https://www.linkedin.com"
    JOBS_URL = "https://www.linkedin.com/jobs/search/"
    MAX_LOCATIONS_PER_SEARCH = 6
    SEARCH_SCROLL_ROUNDS = 5
    MAX_CARDS_PER_SEARCH = 30
    RESULTS_RAIL_SELECTORS = [
        ".jobs-search-results-list",
        ".jobs-search-results__list",
        ".scaffold-layout__list-container",
        ".scaffold-layout__list",
    ]
    EXPERIENCE_LEVEL_MAP = {
        "internship": "1",
        "entry": "2",
        "entry_level": "2",
        "associate": "3",
        "mid_senior": "4",
        "mid-senior": "4",
        "director": "5",
        "executive": "6",
    }
    CARD_SELECTORS = [
        ".job-card-container",
        ".jobs-search-results__list-item",
        "li.scaffold-layout__list-item",
    ]
    TITLE_SELECTORS = [
        "a.job-card-list__title",
        ".job-card-list__title",
        "a.job-card-container__link",
        "a[href*='/jobs/view/']",
    ]
    COMPANY_SELECTORS = [
        ".job-card-container__company-name",
        ".artdeco-entity-lockup__subtitle",
        ".job-card-container__primary-description",
    ]
    LOCATION_SELECTORS = [
        ".job-card-container__metadata-item",
        ".artdeco-entity-lockup__caption",
        ".job-card-container__metadata-wrapper li",
    ]
    CARD_EASY_APPLY_SELECTORS = [
        ".job-card-container__apply-method",
        ".job-card-container__footer-item",
        ".job-card-list__footer-wrapper",
        "[class*='apply-method']",
        "[class*='footer']",
    ]
    CARD_ALREADY_APPLIED_MARKERS = [
        "applied",
        "application submitted",
        "already applied",
    ]
    LINK_SELECTORS = [
        "a.job-card-list__title",
        "a.job-card-container__link[href*='/jobs/view/']",
        "a[href*='/jobs/view/']",
    ]
    DESCRIPTION_SELECTORS = [
        ".jobs-description__content",
        ".jobs-box__html-content",
        ".jobs-description-content__text",
        ".jobs-description-content__text--stretch",
        ".show-more-less-html__markup",
        "[class*='jobs-description-content__text']",
    ]
    SALARY_SELECTORS = [
        ".job-details-jobs-unified-top-card__job-insight",
        ".jobs-unified-top-card__job-insight",
        ".job-details-fit-level-preferences",
    ]
    EASY_APPLY_SELECTORS = [
        ".jobs-apply-button--top-card",
        "button.jobs-apply-button",
        "button[aria-label*='Easy Apply']",
        "button[aria-label*='easy apply']",
    ]
    ALREADY_APPLIED_SELECTORS = [
        "button[aria-label*='Applied']",
        "button[aria-label*='applied']",
        "button[aria-label*='application submitted']",
        "button:has-text('Applied')",
        "button:has-text('Application submitted')",
        "span:has-text('Applied')",
        "span:has-text('Application submitted')",
    ]
    APPLY_SELECTORS = [
        ".jobs-apply-button--top-card",
        "button.jobs-apply-button",
        "button[aria-label*='Apply to']",
        "button[aria-label*='Apply']",
        "a[data-control-name='jobdetails_topcard_inapply']",
        "a.jobs-apply-button",
        "a[aria-label*='Apply']",
        "a[href*='offsite-apply']",
    ]
    EASY_APPLY_MODAL_SELECTORS = [
        "[role='dialog']",
        ".jobs-easy-apply-modal",
        ".jobs-apply-modal",
        ".artdeco-modal",
        ".artdeco-modal__content",
        "#interop-outlet",
        "[data-testid='interop-shadowdom']",
        "button[aria-label*='Continue to next step']",
        "button[aria-label*='Review your application']",
        "button[aria-label*='Submit application']",
        "button[aria-label*='next step']",
    ]
    INTEROP_HOST_SELECTORS = [
        "#interop-outlet",
        "[data-testid='interop-shadowdom']",
    ]
    DESCRIPTION_EXPAND_SELECTORS = [
        ".jobs-description__footer-button",
        ".show-more-less-html__button--more",
        "button[aria-label*='description']",
        "button[aria-label*='more']",
    ]

    def __init__(self, browser: BrowserController):
        self.browser = browser

    async def ensure_logged_in(self) -> bool:
        """Check if logged in, if not wait for user to log in."""
        await self.browser.goto("https://www.linkedin.com/feed/")
        await asyncio.sleep(2)
        url = await self.browser.get_current_url()
        if "feed" in url or "mynetwork" in url:
            print("LinkedIn: Already logged in")
            return True

        print("LinkedIn: Not logged in. Please log in manually in the browser window.")
        print("   Waiting up to 60 seconds for login...")
        for _ in range(60):
            await asyncio.sleep(1)
            url = await self.browser.get_current_url()
            if "feed" in url or "mynetwork" in url or "jobs" in url:
                print("LinkedIn: Login detected!")
                return True

        print("LinkedIn: Login timeout")
        return False

    async def search_jobs(self, preferences: dict) -> list:
        """Search for jobs matching preferences and return job listings."""
        jobs = []
        seen_ids = set()
        linkedin_prefs = preferences.get("job_boards", {}).get("linkedin", {})
        max_titles = int(linkedin_prefs.get("max_titles_per_search", 6) or 0)
        max_jobs_to_collect = int(linkedin_prefs.get("max_jobs_to_collect", 25) or 0)
        search_titles = preferences.get("job_titles", [])
        if max_titles > 0:
            search_titles = search_titles[:max_titles]

        for title in search_titles:
            for location in preferences.get("locations", ["Remote"])[:self.MAX_LOCATIONS_PER_SEARCH]:
                page_jobs = await self._search_once(title, location, preferences)
                for job in page_jobs:
                    if job.get("id") and job["id"] not in seen_ids:
                        job["source"] = "linkedin"
                        jobs.append(job)
                        seen_ids.add(job["id"])
                        if max_jobs_to_collect > 0 and len(jobs) >= max_jobs_to_collect:
                            print(
                                f"LinkedIn: Reached collection cap of {max_jobs_to_collect} jobs, "
                                "stopping search early"
                            )
                            print(f"LinkedIn: Found {len(jobs)} jobs")
                            return jobs

                await self.browser.human_delay(2, 4)

        print(f"LinkedIn: Found {len(jobs)} jobs")
        return jobs

    async def validate_search(self, preferences: dict) -> dict:
        """Open one LinkedIn search and report selector health."""
        if not await self.ensure_logged_in():
            return {
                "board": "LinkedIn",
                "status": "login_required",
                "cards_seen": 0,
                "jobs_extracted": 0,
                "sample": "",
                "notes": "Login required before validation",
            }

        title = preferences.get("job_titles", [""])[0]
        location = preferences.get("locations", ["Remote"])[0]
        search_title = self._normalized_search_title(
            title, preferences.get("job_boards", {}).get("linkedin", {})
        )
        url = self._build_search_url(title, location, preferences)
        print(f"LinkedIn: Validating '{search_title}' in '{location}'")
        await self.browser.goto(url)
        await asyncio.sleep(3)
        for _ in range(self.SEARCH_SCROLL_ROUNDS):
            await self._scroll_search_results(600)
            await asyncio.sleep(1)

        cards, card_selector, rail_selector = await self._find_cards()
        jobs = await self._extract_job_cards()
        note = f"search={url}"
        if card_selector:
            note = f"card_selector={card_selector}"
        if rail_selector:
            note = f"{note} rail_selector={rail_selector}"

        sample_job = self._pick_validation_sample(jobs, preferences)
        sample = sample_job["title"] if sample_job else ""
        if sample_job:
            details = await self.get_job_details(dict(sample_job))
            description_length = len(details.get("description", ""))
            note += f"; description_chars={description_length}; easy_apply={details.get('easy_apply', False)}"

        return {
            "board": "LinkedIn",
            "status": "ok" if jobs else "needs_review",
            "cards_seen": len(cards),
            "jobs_extracted": len(jobs),
            "sample": sample,
            "notes": note,
        }

    def _build_search_url(self, title: str, location: str, preferences: dict) -> str:
        linkedin_prefs = preferences.get("job_boards", {}).get("linkedin", {})
        posted_within_days = max(
            1,
            int(preferences.get("filters", {}).get("posted_within_days", 7)),
        )
        search_title = self._normalized_search_title(title, linkedin_prefs)
        params = {
            "keywords": search_title,
            "location": location,
            "f_TPR": f"r{posted_within_days * 86400}",
            "sortBy": "DD",
        }
        distance_miles = linkedin_prefs.get("distance_miles", 10)
        if distance_miles is not None and "remote" not in location.lower():
            try:
                params["distance"] = str(max(0, int(distance_miles)))
            except (TypeError, ValueError):
                pass

        experience_values = self._linkedin_experience_values(
            linkedin_prefs.get("experience_levels", ["entry", "associate"])
        )
        if experience_values:
            params["f_E"] = ",".join(experience_values)

        if linkedin_prefs.get("easy_apply_only", False):
            params["f_AL"] = "true"

        runtime_scope = preferences.get("_runtime_search_scope")
        if runtime_scope and runtime_scope.get("workplace_types"):
            wt_codes = linkedin_workplace_type_codes(runtime_scope)
            if wt_codes:
                params["f_WT"] = ",".join(wt_codes)
        elif not preferences.get("onsite_ok", True) and preferences.get("remote_ok"):
            params["f_WT"] = "2"
        return f"{self.JOBS_URL}?{urllib.parse.urlencode(params)}"

    async def _search_once(self, title: str, location: str, preferences: dict) -> list:
        linkedin_prefs = preferences.get("job_boards", {}).get("linkedin", {})
        search_title = self._normalized_search_title(title, linkedin_prefs)
        url = self._build_search_url(title, location, preferences)
        print(f"LinkedIn: Searching '{search_title}' in '{location}'")
        await self.browser.goto(url)
        await asyncio.sleep(3)

        for _ in range(self.SEARCH_SCROLL_ROUNDS):
            await self._scroll_search_results(600)
            await asyncio.sleep(1)

        jobs = await self._extract_job_cards()
        if linkedin_prefs.get("easy_apply_only", False):
            jobs = [
                job for job in jobs
                if job.get("easy_apply") and not job.get("already_applied")
            ]
        return jobs

    async def _find_cards(self):
        for rail_selector in self.RESULTS_RAIL_SELECTORS:
            try:
                rails = await self.browser.page.query_selector_all(rail_selector)
            except Exception:
                continue
            for rail in rails:
                for selector in self.CARD_SELECTORS:
                    try:
                        cards = await rail.query_selector_all(selector)
                    except Exception:
                        continue
                    if cards:
                        return cards, selector, rail_selector
        return [], None, None

    async def _extract_job_cards(self) -> list:
        """Extract job cards from the search results page."""
        jobs = []
        try:
            cards, card_selector, rail_selector = await self._find_cards()
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
                    job_id = await card.get_attribute("data-job-id") or self._extract_job_id(href)
                    preview_text = await self._safe_inner_text(card)
                    easy_apply = await self._card_has_easy_apply(card)
                    already_applied = self._contains_any_marker(
                        preview_text,
                        self.CARD_ALREADY_APPLIED_MARKERS,
                    )

                    if title and company and href:
                        jobs.append({
                            "id": f"linkedin_{job_id}" if job_id else f"linkedin_{href}",
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": self._absolute_url(href),
                            "preview_text": preview_text[:1200],
                            "easy_apply": easy_apply,
                            "already_applied": already_applied,
                            "_raw_url": href,
                            "_card_selector": card_selector or "",
                            "_results_rail_selector": rail_selector or "",
                            "_link_selector": link_selector or "",
                        })
                except Exception:
                    continue
        except Exception as exc:
            print(f"   Warning: Could not extract LinkedIn cards: {exc}")
        return jobs

    async def _card_has_easy_apply(self, card) -> bool:
        card_text = (await self._safe_inner_text(card)).lower()
        if "easy apply" in card_text:
            return True

        for selector in self.CARD_EASY_APPLY_SELECTORS:
            try:
                elements = await card.query_selector_all(selector)
                for element in elements:
                    text = (await element.inner_text()).strip().lower()
                    if "easy apply" in text:
                        return True
            except Exception:
                continue
        return False

    async def _safe_inner_text(self, root) -> str:
        try:
            return (await root.inner_text()).strip()
        except Exception:
            return ""

    async def get_job_details(self, job: dict) -> dict:
        """Open a job listing and extract details including description."""
        await self.browser.goto(job["url"])
        await asyncio.sleep(2)

        try:
            await self.browser.wait_for_navigation(5000)
            await self._wait_for_apply_state()
            await self._expand_description()
            page_text = await self.browser.get_page_text()
            detail_easy_apply = await self._is_any_visible(self.EASY_APPLY_SELECTORS)
            detail_already_applied = await self._is_any_visible(self.ALREADY_APPLIED_SELECTORS)
            page_text_lower = page_text.lower()
            job["easy_apply"] = bool(job.get("easy_apply")) or detail_easy_apply or (
                "easy apply" in page_text_lower
            )
            job["already_applied"] = bool(job.get("already_applied")) or detail_already_applied or (
                "already applied" in page_text_lower
                or "application submitted" in page_text_lower
            )

            description = await self._page_first_text(self.DESCRIPTION_SELECTORS)
            if not description:
                description = self._extract_description_from_page_text(page_text)
            if description:
                job["description"] = description[:3000]

            salary = await self._page_first_text(self.SALARY_SELECTORS)
            if salary:
                job["salary"] = salary
        except Exception as exc:
            print(f"   Warning: Could not get LinkedIn job details: {exc}")

        return job

    async def click_apply(self, job: dict) -> bool:
        """Click the apply button. Returns True if an apply flow appears."""
        await self._scroll_to_apply_region()
        await self._wait_for_apply_state()

        if job.get("already_applied"):
            return False

        prefer_easy_apply = bool(job.get("easy_apply"))

        click_strategies = []
        if prefer_easy_apply:
            click_strategies.extend([
                ("selector", "button[aria-label*='Easy Apply']"),
                ("selector", "button[aria-label*='easy apply']"),
                ("selector", "button:has-text('Easy Apply')"),
                ("selector", "a:has-text('Easy Apply')"),
                ("role_button", r"easy apply"),
                ("role_link", r"easy apply"),
            ])

        click_strategies.extend([
            ("selector", ".jobs-apply-button--top-card"),
            ("selector", "button.jobs-apply-button"),
            ("selector", "button[aria-label*='Apply to']"),
            ("selector", "button[aria-label*='Apply']"),
            ("selector", "a[data-control-name='jobdetails_topcard_inapply']"),
            ("selector", "a.jobs-apply-button"),
            ("selector", "a[aria-label*='Apply']"),
            ("role_button", r"apply"),
            ("role_link", r"apply"),
        ])

        for strategy, value in click_strategies:
            clicked = await self._try_click_apply_strategy(strategy, value)
            if not clicked:
                continue

            await asyncio.sleep(2)
            if await self._wait_for_easy_apply_modal():
                job["easy_apply"] = True
                return True

            page_text = (await self.browser.get_page_text()).lower()
            if any(marker in page_text for marker in [
                "continue to next step",
                "review your application",
                "submit application",
                "application submitted",
            ]):
                job["easy_apply"] = True
                return True

            if "linkedin.com" not in (await self.browser.get_current_url()):
                return True

        return False

    async def is_easy_apply_modal_open(self) -> bool:
        state = await self.inspect_easy_apply_modal()
        return bool(state.get("open"))

    async def inspect_easy_apply_modal(self) -> dict:
        modal = await self._get_active_modal_locator()
        if modal is None:
            return {"open": False, "fields": []}

        try:
            if not await modal.is_visible(timeout=300):
                return {"open": False, "fields": []}
        except Exception:
            return {"open": False, "fields": []}

        text = await self._safe_locator_text(modal)
        title = await self._safe_locator_text(modal.locator("h2, h3").first)
        is_interop_host = False
        try:
            is_interop_host = await modal.evaluate(
                """(el) => {
                    if (!el) return false;
                    return el.id === "interop-outlet" ||
                        el.getAttribute("data-testid") === "interop-shadowdom";
                }"""
            )
        except Exception:
            is_interop_host = False

        primary_button = ""
        buttons = modal.locator("button")
        button_count = await buttons.count()
        for index in range(button_count):
            button = buttons.nth(index)
            try:
                if not await button.is_visible(timeout=150):
                    continue
            except Exception:
                continue
            label = await self._safe_locator_text(button)
            aria = (await button.get_attribute("aria-label") or "").strip()
            combined = f"{label} {aria}".lower()
            if re.search(r"continue|next|review|submit|volgende|beoordelen|versturen", combined):
                primary_button = label or aria
                break

        controls = modal.locator(
            "input:not([type='hidden']):not([disabled]), "
            "textarea, "
            "select, "
            "button[aria-haspopup='listbox'], "
            "button.artdeco-dropdown__trigger"
        )
        control_count = await controls.count()
        seen = set()
        fields = []

        for index in range(control_count):
            control = controls.nth(index)
            try:
                if not await control.is_visible(timeout=150):
                    continue
            except Exception:
                continue

            try:
                field = await control.evaluate(
                    """(control) => {
                        function clean(text) {
                            return (text || "").replace(/\\s+/g, " ").trim();
                        }

                        function dedupeRepeatedPhrase(text) {
                            const cleaned = clean(text);
                            if (!cleaned) return "";
                            const words = cleaned.split(" ").filter(Boolean);
                            if (words.length >= 4 && words.length % 2 === 0) {
                                const half = words.length / 2;
                                const first = words.slice(0, half).join(" ");
                                const second = words.slice(half).join(" ");
                                if (first.toLowerCase() === second.toLowerCase()) {
                                    return first;
                                }
                            }
                            return cleaned;
                        }

                        function textOf(el) {
                            return dedupeRepeatedPhrase(clean(el?.innerText || el?.textContent || ""));
                        }

                        function controlKind(el) {
                            const tag = (el.tagName || "").toLowerCase();
                            const type = (el.getAttribute("type") || "").toLowerCase();
                            if (tag === "textarea") return "textarea";
                            if (tag === "select") return "select";
                            if (tag === "input" && type) return type;
                            if (tag === "button") return "dropdown";
                            return tag || "unknown";
                        }

                        function currentValue(el) {
                            const kind = controlKind(el);
                            if (kind === "radio" || kind === "checkbox") {
                                if (kind === "checkbox") {
                                    return el.checked ? "checked" : "";
                                }

                                const name = el.getAttribute("name") || "";
                                const radios = Array.from(
                                    container.querySelectorAll(
                                        name
                                            ? `input[type="radio"][name="${CSS.escape(name)}"]`
                                            : 'input[type="radio"]'
                                    )
                                );
                                const checked = radios.find(radio => radio.checked);
                                if (!checked) {
                                    return "";
                                }

                                const checkedId = checked.getAttribute("id");
                                if (checkedId) {
                                    const label = container.querySelector(`label[for="${checkedId}"]`);
                                    const labelText = textOf(label).replace(/\\*+/g, "");
                                    if (labelText) return labelText;
                                }

                                const closestLabel = checked.closest("label");
                                if (closestLabel) {
                                    const labelText = textOf(closestLabel).replace(/\\*+/g, "");
                                    if (labelText) return labelText;
                                }

                                return "checked";
                            }
                            if (kind === "select") {
                                const option = el.options[el.selectedIndex];
                                const text = dedupeRepeatedPhrase(clean(option ? option.text : ""));
                                return /^(select an option|selecteer een optie|choose an option|kies een optie)$/i.test(text)
                                    ? ""
                                    : text;
                            }
                            if (kind === "dropdown") {
                                const text = dedupeRepeatedPhrase(clean(textOf(el)));
                                return /^(select an option|selecteer een optie|choose an option|kies een optie)$/i.test(text)
                                    ? ""
                                    : text;
                            }
                            return dedupeRepeatedPhrase(clean(el.value || ""));
                        }

                        function getQuestion(container, el, kind) {
                            const controlId = el.getAttribute("id");
                            const legend = container.querySelector("legend");
                            if (legend) {
                                const candidate = clean(textOf(legend).replace(/\\*+/g, ""));
                                if (candidate) return candidate;
                            }

                            if (kind !== "radio" && kind !== "checkbox") {
                                const root = el.getRootNode && el.getRootNode();
                                if (controlId) {
                                    let explicitLabel = container.querySelector(`label[for="${controlId}"]`);
                                    if (!explicitLabel && root && root.querySelector) {
                                        explicitLabel = root.querySelector(`label[for="${controlId}"]`);
                                    }
                                    if (explicitLabel) return clean(textOf(explicitLabel).replace(/\\*+/g, ""));
                                }

                                const closestLabel = el.closest("label");
                                if (closestLabel) {
                                    const candidate = clean(textOf(closestLabel).replace(/\\*+/g, ""));
                                    if (candidate) return candidate;
                                }
                            }

                            const labels = Array.from(container.querySelectorAll("label, legend, span, p, h3, h4, div"))
                                .map(textOf)
                                .map(t => clean(t.replace(/\\*+/g, "")))
                                .filter(Boolean)
                                .filter(t => !/^(yes|no|required|optional|select an option|selecteer een optie)$/i.test(t));

                            const questionLike = labels.find(t => t.includes("?"));
                            if (questionLike) {
                                return dedupeRepeatedPhrase(
                                    clean(questionLike.replace(/\b(required|optional)\b/ig, ""))
                                );
                            }

                            const fallback = labels.find(t => t.length > 2) || "";
                            return dedupeRepeatedPhrase(
                                clean(fallback.replace(/\b(required|optional)\b/ig, ""))
                            );
                        }

                        const container =
                            control.closest(".jobs-easy-apply-form-section__grouping") ||
                            control.closest(".fb-dash-form-element") ||
                            control.closest("fieldset") ||
                            control.parentElement ||
                            control;

                        const kind = controlKind(control);
                        const question = getQuestion(container, control, kind);
                        const name = clean(control.getAttribute("name") || "");
                        const containerText = textOf(container);
                        const requiredText = `${question} ${containerText}`.toLowerCase();
                        const isConsentCheckbox =
                            kind === "checkbox" &&
                            (
                                /consent|privacy|collect.*process|process.*data|store.*process|data for the purpose/.test(requiredText) ||
                                /toestemming|gegevens|privacy|vink selectievakje|selectievakje aan/.test(requiredText)
                            );
                        const required =
                            control.required ||
                            control.getAttribute("aria-required") === "true" ||
                            /\\*/.test(containerText) ||
                            /\\b(required|verplicht)\\b/i.test(requiredText) ||
                            isConsentCheckbox;
                        const value = currentValue(control);
                        const invalid =
                            control.getAttribute("aria-invalid") === "true" ||
                            /enter a whole number/i.test(containerText) ||
                            /voer een geheel getal/i.test(containerText) ||
                            /whole number between/i.test(containerText) ||
                            /enter a decimal number/i.test(containerText) ||
                            /decimal number larger than/i.test(containerText) ||
                            /voer een decimaal getal/i.test(containerText);

                        return {
                            question,
                            kind,
                            required,
                            answered: !!value && !invalid,
                            invalid,
                            value,
                            name,
                        };
                    }"""
                )
            except Exception:
                continue

            question = (field.get("question") or "").strip()
            if not question:
                continue
            key = f"{question}|{field.get('kind', '')}|{field.get('name', '')}"
            if key in seen:
                continue
            seen.add(key)
            fields.append(field)

        return {
            "open": True,
            "title": title,
            "text": text,
            "primary_button": primary_button,
            "fields": fields,
            "interop_host": bool(is_interop_host),
        }

    def _active_easy_apply_modal_locator(self):
        """Sync locator — prefers LinkedIn-specific selectors over generic [role='dialog']."""
        # Try LinkedIn-specific classes first; these are less ambiguous than [role='dialog']
        # which can match unrelated overlays (help bubbles, notification popovers, etc.)
        specific = self.browser.page.locator(
            "[data-test-modal-container]:visible, .jobs-easy-apply-modal:visible, "
            "#interop-outlet:visible, [data-testid='interop-shadowdom']:visible"
        )
        # Playwright locators are lazy — we can return the more-specific one directly.
        # Callers that need async resolution should use _get_active_modal_locator() instead.
        return self.browser.page.locator(
            "[data-test-modal-container]:visible, .jobs-easy-apply-modal:visible, "
            "#interop-outlet:visible, [data-testid='interop-shadowdom']:visible, "
            "[role='dialog'][aria-labelledby]:visible, [role='dialog']:visible"
        ).last

    async def _get_active_modal_locator(self):
        """Find the active Easy Apply modal using Playwright locators.

        This intentionally avoids document.querySelector-based inspection because
        LinkedIn sometimes renders the modal through interop/shadow-dom layers.
        """
        modal_markers = re.compile(
            r"apply to|contact info|contactgegevens|voornaam|first name|achternaam|"
            r"last name|landcode|country code|e-mailadres|email address|"
            r"application powered by greenhouse|resume|additional questions|"
            r"review your application|submit application|sollicitatie versturen|"
            r"beoordelen|work authorization",
            re.IGNORECASE,
        )

        selectors = [
            "[data-test-modal-container]",
            ".jobs-easy-apply-modal",
            ".artdeco-modal",
            ".artdeco-modal__content",
            "#interop-outlet",
            "[data-testid='interop-shadowdom']",
            "[role='dialog']",
        ]

        for selector in selectors:
            loc = self.browser.page.locator(f"{selector}:visible")
            try:
                count = await loc.count()
            except Exception:
                continue

            for index in range(count - 1, -1, -1):
                candidate = loc.nth(index)
                try:
                    text = await candidate.inner_text(timeout=500)
                except Exception:
                    text = ""
                if modal_markers.search(text or ""):
                    print(f"[MODAL-SELECT] Using {selector} with Easy Apply markers")
                    return candidate

            if count > 0 and selector in {
                "[data-test-modal-container]",
                ".jobs-easy-apply-modal",
                ".artdeco-modal",
                ".artdeco-modal__content",
                "#interop-outlet",
                "[data-testid='interop-shadowdom']",
            }:
                print(f"[MODAL-SELECT] Using visible modal selector fallback: {selector}")
                return loc.nth(count - 1)

        button_loc = self.browser.page.get_by_role(
            "button",
            name=re.compile(r"next|review|submit|continue|volgende|beoordelen|versturen", re.IGNORECASE),
        )
        try:
            button_count = await button_loc.count()
            for index in range(button_count):
                button = button_loc.nth(index)
                try:
                    if not await button.is_visible(timeout=150):
                        continue
                except Exception:
                    continue
                ancestor = button.locator(
                    "xpath=ancestor-or-self::*[@data-test-modal-container or contains(@class,'jobs-easy-apply-modal') or contains(@class,'artdeco-modal') or @role='dialog'][1]"
                ).first
                try:
                    if await ancestor.is_visible(timeout=150):
                        print("[MODAL-SELECT] Using button-seeded modal ancestor")
                        return ancestor
                except Exception:
                    continue
        except Exception:
            pass

        print("[MODAL-SELECT] No Easy Apply modal found")
        return None

    async def _safe_locator_text(self, locator) -> str:
        try:
            return (await locator.inner_text(timeout=500)).strip()
        except Exception:
            return ""

    async def _is_interop_host_visible(self) -> bool:
        return await self._is_any_visible(self.INTEROP_HOST_SELECTORS)

    async def _get_interop_host_locator(self):
        for selector in self.INTEROP_HOST_SELECTORS:
            locator = self.browser.page.locator(f"{selector}:visible")
            try:
                count = await locator.count()
            except Exception:
                continue
            if count > 0:
                return locator.nth(count - 1)
        return None

    async def _scroll_modal_to_element(self, element_locator) -> None:
        """Scroll an element into view inside the modal.

        Walks up the DOM only until it hits the modal boundary or document.body —
        never scrolls the background page.
        """
        try:
            element_handle = await element_locator.element_handle()
            if not element_handle:
                return
            await self.browser.page.evaluate(
                """(el) => {
                    if (!el) return;
                    const MODAL_SELECTOR =
                        "[data-test-modal-container], .jobs-easy-apply-modal, " +
                        "#interop-outlet, [data-testid='interop-shadowdom'], [role='dialog']";
                    let container = el.parentElement;
                    // Hard stop: never walk above the modal or above document.body
                    while (container && container !== document.body && container !== document.documentElement) {
                        if (container.matches(MODAL_SELECTOR)) {
                            const eRect = el.getBoundingClientRect();
                            const cRect = container.getBoundingClientRect();
                            if (eRect.bottom > cRect.bottom) {
                                container.scrollTop += (eRect.bottom - cRect.bottom) + 24;
                            } else if (eRect.top < cRect.top) {
                                container.scrollTop -= (cRect.top - eRect.top) + 24;
                            }
                            return;
                        }
                        const style = window.getComputedStyle(container);
                        const overflow = style.overflowY || "";
                        if (/(auto|scroll)/i.test(overflow) && container.scrollHeight > container.clientHeight + 5) {
                            const eRect = el.getBoundingClientRect();
                            const cRect = container.getBoundingClientRect();
                            if (eRect.bottom > cRect.bottom) {
                                container.scrollTop += (eRect.bottom - cRect.bottom) + 24;
                            } else if (eRect.top < cRect.top) {
                                container.scrollTop -= (cRect.top - eRect.top) + 24;
                            }
                            return;
                        }
                        container = container.parentElement;
                    }
                    // Reached modal boundary without finding a scrollable ancestor — do nothing
                }""",
                element_handle,
            )
        except Exception:
            pass

    async def _scroll_modal_down(self, amount: int = 300) -> bool:
        """Scroll down inside the Easy Apply modal without touching the background page.

        Excludes the modal root element itself and any element that covers most of
        the viewport (which is a full-page overlay, not the scrollable content area).
        Returns True if a modal was found and scrolled.
        """
        result = await self.browser.page.evaluate(
            """(amount) => {
                function visible(el) {
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.visibility !== "hidden" && s.display !== "none" && r.width > 0 && r.height > 0;
                }
                // Pick the most relevant Easy Apply modal
                const candidates = Array.from(document.querySelectorAll(
                    "[data-test-modal-container], .jobs-easy-apply-modal, " +
                    "#interop-outlet, [data-testid='interop-shadowdom'], [role='dialog']"
                )).filter(visible);
                if (!candidates.length) return false;
                // Sort by z-index descending; take highest
                candidates.sort((a, b) => {
                    function maxZ(el) {
                        let z = 0, n = el;
                        while (n) { const v = parseInt(window.getComputedStyle(n).zIndex, 10); if (!isNaN(v) && v > z) z = v; n = n.parentElement; }
                        return z;
                    }
                    return maxZ(b) - maxZ(a);
                });
                const modal = candidates[0];

                const vpW = window.innerWidth;
                const vpH = window.innerHeight;

                // Search only INSIDE the modal (exclude the modal root itself).
                // Also exclude anything that covers ≥95 % of the viewport — those are
                // full-page overlays, not the scrollable content box.
                const scrollables = Array.from(modal.querySelectorAll("*")).filter(el => {
                    if (!visible(el)) return false;
                    const s = window.getComputedStyle(el);
                    if (!/(auto|scroll)/i.test(s.overflowY || "")) return false;
                    if (el.scrollHeight <= el.clientHeight + 10) return false;
                    const r = el.getBoundingClientRect();
                    if (r.width > vpW * 0.95 && r.height > vpH * 0.9) return false;
                    return true;
                });
                scrollables.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                // Never fall back to scrolling the modal root — if nothing inner is
                // scrollable the content already fits and we must not touch the page.
                if (!scrollables.length) return false;
                const target = scrollables[0];

                const before = target.scrollTop;
                target.scrollTop = Math.min(target.scrollTop + amount, target.scrollHeight);
                target.dispatchEvent(new Event("scroll", { bubbles: true }));
                return target.scrollTop > before;  // true = actually scrolled
            }""",
            amount,
        )
        if result:
            print(f"[MODAL-SCROLL] Scrolled {amount}px within modal container")
        else:
            print("[MODAL-SCROLL] No scrollable modal container found (or already at bottom)")
        return bool(result)

    async def is_easy_apply_flow_active(self) -> bool:
        # Retry briefly — the modal may not have fully rendered yet when first checked.
        for attempt in range(3):
            if await self.is_easy_apply_modal_open() or await self._is_interop_host_visible():
                return True
            if attempt < 2:
                await asyncio.sleep(0.8)
        try:
            page_text = (await self.browser.get_page_text()).lower()
        except Exception:
            return False
        return any(
            marker in page_text
            for marker in [
                "contact info",
                "contact information",
                "resume",
                "additional questions",
                "review your application",
                "submit application",
                "application submitted",
                "application sent",
            ]
        )

    async def handle_easy_apply_modal(self, brain) -> dict | None:
        state = await self.inspect_easy_apply_modal()
        if not state.get("open"):
            return None

        modal_title = state.get("title", "")
        primary_button = state.get("primary_button", "")
        field_count = len(state.get("fields", []))
        print(
            f"[MODAL] Active — title='{modal_title}' "
            f"primary_button='{primary_button}' fields={field_count}"
        )

        modal_text = (state.get("text") or "").lower()
        if any(marker in modal_text for marker in [
            "application submitted",
            "your application was sent",
            "application sent",
            "submitted successfully",
        ]):
            print("[MODAL] Confirmation text detected — application submitted")
            return {
                "status": "applied",
                "reason": "LinkedIn Easy Apply confirmation detected",
            }

        unknown_questions = []
        filled_any = False
        ai_filled_questions = []

        for field in state.get("fields", []):
            if field.get("answered"):
                continue

            question_text = field.get("question", "")
            context = state.get("text", "")
            answer_source = "structured"
            answer = brain.get_structured_question_answer(question_text, context=context)

            if not field.get("required"):
                if not answer:
                    continue
            elif not answer:
                try:
                    print(f"[MODAL] Asking AI fallback for required field: '{question_text[:80]}'")
                    answer = brain.answer_question(question_text, context=context)
                    answer_source = "ai"
                except Exception as exc:
                    print(f"[MODAL] AI fallback failed for '{question_text[:80]}': {exc}")
                    answer = ""
            if field.get("required") and not answer:
                print(f"[MODAL] No answer found for required field: '{question_text[:80]}'")
                unknown_questions.append(question_text)
                continue

            answer = self._normalize_answer_for_field(field, answer)
            if field.get("required") and not str(answer).strip():
                print(f"[MODAL] Normalized answer is empty for required field: '{question_text[:80]}'")
                unknown_questions.append(question_text)
                continue

            filled = await self._fill_easy_apply_field(field, answer)
            if filled:
                print(
                    f"[MODAL] Filled ({answer_source}) field "
                    f"'{question_text[:60]}' = '{str(answer)[:40]}'"
                )
                if answer_source == "ai":
                    ai_filled_questions.append(question_text)
                filled_any = True
            else:
                print(f"[MODAL] Failed to fill field: '{question_text[:80]}'")
                if field.get("required"):
                    unknown_questions.append(question_text)

        if unknown_questions:
            return {
                "status": "failed",
                "reason": f"Could not answer or fill LinkedIn Easy Apply question: {unknown_questions[0]}",
                "questions": unknown_questions,
            }

        if filled_any:
            # Give LinkedIn a moment to run its validation after we filled fields
            await asyncio.sleep(0.5)
            if ai_filled_questions:
                await self._persist_verified_ai_answers(brain, ai_filled_questions)
            return {
                "status": "continue",
                "reason": "Filled LinkedIn Easy Apply fields",
            }

        # All required fields are satisfied.
        # Fire React input/change/blur events on any pre-filled fields so that
        # LinkedIn's internal validation state is in sync before we click Next.
        await self._touch_prefilled_fields()

        # Try clicking the primary button.
        clicked = await self._click_easy_apply_primary_button(primary_button)
        if clicked:
            await asyncio.sleep(1.5)
            return {
                "status": "continue",
                "reason": f"Clicked modal primary button: {primary_button!r}",
            }

        print("[MODAL] Waiting for stable actionable state in modal...")
        return {
            "status": "continue",
            "reason": "Easy Apply modal is open — waiting for a stable actionable button",
            "questions": [],
        }

    async def capture_answered_questions(self, questions: list[str]) -> dict:
        if not questions:
            return {}

        state = await self.inspect_easy_apply_modal()
        learned = {}
        normalized_questions = {self._normalize_question(question): question for question in questions if question}
        for field in state.get("fields", []):
            normalized = self._normalize_question(field.get("question", ""))
            if normalized in normalized_questions and field.get("answered") and field.get("value"):
                learned[normalized_questions[normalized]] = field.get("value", "").strip()
        return learned

    async def _persist_verified_ai_answers(self, brain, questions: list[str]) -> None:
        """Save AI answers only after LinkedIn accepts them in the modal."""
        verified_answers = await self.capture_answered_questions(questions)
        for question in questions:
            accepted_value = verified_answers.get(question)
            if not accepted_value:
                continue
            brain.save_learned_answer(question, accepted_value)
            print(f"[MODAL] Learned accepted AI answer for future runs: '{question[:60]}'")

    async def _try_click_apply_strategy(self, strategy: str, value: str) -> bool:
        try:
            if strategy == "selector":
                locator = self.browser.page.locator(value).first
            elif strategy == "role_button":
                locator = self.browser.page.get_by_role("button", name=re.compile(value, re.IGNORECASE)).first
            elif strategy == "role_link":
                locator = self.browser.page.get_by_role("link", name=re.compile(value, re.IGNORECASE)).first
            else:
                return False

            if await locator.is_visible(timeout=2500):
                await locator.click()
                await self.browser.human_delay(0.3, 0.8)
                return True
        except Exception:
            return False
        return False

    async def _touch_prefilled_fields(self) -> None:
        """Fire input/change/blur events on already-filled form fields.

        LinkedIn's React form tracks internal state separately from DOM values.
        When fields are pre-filled (email, phone) but the user never typed in
        them, React's internal state may still be empty, causing the Next button
        to appear enabled but silently do nothing when clicked.  This method
        re-syncs React's state by dispatching the native events React intercepts.
        """
        modal = await self._get_active_modal_locator()
        if modal is None:
            return

        inputs = modal.locator(
            'input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]), textarea'
        )
        try:
            count = await inputs.count()
        except Exception:
            return

        for index in range(count):
            input_locator = inputs.nth(index)
            try:
                if not await input_locator.is_visible(timeout=150):
                    continue
                value = await input_locator.input_value()
                if not value:
                    continue
                await input_locator.evaluate(
                    """(el) => {
                        try {
                            const proto = Object.getOwnPropertyDescriptor(
                                el.tagName === 'TEXTAREA'
                                    ? window.HTMLTextAreaElement.prototype
                                    : window.HTMLInputElement.prototype,
                                'value'
                            );
                            if (proto && proto.set) proto.set.call(el, el.value);
                        } catch (_) {}
                        el.dispatchEvent(new Event('input',  { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur',   { bubbles: true }));
                    }"""
                )
            except Exception:
                continue

    async def _fill_easy_apply_field(self, field: dict, answer: str) -> bool:
        container = self._question_container_locator(field.get("question", ""))
        if container is None:
            return False

        kind = (field.get("kind") or "").lower()
        if kind in {"text", "email", "tel", "number", "textarea"}:
            return await self._fill_text_like_field(container, answer)
        if kind == "select":
            return await self._select_native_option(container, field.get("question", ""), answer)
        if kind in {"dropdown", "radio"}:
            return await self._choose_modal_option(container, field.get("question", ""), answer)
        if kind == "checkbox":
            return await self._set_checkbox_field_value(field, container, answer)
        return False

    def _question_container_locator(self, question: str):
        search_terms = self._question_search_terms(question)
        if not search_terms:
            return None

        modal = self._active_easy_apply_modal_locator()
        containers = []
        for search_term in search_terms:
            containers.extend([
                modal.locator(".jobs-easy-apply-form-section__grouping").filter(has_text=search_term).first,
                modal.locator(".fb-dash-form-element").filter(has_text=search_term).first,
                modal.locator("fieldset").filter(has_text=search_term).first,
            ])
        return containers

    async def _find_visible_container(self, question: str):
        containers = self._question_container_locator(question)
        if not containers:
            return None
        for locator in containers:
            try:
                if await locator.is_visible(timeout=1500):
                    return locator
            except Exception:
                continue
        return None

    async def _fill_text_like_field(self, containers, answer: str) -> bool:
        for container in containers:
            try:
                if not await container.is_visible(timeout=1000):
                    continue
                input_locator = container.locator("textarea, input:not([type='hidden']):not([type='radio']):not([type='checkbox'])").first
                if await input_locator.is_visible(timeout=1000):
                    await input_locator.fill(answer)
                    await self.browser.human_delay(0.2, 0.6)
                    return True
            except Exception:
                continue
        return False

    def _normalize_answer_for_field(self, field: dict, answer) -> str:
        normalized = str(answer or "").strip()
        if not normalized:
            return ""

        kind = (field.get("kind") or "").lower()
        question = (field.get("question") or "").lower()

        if kind in {"radio", "select", "dropdown"}:
            lowered = normalized.lower()
            if lowered.startswith(("yes", "ja", "yep", "affirmative")):
                return "Yes"
            if lowered.startswith(("no", "nee", "nope", "negative", "not ", "do not", "don't")):
                return "No"

        if kind in {"text", "textarea", "number"} and self._looks_like_numeric_question(question):
            coerced = self._coerce_numeric_answer(normalized)
            if coerced:
                return coerced

        return normalized

    def _looks_like_numeric_question(self, question: str) -> bool:
        lowered = (question or "").lower()
        return any(
            token in lowered
            for token in [
                "how many",
                "hoeveel",
                "years of work experience",
                "years of experience",
                "year of experience",
                "jaar werkervaring",
                "jaar ervaring",
                "whole number",
                "geheel getal",
                "average deal size",
                "deal size",
                "eur",
                "euro",
                "decimal number",
                "thousands",
                "amount",
                "revenue",
            ]
        )

    def _coerce_numeric_answer(self, answer: str) -> str:
        lowered = (answer or "").strip().lower()
        if not lowered:
            return ""
        if lowered in {"yes", "ja"}:
            return "1"
        if lowered in {"no", "nee", "none", "n/a"}:
            return "0"
        if lowered.startswith(("no", "nee", "none", "not ", "don't", "do not")):
            return "0"

        match = re.search(r"\d+(?:[.,]\d+)?", lowered)
        if not match:
            return ""

        numeric = match.group(0).replace(",", ".")
        try:
            return str(max(0, int(float(numeric))))
        except ValueError:
            return ""

    async def _select_native_option(self, containers, question: str, answer: str) -> bool:
        candidates = self._option_candidates(question, answer)
        for container in containers:
            try:
                if not await container.is_visible(timeout=1000):
                    continue
                select_locator = container.locator("select").first
                if not await select_locator.is_visible(timeout=1000):
                    continue
                for candidate in candidates:
                    try:
                        await select_locator.select_option(label=candidate)
                        await self.browser.human_delay(0.2, 0.5)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    async def _choose_modal_option(self, containers, question: str, answer: str) -> bool:
        candidates = self._option_candidates(question, answer)
        for container in containers:
            try:
                if not await container.is_visible(timeout=1000):
                    continue

                radio_labels = container.locator("label")
                count = await radio_labels.count()
                if count:
                    for index in range(count):
                        label = radio_labels.nth(index)
                        text = (await label.inner_text()).strip()
                        if self._matches_any_option(text, candidates):
                            await label.click()
                            await self.browser.human_delay(0.2, 0.5)
                            return True

                dropdown = container.locator("button[aria-haspopup='listbox'], button.artdeco-dropdown__trigger").first
                if await dropdown.is_visible(timeout=1000):
                    await dropdown.click()
                    await self.browser.human_delay(0.3, 0.8)
                    if await self._click_visible_option(candidates):
                        return True
            except Exception:
                continue
        return False

    async def _set_checkbox_field_value(self, field: dict, containers, answer: str) -> bool:
        if await self._set_checkbox_value(containers, answer):
            return True

        modal = await self._get_active_modal_locator()
        if modal is None:
            return False

        desired = answer.strip().lower() in {"yes", "true", "checked"}
        question = field.get("question", "")
        name = field.get("name", "")
        try:
            changed = await modal.evaluate(
                """(root, args) => {
                    const { desired, question, name } = args;

                    function clean(text) {
                        return (text || "").replace(/\\s+/g, " ").trim();
                    }

                    function textOf(el) {
                        return clean(el?.innerText || el?.textContent || "");
                    }

                    function isVisible(el) {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== "hidden" &&
                            style.display !== "none" &&
                            rect.width > 0 &&
                            rect.height > 0;
                    }

                    function dispatch(el) {
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        el.dispatchEvent(new Event("blur", { bubbles: true }));
                    }

                    function setNative(box) {
                        if (!box) return false;
                        if (box.checked === desired) return true;

                        const id = box.getAttribute("id");
                        const label = id
                            ? root.querySelector(`label[for="${CSS.escape(id)}"]`)
                            : null;
                        const wrappingLabel = box.closest("label");

                        for (const target of [label, wrappingLabel, box]) {
                            if (!target) continue;
                            try {
                                target.click();
                                dispatch(box);
                                if (box.checked === desired) return true;
                            } catch (_) {}
                        }

                        try {
                            const descriptor = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype,
                                "checked"
                            );
                            if (descriptor && descriptor.set) {
                                descriptor.set.call(box, desired);
                            } else {
                                box.checked = desired;
                            }
                            dispatch(box);
                            return box.checked === desired;
                        } catch (_) {
                            return false;
                        }
                    }

                    function setRoleCheckbox(box) {
                        if (!box) return false;
                        const current = box.getAttribute("aria-checked") === "true";
                        if (current === desired) return true;
                        try {
                            box.click();
                            if ((box.getAttribute("aria-checked") === "true") === desired) {
                                return true;
                            }
                        } catch (_) {}
                        box.setAttribute("aria-checked", String(desired));
                        box.dispatchEvent(new Event("change", { bubbles: true }));
                        return (box.getAttribute("aria-checked") === "true") === desired;
                    }

                    const questionLower = clean(question).toLowerCase();
                    const consentPattern =
                        /consent|privacy|collect.*process|process.*data|store.*process|data for the purpose|toestemming|gegevens|selectievakje/;
                    const nativeBoxes = Array.from(root.querySelectorAll('input[type="checkbox"]'));
                    const roleBoxes = Array.from(root.querySelectorAll('[role="checkbox"]'));

                    if (name) {
                        const byName = nativeBoxes.find(box => box.getAttribute("name") === name);
                        if (byName && setNative(byName)) return true;
                    }

                    const nativeMatches = nativeBoxes.filter(box => {
                        const id = box.getAttribute("id");
                        const label = id
                            ? root.querySelector(`label[for="${CSS.escape(id)}"]`)
                            : null;
                        const container = box.closest("fieldset, .fb-dash-form-element, .jobs-easy-apply-form-section__grouping, div") || box.parentElement || box;
                        const text = clean(`${textOf(label)} ${textOf(box.closest("label"))} ${textOf(container)}`).toLowerCase();
                        return text.includes(questionLower.slice(0, 60)) ||
                            consentPattern.test(text) ||
                            consentPattern.test(questionLower);
                    });

                    for (const box of nativeMatches) {
                        if (setNative(box)) return true;
                    }

                    const roleMatches = roleBoxes.filter(box => {
                        const container = box.closest("fieldset, .fb-dash-form-element, .jobs-easy-apply-form-section__grouping, div") || box.parentElement || box;
                        const text = clean(`${textOf(box)} ${textOf(container)}`).toLowerCase();
                        return text.includes(questionLower.slice(0, 60)) ||
                            consentPattern.test(text) ||
                            consentPattern.test(questionLower);
                    });

                    for (const box of roleMatches) {
                        if (setRoleCheckbox(box)) return true;
                    }

                    if (consentPattern.test(questionLower)) {
                        const visibleNative = nativeBoxes.find(isVisible) || nativeBoxes[0];
                        if (visibleNative && setNative(visibleNative)) return true;

                        const visibleRole = roleBoxes.find(isVisible) || roleBoxes[0];
                        if (visibleRole && setRoleCheckbox(visibleRole)) return true;

                        const yesLabel = Array.from(root.querySelectorAll("label, span, div, p"))
                            .find(el => /^yes$|^ja$/i.test(clean(textOf(el))));
                        if (yesLabel) {
                            try {
                                yesLabel.click();
                            } catch (_) {}
                            const checkedNative = nativeBoxes.some(box => box.checked === desired);
                            const checkedRole = roleBoxes.some(box => (box.getAttribute("aria-checked") === "true") === desired);
                            if (checkedNative || checkedRole) return true;
                        }
                    }

                    return false;
                }""",
                {"desired": desired, "question": question, "name": name},
            )
            if changed:
                await self.browser.human_delay(0.2, 0.5)
                print(f"[MODAL] Checkbox fallback selected '{question[:60]}'")
                return True
        except Exception:
            return False

        return False

    async def _set_checkbox_value(self, containers, answer: str) -> bool:
        desired = answer.strip().lower() in {"yes", "true", "checked"}
        for container in containers:
            try:
                if not await container.is_visible(timeout=1000):
                    continue

                if await self._checkbox_container_matches(container, desired):
                    return True

                checkboxes = container.locator("input[type='checkbox']")
                checkbox_count = await checkboxes.count()
                for index in range(checkbox_count):
                    checkbox = checkboxes.nth(index)
                    try:
                        current = await checkbox.is_checked()
                        if current == desired:
                            return True

                        try:
                            if await checkbox.is_visible(timeout=200):
                                await checkbox.click(timeout=1000)
                            else:
                                await checkbox.click(timeout=1000, force=True)
                        except Exception:
                            await checkbox.evaluate(
                                """(el, desired) => {
                                    const descriptor = Object.getOwnPropertyDescriptor(
                                        window.HTMLInputElement.prototype,
                                        'checked'
                                    );
                                    if (descriptor && descriptor.set) {
                                        descriptor.set.call(el, desired);
                                    } else {
                                        el.checked = desired;
                                    }
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                                }""",
                                desired,
                            )

                        await self.browser.human_delay(0.2, 0.5)
                        if await self._checkbox_container_matches(container, desired):
                            return True
                    except Exception:
                        continue

                clickable_targets = [
                    container.locator("[role='checkbox']").first,
                    container.locator("label").first,
                    container.locator(".artdeco-checkbox").first,
                    container.locator(".fb-dash-form-element__checkbox").first,
                    container.locator("span, div").filter(has_text=re.compile(r"^(yes|ja)$", re.IGNORECASE)).first,
                ]
                for target in clickable_targets:
                    try:
                        if not await target.is_visible(timeout=300):
                            continue
                        await target.click(timeout=1000)
                        await self.browser.human_delay(0.2, 0.5)
                        if await self._checkbox_container_matches(container, desired):
                            return True
                    except Exception:
                        continue

                changed = await container.evaluate(
                    """(root, desired) => {
                        const boxes = Array.from(root.querySelectorAll('input[type="checkbox"]'));
                        for (const box of boxes) {
                            const descriptor = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype,
                                'checked'
                            );
                            if (descriptor && descriptor.set) {
                                descriptor.set.call(box, desired);
                            } else {
                                box.checked = desired;
                            }
                            box.dispatchEvent(new Event('input', { bubbles: true }));
                            box.dispatchEvent(new Event('change', { bubbles: true }));
                            box.dispatchEvent(new Event('blur', { bubbles: true }));
                        }

                        for (const box of Array.from(root.querySelectorAll('[role="checkbox"]'))) {
                            box.setAttribute('aria-checked', String(desired));
                            box.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                            box.dispatchEvent(new Event('change', { bubbles: true }));
                        }

                        return boxes.length > 0 || root.querySelectorAll('[role="checkbox"]').length > 0;
                    }""",
                    desired,
                )
                if changed:
                    await self.browser.human_delay(0.2, 0.5)
                    if await self._checkbox_container_matches(container, desired):
                        return True
            except Exception:
                continue
        return False

    async def _checkbox_container_matches(self, container, desired: bool) -> bool:
        try:
            checkboxes = container.locator("input[type='checkbox']")
            count = await checkboxes.count()
            for index in range(count):
                try:
                    if await checkboxes.nth(index).is_checked() == desired:
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        try:
            role_checkboxes = container.locator("[role='checkbox']")
            count = await role_checkboxes.count()
            for index in range(count):
                try:
                    aria_checked = (
                        await role_checkboxes.nth(index).get_attribute("aria-checked")
                        or ""
                    ).lower()
                    if (aria_checked == "true") == desired:
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    async def _click_visible_option(self, candidates: list[str]) -> bool:
        option_locators = [
            self.browser.page.locator("[role='option']"),
            self.browser.page.locator(".artdeco-dropdown__item"),
            self.browser.page.locator("li"),
        ]
        for option_locator in option_locators:
            try:
                count = await option_locator.count()
                for index in range(count):
                    option = option_locator.nth(index)
                    if not await option.is_visible(timeout=200):
                        continue
                    text = (await option.inner_text()).strip()
                    if self._matches_any_option(text, candidates):
                        await option.click()
                        await self.browser.human_delay(0.2, 0.5)
                        return True
            except Exception:
                continue
        return False

    async def _click_easy_apply_primary_button(self, button_text: str) -> bool:
        """Click the primary action button inside the Easy Apply modal.

        Two-step approach:
        1. JavaScript locates the button and returns its viewport coordinates.
           This is immune to Playwright text-matching quirks and class-name changes.
        2. Playwright's page.mouse.click(x, y) performs the actual click.
           This dispatches the full mousedown→mouseup→click sequence that React/
           LinkedIn needs to recognise the interaction — bare JS btn.click() only
           fires the click event and is often silently ignored by React forms.
        """
        candidates = []
        if button_text and button_text.strip():
            candidates.append(button_text.strip())
        candidates.extend([
            "Continue to next step",
            "Next",
            "Volgende",           # Dutch UI variant
            "Review your application",
            "Review",
            "Submit application",
            "Submit",
            "Indienen",           # Dutch UI variant
            "Done",
        ])

        modal = await self._get_active_modal_locator()
        if modal is not None:
            buttons = modal.locator("button")
            try:
                button_count = await buttons.count()
            except Exception:
                button_count = 0

            for candidate in candidates:
                lowered = candidate.lower().strip()
                if not lowered:
                    continue
                for index in range(button_count):
                    button = buttons.nth(index)
                    try:
                        if not await button.is_visible(timeout=150):
                            continue
                        label = await self._safe_locator_text(button)
                        aria = (await button.get_attribute("aria-label") or "").strip()
                        combined = f"{label} {aria}".lower()
                        if lowered not in combined:
                            continue
                        await self._scroll_modal_to_element(button)
                        try:
                            await button.click(timeout=1500)
                        except Exception:
                            await button.click(timeout=1500, force=True)
                        await self.browser.human_delay(0.3, 0.8)
                        print(f"[MODAL-CLICK] Locator-clicked modal button '{label or aria or candidate}'")
                        return True
                    except Exception:
                        continue

        _JS_FIND_BUTTON = """(args) => {
            const { candidates } = args;

            function visible(el) {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.visibility !== 'hidden' && s.display !== 'none' &&
                       parseFloat(s.opacity || '1') > 0 &&
                       r.width > 0 && r.height > 0;
            }

            function maxZ(el) {
                let z = 0, node = el;
                while (node) {
                    const v = parseInt(window.getComputedStyle(node).zIndex, 10);
                    if (!isNaN(v) && v > z) z = v;
                    node = node.parentElement;
                }
                return z;
            }

            function looksLikeEasyApply(el) {
                const t = (el.innerText || '').toLowerCase();
                return t.includes('apply to') || t.includes('contact info') ||
                       t.includes('contactgegevens') ||
                       t.includes('contact information') || t.includes('resume') ||
                       t.includes('cv') || t.includes('additional questions') ||
                       t.includes('review your application') ||
                       t.includes('submit application') || t.includes('work authorization');
            }

            // Locate the modal — prefer specific selectors, fall back to [role='dialog']
            let modal = null;
            for (const sel of ['[data-test-modal-container]', '.jobs-easy-apply-modal']) {
                const el = document.querySelector(sel);
                if (el && visible(el)) { modal = el; break; }
            }
            if (!modal) {
                const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'))
                    .filter(visible);
                if (dialogs.length) {
                    dialogs.sort((a, b) => {
                        const sA = maxZ(a) + (looksLikeEasyApply(a) ? 10000 : 0);
                        const sB = maxZ(b) + (looksLikeEasyApply(b) ? 10000 : 0);
                        return sB - sA;
                    });
                    modal = dialogs[0];
                }
            }
            if (!modal) return { found: false, reason: 'no modal found' };

            const buttons = Array.from(modal.querySelectorAll('button')).filter(visible);

            for (const text of candidates) {
                const lower = text.toLowerCase().trim();
                if (!lower) continue;
                const btn = buttons.find(b => {
                    const bText = (b.textContent || '').trim().toLowerCase();
                    const bLabel = (b.getAttribute('aria-label') || '').trim().toLowerCase();
                    return bText === lower || bLabel === lower ||
                           bText.includes(lower) || bLabel.includes(lower);
                });
                if (!btn) continue;

                const rect = btn.getBoundingClientRect();
                const vpH = window.innerHeight;
                const vpW = window.innerWidth;
                return {
                    found: true,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    inViewport: rect.top >= 0 && rect.bottom <= vpH &&
                                rect.left >= 0 && rect.right <= vpW,
                    label: (btn.getAttribute('aria-label') || btn.textContent || text).trim().slice(0, 60),
                };
            }

            // Not found — return debug info
            const allButtons = buttons.map(b => ({
                text: (b.textContent || '').trim().slice(0, 50),
                label: b.getAttribute('aria-label') || '',
                disabled: b.disabled,
            }));
            return { found: false, reason: 'no matching button', buttons: allButtons };
        }"""

        for attempt in range(2):
            if attempt == 1:
                # Second attempt: try scrolling the modal down to reveal a hidden button
                await self._scroll_modal_down(200)
                await asyncio.sleep(0.3)

            info = await self.browser.page.evaluate(_JS_FIND_BUTTON, {"candidates": candidates})

            if not info.get("found"):
                if attempt == 1:
                    debug_buttons = info.get("buttons", [])
                    if debug_buttons:
                        readable = "; ".join(
                            f"'{b['text']}' (label='{b['label']}', disabled={b['disabled']})"
                            for b in debug_buttons[:6]
                        )
                        print(f"[MODAL-CLICK] No matching button. Visible buttons in modal: {readable}")
                    else:
                        print(f"[MODAL-CLICK] {info.get('reason', 'unknown')}")
                continue

            if not info.get("inViewport"):
                # Button exists but is off-screen — scroll and retry
                await self._scroll_modal_down(200)
                await asyncio.sleep(0.3)
                continue

            x, y = info["x"], info["y"]
            label = info.get("label", "?")
            print(f"[MODAL-CLICK] Mouse-clicking '{label}' at ({x:.0f}, {y:.0f})")
            # Use Playwright's real mouse events — this fires mousedown+mouseup+click
            # which React's synthetic event system requires to register the interaction.
            await self.browser.page.mouse.click(x, y)
            await self.browser.human_delay(0.3, 0.8)
            return True

        if await self._click_interop_primary_button_fallback():
            return True

        return False

    async def _click_interop_primary_button_fallback(self) -> bool:
        host = await self._get_interop_host_locator()
        if host is None:
            return False

        try:
            box = await host.bounding_box()
        except Exception:
            box = None
        if not box:
            return False

        viewport = self.browser.page.viewport_size or {
            "width": max(int(box["width"]), 1),
            "height": max(int(box["height"]), 1),
        }

        host_x = float(box["x"])
        host_y = float(box["y"])
        host_w = float(box["width"])
        host_h = float(box["height"])

        if host_w >= viewport["width"] * 0.9 and host_h >= viewport["height"] * 0.7:
            modal_w = min(host_w * 0.76, 780.0)
            modal_h = min(host_h * 0.78, 660.0)
            modal_x = host_x + (host_w - modal_w) / 2
            modal_y = host_y + max(24.0, (host_h - modal_h) / 2)
        else:
            modal_w = host_w
            modal_h = host_h
            modal_x = host_x
            modal_y = host_y

        click_points = [
            (modal_x + modal_w - 82.0, modal_y + modal_h - 34.0),
            (modal_x + modal_w - 120.0, modal_y + modal_h - 34.0),
            (modal_x + modal_w - 82.0, modal_y + modal_h - 56.0),
        ]

        for x, y in click_points:
            if x <= 0 or y <= 0:
                continue
            print(f"[MODAL-CLICK] Interop fallback click at ({x:.0f}, {y:.0f})")
            try:
                await self.browser.page.mouse.click(x, y)
                await self.browser.human_delay(0.3, 0.8)
                return True
            except Exception:
                continue

        return False

    def _option_candidates(self, question: str, answer: str) -> list[str]:
        raw = (answer or "").strip()
        lowered = raw.lower()
        candidates = [raw]
        question_lower = (question or "").lower()

        affirmative_prefixes = ("yes", "ja", "yep", "sure", "correct", "affirmative")
        negative_prefixes = ("no", "nee", "not", "don't", "do not", "nope")

        if lowered in {"yes", "true"} or any(lowered.startswith(prefix) for prefix in affirmative_prefixes):
            candidates.extend(["Yes", "Ja", "I do", "Present", "Y"])
        elif lowered in {"no", "false"} or any(lowered.startswith(prefix) for prefix in negative_prefixes):
            candidates.extend(["No", "Nee", "I do not", "N"])

        if "dutch" in question_lower:
            if any(token in lowered for token in ["b1", "intermediate", "conversational"]):
                candidates.extend(["Conversational", "Intermediate", "B1"])
            elif any(token in lowered for token in ["fluent", "c1", "c2", "advanced"]):
                candidates.extend(["Fluent", "Advanced", "C1", "C2"])
            elif any(token in lowered for token in ["basic", "a1", "a2"]):
                candidates.extend(["Basic", "Beginner", "A1", "A2"])

        if any(token in question_lower for token in ["where did you hear", "hear about this role", "hear about this job"]):
            if "linkedin" in lowered:
                candidates.extend(["LinkedIn"])
            if any(token in lowered for token in ["job board", "online job search", "online search"]):
                candidates.extend([
                    "Job board (e.g., Indeed, Glassdoor, Workopolis)",
                    "Job board",
                ])

        deduped = []
        for candidate in candidates:
            if candidate and candidate.lower() not in {item.lower() for item in deduped}:
                deduped.append(candidate)
        return deduped

    def _matches_any_option(self, text: str, candidates: list[str]) -> bool:
        lowered_text = (text or "").strip().lower()
        for candidate in candidates:
            lowered_candidate = (candidate or "").strip().lower()
            if not lowered_candidate:
                continue
            if lowered_text == lowered_candidate or lowered_candidate in lowered_text:
                return True
        return False

    def _normalize_question(self, question: str) -> str:
        normalized = re.sub(r"\s+", " ", (question or "").strip().lower())
        return re.sub(r"[^a-z0-9 ?/+-]", "", normalized)

    def _question_search_terms(self, question: str) -> list[str]:
        raw = re.sub(r"\s+", " ", (question or "").strip())
        if not raw:
            return []

        candidates = [raw]
        without_meta = re.sub(r"\b(required|optional)\b", "", raw, flags=re.IGNORECASE)
        without_meta = re.sub(r"\s+", " ", without_meta).strip(" -:")
        if without_meta:
            candidates.append(without_meta)

        duplicate_match = re.match(r"^(?P<phrase>.+?\?)(?:\s+(?P=phrase))+$", without_meta, flags=re.IGNORECASE)
        if duplicate_match:
            candidates.append(duplicate_match.group("phrase").strip())

        if "?" in without_meta:
            candidates.append(without_meta.split("?")[0].strip() + "?")

        deduped = []
        seen = set()
        for candidate in candidates:
            normalized = self._normalize_question(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(candidate)
        return deduped

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

    async def _wait_for_apply_state(self, attempts: int = 6, delay_seconds: float = 1.0):
        for _ in range(attempts):
            if await self._is_any_visible(self.EASY_APPLY_SELECTORS):
                return
            if await self._is_any_visible(self.ALREADY_APPLIED_SELECTORS):
                return
            if await self._is_any_visible(self.APPLY_SELECTORS):
                return

            try:
                page_text = (await self.browser.get_page_text()).lower()
                if any(marker in page_text for marker in [
                    "easy apply",
                    "already applied",
                    "application submitted",
                    "apply now",
                    "continue to next step",
                ]):
                    return
            except Exception:
                pass

            await asyncio.sleep(delay_seconds)

    async def _wait_for_easy_apply_modal(self, attempts: int = 5, delay_seconds: float = 1.0) -> bool:
        for _ in range(attempts):
            if await self.is_easy_apply_modal_open() or await self._is_interop_host_visible():
                return True
            try:
                page_text = (await self.browser.get_page_text()).lower()
                if any(marker in page_text for marker in [
                    "continue to next step",
                    "review your application",
                    "submit application",
                    "resume",
                    "contact info",
                    "contactgegevens",
                    "voornaam",
                    "achternaam",
                    "landcode",
                    "e-mailadres",
                    "application powered by greenhouse",
                    "work authorization",
                ]):
                    return True
            except Exception:
                pass
            await asyncio.sleep(delay_seconds)
        return False

    async def _scroll_search_results(self, amount: int = 600) -> None:
        """Scroll the LinkedIn job search results panel — not the browser window.

        Instead of guessing class names (LinkedIn changes them constantly) we walk
        UP the DOM from the first visible job card to find its actual scrollable
        ancestor.  Falls back to window.scrollBy only if nothing is found.
        """
        async def _scroll_once(step_amount: int):
            return await self.browser.page.evaluate(
                """(amount) => {
                // Strategy 1: walk up from any job card to its scrollable ancestor
                const cardSelectors = [
                    '.job-card-container',
                    '.jobs-search-results__list-item',
                    'li.scaffold-layout__list-item',
                    '[data-job-id]',
                ];
                let card = null;
                for (const sel of cardSelectors) {
                    card = document.querySelector(sel);
                    if (card) break;
                }
                if (card) {
                    let el = card.parentElement;
                    let depth = 0;
                    while (el && depth < 12) {
                        const s = window.getComputedStyle(el);
                        if (/(auto|scroll)/i.test(s.overflowY) &&
                            el.scrollHeight > el.clientHeight + 50) {
                            el.scrollTop = Math.min(el.scrollTop + amount, el.scrollHeight);
                            return 'card-ancestor:' + (el.className || el.tagName).slice(0, 40);
                        }
                        el = el.parentElement;
                        depth++;
                    }
                }
                // Strategy 2: try known selector names as last resort
                const fallbackSelectors = [
                    '.jobs-search-results-list',
                    '.scaffold-layout__list-container',
                    '.jobs-search-results__list',
                    '.scaffold-layout__list',
                ];
                for (const sel of fallbackSelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.scrollHeight > el.clientHeight + 50) {
                        el.scrollTop = Math.min(el.scrollTop + amount, el.scrollHeight);
                        return 'selector:' + sel;
                    }
                }
                // Final fallback
                window.scrollBy(0, amount);
                return null;
            }""",
                step_amount,
            )

        used = None
        if self.browser.use_human_delays:
            remaining = max(0, int(amount))
            while remaining > 0:
                step = min(remaining, random.randint(120, 260))
                used = await _scroll_once(step)
                remaining -= step
                await asyncio.sleep(random.uniform(0.35, 1.1))
        else:
            used = await _scroll_once(amount)
        if not used:
            print(f"[SCROLL-SEARCH] Job list panel not found — used window.scrollBy({amount}px)")

    async def _scroll_to_apply_region(self):
        try:
            await self.browser.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _expand_description(self):
        for selector in self.DESCRIPTION_EXPAND_SELECTORS:
            try:
                if await self.browser.is_visible(selector):
                    await self.browser.click_selector(selector)
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue

    async def _is_any_visible(self, selectors) -> bool:
        for selector in selectors:
            try:
                if await self.browser.is_visible(selector):
                    return True
            except Exception:
                continue
        return False

    def _contains_any_marker(self, text: str, markers: list) -> bool:
        lowered = (text or "").lower()
        return any(marker in lowered for marker in markers)

    def _extract_job_id(self, href: str) -> str:
        if not href:
            return ""
        match = re.search(r"/jobs/view/(\d+)", href)
        return match.group(1) if match else ""

    def _extract_description_from_page_text(self, page_text: str) -> str:
        if not page_text:
            return ""

        cleaned = re.sub(r"\s+", " ", page_text).strip()
        section_starts = [
            "About the job",
            "About the role",
            "Job description",
            "Description",
            "What you'll do",
            "What you will do",
            "Responsibilities",
        ]
        section_ends = [
            "Seniority level",
            "Employment type",
            "Job function",
            "Industries",
            "Referrals increase your chances",
            "Get notified about new",
            "Similar jobs",
            "People also viewed",
        ]

        for marker in section_starts:
            start_index = cleaned.find(marker)
            if start_index == -1:
                continue
            snippet = cleaned[start_index + len(marker):]
            end_index = len(snippet)
            for end_marker in section_ends:
                marker_index = snippet.find(end_marker)
                if marker_index != -1:
                    end_index = min(end_index, marker_index)
            snippet = snippet[:end_index].strip(" :-")
            if len(snippet) > 120:
                return snippet

        return ""

    def _absolute_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("/"):
            return f"{self.BASE_URL}{href}"
        return href

    def _pick_validation_sample(self, jobs: list, preferences: dict):
        if not jobs:
            return None

        excluded_keywords = [value.lower() for value in preferences.get("keywords_exclude", [])]
        target_terms = set()
        for title in preferences.get("job_titles", []):
            normalized = re.sub(r"[^a-z0-9]+", " ", title.lower())
            target_terms.update(token for token in normalized.split() if len(token) > 2)

        for job in jobs:
            title = (job.get("title") or "").lower()
            if any(keyword in title for keyword in excluded_keywords):
                continue
            title_terms = set(re.sub(r"[^a-z0-9]+", " ", title).split())
            if title_terms.intersection(target_terms):
                return job

        return jobs[0]

    def _normalized_search_title(self, title: str, linkedin_prefs: dict) -> str:
        normalized = title or ""
        if linkedin_prefs.get("search_titles_without_seniority", True):
            normalized = re.sub(
                r"\b(junior|jr\.?|senior|sr\.?|lead|principal)\b",
                "",
                normalized,
                flags=re.IGNORECASE,
            )
            normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized or title

    def _linkedin_experience_values(self, experience_levels: list) -> list:
        values = []
        for level in experience_levels or []:
            mapped = self.EXPERIENCE_LEVEL_MAP.get((level or "").lower())
            if mapped and mapped not in values:
                values.append(mapped)
        return values
