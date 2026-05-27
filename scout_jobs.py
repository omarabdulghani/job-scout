import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from agent.browser import BrowserController
from agent.indeed_job_scout import IndeedJobScout
from agent.job_scout import LinkedInJobScout
from agent.scout_cli_modes import (
    add_board_mode_arguments,
    board_display_name,
    default_browser_profile_dir,
    requires_description_only,
    resolve_board_mode,
    supported_browser_executable,
)
from agent.scout_console_reporter import ScoutConsoleReporter
from agent.scout_progress import ScoutProgressStore
from agent.recommended_jobs_dashboard import update_recommended_jobs_html
from agent.live_recommended_jobs_dashboard import LiveRecommendedJobsDashboard
from agent.scout_review_latest import ScoutReviewLatestWriter
from agent.scout_run_logger import ScoutRunLogger

load_dotenv()
console = Console()
ACTIVE_RUN_LOGGER: ScoutRunLogger | None = None

PROFILE_PATH = Path("config/profile.json")
PREFERENCES_PATH = Path("config/preferences.json")
PROGRESS_MODE = "single_query_scout"


def _load_json_file(path: Path, label: str) -> dict:
    if not path.exists():
        raise SystemExit(f"{label} not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} contains invalid JSON: {exc}")


def load_config() -> tuple[dict, dict]:
    profile = _load_json_file(PROFILE_PATH, "Profile config")
    preferences = _load_json_file(PREFERENCES_PATH, "Preferences config")
    return profile, preferences


def _parse_max_pages(value: str | int | None) -> tuple[int | None, str]:
    raw = str(value or "2").strip().lower()
    if raw == "all":
        return None, "all available"

    try:
        parsed = max(1, int(raw))
    except ValueError as exc:
        raise SystemExit("--max-pages must be a positive integer or 'all'.") from exc

    return parsed, str(parsed)


def _normalize_query(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _ai_backend_label(scout: LinkedInJobScout) -> str:
    backend = (scout.brain.scoring_backend or "claude").strip().lower()
    if backend == "auto":
        labels = [
            scout.brain._hosted_model_label(item)
            for item in scout.brain._configured_auto_backends()
        ]
        return "Auto (" + " -> ".join(labels) + ")" if labels else "Auto (no configured providers)"
    if backend == "cerebras":
        return f"Cerebras ({scout.brain.cerebras_model or '<unset>'})"
    if backend == "ollama_cloud":
        return f"Ollama Cloud ({scout.brain.ollama_model or '<unset>'})"
    if backend == "openai_compatible":
        return f"OpenAI-compatible ({scout.brain.openai_compatible_model or '<unset>'})"
    if backend == "gemini":
        return f"Gemini ({scout.brain.gemini_model or '<unset>'})"
    if backend == "lmstudio":
        return f"LM Studio ({scout.brain.lmstudio_model or '<unset>'})"
    return f"Claude ({scout.brain.model})"


async def main():
    global console, ACTIVE_RUN_LOGGER
    ACTIVE_RUN_LOGGER = ScoutRunLogger()
    ACTIVE_RUN_LOGGER.install()
    console = Console()

    parser = argparse.ArgumentParser(
        description="Scout job descriptions and keep only high-quality entry-level candidates."
    )
    add_board_mode_arguments(parser)
    parser.add_argument("query", help="Job search query, for example: 'brand strategy'")
    parser.add_argument(
        "--location",
        default="Amstelveen",
        help="Search location. Defaults to 'Amstelveen'.",
    )
    parser.add_argument(
        "--max-pages",
        default="2",
        help="How many result pages to scan: 1, 2, or 'all'.",
    )
    parser.add_argument("--pages", dest="legacy_pages", help=argparse.SUPPRESS)
    parser.add_argument(
        "--human-mode",
        action="store_true",
        help="Use slower, randomized human-like pacing to reduce bot-like behavior.",
    )
    parser.add_argument(
        "--description-only",
        "--extract-descriptions-only",
        dest="description_only",
        action="store_true",
        help="Extract and save job descriptions without AI scoring.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from saved scout progress when possible.",
    )
    parser.add_argument(
        "--process-only",
        action="store_true",
        help="Skip scraping and process already collected jobs only.",
    )
    parser.add_argument(
        "--browser",
        choices=["chromium", "firefox"],
        default="chromium",
        help="Browser engine to use for the scout. Defaults to chromium.",
    )
    parser.add_argument(
        "--browser-profile-dir",
        default=None,
        help=(
            "Dedicated browser profile directory. Defaults to data/browser_profile "
            "for LinkedIn and data/indeed_browser_profile for Indeed."
        ),
    )
    parser.add_argument(
        "--browser-executable",
        default=None,
        help="Optional path to an installed browser executable, such as Firefox.",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Clear scout_progress.json before continuing.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    args = parser.parse_args()
    board_mode = resolve_board_mode(args)
    board_name = board_display_name(board_mode)
    if requires_description_only(board_mode):
        args.description_only = True
    browser_executable, executable_warning = supported_browser_executable(
        args.browser,
        args.browser_executable,
    )
    if executable_warning:
        console.print(f"[yellow]Warning:[/yellow] {executable_warning}")

    profile, preferences = load_config()
    max_pages_value = args.legacy_pages if args.legacy_pages is not None else args.max_pages
    effective_pages, page_label = _parse_max_pages(max_pages_value)
    progress_store = ScoutProgressStore()
    if args.reset_progress:
        progress_store.clear()
        console.print("[yellow]Cleared scout progress.[/yellow]")

    progress = progress_store.load() if args.resume else {}
    run_started_at = datetime.now().astimezone().isoformat()
    progress_mode = PROGRESS_MODE if board_mode == "linkedin" else f"{board_mode}_{PROGRESS_MODE}"
    resume_active = bool(
        progress
        and progress.get("mode") == progress_mode
        and progress.get("status") != "completed"
        and _normalize_query(progress.get("current_query", "")) == _normalize_query(args.query)
        and progress.get("location", "") == args.location
        and str(progress.get("max_pages", "")) == page_label
    )
    stable_pages = int(progress.get("stable_total_pages_processed", 0) or 0) if resume_active else 0
    stable_jobs = int(progress.get("stable_total_jobs_processed", 0) or 0) if resume_active else 0

    profile_dir = args.browser_profile_dir or default_browser_profile_dir(board_mode, args.browser)
    browser = None if args.process_only else BrowserController(
        headless=args.headless,
        profile_dir=profile_dir,
        use_automation_overrides=(board_mode == "linkedin" and args.browser == "chromium"),
        browser_type=args.browser,
        executable_path=browser_executable,
        start_new_page=(board_mode == "indeed"),
    )
    if browser:
        browser.set_human_delays(args.human_mode or board_mode == "indeed")
    reporter = ScoutConsoleReporter(console=console)
    review_writer = ScoutReviewLatestWriter()
    scout_cls = IndeedJobScout if board_mode == "indeed" else LinkedInJobScout
    scout = scout_cls(profile, preferences, browser, reporter=reporter)
    live_dashboard = None
    live_run = None
    live_run_completed = False
    live_completion_status = "failed"
    if not args.description_only:
        try:
            live_dashboard = LiveRecommendedJobsDashboard()
            live_run = live_dashboard.start_run(
                mode=f"{board_mode}_single_query_scout",
                board=board_mode,
                location=args.location,
                max_pages=page_label,
                queries=[args.query],
                started_at=run_started_at,
            )
            console.print(
                "[green]Live dashboard:[/green] "
                "recommended_jobs_dashboard.html"
            )
        except Exception as exc:
            live_dashboard = None
            live_run = None
            console.print(f"[yellow]Live dashboard disabled:[/yellow] {exc}")

    def on_live_result(event: dict):
        if not live_dashboard or not live_run:
            return
        event = dict(event)
        event["run_id"] = live_run["run_id"]
        live_dashboard.record_job(event)

    mode_label = (
        f"{board_name} description extraction only (no AI scoring)"
        if args.description_only
        else ("Process-only reuse" if args.process_only else "Non-AI filtering + AI scoring")
    )
    ai_backend_label = "disabled (description-only)" if args.description_only else _ai_backend_label(scout)
    console.print(
        Panel(
            f"[bold green]{board_name} Scout[/bold green]\n"
            f"Query: {args.query}\n"
            f"Location: {args.location}\n"
            f"Pages: {page_label}\n"
            f"Browser: {args.browser}\n"
            f"Interaction: {'human-like' if args.human_mode or board_mode == 'indeed' else 'fast'}\n"
            f"AI Backend: {ai_backend_label}\n"
            f"Started: {run_started_at}\n"
            f"Mode: {mode_label}",
            title="Scouting Configuration",
        )
    )

    progress_state = {
        "mode": progress_mode,
        "status": "in_progress",
        "phase": "idle",
        "location": args.location,
        "max_pages": page_label,
        "queries": [args.query],
        "current_query_index": 0,
        "current_query": args.query,
        "current_page_number": 0,
        "total_pages_processed": stable_pages,
        "total_jobs_processed": stable_jobs,
        "stable_total_pages_processed": stable_pages,
        "stable_total_jobs_processed": stable_jobs,
        "last_completed_query_index": int(progress.get("last_completed_query_index", -1) or -1)
        if resume_active
        else -1,
        "last_completed_query": progress.get("last_completed_query", "") if resume_active else "",
        "last_completed_page_number": int(progress.get("last_completed_page_number", 0) or 0)
        if resume_active
        else 0,
    }

    def save_progress(**updates):
        if args.process_only:
            return
        progress_state.update(updates)
        progress_store.save(progress_state)

    try:
        if browser:
            await browser.start()
        reporter.start_query(
            query_index=1,
            total_queries=1,
            query_name=args.query,
            max_pages=effective_pages,
            process_only=args.process_only,
        )
        if args.process_only:
            if args.resume:
                console.print("[yellow]Process-only mode ignores --resume and uses collected jobs directly.[/yellow]")
            report = await scout.process_collected_jobs(
                query=args.query,
                location=args.location,
                max_pages=effective_pages,
                same_run_job_registry={},
                run_started_at=run_started_at,
                description_only=args.description_only,
                live_result_callback=on_live_result if live_dashboard else None,
            )
        else:
            if resume_active:
                console.print(
                    "[yellow]Resuming the unfinished query from a safe restart of that query.[/yellow] "
                    f"Last seen page was {int(progress.get('current_page_number', 0) or 0)}."
                )
            save_progress(status="in_progress", phase="collecting_pages")

            current_query_pages = {"value": 0}

            def on_page_scanned(query: str, page_number: int, pages_scanned: int, total_jobs_collected: int):
                current_query_pages["value"] = pages_scanned
                save_progress(
                    status="in_progress",
                    phase="collecting_pages",
                    current_query_index=0,
                    current_query=query,
                    current_page_number=page_number,
                    last_completed_page_number=page_number,
                    total_pages_processed=stable_pages + pages_scanned,
                    total_jobs_processed=stable_jobs,
                )

            def on_job_processed(query: str, processed_jobs: int, page_number: int):
                save_progress(
                    status="in_progress",
                    phase="processing_jobs",
                    current_query_index=0,
                    current_query=query,
                    current_page_number=int(page_number or 0),
                    last_completed_page_number=current_query_pages["value"],
                    total_pages_processed=stable_pages + current_query_pages["value"],
                    total_jobs_processed=stable_jobs + int(processed_jobs or 0),
                )

            report = await scout.run(
                query=args.query,
                location=args.location,
                max_pages=effective_pages,
                human_mode=args.human_mode,
                same_run_job_registry={},
                start_page=1,
                page_scanned_callback=on_page_scanned,
                job_processed_callback=on_job_processed,
                live_result_callback=on_live_result if live_dashboard else None,
                run_started_at=run_started_at,
                description_only=args.description_only,
            )
            stats_for_progress = report.get("stats", {})
            save_progress(
                status="completed",
                phase="completed",
                current_query_index=0,
                current_query=args.query,
                current_page_number=0,
                last_completed_query_index=0,
                last_completed_query=args.query,
                last_completed_page_number=int(report.get("pages_scanned", 0) or 0),
                total_pages_processed=stable_pages + int(report.get("pages_scanned", 0) or 0),
                total_jobs_processed=stable_jobs + int(stats_for_progress.get("job_cards_collected", 0) or 0),
                stable_total_pages_processed=stable_pages + int(report.get("pages_scanned", 0) or 0),
                stable_total_jobs_processed=stable_jobs + int(stats_for_progress.get("job_cards_collected", 0) or 0),
            )

        stats = report.get("stats", {})
        if args.description_only:
            description_log_path = report.get("description_log_path", "")
            if description_log_path:
                console.print(f"[green]Description log:[/green] {description_log_path}")
        else:
            review_writer.write(report)
            try:
                dashboard_result = update_recommended_jobs_html()
                if dashboard_result.get("updated"):
                    console.print(
                        "[green]Updated recommended_jobs.html[/green] "
                        f"(+{dashboard_result.get('new_go_jobs_added', 0)} GO, "
                        f"+{dashboard_result.get('new_consider_jobs_added', 0)} CONSIDER)."
                    )
                else:
                    console.print(
                        "[yellow]Recommended jobs dashboard was not updated:[/yellow] "
                        f"{dashboard_result.get('reason', 'unknown reason')}"
                    )
            except Exception as exc:
                console.print(f"[yellow]Could not update recommended_jobs.html:[/yellow] {exc}")
        reporter.finish_query(stats)
        reporter.finish_run(
            output_path=report.get("description_log_path") if args.description_only else scout.output_path,
            final_stats=stats,
            completed_at=report.get("completed_at", report.get("generated_at", "")),
        )
        if live_dashboard and live_run:
            live_dashboard.complete_run(live_run["run_id"], status="completed")
            live_run_completed = True
    except KeyboardInterrupt:
        live_completion_status = "stopped"
        console.print("\n[yellow]Scouting stopped by user.[/yellow]")
    finally:
        if live_dashboard and live_run and not live_run_completed:
            try:
                live_dashboard.complete_run(live_run["run_id"], status=live_completion_status)
            except Exception as exc:
                console.print(f"[yellow]Could not complete live dashboard run:[/yellow] {exc}")
        if browser:
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
    finally:
        if ACTIVE_RUN_LOGGER is not None:
            ACTIVE_RUN_LOGGER.close()
