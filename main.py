"""
Job Application Agent
=====================
An AI-powered agent that searches for jobs and applies on your behalf.
Uses Claude (vision) to navigate any job application form automatically.

Usage:
    python main.py              # Run normally (browser visible)
    python main.py --headless   # Run without visible browser (not recommended)
    python main.py --dry-run    # Search and score jobs but don't apply
    python main.py --validate-boards  # Validate job board selectors without applying
    python main.py --stats      # Show application statistics only
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from agent.env_loader import load_workspace_env
from rich.console import Console
from rich.panel import Panel
from agent.user_workspace import load_user_config

load_workspace_env()
console = Console()

def get_default_cv_path(profile: dict) -> Path:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    name = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip() or "Your Name"
    return Path(f"cv/{name} - CV Resume (English).pdf")
REQUIRED_PROFILE_FIELDS = [
    "personal.first_name",
    "personal.last_name",
    "personal.email",
    "personal.phone",
    "personal.location.city",
    "personal.location.country",
    "work_experience",
    "salary.target",
    "salary.currency",
]
REQUIRED_PREFERENCE_FIELDS = [
    "job_titles",
    "locations",
]


def _exit_with_error(message: str):
    console.print(f"[red]Error:[/red] {message}")
    raise SystemExit(1)


def _has_required_value(data: dict, dotted_path: str) -> bool:
    value = data
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]

    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return value is not None


def _validate_config(profile: dict, preferences: dict):
    missing_profile = [
        field for field in REQUIRED_PROFILE_FIELDS
        if not _has_required_value(profile, field)
    ]
    missing_preferences = [
        field for field in REQUIRED_PREFERENCE_FIELDS
        if not _has_required_value(preferences, field)
    ]

    if missing_profile:
        console.print("[red]Profile config is missing required fields:[/red]")
        for field in missing_profile:
            console.print(f"  - {field}")
        raise SystemExit(1)

    if missing_preferences:
        console.print("[red]Preferences config is missing required fields:[/red]")
        for field in missing_preferences:
            console.print(f"  - {field}")
        raise SystemExit(1)


def load_config():
    try:
        profile, preferences = load_user_config()
    except (FileNotFoundError, ValueError) as exc:
        _exit_with_error(str(exc))
    _validate_config(profile, preferences)
    Path("data").mkdir(parents=True, exist_ok=True)

    cv_path = Path(profile.get("cv_path", get_default_cv_path(profile).as_posix()))
    if not cv_path.exists():
        console.print(f"[yellow]Warning:[/yellow] CV not found at {cv_path}")
        console.print("   Place your CV PDF at that path before applying.")

    return profile, preferences


async def main():
    parser = argparse.ArgumentParser(description="AI Job Application Agent")
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    parser.add_argument("--dry-run", action="store_true", help="Find jobs but don't apply")
    parser.add_argument(
        "--validate-boards",
        action="store_true",
        help="Validate enabled job boards without applying",
    )
    parser.add_argument("--stats", action="store_true", help="Show stats and exit")
    args = parser.parse_args()

    if args.stats:
        from agent.tracker import ApplicationTracker

        tracker = ApplicationTracker()
        tracker.print_summary()
        applications = tracker.get_all_applications()
        if applications:
            console.print("\nRecent applications:")
            for application in applications[:10]:
                console.print(
                    f"  * {application['title']} @ {application['company']} "
                    f"- {application['status']} ({application['applied_at'][:10]})"
                )
                if application.get("notes"):
                    console.print(f"      Reason: {application['notes'][:140]}")

        rejected = tracker.get_recent_reviews(decision="rejected", limit=10)
        if rejected:
            console.print("\nRecent rejected jobs:")
            for review in rejected:
                console.print(
                    f"  * {review['title']} @ {review['company']} "
                    f"({review['reviewed_at'][:10]})"
                )
                if review.get("reasons"):
                    console.print(f"      Why: {review['reasons'][:180]}")
        return

    profile, preferences = load_config()

    if args.dry_run:
        preferences["application_behavior"] = preferences.get("application_behavior", {})
        preferences["max_applications_per_run"] = 0
        console.print("[yellow]DRY RUN MODE: Will search and score jobs but not apply.[/yellow]")

    if args.validate_boards:
        preferences["application_behavior"] = preferences.get("application_behavior", {})
        preferences["max_applications_per_run"] = 0
        console.print("[yellow]VALIDATION MODE: Will inspect job board selectors without applying.[/yellow]")

    will_apply = (
        not args.dry_run
        and not args.validate_boards
        and preferences.get("max_applications_per_run", 10) > 0
    )
    cv_path = Path(profile.get("cv_path", get_default_cv_path(profile).as_posix()))

    if will_apply and not cv_path.exists():
        _exit_with_error(
            f"CV file is required for applications but was not found at {cv_path}."
        )

    if will_apply and not os.getenv("ANTHROPIC_API_KEY"):
        _exit_with_error(
            "ANTHROPIC_API_KEY is not set. Add it to .env before running applications."
        )

    mode_text = "Validate boards" if args.validate_boards else (
        "Dry run" if args.dry_run else "Apply"
    )
    console.print(Panel(
        f"[bold green]Job Agent[/bold green]\n"
        f"Looking for: {', '.join(preferences.get('job_titles', [])[:3])}\n"
        f"Locations: {', '.join(preferences.get('locations', []))}\n"
        f"Mode: {mode_text}",
        title="Configuration"
    ))

    from agent.browser import BrowserController
    from agent.tracker import ApplicationTracker
    from agent.job_agent import JobAgent

    tracker = ApplicationTracker()
    browser = BrowserController(headless=args.headless)

    try:
        await browser.start()
        agent = JobAgent(profile, preferences, browser, tracker, runtime_mode=mode_text.lower().replace(" ", "_"))
        if args.validate_boards:
            await agent.validate_boards()
        else:
            await agent.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Agent stopped by user.[/yellow]")
    except Exception as exc:
        console.print(f"\n[red]Agent error:[/red] {exc}")
        import traceback
        traceback.print_exc()
    finally:
        await browser.close()
        console.print("Browser closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[red]Fatal error:[/red] {exc}")
        sys.exit(1)
