from __future__ import annotations

from dataclasses import dataclass
import re

from rich.console import Console
from rich.text import Text


@dataclass
class ScoutRunCounters:
    collected: int = 0
    pages_processed: int = 0
    opened: int = 0
    preopen_skipped: int = 0
    postopen_rejected: int = 0
    survivors: int = 0
    ai_scored: int = 0
    accepted: int = 0
    below_threshold: int = 0
    cache_reused: int = 0
    duplicate_suppressed: int = 0
    same_run_reused: int = 0
    persistent_reused: int = 0
    previously_analyzed_skipped: int = 0
    previously_analyzed_skipped_at_card_stage: int = 0
    duplicate_job_records_prevented: int = 0
    processed: int = 0


class NullScoutConsoleReporter:
    def start_query(self, *args, **kwargs) -> None:
        pass

    def finish_query(self, *args, **kwargs) -> None:
        pass

    def finish_run(self, *args, **kwargs) -> None:
        pass

    def log(self, *args, **kwargs) -> None:
        pass

    def record_page_scan(self, *args, **kwargs) -> None:
        pass

    def record_collected_import(self, *args, **kwargs) -> None:
        pass

    def record_summary_processed(self, *args, **kwargs) -> None:
        pass

    def start_job(self, *args, **kwargs) -> None:
        pass

    def end_job(self, *args, **kwargs) -> None:
        pass

    def record_preopen_skip(self, *args, **kwargs) -> None:
        pass

    def record_job_open(self, *args, **kwargs) -> None:
        pass

    def record_reuse(self, *args, **kwargs) -> None:
        pass

    def record_description_extracted(self, *args, **kwargs) -> None:
        pass

    def record_description_saved(self, *args, **kwargs) -> None:
        pass

    def record_postopen_reject(self, *args, **kwargs) -> None:
        pass

    def record_non_ai_survivor(self, *args, **kwargs) -> None:
        pass

    def record_ai_result(self, *args, **kwargs) -> None:
        pass

    def record_previously_analyzed_skip(self, *args, **kwargs) -> None:
        pass


class ScoutConsoleReporter(NullScoutConsoleReporter):
    CATEGORY_STYLES = {
        "PAGE": "bright_blue",
        "JOB": "white",
        "SKIP-PRE": "yellow",
        "SKIP-POST": "red",
        "AI": "green",
        "AI-CANDIDATE": "bright_cyan",
        "WHY": "cyan",
        "DECISION": "white",
        "REUSE": "magenta",
        "DETAILS": "cyan",
        "DESC": "green",
        "STATE": "bright_cyan",
        "FILE": "green",
        "HUMAN": "magenta",
    }

    def __init__(self, console: Console | None = None, status_every_jobs: int = 5):
        self.console = console or Console()
        self.status_every_jobs = max(1, int(status_every_jobs or 10))
        self.counters = ScoutRunCounters()
        self.total_queries = 0
        self.current_query_index = 0
        self.current_query_name = ""
        self.current_page = 0
        self.current_query_page_limit: int | None = None
        self.current_query_page_label = "?"
        self.current_process_only = False
        self.results_layout_types: set[str] = set()
        self._last_status_processed = 0
        self._run_completed = False
        self._job_open = False
        self._pending_status = False
        self._current_job_index = 0
        self._current_job_total = 0
        self._current_phase = "collecting"
        self._current_query_processed_jobs = 0
        self._current_query_total_jobs = 0
        self._collection_phase_weight = 0.2
        self._processing_phase_weight = 0.8

    def start_query(
        self,
        *,
        query_index: int,
        total_queries: int,
        query_name: str,
        max_pages: int | None = None,
        process_only: bool = False,
    ) -> None:
        self.total_queries = max(1, int(total_queries or 1))
        self.current_query_index = max(1, int(query_index or 1))
        self.current_query_name = (query_name or "").strip()
        self.current_page = 0
        self.current_query_page_limit = max_pages if isinstance(max_pages, int) and max_pages > 0 else None
        self.current_query_page_label = (
            str(self.current_query_page_limit) if self.current_query_page_limit is not None else "all"
        )
        self.current_process_only = bool(process_only)
        self._current_phase = "processing" if self.current_process_only else "collecting"
        self._current_query_processed_jobs = 0
        self._current_query_total_jobs = 0

        separator = "=" * 60
        self.console.print(Text(separator, style="bold bright_cyan"))
        self.console.print(
            Text(
                f"QUERY {self.current_query_index} / {self.total_queries} -- {self.current_query_name}",
                style="bold bright_cyan",
            )
        )
        self.console.print(Text(separator, style="bold bright_cyan"))
        if self.current_process_only:
            self.log("STATE", "Process-only mode: reusing collected jobs instead of opening the job board.", style="bright_cyan")

    def finish_query(self, stats: dict | None = None) -> None:
        if self._job_open:
            self.end_job()
        if self._pending_status or self._last_status_processed != self.counters.processed:
            self._emit_live_status(force=True)
        if not stats:
            return
        self.log(
            "STATE",
            (
                f"Query complete | collected={int(stats.get('job_cards_collected', 0) or 0)} "
                f"opened={int(stats.get('jobs_opened', 0) or 0)} "
                f"survivors={int(stats.get('survived_non_ai', 0) or 0)} "
                f"accepted={int(stats.get('accepted_after_ai', 0) or 0)} "
                f"known_skipped={int(stats.get('previously_analyzed_jobs_skipped', 0) or 0)}"
            ),
            style="bright_cyan",
        )

    def finish_run(self, *, output_path=None, final_stats: dict | None = None, completed_at: str = "") -> None:
        self._run_completed = True
        if self._job_open:
            self.end_job()
        if self._pending_status or self._last_status_processed != self.counters.processed:
            self._emit_live_status(force=True)

        counters = self.counters
        accepted = counters.accepted
        below_threshold = counters.below_threshold
        cache_reused = counters.cache_reused
        duplicate_suppressed = counters.duplicate_suppressed
        previously_analyzed_skipped = counters.previously_analyzed_skipped
        previously_analyzed_skipped_at_card_stage = counters.previously_analyzed_skipped_at_card_stage
        duplicate_job_records_prevented = counters.duplicate_job_records_prevented
        fresh_stopped_early = False
        fresh_stop_reason = ""
        fresh_apply_first = 0
        fresh_good_or_better = 0
        fresh_new_jobs_seen = 0
        fresh_ai_calls = 0
        if final_stats:
            accepted = int(
                final_stats.get("accepted_after_ai")
                or final_stats.get("accepted")
                or final_stats.get("new_recommendations", 0)
                + final_stats.get("cached_previous_recommendations", 0)
                or accepted
            )
            below_threshold = int(final_stats.get("ai_below_threshold", below_threshold) or 0)
            cache_reused = int(final_stats.get("ai_cache_reused", cache_reused) or 0)
            duplicate_suppressed = int(
                final_stats.get("ai_duplicate_suppressed", duplicate_suppressed) or 0
            )
            previously_analyzed_skipped = int(
                final_stats.get("previously_analyzed_jobs_skipped", previously_analyzed_skipped) or 0
            )
            previously_analyzed_skipped_at_card_stage = int(
                final_stats.get(
                    "previously_analyzed_jobs_skipped_at_card_stage",
                    previously_analyzed_skipped_at_card_stage,
                )
                or 0
            )
            duplicate_job_records_prevented = int(
                final_stats.get("duplicate_job_records_prevented", duplicate_job_records_prevented) or 0
            )
            fresh_stopped_early = bool(final_stats.get("fresh_stopped_early"))
            fresh_stop_reason = str(final_stats.get("fresh_stop_reason", "") or "").strip()
            fresh_apply_first = int(final_stats.get("fresh_apply_first_jobs", 0) or 0)
            fresh_good_or_better = int(final_stats.get("fresh_good_or_better_jobs", 0) or 0)
            fresh_new_jobs_seen = int(final_stats.get("fresh_new_jobs_seen", 0) or 0)
            fresh_ai_calls = int(final_stats.get("fresh_ai_calls", 0) or 0)

        self.console.print(Text("--- RUN SUMMARY ---", style="bold bright_cyan"))
        self._summary_line("Collected", counters.collected, "bright_cyan")
        self._summary_line("Pre-open skipped", counters.preopen_skipped, "yellow")
        self._summary_line("Post-open rejected", counters.postopen_rejected, "red")
        self._summary_line("Survived to AI", counters.survivors, "bright_cyan")
        self._summary_line("Accepted", accepted, "green")
        self._summary_line("Below threshold", below_threshold, "red")
        self._summary_line("Cache reused", cache_reused, "magenta")
        self._summary_line("Duplicate suppressed", duplicate_suppressed, "magenta")
        self._summary_line("Known jobs skipped", previously_analyzed_skipped, "yellow")
        self._summary_line(
            "Known jobs skipped at card stage",
            previously_analyzed_skipped_at_card_stage,
            "yellow",
        )
        self._summary_line("Duplicate records prevented", duplicate_job_records_prevented, "magenta")
        if fresh_stopped_early or fresh_stop_reason:
            self._summary_line("Fresh stop", fresh_stop_reason or "fresh target reached", "green")
            self._summary_line("Fresh APPLY FIRST", fresh_apply_first, "green")
            self._summary_line("Fresh good or better", fresh_good_or_better, "green")
            self._summary_line("Fresh new jobs seen", fresh_new_jobs_seen, "bright_cyan")
            self._summary_line("Fresh AI calls", fresh_ai_calls, "bright_cyan")
        if completed_at:
            self._summary_line("Completed at", completed_at, "bright_cyan")
        self.console.print(Text("-------------------", style="bold bright_cyan"))
        if output_path:
            self.log("FILE", f"Output file: {output_path}", style="green")

    def log(self, category: str, message: str, *, style: str | None = None) -> None:
        prefix_style = self.CATEGORY_STYLES.get(category, "white")
        line = Text()
        line.append(f"[{category}] ", style=prefix_style)
        line.append((message or "").strip(), style=style or "white")
        self.console.print(line)

    def record_page_scan(
        self,
        *,
        page_number: int,
        new_cards: int,
        total_collected: int,
        results_layout_type: str = "",
        cards_seen: int = 0,
        known_cards: int = 0,
        known_ratio: float = 0.0,
    ) -> None:
        self._current_phase = "collecting"
        self.current_page = max(self.current_page, int(page_number or 0))
        self.counters.pages_processed += 1
        self.counters.collected += int(new_cards or 0)
        if results_layout_type:
            self.results_layout_types.add(results_layout_type)
        total_label = self.current_query_page_label
        if cards_seen:
            known_percent = round(float(known_ratio or 0) * 100)
            self.log(
                "PAGE",
                (
                    f"Page {page_number}/{total_label} scanned | "
                    f"cards={cards_seen} known={known_cards} new={new_cards} "
                    f"known_ratio={known_percent}%"
                ),
                style="bright_blue",
            )
        else:
            self.log("PAGE", f"Page {page_number}/{total_label} scanned | new={new_cards}", style="bright_blue")
        self._emit_live_status(force=True)

    def record_collected_import(self, *, total_collected: int) -> None:
        self.counters.collected += int(total_collected or 0)
        self._current_phase = "processing"
        self._current_query_total_jobs = int(total_collected or 0)
        self._current_query_processed_jobs = 0
        self.log(
            "REUSE",
            f"Loaded {int(total_collected or 0)} stored collected jobs for processing-only reuse.",
            style="magenta",
        )
        self._emit_live_status(force=True)

    def record_summary_processed(self, *, page_number: int | None = None, processed_index: int | None = None) -> None:
        self.counters.processed += 1
        if page_number:
            self.current_page = max(self.current_page, int(page_number or 0))
        if processed_index is not None:
            self._current_query_processed_jobs = max(
                self._current_query_processed_jobs,
                int(processed_index or 0),
            )
        if (self.counters.processed - self._last_status_processed) < self.status_every_jobs:
            return
        if self._job_open:
            self._pending_status = True
            return
        self._emit_live_status(force=False)

    def start_job(self, *, index: int, total: int, title: str, company: str, url: str = "") -> None:
        if self._job_open:
            self.end_job()
        self._job_open = True
        self._current_phase = "processing"
        self._current_job_index = int(index or 0)
        self._current_job_total = int(total or 0)
        self._current_query_total_jobs = max(self._current_query_total_jobs, self._current_job_total)
        separator = "-" * 16 + f" JOB {self._current_job_index}/{self._current_job_total} " + "-" * 16
        self.console.print(Text(separator, style="bold white"))
        query_line = Text()
        query_line.append("Query: ", style="bold white")
        query_line.append(self.current_query_name, style="white")
        self.console.print(query_line)
        title_line = Text()
        title_line.append("Title: ", style="bold white")
        title_line.append(
            f"{self._truncate_display(self._clean_title(title))} @ {self._clean_company(company)}",
            style="white",
        )
        self.console.print(title_line)
        if (url or "").strip():
            link_line = Text()
            link_line.append("Link: ", style="bold white")
            link_line.append((url or "").strip(), style="white")
            self.console.print(link_line)

    def end_job(self) -> None:
        if not self._job_open:
            return
        self.console.print(Text("-" * 41, style="dim"))
        self._job_open = False
        if self._pending_status:
            self._pending_status = False
            self._emit_live_status(force=True)

    def record_preopen_skip(self, *, reason: str) -> None:
        self.counters.preopen_skipped += 1
        self.log(
            "SKIP-PRE",
            reason,
            style="yellow",
        )

    def record_job_open(self, *, title: str = "", company: str = "", index: int = 0, total: int = 0) -> None:
        self.counters.opened += 1

    def record_reuse(self, *, kind: str, detail: str = "") -> None:
        if kind == "same_run":
            self.counters.same_run_reused += 1
        elif kind == "persistent":
            self.counters.persistent_reused += 1

    def record_description_extracted(self, *, length: int, extracted: bool, mode: str = "extracted") -> None:
        if extracted:
            self.log("DETAILS", f"len={int(length or 0)}", style="cyan")
        else:
            self.log("DETAILS", "len=0", style="red")

    def record_description_saved(self, *, count: int, file_name: str, language_tag: str) -> None:
        self.log(
            "DESC",
            f"Saved description {int(count or 0)} -> {file_name} | {language_tag}",
            style="green",
        )

    def record_postopen_reject(self, *, reason: str) -> None:
        self.counters.postopen_rejected += 1
        self.log(
            "SKIP-POST",
            reason,
            style="red",
        )

    def record_non_ai_survivor(self) -> None:
        self.counters.survivors += 1

    def record_ai_result(
        self,
        *,
        title: str,
        score: int,
        match_tier: str,
        status: str,
        cache_status: str,
        reason: str = "",
    ) -> None:
        normalized_status = (status or "").strip().lower()
        normalized_cache_status = (cache_status or "").strip().lower()
        if normalized_cache_status == "reused_unchanged":
            self.counters.cache_reused += 1
        else:
            self.counters.ai_scored += 1

        if normalized_status in {"accepted", "duplicate_suppressed"}:
            self.counters.accepted += 1
        elif normalized_status == "below_threshold":
            self.counters.below_threshold += 1

        if normalized_status == "duplicate_suppressed":
            self.counters.duplicate_suppressed += 1

        if normalized_status == "ai_error":
            self.log("AI", "Score: unavailable | ai_error", style="red")
            short_reason = self._short_ai_reason(reason)
            if short_reason:
                self.log("WHY", short_reason, style="red")
            self.log("DECISION", "NO GO", style="red")
            return

        decision, decision_style = self._decision_label(int(score or 0))
        self.log("AI", f"Score: {int(score or 0)} | {match_tier}", style=decision_style)
        short_reason = self._short_ai_reason(reason)
        if short_reason:
            self.log("WHY", short_reason, style="white")
        self.log("DECISION", decision, style=decision_style)

    def record_previously_analyzed_skip(self, *, stage: str = "card_stage", count: int = 1) -> None:
        amount = max(0, int(count or 0))
        if amount <= 0:
            return
        self.counters.previously_analyzed_skipped += amount
        self.counters.duplicate_job_records_prevented += amount
        if (stage or "").strip().lower() == "card_stage":
            self.counters.previously_analyzed_skipped_at_card_stage += amount

    def _emit_live_status(self, *, force: bool) -> None:
        if not force and (self.counters.processed - self._last_status_processed) < self.status_every_jobs:
            return
        self._last_status_processed = self.counters.processed

        self.console.print(Text("--- STATUS ---", style="bold bright_cyan"))
        line_one = Text()
        line_one.append(self._progress_label(), style="white")
        self.console.print(line_one)
        line_two = Text()
        line_two.append(
            (
                f"Collected: {self.counters.collected} | Opened: {self.counters.opened} "
                f"| Survivors: {self.counters.survivors} | AI: {self.counters.ai_scored}"
            ),
            style="white",
        )
        self.console.print(line_two)
        self.console.print(Text("--------------", style="bold bright_cyan"))

    def _approx_progress_percent(self) -> int:
        if self._run_completed:
            return 100
        if self.total_queries <= 0:
            return 0

        completed_queries = max(0, self.current_query_index - 1)
        query_fraction = self._current_query_fraction()

        percent = int(((completed_queries + query_fraction) / self.total_queries) * 100)
        return max(0, min(percent, 99))

    def _current_query_fraction(self) -> float:
        if self.current_process_only:
            if self._current_query_total_jobs > 0:
                return min(self._current_query_processed_jobs / self._current_query_total_jobs, 1.0)
            return 0.0

        if self._current_phase == "processing":
            if self._current_query_total_jobs > 0:
                jobs_fraction = min(self._current_query_processed_jobs / self._current_query_total_jobs, 1.0)
            else:
                jobs_fraction = 0.0
            return min(
                self._collection_phase_weight + (jobs_fraction * self._processing_phase_weight),
                1.0,
            )

        if self.current_query_page_limit:
            page_fraction = min((self.current_page or 0) / self.current_query_page_limit, 1.0)
        elif self.current_page > 0:
            page_fraction = min(self.current_page / (self.current_page + 2), 0.85)
        else:
            page_fraction = 0.0
        return min(page_fraction * self._collection_phase_weight, self._collection_phase_weight)

    def _progress_label(self) -> str:
        percent = self._approx_progress_percent()
        if self._current_phase == "processing":
            if self._current_query_total_jobs > 0:
                phase_detail = f"Jobs {self._current_query_processed_jobs}/{self._current_query_total_jobs}"
            else:
                phase_detail = "Jobs 0/0"
        else:
            phase_detail = f"Collecting pages (Page {self.current_page or 0})"
        return (
            f"Progress: ~{percent}% | Query {self.current_query_index}/{self.total_queries} | "
            f"{phase_detail}"
        )

    def _summary_line(self, label: str, value, style: str) -> None:
        line = Text()
        line.append(f"{label}: ", style=style)
        if isinstance(value, int):
            rendered = str(int(value or 0))
        else:
            rendered = str(value or "")
        line.append(rendered, style="white")
        self.console.print(line)

    def _clean_company(self, company: str) -> str:
        return " ".join((company or "").split())

    def _clean_title(self, title: str) -> str:
        words = " ".join((title or "").split()).split()
        if not words:
            return ""
        changed = True
        while changed:
            changed = False
            max_n = min(len(words) // 2, 6)
            for size in range(max_n, 1, -1):
                if words[:size] == words[size : size * 2]:
                    words = words[:size] + words[size * 2 :]
                    changed = True
                    break
        return " ".join(words)

    def _truncate_display(self, value: str, max_chars: int = 96) -> str:
        text = " ".join((value or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    def _decision_label(self, score: int) -> tuple[str, str]:
        numeric = int(score or 0)
        if numeric >= 70:
            return "GO", "green"
        if numeric >= 50:
            return "CONSIDER", "yellow"
        return "NO GO", "red"

    def _short_ai_reason(self, reason: str, max_chars: int = 120) -> str:
        normalized = re.sub(r"\s+", " ", str(reason or "").strip())
        if not normalized:
            return ""
        normalized = re.sub(r"^[\"'`\-\s]+", "", normalized)
        sentence_match = re.match(r"(.+?[.!?])(?:\s|$)", normalized)
        if sentence_match:
            normalized = sentence_match.group(1).strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3].rstrip(" ,;:-") + "..."
