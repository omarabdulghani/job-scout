"""Serve the live jobs dashboard with local-only persistence endpoints."""

from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import requests
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from agent.ai_settings_service import AISettingsService
from agent.application_assistant_service import ApplicationAssistantService
from agent.board_settings_service import BoardSettingsService
from agent.dashboard_user_state import (
    DashboardUserStateStore,
    build_job_key,
)
from agent.profile_service import ProfileService
from agent.maintenance_service import MaintenanceService
from agent.legacy_tools_service import LegacyToolsService
from agent.live_recommended_jobs_dashboard import LiveRecommendedJobsDashboard
from agent.operational_store import OperationalStore
from agent.process_identity import inspect_process, terminate_process
from agent.safe_file_io import PersistenceError, atomic_write_json, load_json_with_recovery
from agent.scout_stop import clear_stop_request, request_stop
from agent.search_scope import (
    EMPLOYMENT_PREFERENCES,
    MARKET_PROFILES,
    SEARCH_MARKETS,
    build_search_scope,
    built_in_missions,
    market_profiles,
    platform_capabilities,
)
from agent.strategy_service import StrategyService
from agent.user_workspace import UserWorkspace


DEFAULT_HOST = os.environ.get("HOST", "0.0.0.0") if "PORT" in os.environ else "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("PORT", 8000))
DEFAULT_DASHBOARD_DATA_PATH = Path("data/recommended_jobs_dashboard_data.json")
DEFAULT_USER_STATE_PATH = Path("data/recommended_jobs_dashboard_user_state.json")
DEFAULT_PROGRESS_PATH = Path("data/scout_progress.json")
DEFAULT_RUN_STATE_PATH = Path("data/user_workspace/dashboard_run_state.json")

def _test_proxy_preflight() -> tuple[bool, str]:
    proxy_server = os.environ.get("SCRAPING_PROXY_SERVER")
    proxy_username = os.environ.get("SCRAPING_PROXY_USERNAME")
    proxy_password = os.environ.get("SCRAPING_PROXY_PASSWORD")
    
    if not proxy_server:
        return True, ""
        
    server_clean = proxy_server.replace("http://", "").replace("https://", "")
    proxy_url = f"http://{proxy_username}:{proxy_password}@{server_clean}" if proxy_username else proxy_server
    proxies = {"http": proxy_url, "https": proxy_url}
    
    try:
        response = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
        return True, response.json().get("ip", "unknown")
    except Exception as e:
        return False, str(e)



class DashboardRunController:
    """Local-only controller for approved scout commands."""

    WORKFLOW_LABELS = {
        "linkedin_multi_fresh": "LinkedIn multi-query fresh",
        "linkedin_single": "LinkedIn single query",
        "linkedin_process_only": "LinkedIn process-only",
        "indeed_description": "Indeed description extraction",
        "validate_boards": "Validate job boards (no applications)",
    }
    MAX_PAGE_CHOICES = {"1", "2", "3", "4", "all"}
    BROWSER_CHOICES = {"chromium", "firefox"}
    AI_BUDGET_MODE_CHOICES = {"smart", "deep", "off"}
    SEARCH_GOAL_CHOICES = {
        "career-growth",
        "career-focus",
        "broad",
        "income",
        "custom",
    }
    SEARCH_GROUP_CHOICES = {"primary", "bridge", "fallback"}
    @property
    def SEARCH_MARKET_CHOICES(self) -> set[str]:
        return set(SEARCH_MARKETS)

    RADIUS_KM_CHOICES = {"0", "8", "16", "40", "80", "160"}
    EMPLOYMENT_CHOICES = set(EMPLOYMENT_PREFERENCES)

    def __init__(
        self,
        root: Path,
        *,
        progress_path: Path = DEFAULT_PROGRESS_PATH,
        dashboard_data_path: Path = DEFAULT_DASHBOARD_DATA_PATH,
        state_path: Path = DEFAULT_RUN_STATE_PATH,
        process_inspector=inspect_process,
        process_terminator=terminate_process,
    ) -> None:
        self.root = Path(root).resolve()
        self.progress_path = progress_path if progress_path.is_absolute() else self.root / progress_path
        self.dashboard_data_path = (
            dashboard_data_path
            if dashboard_data_path.is_absolute()
            else self.root / dashboard_data_path
        )
        self.state_path = state_path if state_path.is_absolute() else self.root / state_path
        self.lock = threading.RLock()
        self.process_inspector = process_inspector
        self.process_terminator = process_terminator
        self.process: subprocess.Popen | None = None
        self.log_handle = None
        self.state: dict[str, Any] = self._load_state() or {
            "status": "idle",
            "active": False,
            "workflow": "",
            "workflow_label": "",
            "started_at": "",
            "completed_at": "",
            "return_code": None,
            "log_path": "",
            "log_tail": "",
            "command": [],
            "run_id": "",
            "failure_reason": "",
            "interrupted_at": "",
            "interruption_reason": "",
            "detached": False,
            "process_id": 0,
            "process_creation_token": "",
            "process_executable": "",
            "command_fingerprint": "",
            "lifecycle_reconciliation_warning": "",
        }
        migrated_legacy_state = self._migrate_legacy_interruption()
        self._reconstruct_state()
        if migrated_legacy_state:
            self._save_state_locked()

    def reload_state(self) -> None:
        with self.lock:
            disk_state = self._load_state()
            if disk_state:
                self.state = disk_state
            self._reconstruct_state()

    def status(self) -> dict[str, Any]:

        with self.lock:
            self._refresh_process_locked()
            payload = dict(self.state)
            payload.setdefault("interrupted_at", "")
            payload.setdefault("interruption_reason", "")
            payload.setdefault("detached", False)
            payload.setdefault("process_id", 0)
            payload.setdefault("lifecycle_reconciliation_warning", "")
            payload["resume_available"] = self._resume_available()
            payload["resumable"] = payload["resume_available"] and payload.get("status") in {
                "interrupted",
                "failed",
                "stopped",
                "idle",
            }
            payload["resolved_failure"] = self._failure_is_resolved()
            payload["workflows"] = [
                {"value": key, "label": label}
                for key, label in self.WORKFLOW_LABELS.items()
            ]
            payload["log_tail"] = self._read_log_tail(payload.get("log_path", ""))
            payload["resume_context"] = self._resume_context()
            return payload

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._refresh_process_locked()
            if (self.process and self.process.poll() is None) or self.state.get("active"):
                raise ValueError("A scout run is already active")

            command, workflow, workflow_label = self.build_command(payload)
            clear_stop_request(self.root / "data" / "scout_stop_request.json")
            logs_dir = self.root / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
            log_path = logs_dir / f"dashboard_run_{timestamp}.txt"
            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"
            env["DASHBOARD_STARTED_SCOUT"] = "1"
            self.log_handle = log_path.open("w", encoding="utf-8")
            
            success, ip_or_error = _test_proxy_preflight()
            if not success:
                self.log_handle.write(f"[Proxy Pre-flight Check] Failed! Proxy connection refused.\nError details: {ip_or_error}\n\nPlease check your proxy credentials in the Railway variables (or .env file) and try resuming the run.\n")
                self.log_handle.flush()
                self.log_handle.close()
                self.state = {
                    "status": "interrupted",
                    "active": False,
                    "workflow": workflow,
                    "workflow_label": workflow_label,
                    "started_at": datetime.now().astimezone().isoformat(),
                    "completed_at": "",
                    "return_code": 1,
                    "log_path": str(log_path),
                    "log_tail": "",
                    "command": self._display_command(command),
                    "interrupted_at": datetime.now().astimezone().isoformat(),
                    "interruption_reason": "Proxy Pre-flight Check Failed",
                    "failure_reason": "Proxy connection refused",
                    "detached": False,
                }
                self._save_state_locked()
                return self.status()
                
            if ip_or_error:
                self.log_handle.write(f"[Proxy Pre-flight Check] Passed! Connecting from IP: {ip_or_error}\n\n")
                self.log_handle.flush()
                
            self.process = subprocess.Popen(
                command,
                cwd=str(self.root),
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                env=env,
            )
            identity = self._capture_process_identity(self.process.pid)
            display_command = self._display_command(command)
            self.state = {
                "status": "running",
                "active": True,
                "workflow": workflow,
                "workflow_label": workflow_label,
                "started_at": datetime.now().astimezone().isoformat(),
                "completed_at": "",
                "return_code": None,
                "log_path": str(log_path),
                "log_tail": "",
                "command": display_command,
                "run_id": "",
                "failure_reason": "",
                "interrupted_at": "",
                "interruption_reason": "",
                "detached": False,
                "process_id": self.process.pid,
                "process_creation_token": str(identity.get("creation_token") or ""),
                "process_executable": str(identity.get("executable") or ""),
                "command_fingerprint": self._command_fingerprint(display_command),
                "search_scope": (
                    build_search_scope(
                        platform="linkedin",
                        search_market=payload.get("search_market", "netherlands"),
                        location=payload.get("location") or "Amstelveen",
                        radius_km=payload.get("radius_km", 40),
                        employment=payload.get("employment", "full-time-preferred"),
                        search_goal=payload.get("search_goal", "career-growth"),
                        search_groups=self._clean_search_groups(payload.get("search_groups")),
                        experience_levels=payload.get("experience_levels"),
                        sponsorship_policy=payload.get("sponsorship_policy"),
                    )
                    if workflow.startswith("linkedin_")
                    else {}
                ),
            }
            self._save_state_locked()
            return self.status()

    def stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str((payload or {}).get("mode", "")).strip().lower()
        if mode not in {"after_current_job", "after_current_page", "now"}:
            raise ValueError("Unsupported stop mode")
        with self.lock:
            self._refresh_process_locked()
            if not self.state.get("active"):
                raise ValueError("No scout run is active")
            request_stop(
                mode,
                path=self.root / "data" / "scout_stop_request.json",
            )
            if mode == "now":
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                elif not self.process_terminator(int(self.state.get("process_id") or 0)):
                    raise ValueError("The detached scout process could not be stopped")
                self.state["status"] = "stopping"
            else:
                self.state["status"] = "stopping_after_job" if mode == "after_current_job" else "stopping_after_page"
            self._save_state_locked()
            return self.status()

    def build_command(self, payload: dict[str, Any]) -> tuple[list[str], str, str]:
        workflow = self._clean_choice(payload.get("workflow"), self.WORKFLOW_LABELS, "linkedin_multi_fresh")
        location = self._clean_text(payload.get("location") or "Amstelveen", max_length=80)
        query = self._clean_text(payload.get("query") or "", max_length=120)
        max_pages = self._clean_choice(payload.get("max_pages"), self.MAX_PAGE_CHOICES, "1")
        browser = self._clean_choice(payload.get("browser"), self.BROWSER_CHOICES, "chromium")
        ai_budget_mode = self._clean_choice(payload.get("ai_budget_mode"), self.AI_BUDGET_MODE_CHOICES, "smart")
        human_mode = bool(payload.get("human_mode", True))
        fresh = bool(payload.get("fresh", workflow == "linkedin_multi_fresh"))
        test_run = bool(payload.get("test_run", False))
        resume = bool(payload.get("resume", False))
        search_goal = self._clean_choice(
            payload.get("search_goal"),
            self.SEARCH_GOAL_CHOICES,
            "career-growth",
        )
        search_groups = self._clean_search_groups(payload.get("search_groups"))
        search_market = self._clean_choice(
            payload.get("search_market"),
            self.SEARCH_MARKET_CHOICES,
            "netherlands",
        )
        radius_km = self._clean_choice(
            str(payload.get("radius_km", "40")),
            self.RADIUS_KM_CHOICES,
            "40",
        )
        employment = self._clean_choice(
            payload.get("employment"),
            self.EMPLOYMENT_CHOICES,
            "full-time-preferred",
        )
        workplace_types = payload.get("workplace_types")
        if isinstance(workplace_types, list):
            valid_wt = {"remote", "hybrid", "onsite"}
            workplace_types = [str(w).strip().lower() for w in workplace_types if str(w).strip().lower() in valid_wt]
        else:
            workplace_types = []
        market_profile = MARKET_PROFILES.get(search_market, {})
        market_availability = str(
            market_profile.get("availability") or "disabled"
        ).lower()
        if workflow.startswith("linkedin_") and market_availability == "disabled":
            raise ValueError(
                f"{market_profile.get('label', search_market)} is not enabled yet"
            )
        if (
            workflow.startswith("linkedin_")
            and market_availability == "experimental"
            and not resume
            and not bool(payload.get("experimental_confirmed"))
        ):
            raise ValueError(
                f"{market_profile.get('label', search_market)} is experimental; "
                "confirm the market warning before starting"
            )

        command = [sys.executable]
        if workflow == "linkedin_multi_fresh":
            command += ["scout_jobs_multi.py", "--linkedin", "--location", location, "--max-pages", max_pages]
            command += ["--search-goal", search_goal]
            if search_goal == "custom":
                if not search_groups:
                    raise ValueError("Custom search goal requires at least one search group")
                command += ["--search-groups", ",".join(search_groups)]
            if fresh:
                command.append("--fresh")
        elif workflow == "linkedin_single":
            if not query:
                raise ValueError("A query is required for single-query scouting")
            command += ["scout_jobs.py", "--linkedin", query, "--location", location, "--max-pages", max_pages]
            if fresh:
                command.append("--fresh")
        elif workflow == "linkedin_process_only":
            command += ["scout_jobs_multi.py", "--linkedin", "--location", location, "--max-pages", max_pages, "--process-only"]
        elif workflow == "indeed_description":
            if not query:
                raise ValueError("A query is required for Indeed description extraction")
            command += ["scout_jobs.py", "--indeed", query, "--location", location, "--max-pages", max_pages, "--description-only"]
        elif workflow == "validate_boards":
            return (
                [sys.executable, "main.py", "--validate-boards"],
                workflow,
                self.WORKFLOW_LABELS[workflow],
            )
        else:
            raise ValueError("Unsupported workflow")

        if workflow in {"linkedin_multi_fresh", "linkedin_single", "linkedin_process_only"}:
            command += [
                "--search-market",
                search_market,
                "--radius-km",
                radius_km,
                "--employment",
                employment,
            ]
            if workplace_types:
                command += ["--workplace-types"] + workplace_types
            sponsorship_policy = payload.get("sponsorship_policy")
            if sponsorship_policy in {"required", "not_required"}:
                command += ["--sponsorship-policy", sponsorship_policy]
            experience_levels = payload.get("experience_levels")
            if isinstance(experience_levels, list) and experience_levels:
                valid_levels = {"internship", "entry", "associate", "mid-senior", "director", "executive"}
                cleaned_levels = [
                    lvl.strip().lower() for lvl in experience_levels
                    if str(lvl).strip().lower() in valid_levels
                ]
                if cleaned_levels:
                    command += ["--experience-levels", ",".join(cleaned_levels)]
            if test_run:
                command.append("--test-run")

        if human_mode:
            command.append("--human-mode")
        if resume and workflow != "linkedin_process_only":
            command.append("--resume")
        if fresh and ai_budget_mode != "smart" and workflow in {"linkedin_multi_fresh", "linkedin_single"}:
            command += ["--ai-budget-mode", ai_budget_mode]
        command += ["--browser", browser]
        if "PORT" in os.environ:
            command.append("--headless")
        return command, workflow, self.WORKFLOW_LABELS[workflow]

    def _refresh_process_locked(self) -> None:
        self._resolve_run_id_locked()
        if not self.process:
            if self.state.get("active") and self.state.get("detached"):
                if self._stored_process_is_alive():
                    return
                run_status = self._associated_run_status(candidate_min_age_seconds=0)
                progress_status = str(
                    self._associated_progress(candidate_min_age_seconds=0).get("status") or ""
                )
                if run_status in {"completed", "stopped", "interrupted", "failed"}:
                    self._transition_lifecycle_locked(run_status)
                elif self.state.get("status") in {
                    "stopping",
                    "stopping_after_job",
                    "stopping_after_page",
                } or progress_status == "stopped":
                    self._transition_lifecycle_locked("stopped")
                elif progress_status == "completed":
                    self._transition_lifecycle_locked("completed")
                else:
                    self._transition_lifecycle_locked(
                        "interrupted",
                        reason="The scout process ended without reporting a final result.",
                    )
            else:
                self._reconcile_terminal_state_locked()
            return
        return_code = self.process.poll()
        if return_code is None:
            self.state["active"] = True
            self._save_state_locked()
            return
        if self.log_handle:
            self.log_handle.close()
            self.log_handle = None
        self.state["active"] = False
        self.state["return_code"] = return_code
        self.state["completed_at"] = self.state.get("completed_at") or datetime.now().astimezone().isoformat()
        run_status = self._associated_run_status(candidate_min_age_seconds=0)
        progress_status = str(
            self._associated_progress(candidate_min_age_seconds=0).get("status") or ""
        )
        if run_status in {"completed", "stopped", "interrupted", "failed"}:
            resolved_status = run_status
        elif self.state.get("status") in {"stopping", "stopping_after_job", "stopping_after_page"}:
            resolved_status = "stopped"
        elif progress_status == "stopped":
            resolved_status = "stopped"
        else:
            resolved_status = "completed" if return_code == 0 else "failed"
        reason = ""
        if resolved_status == "failed":
            reason = self.state.get("failure_reason") or (
                f"Scout process exited with code {return_code}."
                if return_code is not None
                else "Scout process ended unexpectedly."
            )
        self.process = None
        self._transition_lifecycle_locked(
            resolved_status,
            reason=reason,
            return_code=return_code,
        )

    def _resume_available(self) -> bool:
        if self.state.get("status") == "completed":
            return False
        if self._associated_run_status() == "completed":
            return False
        payload = self._associated_progress()
        return bool(payload) and payload.get("status") != "completed"

    def _resume_context(self) -> dict[str, Any]:
        progress = self._associated_progress()
        if not progress:
            return {}
        queries = progress.get("queries", []) if isinstance(progress, dict) else []
        total_queries = len(queries) if isinstance(queries, list) else 0
        current_index = int(progress.get("current_query_index", 0) or 0)
        return {
            "current_query": str(progress.get("current_query") or ""),
            "current_query_index": current_index + 1 if total_queries else 0,
            "total_queries": total_queries,
            "current_page_number": int(progress.get("current_page_number", 0) or 0),
            "processed_jobs": int(progress.get("total_jobs_processed", 0) or 0),
            "last_completed_query": str(progress.get("last_completed_query") or ""),
            "search_goal": str(progress.get("search_goal") or ""),
            "selected_search_groups": list(
                progress.get("selected_search_groups", [])
                if isinstance(progress.get("selected_search_groups"), list)
                else []
            ),
            "current_search_group": str(
                progress.get("current_search_group") or ""
            ),
            "phase_order": list(
                progress.get("phase_order", [])
                if isinstance(progress.get("phase_order"), list)
                else []
            ),
            "search_scope": dict(
                progress.get("search_scope")
                if isinstance(progress.get("search_scope"), dict)
                else {}
            ),
            "log_path": str(self.state.get("log_path") or ""),
            "restart_note": (
                "The unfinished query may restart from its beginning; completed queries are preserved."
                if self._resume_available()
                else ""
            ),
        }

    def _read_progress(
        self,
        *,
        candidate_min_age_seconds: float = 2.0,
    ) -> dict[str, Any]:
        return load_json_with_recovery(
            self.progress_path,
            candidate_min_age_seconds=candidate_min_age_seconds,
        )

    def _associated_progress(
        self,
        *,
        candidate_min_age_seconds: float = 2.0,
    ) -> dict[str, Any]:
        progress = self._read_progress(
            candidate_min_age_seconds=candidate_min_age_seconds
        )
        return progress if self._progress_matches_state(progress) else {}

    def _progress_matches_state(self, progress: dict[str, Any]) -> bool:
        if not isinstance(progress, dict) or not progress:
            return False
        state_run_id = str(self.state.get("run_id") or "")
        progress_run_id = str(progress.get("run_id") or "")
        if state_run_id and progress_run_id:
            return state_run_id == progress_run_id
        if progress_run_id and not state_run_id:
            return False

        # Legacy progress files predate run IDs. When timestamps are available,
        # only associate a checkpoint that was written during this controller run.
        progress_updated = self._parse_timestamp(progress.get("updated_at"))
        state_started = self._parse_timestamp(self.state.get("started_at"))
        state_completed = self._parse_timestamp(self.state.get("completed_at"))
        if progress_updated and state_started and progress_updated < state_started:
            return False
        if progress_updated and state_completed and progress_updated > state_completed:
            return False
        return True

    def _parse_timestamp(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return (
                parsed
                if parsed.tzinfo is not None
                else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
            )
        except ValueError:
            return None

    def _load_state(self) -> dict[str, Any]:
        return load_json_with_recovery(self.state_path)

    def _save_state_locked(self) -> None:
        atomic_write_json(self.state_path, self.state)

    def _dashboard_runs(
        self,
        *,
        candidate_min_age_seconds: float = 2.0,
    ) -> list[dict[str, Any]]:
        payload = load_json_with_recovery(
            self.dashboard_data_path,
            candidate_min_age_seconds=candidate_min_age_seconds,
        )
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        return [dict(run) for run in runs if isinstance(run, dict)]

    def _resolve_run_id_locked(self) -> None:
        if self.state.get("run_id") or not self.state.get("started_at"):
            return
        started_at = str(self.state.get("started_at") or "")
        candidates = [
            run
            for run in self._dashboard_runs()
            if str(run.get("started_at") or "") >= started_at
        ]
        if not candidates:
            return
        run = min(candidates, key=lambda item: str(item.get("started_at") or ""))
        self.state["run_id"] = str(run.get("run_id") or "")

    def _associated_run_status(
        self,
        *,
        candidate_min_age_seconds: float = 2.0,
    ) -> str:
        run_id = str(self.state.get("run_id") or "")
        if not run_id:
            return ""
        for run in self._dashboard_runs(
            candidate_min_age_seconds=candidate_min_age_seconds
        ):
            if str(run.get("run_id") or "") == run_id:
                return str(run.get("status") or "")
        return ""

    def _failure_is_resolved(self) -> bool:
        if self.state.get("status") != "failed":
            return False
        failed_at = str(self.state.get("completed_at") or self.state.get("started_at") or "")
        return any(
            run.get("status") == "completed"
            and str(run.get("completed_at") or "") > failed_at
            for run in self._dashboard_runs()
        )

    def _reconstruct_state(self) -> None:
        with self.lock:
            self._resolve_run_id_locked()
            if not self.state.get("active"):
                self._reconcile_terminal_state_locked()
                return
            if self._stored_process_is_alive():
                self.state["status"] = "running"
                self.state["active"] = True
                self.state["detached"] = True
                self._save_state_locked()
                return
            run_status = self._associated_run_status(candidate_min_age_seconds=0)
            progress_status = str(
                self._associated_progress(candidate_min_age_seconds=0).get("status") or ""
            )
            if run_status in {"completed", "stopped", "interrupted", "failed"}:
                self._transition_lifecycle_locked(run_status)
            elif progress_status == "completed":
                self._transition_lifecycle_locked("completed")
            else:
                self._transition_lifecycle_locked(
                    "interrupted",
                    reason=(
                        "The dashboard restarted after the scout process ended without "
                        "reporting a final result."
                    ),
                )

    def _migrate_legacy_interruption(self) -> bool:
        reason = str(self.state.get("failure_reason") or "")
        if (
            self.state.get("status") == "failed"
            and self.state.get("return_code") is None
            and "dashboard server restarted while the scout process was active" in reason.lower()
        ):
            self.state["status"] = "interrupted"
            self.state["interrupted_at"] = str(self.state.get("completed_at") or "")
            self.state["interruption_reason"] = (
                "The scout process ended without reporting a final result; "
                "saved progress is available."
            )
            self.state["failure_reason"] = ""
            return True
        return False

    def _stored_process_is_alive(self) -> bool:
        process_id = int(self.state.get("process_id") or 0)
        expected_token = str(self.state.get("process_creation_token") or "")
        expected_fingerprint = str(self.state.get("command_fingerprint") or "")
        command = self.state.get("command", [])
        if (
            process_id <= 0
            or not expected_token
            or not expected_fingerprint
            or expected_fingerprint != self._command_fingerprint(command)
        ):
            return False
        current = self.process_inspector(process_id)
        if not current.get("alive"):
            return False
        if str(current.get("creation_token") or "") != expected_token:
            return False
        expected_executable = str(self.state.get("process_executable") or "").lower()
        current_executable = str(current.get("executable") or "").lower()
        return not expected_executable or not current_executable or expected_executable == current_executable

    def _capture_process_identity(self, process_id: int) -> dict[str, Any]:
        identity: dict[str, Any] = {}
        for delay in (0.0, 0.02, 0.05, 0.1):
            if delay:
                time.sleep(delay)
            identity = self.process_inspector(process_id)
            if identity.get("alive") and identity.get("creation_token"):
                return identity
        return identity

    def _transition_lifecycle_locked(
        self,
        status: str,
        *,
        reason: str = "",
        return_code: int | None = None,
    ) -> None:
        allowed = {"completed", "stopped", "interrupted", "failed"}
        if status not in allowed:
            raise ValueError(f"Unsupported run lifecycle status: {status}")
        event_at = datetime.now().astimezone().isoformat()
        self.state["status"] = status
        self.state["active"] = False
        self.state["detached"] = False
        self.state["completed_at"] = self.state.get("completed_at") or event_at
        if return_code is not None:
            self.state["return_code"] = return_code
        if status == "interrupted":
            self.state["interrupted_at"] = self.state.get("interrupted_at") or event_at
            self.state["interruption_reason"] = reason or self.state.get("interruption_reason") or (
                "The scout process ended without reporting a final result."
            )
            self.state["failure_reason"] = ""
        elif status == "failed":
            self.state["failure_reason"] = reason or self.state.get("failure_reason") or "Scout run failed."
        self._sync_live_run_lifecycle_locked(status, reason=reason, event_at=event_at)
        self._save_state_locked()

    def _sync_live_run_lifecycle_locked(
        self,
        status: str,
        *,
        reason: str,
        event_at: str,
    ) -> None:
        self._resolve_run_id_locked()
        run_id = str(self.state.get("run_id") or "")
        if not run_id:
            return
        try:
            writer = LiveRecommendedJobsDashboard(self.dashboard_data_path)
            run = next(
                (
                    item
                    for item in writer.data.get("runs", [])
                    if str(item.get("run_id") or "") == run_id
                ),
                None,
            )
            if not run:
                return
            if run.get("status") == status and writer.data.get("active_run_id") != run_id:
                self.state["lifecycle_reconciliation_warning"] = ""
                return
            writer.transition_run(
                run_id,
                status=status,
                transitioned_at=event_at,
                reason=reason,
            )
            self.state["lifecycle_reconciliation_warning"] = ""
        except (PersistenceError, OSError) as exc:
            self.state["lifecycle_reconciliation_warning"] = str(exc)

    def _reconcile_terminal_state_locked(self) -> None:
        status = str(self.state.get("status") or "")
        if status not in {"completed", "stopped", "interrupted", "failed"}:
            return
        run_status = self._associated_run_status(candidate_min_age_seconds=0)
        if run_status != status:
            reason = str(
                self.state.get("interruption_reason")
                if status == "interrupted"
                else self.state.get("failure_reason")
                if status == "failed"
                else ""
            )
            self._sync_live_run_lifecycle_locked(
                status,
                reason=reason,
                event_at=str(self.state.get("completed_at") or datetime.now().astimezone().isoformat()),
            )

    def _command_fingerprint(self, command: Any) -> str:
        normalized = [str(part) for part in command] if isinstance(command, list) else []
        encoded = json.dumps(normalized, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _read_log_tail(self, path: str, *, max_chars: int = 5000) -> str:
        if not path:
            return ""
        log_path = Path(path)
        if not log_path.exists():
            return ""
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-max_chars:]

    def _display_command(self, command: list[str]) -> list[str]:
        return [Path(command[0]).name, *command[1:]]

    def _clean_choice(self, value: Any, choices, default: str) -> str:
        cleaned = str(value or default).strip()
        return cleaned if cleaned in choices else default

    def _clean_text(self, value: Any, *, max_length: int) -> str:
        cleaned = " ".join(str(value or "").split())
        return cleaned[:max_length]

    def _clean_search_groups(self, value: Any) -> list[str]:
        candidates = value if isinstance(value, list) else str(value or "").split(",")
        selected = {
            str(group or "").strip().lower()
            for group in candidates
        }
        return [
            group
            for group in ("primary", "bridge", "fallback")
            if group in selected and group in self.SEARCH_GROUP_CHOICES
        ]


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """Static dashboard server plus tiny JSON API for manual job status."""

    dashboard_data_path: Path = DEFAULT_DASHBOARD_DATA_PATH
    user_state_path: Path = DEFAULT_USER_STATE_PATH
    run_controller: DashboardRunController | None = None
    user_workspace: UserWorkspace | None = None
    operational_store: OperationalStore | None = None

    def log_message(self, format: str, *args) -> None:
        return

    def _authenticate(self) -> bool:
        username = os.environ.get("DASHBOARD_USERNAME")
        password = os.environ.get("DASHBOARD_PASSWORD")
        if not username or not password:
            return True  # If no auth is configured, pass-through

        auth_header = self.headers.get("Authorization")
        if auth_header and auth_header.startswith("Basic "):
            import base64
            try:
                encoded = auth_header.split(" ", 1)[1]
                decoded = base64.b64decode(encoded).decode("utf-8")
                req_username, req_password = decoded.split(":", 1)
                if req_username == username and req_password == password:
                    return True
            except Exception:
                pass

        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Job Scout Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Unauthorized")
        return False

    def do_GET(self) -> None:
        if not self._authenticate():
            return
        if self.path in {"", "/"}:
            self.send_response(302)
            self.send_header("Location", "/recommended_jobs_dashboard.html")
            self.end_headers()
            return
        if self._path_without_query() == "/api/dashboard-data":
            if self._query_value("include_jobs").lower() in {"0", "false", "no"}:
                self._send_json(self._load_dashboard_metadata())
            else:
                self._send_json(self._load_dashboard_with_user_state())
            return
        if self._path_without_query() == "/api/jobs":
            if not self.operational_store:
                self._send_json({"jobs": [], "total": 0, "error": "Operational store unavailable"}, status=503)
                return
            self._sync_operational_store_if_changed()
            self._send_json(
                self.operational_store.job_records(
                    search=self._query_value("search"),
                    decision=self._query_value("decision"),
                    run=self._query_value("run"),
                    domain=self._query_value("domain"),
                    search_group=self._query_value("search_group"),
                    career_lane=self._query_value("career_lane"),
                    search_market=self._query_value("search_market"),
                    country=self._query_value("country"),
                    employment_type=self._query_value("employment_type"),
                    flexible_hours=self._query_value("flexible_hours"),
                    sponsorship_status=self._query_value("sponsorship_status"),
                    platform=self._query_value("platform"),
                    flag=self._query_value("flag"),
                    apply_method=self._query_value("apply_method"),
                    status=self._query_value("status"),
                    preset=self._query_value("preset"),
                    sort=self._query_value("sort") or "newest",
                    limit=self._query_int("limit", 100),
                    offset=self._query_int("offset", 0),
                )
            )
            return
        if self._path_without_query() == "/api/user-state":
            self._send_json(DashboardUserStateStore(self.user_state_path).data)
            return
        if self._path_without_query() == "/api/run-control":
            if not self.run_controller:
                self._send_json({"active": False, "status": "unavailable"}, status=503)
                return
            self._send_json(self.run_controller.status())
            return
        if self._path_without_query() == "/api/profile":
            self._send_json(self._profile_service().payload())
            return
        if self._path_without_query() == "/api/strategy":
            self._send_json(self._strategy_service().payload())
            return
        if self._path_without_query() == "/api/ai-settings":
            self._send_json(self._ai_settings_service().payload())
            return
        if self._path_without_query() == "/api/board-settings":
            self._send_json(self._board_settings_service().payload())
            return
        if self._path_without_query() == "/api/applications":
            store = DashboardUserStateStore(self.user_state_path)
            dashboard = self._read_dashboard_data()
            if self.operational_store:
                self._sync_operational_store_if_changed()
                stage = self._query_value("stage")
                search = self._query_value("search")
                limit = self._query_int("limit", 50)
                offset = self._query_int("offset", 0)
                records = self.operational_store.application_records(
                    stage=stage,
                    search=search,
                    limit=limit,
                    offset=offset,
                )
                total = self.operational_store.application_count(
                    stage=stage,
                    search=search,
                )
                counts = self.operational_store.stage_counts()
            else:
                records = store.application_records(dashboard)
                total = len(records)
                counts: dict[str, int] = {}
                for record in records:
                    stage = str(record.get("application_stage") or "applied")
                    counts[stage] = counts.get(stage, 0) + 1
            self._send_json(
                {
                    "applications": records,
                    "by_stage": counts,
                    "total": total,
                    "limit": self._query_int("limit", 50),
                    "offset": self._query_int("offset", 0),
                    "has_more": self._query_int("offset", 0) + len(records) < total,
                }
            )
            return
        if self._path_without_query() == "/api/application-assistant":
            dashboard = self._load_dashboard_with_user_state()
            self._send_json(
                self._application_assistant_service().payload(dashboard.get("jobs", []))
            )
            return
        if self._path_without_query() == "/api/maintenance":
            self._send_json(self._maintenance_service().payload())
            return
        if self._path_without_query() == "/api/legacy-tools":
            self._send_json(self._legacy_tools_service().payload())
            return
        if self._path_without_query() == "/api/log-file":
            name = self._query_value("name")
            try:
                self._send_json(self._maintenance_service().read_log(name))
            except (ValueError, FileNotFoundError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        if self._path_without_query() == "/api/backup-file":
            name = self._query_value("name")
            try:
                path = self._maintenance_service().backup_path(name)
                self._send_binary(
                    path.read_bytes(),
                    content_type="application/zip",
                    filename=path.name,
                )
            except (ValueError, FileNotFoundError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        if self._path_without_query() == "/api/maintenance/export-backup":
            try:
                service = self._maintenance_service()
                zip_path = service.create_migration_zip()
                self._send_binary(
                    zip_path.read_bytes(),
                    content_type="application/zip",
                    filename=zip_path.name,
                )
                if zip_path.exists():
                    zip_path.unlink()
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if self._path_without_query() == "/api/maintenance/export-session":
            try:
                service = self._maintenance_service()
                zip_path = service.create_session_backup_zip()
                self._send_binary(
                    zip_path.read_bytes(),
                    content_type="application/zip",
                    filename=zip_path.name,
                )
                if zip_path.exists():
                    zip_path.unlink()
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if self._path_without_query() == "/api/profile/cv/file":
            cv_path = self._profile_service().active_cv_path()
            if not cv_path:
                self.send_error(404, "Active CV not found")
                return
            self._send_binary(cv_path.read_bytes(), content_type="application/pdf")
            return
        super().do_GET()

    def do_POST(self) -> None:
        if not self._authenticate():
            return
        if not self._local_origin_allowed():
            self._send_json({"ok": False, "error": "Request origin is not allowed"}, status=403)
            return

        if self._path_without_query() == "/api/maintenance/import-session":
            if self.run_controller and self.run_controller.state.get("active"):
                self._send_json({"ok": False, "error": "Cannot import browser session while a scout run is active"}, status=400)
                return
            try:
                payload = self._read_json_body(max_bytes=250 * 1024 * 1024)
                content_base64 = str(payload.get("content_base64") or "")
                if not content_base64:
                    raise ValueError("No file content received")
                import base64
                import time
                file_bytes = base64.b64decode(content_base64)
                service = self._maintenance_service()
                temp_path = service.root / "backups" / f"temp_import_{int(time.time())}.zip"
                temp_path.write_bytes(file_bytes)
                service.import_session_backup_zip(temp_path)
                if temp_path.exists():
                    temp_path.unlink()
                self._send_json({"ok": True, "data": {"status": "imported"}})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if self._path_without_query() == "/api/maintenance/import-backup":
            if self.run_controller and self.run_controller.state.get("active"):
                self._send_json({"ok": False, "error": "Cannot import configuration backup while a scout run is active"}, status=400)
                return
            try:
                payload = self._read_json_body(max_bytes=250 * 1024 * 1024)
                content_base64 = str(payload.get("content_base64") or "")
                if not content_base64:
                    raise ValueError("No file content received")
                import base64
                import time
                file_bytes = base64.b64decode(content_base64)
                service = self._maintenance_service()
                temp_path = service.root / "backups" / f"temp_import_backup_{int(time.time())}.zip"
                temp_path.write_bytes(file_bytes)
                service.import_migration_zip(temp_path)
                if self.run_controller:
                    self.run_controller.reload_state()
                if temp_path.exists():
                    temp_path.unlink()
                self._send_json({"ok": True, "data": {"status": "imported"}})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return


        if self._path_without_query() in {
            "/api/profile",
            "/api/profile/cv",
            "/api/strategy",
            "/api/ai-settings",
            "/api/ai-settings/test",
            "/api/board-settings",
            "/api/application",
            "/api/application-assistant",
            "/api/application-assistant/draft",
            "/api/application-assistant/answer",
            "/api/maintenance/backup",
            "/api/maintenance/prune-logs",
            "/api/maintenance/archive",
            "/api/markets",
            "/api/markets/delete",
        }:
            try:
                payload = self._read_json_body(max_bytes=12 * 1024 * 1024)
                if self._path_without_query() == "/api/ai-settings/test":
                    data = self._ai_settings_service().test_connection(
                        str(payload.get("provider") or ""),
                        payload.get("provider_settings")
                    )
                elif self._path_without_query() == "/api/ai-settings":
                    data = self._ai_settings_service().save(payload)
                elif self._path_without_query() == "/api/board-settings":
                    data = self._board_settings_service().save(payload)
                elif self._path_without_query() == "/api/markets":
                    data = self._board_settings_service().save_market(payload)
                elif self._path_without_query() == "/api/markets/delete":
                    data = self._board_settings_service().delete_market(payload)
                elif self._path_without_query() == "/api/application":
                    job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
                    data = DashboardUserStateStore(self.user_state_path).update_application(
                        job,
                        stage=str(payload.get("stage") or ""),
                        notes=str(payload.get("notes") or ""),
                        applied_at=str(payload.get("applied_at") or ""),
                        follow_up_at=str(payload.get("follow_up_at") or ""),
                    )
                    self._sync_operational_store()
                elif self._path_without_query() == "/api/application-assistant":
                    data = self._application_assistant_service().save_knowledge(payload)
                elif self._path_without_query() == "/api/application-assistant/draft":
                    job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
                    mode = str(payload.get("mode") or "local").strip().lower()
                    if mode == "ai":
                        draft = self._application_assistant_service().ai_cover_letter_draft(job)
                    elif mode == "local":
                        draft = self._application_assistant_service().local_cover_letter_draft(job)
                    else:
                        raise ValueError("Unsupported document generation mode")
                    data = {"draft": draft, "mode": mode}
                elif self._path_without_query() == "/api/application-assistant/answer":
                    data = self._application_assistant_service().answer_question(
                        str(payload.get("question") or ""),
                        str(payload.get("context") or ""),
                    )
                elif self._path_without_query() == "/api/maintenance/backup":
                    data = self._maintenance_service().create_backup()
                elif self._path_without_query() == "/api/maintenance/prune-logs":
                    data = self._maintenance_service().prune_logs(
                        older_than_days=int(payload.get("older_than_days") or 90),
                        keep_latest=int(payload.get("keep_latest") or 10),
                    )
                elif self._path_without_query() == "/api/maintenance/archive":
                    data = self._maintenance_service().archive_historical_data()
                elif self._path_without_query() == "/api/strategy":
                    data = self._strategy_service().save(payload)
                elif self._path_without_query().endswith("/cv"):
                    data = self._profile_service().upload_cv(
                        str(payload.get("filename") or ""),
                        str(payload.get("content_base64") or ""),
                    )
                else:
                    profile = payload.get("profile")
                    if not isinstance(profile, dict):
                        raise ValueError("Profile object is required")
                    data = self._profile_service().save_profile(profile)
                self._send_json({"ok": True, "data": data})
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if self._path_without_query() in {"/api/run-control/start", "/api/run-control/stop"}:
            if not self.run_controller:
                self._send_json({"ok": False, "error": "Run controller unavailable"}, status=503)
                return
            try:
                payload = self._read_json_body()
                if self._path_without_query().endswith("/start"):
                    state = self.run_controller.start(payload)
                else:
                    state = self.run_controller.stop(payload)
                self._send_json({"ok": True, "state": state})
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if self._path_without_query() == "/api/track-manual-job":
            try:
                payload = self._read_json_body()
                job_ref = str(payload.get("job_reference") or "").strip()
                status = str(payload.get("status") or "").strip()
                if not job_ref or not status:
                    raise ValueError("job_reference and status are required")
                
                from agent.job_tracking import JobTrackingStore
                store = JobTrackingStore()
                from track_job_status import _find_known_metadata
                metadata = _find_known_metadata(store, job_ref)
                record = store.set_status(
                    status=status,
                    job_id=metadata.get("job_id", ""),
                    url=metadata.get("url", ""),
                    title=metadata.get("title", ""),
                    company=metadata.get("company", ""),
                    location=metadata.get("location", ""),
                )
                self._send_json({"ok": True, "record": record})
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if self._path_without_query() != "/api/job-status":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            payload = self._read_json_body()
            job = payload.get("job") if isinstance(payload.get("job"), dict) else payload
            status = payload.get("status", "")
            store = DashboardUserStateStore(self.user_state_path)
            record = store.set_status(job, status)
            self._sync_operational_store(store=store)
            response = {
                "ok": True,
                "record": record,
                "job_key": record.get("job_key") or build_job_key(job),
            }
            if not bool(payload.get("compact")):
                response["data"] = self._load_dashboard_with_user_state(store=store)
            self._send_json(response)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _load_dashboard_with_user_state(
        self,
        *,
        store: DashboardUserStateStore | None = None,
    ) -> dict[str, Any]:
        dashboard_data = self._read_dashboard_data()
        state_store = store or DashboardUserStateStore(self.user_state_path)
        return state_store.apply_to_dashboard_data(dashboard_data)

    def _load_dashboard_metadata(self) -> dict[str, Any]:
        dashboard_data = self._read_dashboard_data()
        dashboard_data["jobs"] = []
        state = DashboardUserStateStore(self.user_state_path).data
        manual_counts = {"unreviewed": 0, "applied": 0, "irrelevant": 0}
        total_jobs = int((dashboard_data.get("summary") or {}).get("total_jobs") or 0)
        saved_jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
        for record in saved_jobs.values() if isinstance(saved_jobs, dict) else []:
            if not isinstance(record, dict):
                continue
            status = str(record.get("status") or "unreviewed")
            if status in manual_counts:
                manual_counts[status] += 1
        manual_counts["unreviewed"] = max(
            0,
            total_jobs - manual_counts["applied"] - manual_counts["irrelevant"],
        )
        dashboard_data.setdefault("summary", {})["by_manual_status"] = manual_counts
        dashboard_data.setdefault("filter_options", {})["manual_statuses"] = [
            {"value": "unreviewed", "label": "Unreviewed"},
            {"value": "applied", "label": "Applied"},
            {"value": "irrelevant", "label": "Irrelevant"},
        ]
        if self.operational_store:
            self._sync_operational_store_if_changed()
            actionable = self.operational_store.job_records(
                decision="APPLY_FIRST,GOOD_OPTIONS",
                status="unreviewed",
                limit=1,
            )
            actionable_apply = self.operational_store.job_records(
                decision="APPLY_FIRST",
                status="unreviewed",
                limit=1,
            )
            actionable_good = self.operational_store.job_records(
                decision="GOOD_OPTIONS",
                status="unreviewed",
                limit=1,
            )
            dashboard_data["summary"]["actionable_jobs"] = actionable["total"]
            dashboard_data["summary"]["actionable_apply_first"] = actionable_apply["total"]
            dashboard_data["summary"]["actionable_good_options"] = actionable_good["total"]
        return dashboard_data

    def _read_dashboard_data(self) -> dict[str, Any]:
        try:
            print("READING DASHBOARD DATA FROM:", self.dashboard_data_path)
            payload = json.loads(self.dashboard_data_path.read_text(encoding="utf-8"))
            print("SUMMARY IN PAYLOAD:", payload.get("summary"))
        except FileNotFoundError as e:
            print("FILE NOT FOUND:", e)
            payload = {}
        except json.JSONDecodeError as e:
            print("JSON ERROR:", e)
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", "live_dashboard.v1")
        payload.setdefault("runs", [])
        payload.setdefault("jobs", [])
        payload.setdefault("summary", {})
        payload.setdefault("filter_options", {})
        return payload

    def _read_json_body(self, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            raise ValueError("JSON body is required")
        if length > max_bytes:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON object body is required")
        return payload

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(
        self,
        body: bytes,
        *,
        content_type: str,
        filename: str = "",
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{Path(filename).name}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _profile_service(self) -> ProfileService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return ProfileService(self.user_workspace)

    def _strategy_service(self) -> StrategyService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return StrategyService(self.user_workspace)

    def _ai_settings_service(self) -> AISettingsService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return AISettingsService(self.user_workspace)

    def _board_settings_service(self) -> BoardSettingsService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return BoardSettingsService(self.user_workspace)

    def _application_assistant_service(self) -> ApplicationAssistantService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return ApplicationAssistantService(self.user_workspace)

    def _maintenance_service(self) -> MaintenanceService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return MaintenanceService(self.user_workspace)

    def _legacy_tools_service(self) -> LegacyToolsService:
        if not self.user_workspace:
            raise RuntimeError("User workspace is unavailable")
        return LegacyToolsService(self.user_workspace.root)

    def _sync_operational_store(
        self,
        *,
        store: DashboardUserStateStore | None = None,
    ) -> None:
        if not self.operational_store:
            return
        state_store = store or DashboardUserStateStore(self.user_state_path)
        self.operational_store.sync(self._read_dashboard_data(), state_store.data)

    def _sync_operational_store_if_changed(self) -> None:
        if not self.operational_store:
            return
        self.operational_store.sync_if_changed(
            self.dashboard_data_path,
            self.user_state_path,
        )

    def _local_origin_allowed(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        host = str(self.headers.get("Host") or "").strip()
        return origin in {f"http://{host}", f"https://{host}"}

    def _path_without_query(self) -> str:
        return self.path.split("?", 1)[0]

    def _query_value(self, name: str) -> str:
        values = parse_qs(urlsplit(self.path).query).get(name, [])
        return str(values[0] if values else "")

    def _query_int(self, name: str, default: int) -> int:
        try:
            return int(self._query_value(name) or default)
        except ValueError:
            return default


def make_handler(
    *,
    directory: Path,
    dashboard_data_path: Path,
    user_state_path: Path,
    run_controller: DashboardRunController | None = None,
    user_workspace: UserWorkspace | None = None,
    operational_store: OperationalStore | None = None,
):
    class ConfiguredDashboardRequestHandler(DashboardRequestHandler):
        pass

    ConfiguredDashboardRequestHandler.dashboard_data_path = dashboard_data_path
    ConfiguredDashboardRequestHandler.user_state_path = user_state_path
    ConfiguredDashboardRequestHandler.run_controller = run_controller
    ConfiguredDashboardRequestHandler.user_workspace = user_workspace
    ConfiguredDashboardRequestHandler.operational_store = operational_store
    return partial(ConfiguredDashboardRequestHandler, directory=str(directory))


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    directory: Path | str = ".",
    dashboard_data_path: Path | str = DEFAULT_DASHBOARD_DATA_PATH,
    user_state_path: Path | str = DEFAULT_USER_STATE_PATH,
) -> None:
    root = Path(directory).resolve()
    data_path = Path(dashboard_data_path)
    state_path = Path(user_state_path)
    if not data_path.is_absolute():
        data_path = root / data_path
    if not state_path.is_absolute():
        state_path = root / state_path

    DashboardUserStateStore(state_path).write()
    user_workspace = UserWorkspace(root).ensure_initialized()
    operational_store = OperationalStore(user_workspace.path / "job_scout.db")
    operational_store.sync_if_changed(data_path, state_path)
    
    from agent.scout_collected_jobs import ScoutCollectedJobsStore
    collected_jobs_path = root / "scout_collected_jobs.json"
    collected_jobs_store = ScoutCollectedJobsStore(
        path=collected_jobs_path,
        operational_store=operational_store,
    )
    operational_store.sync_collected_jobs(collected_jobs_store.jobs)
    
    run_controller = DashboardRunController(root, dashboard_data_path=data_path)
    handler = make_handler(
        directory=root,
        dashboard_data_path=data_path,
        user_state_path=state_path,
        run_controller=run_controller,
        user_workspace=user_workspace,
        operational_store=operational_store,
    )
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/recommended_jobs_dashboard.html"
    print(f"Dashboard server running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the live jobs dashboard with local Applied/Irrelevant persistence."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind. Defaults to 8000.")
    parser.add_argument("--directory", default=".", help="Project directory to serve.")
    parser.add_argument("--data-path", default=str(DEFAULT_DASHBOARD_DATA_PATH), help="Live dashboard data JSON path.")
    parser.add_argument("--state-path", default=str(DEFAULT_USER_STATE_PATH), help="Manual dashboard state JSON path.")
    args = parser.parse_args()
    serve(
        host=args.host,
        port=args.port,
        directory=args.directory,
        dashboard_data_path=args.data_path,
        user_state_path=args.state_path,
    )


if __name__ == "__main__":
    main()
