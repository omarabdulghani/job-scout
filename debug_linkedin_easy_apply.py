import argparse
import asyncio
import json
from pathlib import Path

from agent.brain import JobBrain
from agent.browser import BrowserController
from scrapers.linkedin import LinkedInScraper


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "config" / "profile.json"
PREFERENCES_PATH = ROOT / "config" / "preferences.json"
DEBUG_DIR = ROOT / "data" / "easy_apply_debug"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    return safe[:80] or "step"


async def save_debug_snapshot(browser: BrowserController, linkedin: LinkedInScraper, step: int, label: str):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    base = DEBUG_DIR / f"{step:02d}_{sanitize_name(label)}"
    await browser.page.screenshot(path=str(base.with_suffix(".png")))
    state = await linkedin.inspect_easy_apply_modal()
    base.with_suffix(".json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return state


def print_modal_state(step: int, state: dict):
    print(f"\n[DEBUG] Step {step}")
    print(f"[DEBUG] Modal open: {state.get('open')}")
    print(f"[DEBUG] Title: {state.get('title', '')}")
    print(f"[DEBUG] Primary button: {state.get('primary_button', '')}")
    fields = state.get("fields", [])
    print(f"[DEBUG] Fields: {len(fields)}")
    for field in fields:
        question = field.get("question", "")[:90]
        kind = field.get("kind", "")
        required = field.get("required", False)
        answered = field.get("answered", False)
        value = str(field.get("value", ""))[:60]
        print(
            f"  - required={required} answered={answered} kind={kind} "
            f"question={question!r} value={value!r}"
        )


async def run_debug(url: str, max_steps: int, stop_before_submit: bool, pause_on_finish: bool):
    profile = load_json(PROFILE_PATH)
    preferences = load_json(PREFERENCES_PATH)
    behavior = preferences.get("application_behavior", {})

    browser = BrowserController(
        headless=False,
        profile_dir="data/browser_profile",
        use_human_delays=behavior.get("add_human_like_delays", True),
    )
    linkedin = LinkedInScraper(browser)
    brain = JobBrain(profile, preferences)

    await browser.start()
    try:
        logged_in = await linkedin.ensure_logged_in()
        if not logged_in:
            print("[DEBUG] LinkedIn login not detected.")
            return

        print(f"[DEBUG] Opening job URL: {url}")
        job = {
            "id": f"debug_{url}",
            "url": url,
            "source": "linkedin",
            "title": "Debug LinkedIn Job",
            "company": "",
        }
        job = await linkedin.get_job_details(job)
        print(
            f"[DEBUG] Job details: easy_apply={job.get('easy_apply')} "
            f"already_applied={job.get('already_applied')} title={job.get('title', '')!r}"
        )

        clicked = await linkedin.click_apply(job)
        print(f"[DEBUG] click_apply returned: {clicked}")
        if not clicked:
            await save_debug_snapshot(browser, linkedin, 0, "click_apply_failed")
            print("[DEBUG] Could not open Easy Apply. Snapshot saved in data/easy_apply_debug.")
            return

        for step in range(1, max_steps + 1):
            state = await save_debug_snapshot(browser, linkedin, step, "modal")
            print_modal_state(step, state)

            if not state.get("open"):
                page_text = (await browser.get_page_text()).lower()
                if any(
                    marker in page_text
                    for marker in [
                        "application submitted",
                        "application sent",
                        "your application was sent",
                    ]
                ):
                    print("[DEBUG] Application confirmation detected after modal closed.")
                    return
                print("[DEBUG] Modal is not open anymore. Stopping debug run.")
                return

            primary_button = (state.get("primary_button") or "").lower()
            if stop_before_submit and "submit" in primary_button:
                print("[DEBUG] Stop-before-submit enabled. Modal reached submit step.")
                print("[DEBUG] Inspect the browser and artifacts in data/easy_apply_debug.")
                return

            result = await linkedin.handle_easy_apply_modal(brain)
            print(f"[DEBUG] handle_easy_apply_modal -> {result}")

            if result and result.get("status") in {"applied", "failed", "skipped"}:
                print("[DEBUG] Modal flow reached terminal state.")
                return

            await browser.human_delay(0.5, 1.0)

        print("[DEBUG] Reached max debug steps without terminal state.")
    finally:
        if pause_on_finish:
            try:
                input("\nPress Enter to close the browser...")
            except EOFError:
                pass
        await browser.close()


def main():
    parser = argparse.ArgumentParser(description="Debug one LinkedIn Easy Apply flow.")
    parser.add_argument("url", help="LinkedIn job URL to test")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=15,
        help="Maximum Easy Apply modal steps to execute",
    )
    parser.add_argument(
        "--stop-before-submit",
        action="store_true",
        help="Stop before clicking the final submit button",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Close the browser immediately when the run finishes",
    )
    args = parser.parse_args()

    asyncio.run(
        run_debug(
            url=args.url,
            max_steps=args.max_steps,
            stop_before_submit=args.stop_before_submit,
            pause_on_finish=not args.no_pause,
        )
    )


if __name__ == "__main__":
    main()
