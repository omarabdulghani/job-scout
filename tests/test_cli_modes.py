import argparse
import contextlib
import io
import unittest
import urllib.parse

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


if __name__ == "__main__":
    unittest.main()
