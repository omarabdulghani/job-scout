import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from agent.scout_cli_modes import (
    add_board_mode_arguments,
    default_browser_profile_dir,
    requires_description_only,
    resolve_board_mode,
    supported_browser_executable,
)
from agent.browser import BrowserController
from agent.indeed_job_scout import IndeedJobScout
from scrapers.indeed import IndeedScraper


ROOT = Path(__file__).resolve().parents[1]


class ScoutCliModeTests(unittest.TestCase):
    def _parse(self, argv):
        parser = argparse.ArgumentParser()
        add_board_mode_arguments(parser)
        return parser.parse_args(argv)

    def test_default_mode_is_linkedin(self):
        args = self._parse([])
        self.assertEqual(resolve_board_mode(args), "linkedin")
        self.assertFalse(requires_description_only("linkedin"))

    def test_explicit_linkedin_mode(self):
        args = self._parse(["--linkedin"])
        self.assertEqual(resolve_board_mode(args), "linkedin")

    def test_indeed_mode_requires_description_only(self):
        args = self._parse(["--indeed"])
        self.assertEqual(resolve_board_mode(args), "indeed")
        self.assertTrue(requires_description_only("indeed"))

    def test_installed_firefox_executable_is_not_used(self):
        executable, warning = supported_browser_executable(
            "firefox",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
        )
        self.assertIsNone(executable)
        self.assertIn("bundled Firefox", warning)

    def test_indeed_firefox_uses_playwright_specific_profile(self):
        self.assertEqual(
            default_browser_profile_dir("indeed", "firefox"),
            "data/indeed_playwright_firefox_profile",
        )

    def test_board_modes_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self._parse(["--linkedin", "--indeed"])


class IndeedUrlTests(unittest.TestCase):
    def test_configured_search_url_preserves_indeed_filters(self):
        scraper = IndeedScraper(browser=None)
        preferences = {
            "job_boards": {
                "indeed": {
                    "search_url": (
                        "https://nl.indeed.com/jobs?q=&l=Amstelveen&radius=25"
                        "&sc=0kf%3Aattr%28HFDVW%29%3B&from=searchOnDesktopSerp"
                        "&vjk=c39278b37ee5f231"
                    ),
                    "radius_km": 25,
                }
            },
            "filters": {"posted_within_days": 14},
        }

        url = scraper._build_url(
            "UX Designer",
            "Amsterdam",
            preferences,
            start=10,
        )
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)

        self.assertEqual(parsed.netloc, "nl.indeed.com")
        self.assertEqual(query["q"], ["UX Designer"])
        self.assertEqual(query["l"], ["Amsterdam"])
        self.assertEqual(query["radius"], ["25"])
        self.assertEqual(query["start"], ["10"])
        self.assertEqual(query["sc"], ["0kf:attr(HFDVW);"])
        self.assertEqual(query["from"], ["searchOnDesktopSerp"])

    def test_indeed_job_url_canonicalizes_to_nl_viewjob(self):
        scout = object.__new__(IndeedJobScout)
        analysis = scout._analyze_indeed_job_url(
            "https://nl.indeed.com/rc/clk?jk=abc123def456&from=vj"
        )

        self.assertTrue(analysis["valid"])
        self.assertEqual(analysis["job_id"], "abc123def456")
        self.assertEqual(
            analysis["canonical_url"],
            "https://nl.indeed.com/viewjob?jk=abc123def456",
        )


class FreshCliFlagTests(unittest.TestCase):
    def _help_output(self, script_name: str) -> str:
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ)
            env["JOB_SCOUT_LOG_DIR"] = str(Path(temporary) / "logs")
            completed = subprocess.run(
                [sys.executable, str(ROOT / script_name), "--help"],
                cwd=temporary,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        return completed.stdout

    def test_single_query_cli_exposes_fresh_flag(self):
        self.assertIn("--fresh", self._help_output("scout_jobs.py"))

    def test_multi_query_cli_exposes_fresh_flag(self):
        self.assertIn("--fresh", self._help_output("scout_jobs_multi.py"))

    def test_multi_query_cli_exposes_query_learning_opt_out(self):
        self.assertIn("--no-query-learning", self._help_output("scout_jobs_multi.py"))

    def test_help_commands_do_not_create_real_workspace_logs(self):
        logs_dir = ROOT / "logs"
        before = {path.name for path in logs_dir.glob("*") if path.is_file()}

        self._help_output("scout_jobs.py")
        self._help_output("scout_jobs_multi.py")

        after = {path.name for path in logs_dir.glob("*") if path.is_file()}
        self.assertEqual(after, before)


class BrowserControllerConfigTests(unittest.TestCase):
    def test_firefox_engine_can_use_dedicated_profile_config(self):
        browser = BrowserController(
            browser_type="firefox",
            profile_dir="data/indeed_browser_profile",
            use_automation_overrides=False,
            start_new_page=True,
        )

        self.assertEqual(browser.browser_type, "firefox")
        self.assertEqual(browser.profile_dir, "data/indeed_browser_profile")
        self.assertFalse(browser.use_automation_overrides)
        self.assertTrue(browser.start_new_page)


class FakeNavigationPage:
    def __init__(self, *, target_visible_after_timeout: bool):
        self.url = "https://www.linkedin.com/jobs/view/old-job/"
        self.goto_calls = 0
        self.evaluate_calls = 0
        self.target_visible_after_timeout = target_visible_after_timeout

    def is_closed(self):
        return False

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls += 1
        if self.goto_calls == 1:
            if self.target_visible_after_timeout:
                self.url = url
            raise PlaywrightTimeoutError("navigation timed out")
        self.url = url

    async def wait_for_selector(self, selector, timeout=None):
        if selector == "body" and self.target_visible_after_timeout:
            return object()
        raise PlaywrightTimeoutError("body not visible")

    async def evaluate(self, script):
        self.evaluate_calls += 1


class FakeNavigationContext:
    async def new_page(self):
        return FakeNavigationPage(target_visible_after_timeout=False)


class BrowserControllerNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_goto_continues_when_timeout_landed_on_target_page(self):
        browser = BrowserController(use_human_delays=False)
        browser.context = FakeNavigationContext()
        browser.page = FakeNavigationPage(target_visible_after_timeout=True)

        with patch("builtins.print"):
            await browser.goto("https://www.linkedin.com/feed/")

        self.assertEqual(browser.page.goto_calls, 1)
        self.assertEqual(browser.page.url, "https://www.linkedin.com/feed/")

    async def test_goto_retries_when_timeout_did_not_reach_target_page(self):
        browser = BrowserController(use_human_delays=False)
        browser.context = FakeNavigationContext()
        browser.page = FakeNavigationPage(target_visible_after_timeout=False)

        with patch("builtins.print"):
            await browser.goto("https://www.linkedin.com/feed/")

        self.assertEqual(browser.page.goto_calls, 2)
        self.assertEqual(browser.page.evaluate_calls, 1)
        self.assertEqual(browser.page.url, "https://www.linkedin.com/feed/")


if __name__ == "__main__":
    unittest.main()
