import asyncio
from time import perf_counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.brain import JobBrain
from agent.browser import BrowserController
from agent.tracker import ApplicationTracker
from scrapers.glassdoor import GlassdoorScraper
from scrapers.indeed import IndeedScraper
from scrapers.linkedin import LinkedInScraper

console = Console()


class JobAgent:
    """
    Main orchestrator. Searches for jobs, evaluates them, and applies.
    Claude (brain) looks at each page and decides what to do next.
    """

    MAX_ACTIONS_PER_APPLICATION = 50
    ASSESSMENT_HINTS = (
        "skills assessment",
        "personality test",
        "cognitive test",
        "aptitude test",
        "coding challenge",
        "take-home assignment",
        "pre-employment test",
        "online assessment",
        "complete this assessment",
    )

    def __init__(
        self,
        profile: dict,
        preferences: dict,
        browser: BrowserController,
        tracker: ApplicationTracker,
        runtime_mode: str = "apply",
        selected_jobs_file: str | None = None,
    ):
        self.profile = profile
        self.preferences = preferences
        self.browser = browser
        self.tracker = tracker
        self.brain = JobBrain(profile, preferences)
        self.runtime_mode = runtime_mode
        self.selected_jobs_file = selected_jobs_file

        application_behavior = self.preferences.get("application_behavior", {})
        self.browser.set_human_delays(
            application_behavior.get("add_human_like_delays", True)
        )

        self.linkedin = LinkedInScraper(browser)
        self.indeed = IndeedScraper(browser)
        self.glassdoor = GlassdoorScraper(browser)

    async def run(self):
        """Main loop: search -> evaluate -> apply."""
        session_started_at = perf_counter()
        console.print(Panel("[bold green]Job Agent Started[/bold green]", expand=False))

        today_count = self.tracker.get_today_count()
        max_today = self.preferences.get("max_applications_per_day", 20)
        console.print(f"Applications today so far: {today_count}/{max_today}")

        if today_count >= max_today:
            console.print("[yellow]Daily limit reached. Come back tomorrow![/yellow]")
            return

        search_started_at = perf_counter()
        all_jobs = await self._collect_jobs()
        search_elapsed = perf_counter() - search_started_at
        console.print(f"\nTotal jobs found: [bold]{len(all_jobs)}[/bold]")

        scored_jobs = []
        skip_duplicates = self.preferences.get("application_behavior", {}).get(
            "skip_if_already_applied", True
        )

        for job in all_jobs:
            job_id = job.get("id", "")
            if job_id:
                self.tracker.mark_seen(job_id)
            if skip_duplicates and (
                self.tracker.already_processed(job_id)
                or (self.runtime_mode != "dry_run" and self.tracker.already_rejected(job_id))
            ):
                continue

            match = self.brain.evaluate_job_match(job)
            job["match_score"] = match["score"]
            job["match_reasons"] = match["reasons"]
            if match["apply"]:
                if self.runtime_mode != "dry_run":
                    self.tracker.record_review(
                        job,
                        "qualified",
                        "; ".join(match["reasons"]),
                    )
                scored_jobs.append(job)
            elif self.runtime_mode != "dry_run":
                self.tracker.record_review(
                    job,
                    "rejected",
                    "; ".join(match["reasons"]),
                )

        scored_jobs.sort(key=lambda item: item["match_score"], reverse=True)
        console.print(f"Jobs passing filter: [bold]{len(scored_jobs)}[/bold]")

        self._print_job_table(scored_jobs[:10])

        max_per_run = self.preferences.get("max_applications_per_run", 10)
        max_jobs_to_try = self.preferences.get(
            "max_jobs_to_try_per_run",
            max(3, max_per_run),
        )
        applied = 0
        attempted = 0
        apply_started_at = perf_counter()

        for job in scored_jobs:
            if today_count + applied >= max_today:
                console.print("[yellow]Daily limit reached, stopping.[/yellow]")
                break
            if applied >= max_per_run:
                break
            if attempted >= max_jobs_to_try:
                console.print(
                    f"[yellow]Reached attempt limit for this run ({max_jobs_to_try} jobs tried).[/yellow]"
                )
                break

            attempted += 1

            console.print(
                f"\nApplying to: [bold]{job['title']}[/bold] at [cyan]{job['company']}[/cyan]"
            )
            console.print(f"   Score: {job['match_score']} | Source: {job.get('source', 'linkedin')}")

            result = await self._apply_to_job(job)
            if result == "roadblock":
                console.print("[bold red][ROADBLOCK] Hit LinkedIn limit or roadblock. Halting batch safely — remaining un-attempted jobs stay unreviewed.[/bold red]")
                break
            success = bool(result)

            if success:
                applied += 1
                console.print("   [green]Applied successfully![/green]")
            else:
                console.print("   [yellow]Skipped or failed[/yellow]")

            await asyncio.sleep(10 + (applied * 2))

        apply_elapsed = perf_counter() - apply_started_at
        total_elapsed = perf_counter() - session_started_at

        console.print(f"\nSession complete. Applied to {applied} jobs.")
        console.print(f"Jobs tried this run: {attempted}")
        console.print(
            "Timing: "
            f"search {self._format_elapsed(search_elapsed)} | "
            f"apply {self._format_elapsed(apply_elapsed)} | "
            f"total {self._format_elapsed(total_elapsed)}"
        )
        self.tracker.print_summary()

    async def validate_boards(self):
        """Validate the current job-board selectors without applying."""
        started_at = perf_counter()
        console.print(Panel("[bold green]Job Board Validation[/bold green]", expand=False))

        results = []
        boards = self.preferences.get("job_boards", {})

        if boards.get("standalone_sites", {}).get("enabled", False):
            console.print(
                "[yellow]Warning:[/yellow] standalone_sites is enabled in config but is not implemented yet."
            )

        if boards.get("linkedin", {}).get("enabled", True):
            results.append(await self._validate_board("LinkedIn", self.linkedin.validate_search))

        if boards.get("indeed", {}).get("enabled", True):
            results.append(await self._validate_board("Indeed", self.indeed.validate_search))

        if boards.get("glassdoor", {}).get("enabled", True):
            results.append(await self._validate_board("Glassdoor", self.glassdoor.validate_search))

        table = Table(title="Board Validation Summary", show_lines=True)
        table.add_column("Board", style="bold")
        table.add_column("Status", style="cyan")
        table.add_column("Cards", justify="right")
        table.add_column("Jobs", justify="right")
        table.add_column("Sample", style="green")
        table.add_column("Notes", overflow="fold")

        for result in results:
            table.add_row(
                result.get("board", ""),
                result.get("status", ""),
                str(result.get("cards_seen", 0)),
                str(result.get("jobs_extracted", 0)),
                result.get("sample", "")[:40],
                result.get("notes", "")[:80],
            )

        console.print(table)
        console.print(f"Validation finished in {self._format_elapsed(perf_counter() - started_at)}")
        return results

    def _load_local_unreviewed_jobs(self) -> list:
        """Load unreviewed jobs directly from local database without running search queries."""
        import json
        from pathlib import Path

        target_keys = set()
        if self.selected_jobs_file:
            sel_path = Path(self.selected_jobs_file)
            if sel_path.exists():
                try:
                    sel_data = json.loads(sel_path.read_text(encoding="utf-8"))
                    keys_list = sel_data.get("selected_keys", []) if isinstance(sel_data, dict) else []
                    target_keys = set(keys_list)
                    if target_keys:
                        console.print(f"[cyan][TARGETED APPLY MODE][/cyan] Filtered to apply specifically to {len(target_keys)} selected job(s).")
                except Exception as exc:
                    console.print(f"[yellow]Could not parse selected jobs file: {exc}[/yellow]")

        paths = [
            Path("data/recommended_jobs_dashboard_data.json"),
            Path("data/user_workspace/dashboard_data.json"),
            Path("data/recommended_jobs_dashboard.json"),
        ]
        all_jobs = []
        
        db_path = Path("data/user_workspace/job_scout.db")
        if db_path.exists():
            try:
                import sqlite3
                with sqlite3.connect(db_path) as conn:
                    for row in conn.execute("SELECT payload_json FROM jobs"):
                        if not row[0]: continue
                        try:
                            job = json.loads(row[0])
                            status = job.get("manual_status", "unreviewed")
                            if status not in {"unreviewed", "qualified"}:
                                continue
                            raw_job_key = str(job.get("job_key") or "")
                            raw_job_id = str(job.get("job_id") or "")
                            raw_url = str(job.get("url", ""))
                            if target_keys:
                                matched = False
                                for tk in target_keys:
                                    if (raw_job_key and raw_job_key == tk) or \
                                       (raw_job_id and (raw_job_id == tk or raw_job_id in tk)) or \
                                       (raw_url and raw_url == tk):
                                        matched = True
                                        break
                                if matched:
                                    all_jobs.append(job)
                            else:
                                all_jobs.append(job)
                        except Exception:
                            pass
            except Exception as exc:
                console.print(f"[yellow]Warning loading job_scout.db: {exc}[/yellow]")
                
        for path in paths:
            if all_jobs:
                break
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
                    for job in jobs:
                        if not isinstance(job, dict):
                            continue
                        status = job.get("manual_status", "unreviewed")
                        if status not in {"unreviewed", "qualified"}:
                            continue
                        raw_job_key = str(job.get("job_key") or "")
                        raw_job_id = str(job.get("job_id") or "")
                        raw_url = str(job.get("url", ""))
                        if target_keys:
                            matched = False
                            for tk in target_keys:
                                if (raw_job_key and raw_job_key == tk) or \
                                   (raw_job_id and (raw_job_id == tk or raw_job_id in tk)) or \
                                   (raw_url and raw_url == tk):
                                    matched = True
                                    break
                            if matched:
                                all_jobs.append(job)
                        else:
                            all_jobs.append(job)
                except Exception as exc:
                    console.print(f"[yellow]Warning loading {path}: {exc}[/yellow]")
                    continue
            if all_jobs:
                break
        return all_jobs

    async def _collect_jobs(self) -> list:
        """Collect jobs from all enabled job boards or local storage."""
        if self.runtime_mode in {"apply", "auto_apply_selected", "process_only"}:
            console.print("[cyan][APPLY-ONLY MODE][/cyan] Reading unreviewed jobs directly from local database (no search scouting).")
            return self._load_local_unreviewed_jobs()

        all_jobs = []
        boards = self.preferences.get("job_boards", {})

        if boards.get("standalone_sites", {}).get("enabled", False):
            console.print(
                "[yellow]Warning:[/yellow] standalone_sites is enabled in config but is not implemented yet."
            )

        if boards.get("linkedin", {}).get("enabled", True):
            try:
                logged_in = await self.linkedin.ensure_logged_in()
                if logged_in:
                    all_jobs.extend(await self.linkedin.search_jobs(self.preferences))
            except Exception as exc:
                console.print(f"[red]LinkedIn error: {exc}[/red]")

        if boards.get("indeed", {}).get("enabled", True):
            try:
                all_jobs.extend(await self.indeed.search_jobs(self.preferences))
            except Exception as exc:
                console.print(f"[red]Indeed error: {exc}[/red]")

        if boards.get("glassdoor", {}).get("enabled", True):
            try:
                all_jobs.extend(await self.glassdoor.search_jobs(self.preferences))
            except Exception as exc:
                console.print(f"[red]Glassdoor error: {exc}[/red]")

        return all_jobs

    async def _validate_board(self, board_name: str, validator):
        try:
            return await validator(self.preferences)
        except Exception as exc:
            return {
                "board": board_name,
                "status": "error",
                "cards_seen": 0,
                "jobs_extracted": 0,
                "sample": "",
                "notes": str(exc),
            }

    async def _apply_to_job(self, job: dict) -> bool:
        """Full application flow for a single job."""
        try:
            # Deduce source if missing to ensure proper routing
            if not job.get("source"):
                url = str(job.get("url") or job.get("link") or "").lower()
                if "linkedin.com" in url:
                    job["source"] = "linkedin"

            source = job.get("source", "linkedin").lower()
            if source == "linkedin":
                job = await self.linkedin.get_job_details(job)
                if await self.linkedin.is_linkedin_limit_roadblock():
                    console.print("   [bold red][ROADBLOCK] LinkedIn daily limit or captcha detected. Halting batch safely.[/bold red]")
                    return "roadblock"
                if await self.linkedin.is_job_expired_on_page():
                    console.print(f"   [yellow]Job is expired on LinkedIn:[/yellow] {job.get('title')}")
                    self.tracker.record_application(job, "expired", "LinkedIn job listing is closed/expired")
                    return False
                if job.get("already_applied"):
                    console.print("   Skipping LinkedIn job because it is already marked as applied")
                    self.tracker.record_application(
                        job,
                        "skipped",
                        "LinkedIn already shows this job as applied",
                    )
                    return False
                easy_apply_only = self.preferences.get("job_boards", {}).get(
                    "linkedin", {}
                ).get("easy_apply_only", False)
                if easy_apply_only and not job.get("easy_apply"):
                    console.print("   Skipping LinkedIn job because Easy Apply only is enabled")
                    self.tracker.record_application(
                        job,
                        "skipped",
                        "LinkedIn easy_apply_only is enabled",
                    )
                    return False
                clicked = await self.linkedin.click_apply(job)
                if not clicked:
                    console.print("   Could not click Apply button")
                    self.tracker.record_application(job, "failed", "No apply button found")
                    return False
            elif job["source"] == "indeed":
                job = await self.indeed.get_job_details(job)
            elif job["source"] == "glassdoor":
                job = await self.glassdoor.get_job_details(job)
            else:
                await self.browser.goto(job["url"])
                await asyncio.sleep(2)
        except Exception as exc:
            console.print(f"   Error navigating to job: {exc}")
            return False

        match = self.brain.evaluate_job_match(job)
        if not match["apply"]:
            console.print(f"   Skipping after reading full description: {match['reasons']}")
            self.tracker.record_application(job, "skipped", str(match["reasons"]))
            return False

        application_behavior = self.preferences.get("application_behavior", {})
        cover_letter = ""
        should_submit_cover_letter = application_behavior.get("submit_cover_letter", True)
        should_generate_cover_letter = application_behavior.get(
            "generate_cover_letter_with_ai", True
        )

        if should_submit_cover_letter and should_generate_cover_letter:
            try:
                cover_letter = self.brain.generate_cover_letter_reasoning(job)
            except Exception as exc:
                console.print(f"   Cover letter generation failed: {exc}")

        linkedin_easy_apply_active = False
        if job.get("source") == "linkedin":
            linkedin_easy_apply_active = job.get("easy_apply") or await self.linkedin.is_easy_apply_flow_active()
            if linkedin_easy_apply_active:
                job["easy_apply"] = True

        if linkedin_easy_apply_active:
            result = await self._linkedin_easy_apply_flow(job)
        else:
            result = await self._claude_fill_application(job, cover_letter)
        status = result.get("status", "failed")
        reason = result.get("reason", "")

        if status == "needs_human":
            console.print(f"   [yellow]Human review needed:[/yellow] {reason}")
            input("   Handle it in the browser, then press Enter to continue: ")
            learned_answers = {}
            if job.get("source") == "linkedin":
                learned_answers = await self.linkedin.capture_answered_questions(
                    result.get("questions", [])
                )
            if learned_answers:
                for question, answer in learned_answers.items():
                    self.brain.save_learned_answer(question, answer)
                console.print(
                    f"   [green]Saved {len(learned_answers)} answer(s) for future runs.[/green]"
                )
            else:
                unknown_question = result.get("question", "")
                if unknown_question:
                    learned_answer = input(
                        "   Optional: paste the answer you used to save it for next time, or press Enter to skip: "
                    ).strip()
                    if learned_answer:
                        self.brain.save_learned_answer(unknown_question, learned_answer)
                        console.print("   [green]Saved answer for future runs.[/green]")
            result = await self._claude_fill_application(job, cover_letter)
            status = result.get("status", "failed")
            reason = result.get("reason", reason)

        self.tracker.record_application(job, status, reason)
        
        # Sync to dashboard operational store if available
        try:
            from agent.operational_store import OperationalStore
            from agent.dashboard_user_state import DashboardUserStateStore, build_job_key
            import os
            from pathlib import Path
            root = Path(os.getcwd())
            dashboard_path = root / "data" / "recommended_jobs_dashboard_data.json"
            user_state_path = root / "data" / "recommended_jobs_dashboard_user_state.json"
            db_path = root / "data" / "user_workspace" / "job_scout.db"
            
            if db_path.exists():
                job_key = build_job_key(job)
                state_store = DashboardUserStateStore(user_state_path)
                record = state_store.set_status(job, status)
                op_store = OperationalStore(db_path)
                op_store.update_job_status(
                    job_key=job_key,
                    status=status,
                    record=record if status != "unreviewed" else None,
                    dashboard_path=dashboard_path,
                    user_state_path=user_state_path,
                )
        except Exception as exc:
            console.print(f"   [yellow]Warning: Could not sync dashboard status: {exc}[/yellow]")

        return status == "applied"

    async def _linkedin_easy_apply_flow(self, job: dict) -> dict:
        """Handle LinkedIn Easy Apply using modal-only control.

        While this method is running, the generic Claude/browser loop is NOT active.
        All actions are scoped exclusively to the Easy Apply modal.
        """
        console.print(
            f"   [bold cyan][MODAL-FLOW][/bold cyan] Entering modal-only control — "
            f"{job.get('title')} @ {job.get('company')}"
        )

        for step in range(self.MAX_ACTIONS_PER_APPLICATION):
            modal_result = await self.linkedin.handle_easy_apply_modal(self.brain)
            if modal_result:
                modal_status = modal_result.get("status", "")
                modal_reason = modal_result.get("reason", "")
                console.print(
                    f"   Step {step + 1}: [dim]linkedin_modal[/dim] - {modal_reason[:80]}"
                )

                if modal_status == "continue":
                    await self.browser.human_delay(0.4, 0.9)
                    continue
                if modal_status in {"applied", "skipped", "failed"}:
                    console.print(
                        f"   [bold cyan][MODAL-FLOW][/bold cyan] Exiting modal-only control — "
                        f"status={modal_status}"
                    )
                    return modal_result

            if await self.linkedin.is_easy_apply_modal_open():
                await self.browser.human_delay(0.5, 1.0)
                continue

            page_text = (await self.browser.get_page_text()).lower()
            if any(marker in page_text for marker in [
                "application submitted",
                "application sent",
                "your application was sent",
            ]):
                result = {
                    "status": "applied",
                    "reason": "LinkedIn application confirmation detected after modal closed",
                }
                console.print(
                    f"   [bold cyan][MODAL-FLOW][/bold cyan] Exiting modal-only control — "
                    f"status=applied (page confirmation)"
                )
                return result

            if step < 3:
                await self.browser.human_delay(0.6, 1.2)
                continue

            result = {
                "status": "failed",
                "reason": "LinkedIn Easy Apply modal was not available for modal-only control",
            }
            console.print(
                f"   [bold cyan][MODAL-FLOW][/bold cyan] Exiting modal-only control — "
                f"status=failed (modal not available at step {step + 1})"
            )
            return result

        result = {"status": "failed", "reason": "LinkedIn Easy Apply modal steps exceeded"}
        console.print(
            f"   [bold cyan][MODAL-FLOW][/bold cyan] Exiting modal-only control — "
            f"status=failed (max steps reached)"
        )
        return result

    async def _claude_fill_application(self, job: dict, cover_letter: str) -> dict:
        """Core loop: Claude looks at the page, decides an action, browser executes it."""
        history = []
        task = f"Apply for the job: {job['title']} at {job['company']}"
        application_behavior = self.preferences.get("application_behavior", {})
        pause_before_submit = application_behavior.get("pause_before_final_submit", False)

        for step in range(self.MAX_ACTIONS_PER_APPLICATION):
            try:
                screenshot = await self.browser.screenshot_base64()
                page_text = await self.browser.get_page_text()

                if self._should_skip_assessment(page_text):
                    return {
                        "status": "skipped",
                        "reason": "Assessment detected and skip_assessments is enabled",
                    }

                decision = await self.brain.decide_next_action(
                    screenshot_b64=screenshot,
                    page_text=page_text,
                    task=task,
                    cover_letter=cover_letter,
                    history=history
                )

                action = decision.get("action", "wait")
                params = decision.get("params", {})
                reasoning = decision.get("reasoning", "")

                if action == "answer_question":
                    structured_answer = self.brain.get_structured_question_answer(
                        params.get("question", ""),
                        context=params.get("context") or page_text,
                    )
                    if structured_answer:
                        params["_resolved_answer"] = structured_answer
                    elif application_behavior.get("pause_on_unknown_question", False):
                        return {
                            "status": "needs_human",
                            "reason": f"Unknown application question: {params.get('question', '')[:140]}",
                            "question": params.get("question", ""),
                        }

                console.print(f"   Step {step + 1}: [dim]{action}[/dim] - {reasoning[:80]}")

                if pause_before_submit and action == "click_selector" and any(
                    word in str(params).lower()
                    for word in ["submit", "apply now", "send application"]
                ):
                    console.print("   [yellow]About to submit - review in browser[/yellow]")
                    input("   Press Enter to submit, Ctrl+C to cancel: ")

                result = await self._execute_action(action, params, page_text)

                history.append({
                    "step": step + 1,
                    "action": action,
                    "params": params,
                    "reasoning": reasoning,
                    "executed": result,
                })

                if action == "done":
                    return params

                await self.browser.human_delay(0.5, 1.5)
            except Exception as exc:
                console.print(f"   Step error: {exc}")
                history.append({"step": step + 1, "error": str(exc)})
                continue

        return {"status": "failed", "reason": "Max steps reached"}

    async def _execute_action(self, action: str, params: dict, page_text: str) -> bool:
        """Execute a single browser action."""
        try:
            if action == "click_selector":
                selector = params.get("selector", "")
                if selector:
                    await self.browser.click_selector(selector)
            elif action == "click_text":
                await self.browser.click_text(params.get("text", ""))
            elif action == "type_text":
                await self.browser.type_in_field(
                    params.get("selector", ""),
                    params.get("text", "")
                )
            elif action == "fill_field":
                await self.browser.fill_field(
                    params.get("selector", ""),
                    params.get("value", "")
                )
            elif action == "answer_question":
                if not self.preferences.get("application_behavior", {}).get(
                    "answer_screening_questions", True
                ):
                    return False
                answer = params.get("_resolved_answer") or self.brain.answer_question(
                    params.get("question", ""),
                    context=params.get("context") or page_text,
                )
                selector = params.get("selector", "")
                method = params.get("method", "type_text")
                if method == "fill_field":
                    await self.browser.fill_field(selector, answer)
                else:
                    await self.browser.type_in_field(selector, answer)
            elif action == "select_option":
                await self.browser.select_option(
                    params.get("selector", ""),
                    label=params.get("label"),
                    value=params.get("value")
                )
            elif action == "upload_file":
                await self.browser.upload_file(
                    params.get("selector", ""),
                    params.get("path") or self.profile.get(
                        "cv_path",
                        f"cv/{((self.profile.get('personal') or {}).get('first_name', '') + ' ' + (self.profile.get('personal') or {}).get('last_name', '')).strip() or 'Your Name'} - CV Resume (English).pdf",
                    )
                )
            elif action == "scroll_down":
                await self.browser.scroll_down(params.get("amount", 500))
            elif action == "scroll_to_bottom":
                await self.browser.scroll_to_bottom()
            elif action == "navigate":
                await self.browser.goto(params.get("url", ""))
            elif action == "wait":
                await asyncio.sleep(float(params.get("seconds", 2)))
            elif action == "done":
                pass
            return True
        except Exception as exc:
            console.print(f"   Action error ({action}): {exc}")
            return False

    def _should_skip_assessment(self, page_text: str) -> bool:
        if not self.preferences.get("application_behavior", {}).get("skip_assessments", False):
            return False
        lowered = (page_text or "").lower()
        return any(hint in lowered for hint in self.ASSESSMENT_HINTS)

    def _print_job_table(self, jobs: list):
        """Print a summary table of found jobs."""
        if not jobs:
            return

        table = Table(title="Top Job Matches", show_lines=True)
        table.add_column("Score", style="green", width=6)
        table.add_column("Title", style="bold")
        table.add_column("Company", style="cyan")
        table.add_column("Source", style="dim")
        for job in jobs:
            table.add_row(
                str(job.get("match_score", 0)),
                job.get("title", "")[:40],
                job.get("company", "")[:25],
                job.get("source", ""),
            )
        console.print(table)

    def _format_elapsed(self, seconds: float) -> str:
        total_seconds = max(0, int(round(seconds)))
        minutes, remaining_seconds = divmod(total_seconds, 60)
        hours, remaining_minutes = divmod(minutes, 60)

        if hours:
            return f"{hours}h {remaining_minutes}m {remaining_seconds}s"
        if minutes:
            return f"{minutes}m {remaining_seconds}s"
        return f"{remaining_seconds}s"
