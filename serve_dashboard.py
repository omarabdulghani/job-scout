"""Serve the live jobs dashboard with local-only persistence endpoints."""

from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from agent.dashboard_user_state import (
    DashboardUserStateStore,
    build_job_key,
)
from agent.scout_stop import clear_stop_request, request_stop


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_DASHBOARD_DATA_PATH = Path("recommended_jobs_dashboard_data.json")
DEFAULT_USER_STATE_PATH = Path("recommended_jobs_dashboard_user_state.json")
DEFAULT_PROGRESS_PATH = Path("scout_progress.json")


class DashboardRunController:
    """Local-only controller for approved scout commands."""

    WORKFLOW_LABELS = {
        "linkedin_multi_fresh": "LinkedIn multi-query fresh",
        "linkedin_single": "LinkedIn single query",
        "linkedin_process_only": "LinkedIn process-only",
        "indeed_description": "Indeed description extraction",
    }
    MAX_PAGE_CHOICES = {"1", "2", "3", "4", "all"}
    BROWSER_CHOICES = {"chromium", "firefox"}

    def __init__(self, root: Path, *, progress_path: Path = DEFAULT_PROGRESS_PATH) -> None:
        self.root = Path(root).resolve()
        self.progress_path = progress_path if progress_path.is_absolute() else self.root / progress_path
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.log_handle = None
        self.state: dict[str, Any] = {
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
        }

    def status(self) -> dict[str, Any]:
        with self.lock:
            self._refresh_process_locked()
            payload = dict(self.state)
            payload["resume_available"] = self._resume_available()
            payload["workflows"] = [
                {"value": key, "label": label}
                for key, label in self.WORKFLOW_LABELS.items()
            ]
            payload["log_tail"] = self._read_log_tail(payload.get("log_path", ""))
            return payload

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._refresh_process_locked()
            if self.process and self.process.poll() is None:
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
            self.process = subprocess.Popen(
                command,
                cwd=str(self.root),
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                env=env,
            )
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
                "command": self._display_command(command),
            }
            return self.status()

    def stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str((payload or {}).get("mode", "")).strip().lower()
        if mode not in {"after_current_job", "after_current_page", "now"}:
            raise ValueError("Unsupported stop mode")
        with self.lock:
            self._refresh_process_locked()
            if not self.process or self.process.poll() is not None:
                raise ValueError("No scout run is active")
            request_stop(
                mode,
                path=self.root / "data" / "scout_stop_request.json",
            )
            if mode == "now":
                self.process.terminate()
                self.state["status"] = "stopping"
            else:
                self.state["status"] = "stopping_after_job" if mode == "after_current_job" else "stopping_after_page"
            return self.status()

    def build_command(self, payload: dict[str, Any]) -> tuple[list[str], str, str]:
        workflow = self._clean_choice(payload.get("workflow"), self.WORKFLOW_LABELS, "linkedin_multi_fresh")
        location = self._clean_text(payload.get("location") or "Amstelveen", max_length=80)
        query = self._clean_text(payload.get("query") or "", max_length=120)
        max_pages = self._clean_choice(payload.get("max_pages"), self.MAX_PAGE_CHOICES, "1")
        browser = self._clean_choice(payload.get("browser"), self.BROWSER_CHOICES, "chromium")
        human_mode = bool(payload.get("human_mode", True))
        fresh = bool(payload.get("fresh", workflow == "linkedin_multi_fresh"))
        resume = bool(payload.get("resume", False))

        command = [sys.executable]
        if workflow == "linkedin_multi_fresh":
            command += ["scout_jobs_multi.py", "--linkedin", "--location", location, "--max-pages", max_pages]
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
        else:
            raise ValueError("Unsupported workflow")

        if human_mode:
            command.append("--human-mode")
        if resume and workflow != "linkedin_process_only":
            command.append("--resume")
        command += ["--browser", browser]
        return command, workflow, self.WORKFLOW_LABELS[workflow]

    def _refresh_process_locked(self) -> None:
        if not self.process:
            return
        return_code = self.process.poll()
        if return_code is None:
            self.state["active"] = True
            return
        if self.log_handle:
            self.log_handle.close()
            self.log_handle = None
        self.state["active"] = False
        self.state["return_code"] = return_code
        self.state["completed_at"] = self.state.get("completed_at") or datetime.now().astimezone().isoformat()
        if self.state.get("status") in {"stopping", "stopping_after_job", "stopping_after_page"}:
            self.state["status"] = "stopped"
        else:
            self.state["status"] = "completed" if return_code == 0 else "failed"
        self.process = None

    def _resume_available(self) -> bool:
        try:
            payload = json.loads(self.progress_path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return False
        return isinstance(payload, dict) and payload.get("status") != "completed"

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


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """Static dashboard server plus tiny JSON API for manual job status."""

    dashboard_data_path: Path = DEFAULT_DASHBOARD_DATA_PATH
    user_state_path: Path = DEFAULT_USER_STATE_PATH
    run_controller: DashboardRunController | None = None

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path in {"", "/"}:
            self.send_response(302)
            self.send_header("Location", "/recommended_jobs_dashboard.html")
            self.end_headers()
            return
        if self._path_without_query() == "/api/dashboard-data":
            self._send_json(self._load_dashboard_with_user_state())
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
        super().do_GET()

    def do_POST(self) -> None:
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

        if self._path_without_query() != "/api/job-status":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            payload = self._read_json_body()
            job = payload.get("job") if isinstance(payload.get("job"), dict) else payload
            status = payload.get("status", "")
            store = DashboardUserStateStore(self.user_state_path)
            record = store.set_status(job, status)
            self._send_json(
                {
                    "ok": True,
                    "record": record,
                    "job_key": record.get("job_key") or build_job_key(job),
                    "data": self._load_dashboard_with_user_state(store=store),
                }
            )
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

    def _read_dashboard_data(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.dashboard_data_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            payload = {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", "live_dashboard.v1")
        payload.setdefault("runs", [])
        payload.setdefault("jobs", [])
        payload.setdefault("summary", {})
        payload.setdefault("filter_options", {})
        return payload

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            raise ValueError("JSON body is required")
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

    def _path_without_query(self) -> str:
        return self.path.split("?", 1)[0]


def make_handler(
    *,
    directory: Path,
    dashboard_data_path: Path,
    user_state_path: Path,
    run_controller: DashboardRunController | None = None,
):
    class ConfiguredDashboardRequestHandler(DashboardRequestHandler):
        pass

    ConfiguredDashboardRequestHandler.dashboard_data_path = dashboard_data_path
    ConfiguredDashboardRequestHandler.user_state_path = user_state_path
    ConfiguredDashboardRequestHandler.run_controller = run_controller
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
    run_controller = DashboardRunController(root)
    handler = make_handler(
        directory=root,
        dashboard_data_path=data_path,
        user_state_path=state_path,
        run_controller=run_controller,
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
