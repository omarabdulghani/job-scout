import asyncio
import base64
from pathlib import Path
import random
from playwright.async_api import async_playwright, Page, Browser, BrowserContext


class BrowserController:
    """
    Controls a real browser via Playwright.
    Uses a persistent browser profile so you stay logged in across sessions.
    """

    def __init__(
        self,
        headless: bool = False,
        profile_dir: str | None = "data/browser_profile",
        use_human_delays: bool = True,
        use_automation_overrides: bool = True,
        browser_type: str = "chromium",
        executable_path: str | None = None,
        start_new_page: bool = False,
    ):
        self.headless = headless
        self.profile_dir = profile_dir
        self.use_human_delays = use_human_delays
        self.use_automation_overrides = use_automation_overrides
        self.browser_type = (browser_type or "chromium").strip().lower()
        self.executable_path = executable_path
        self.start_new_page = bool(start_new_page)
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None

    def set_human_delays(self, enabled: bool):
        self.use_human_delays = enabled

    async def start(self):
        """Launch the browser, optionally with a persistent profile."""
        self.playwright = await async_playwright().start()
        if self.browser_type not in {"chromium", "firefox"}:
            raise ValueError("browser_type must be 'chromium' or 'firefox'.")

        browser_launcher = getattr(self.playwright, self.browser_type)
        browser_args = []
        if self.browser_type == "chromium":
            browser_args.append("--no-sandbox")
        if self.browser_type == "chromium" and self.use_automation_overrides:
            browser_args.insert(0, "--disable-blink-features=AutomationControlled")

        context_options = {
            "viewport": {"width": 1280, "height": 800},
        }
        if self.browser_type == "chromium":
            context_options["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )

        launch_options = {"headless": self.headless}
        if browser_args:
            launch_options["args"] = browser_args
        if self.executable_path:
            launch_options["executable_path"] = self.executable_path

        if self.profile_dir is None:
            self.browser = await browser_launcher.launch(**launch_options)
            self.context = await self.browser.new_context(**context_options)
        else:
            Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
            self.context = await browser_launcher.launch_persistent_context(
                user_data_dir=self.profile_dir,
                **context_options,
                **launch_options,
            )

        if self.browser_type == "chromium" and self.use_automation_overrides:
            # Existing LinkedIn behavior: keep the current browser profile semantics unchanged.
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)
        self.page = (
            await self.context.new_page()
            if self.start_new_page or not self.context.pages
            else self.context.pages[0]
        )
        await self.page.bring_to_front()
        print(f"Browser started ({self.browser_type})")

    async def close(self):
        if self.context is not None:
            await self.context.close()
            self.context = None
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None

    async def goto(self, url: str):
        if self.page is None or self.page.is_closed():
            self.page = await self.context.new_page()
        await self.page.bring_to_front()
        print(f"Navigating to {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self.page.bring_to_front()
        await self.human_delay(1, 2)

    async def screenshot_base64(self) -> str:
        """Take screenshot and return as base64 — used to show Claude what's on screen."""
        screenshot = await self.page.screenshot(full_page=False)
        return base64.b64encode(screenshot).decode()

    async def get_page_text(self) -> str:
        """Extract readable text from the current page."""
        return await self.page.evaluate("""() => {
            // Remove scripts and styles
            const clone = document.cloneNode(true);
            clone.querySelectorAll('script, style, nav, footer').forEach(e => e.remove());
            return clone.innerText || clone.textContent || '';
        }""")

    async def get_page_html(self) -> str:
        return await self.page.content()

    async def click_text(self, text: str, exact: bool = False):
        """Click an element containing specific text."""
        modal = await self._active_dialog_locator()
        if modal is not None:
            try:
                if exact:
                    await modal.get_by_text(text, exact=True).first.click(timeout=2000)
                else:
                    await modal.get_by_text(text).first.click(timeout=2000)
                await self.human_delay(0.5, 1.5)
                return
            except Exception:
                print(f"[MODAL-BLOCK] Prevented background click_text fallback while modal is open: {text!r}")
                return

        if exact:
            await self.page.get_by_text(text, exact=True).first.click()
        else:
            await self.page.get_by_text(text).first.click()
        await self.human_delay(0.5, 1.5)

    async def click_selector(self, selector: str):
        modal = await self._active_dialog_locator()
        if modal is not None:
            try:
                target = modal.locator(selector).first
                if await target.is_visible(timeout=1000):
                    await target.click(timeout=2000)
                    await self.human_delay(0.3, 1.0)
                    return
            except Exception:
                print(f"[MODAL-BLOCK] Prevented background click_selector fallback while modal is open: {selector!r}")
                return

            print(f"[MODAL-BLOCK] Selector not found in modal; skipped page fallback: {selector!r}")
            return

        await self.page.locator(selector).first.click()
        await self.human_delay(0.3, 1.0)

    async def type_in_field(self, selector: str, text: str, clear_first: bool = True):
        """Type text into a field with human-like delays."""
        field = self.page.locator(selector).first
        if clear_first:
            await field.triple_click()
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Delete")
        # Type with slight random delays between keystrokes
        key_delay = random.randint(30, 80) if self.use_human_delays else 0
        await field.type(text, delay=key_delay)
        await self.human_delay(0.3, 0.8)

    async def fill_field(self, selector: str, text: str):
        """Fast-fill a field (for hidden or programmatic fields)."""
        await self.page.fill(selector, text)

    async def upload_file(self, selector: str, file_path: str):
        """Upload a file to a file input."""
        await self.page.set_input_files(selector, file_path)
        await self.human_delay(1, 2)

    async def select_option(self, selector: str, value: str = None, label: str = None):
        """Select from a dropdown."""
        if value:
            await self.page.select_option(selector, value=value)
        elif label:
            await self.page.select_option(selector, label=label)
        await self.human_delay(0.3, 0.8)

    async def scroll_down(self, amount: int = 500):
        scroll_result = await self._scroll_active_dialog(amount=amount)
        if scroll_result["modal_open"]:
            if scroll_result["scrolled"]:
                print(f"[SCROLL] Scrolled {amount}px within modal dialog")
            else:
                print("[SCROLL] Modal is open but no inner scrolling was needed; blocked background scroll")
            await self.human_delay(0.5, 1.0)
            return
        print(f"[SCROLL] Scrolling background page by {amount}px (no modal detected)")
        await self.page.evaluate(f"window.scrollBy(0, {amount})")
        await self.human_delay(0.5, 1.0)

    async def scroll_to_bottom(self):
        scroll_result = await self._scroll_active_dialog(to_bottom=True)
        if scroll_result["modal_open"]:
            if scroll_result["scrolled"]:
                print("[SCROLL] Scrolled to bottom within modal dialog")
            else:
                print("[SCROLL] Modal is open but no inner scrolling was needed; blocked background scroll")
            await self.human_delay(0.5, 1.0)
            return
        print("[SCROLL] Scrolling background page to bottom (no modal detected)")
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await self.human_delay(0.5, 1.0)

    async def wait_for_selector(self, selector: str, timeout: int = 10000):
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def is_visible(self, selector: str) -> bool:
        try:
            locator = self.page.locator(selector)
            count = await locator.count()
            for index in range(count):
                try:
                    if await locator.nth(index).is_visible(timeout=500):
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    async def _active_dialog_locator(self):
        try:
            dialogs = self.page.locator(
                "[data-test-modal-container], "
                ".jobs-easy-apply-modal, "
                "#interop-outlet, "
                "[data-testid='interop-shadowdom'], "
                "[role='dialog']"
            )
            count = await dialogs.count()
            active_index = None
            for index in range(count):
                try:
                    if await dialogs.nth(index).is_visible(timeout=300):
                        active_index = index
                except Exception:
                    continue
            if active_index is None:
                return None
            return dialogs.nth(active_index)
        except Exception:
            return None

    async def _scroll_active_dialog(self, amount: int = 500, to_bottom: bool = False) -> dict:
        try:
            result = await self.page.evaluate(
                """({ amount, toBottom }) => {
                    function visible(el) {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== "hidden" &&
                            style.display !== "none" &&
                            rect.width > 0 &&
                            rect.height > 0;
                    }

                    function zIndexOf(el) {
                        const raw = window.getComputedStyle(el).zIndex;
                        const parsed = parseInt(raw, 10);
                        return Number.isNaN(parsed) ? 0 : parsed;
                    }

                    const dialogs = Array.from(
                        document.querySelectorAll(
                            "[data-test-modal-container], " +
                            ".jobs-easy-apply-modal, " +
                            "#interop-outlet, " +
                            "[data-testid='interop-shadowdom'], " +
                            "[role='dialog']"
                        )
                    )
                        .filter(visible)
                        .sort((a, b) => zIndexOf(a) - zIndexOf(b));

                    const dialog = dialogs[dialogs.length - 1];
                    if (!dialog) return { modal_open: false, scrolled: false };

                    const candidates = [dialog, ...dialog.querySelectorAll("*")].filter(el => {
                        if (!visible(el)) return false;
                        const style = window.getComputedStyle(el);
                        const canScroll = /(auto|scroll)/i.test(style.overflowY || "");
                        return canScroll && el.scrollHeight > el.clientHeight + 20;
                    });

                    if (!candidates.length) {
                        return { modal_open: true, scrolled: false };
                    }

                    const target = candidates.sort(
                        (a, b) => (a.scrollHeight - a.clientHeight) - (b.scrollHeight - b.clientHeight)
                    )[candidates.length - 1];

                    if (toBottom) {
                        const before = target.scrollTop;
                        target.scrollTop = target.scrollHeight;
                        target.dispatchEvent(new Event("scroll", { bubbles: true }));
                        return { modal_open: true, scrolled: target.scrollTop !== before };
                    } else {
                        const before = target.scrollTop;
                        target.scrollTop = Math.min(
                            target.scrollTop + amount,
                            target.scrollHeight
                        );
                        target.dispatchEvent(new Event("scroll", { bubbles: true }));
                        return { modal_open: true, scrolled: target.scrollTop > before };
                    }
                }""",
                {"amount": amount, "toBottom": to_bottom},
            )
            if isinstance(result, dict):
                return {
                    "modal_open": bool(result.get("modal_open")),
                    "scrolled": bool(result.get("scrolled")),
                }
            return {"modal_open": bool(result), "scrolled": bool(result)}
        except Exception:
            return {"modal_open": False, "scrolled": False}

    async def get_current_url(self) -> str:
        return self.page.url

    async def human_delay(self, min_sec: float = 0.5, max_sec: float = 2.0):
        """Random delay to simulate human behaviour."""
        if not self.use_human_delays:
            return
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def new_tab(self) -> Page:
        page = await self.context.new_page()
        return page

    async def wait_for_navigation(self, timeout: int = 15000):
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
