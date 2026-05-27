"""Serve the live jobs dashboard with local-only persistence endpoints."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any

from agent.dashboard_user_state import (
    DashboardUserStateStore,
    build_job_key,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_DASHBOARD_DATA_PATH = Path("recommended_jobs_dashboard_data.json")
DEFAULT_USER_STATE_PATH = Path("recommended_jobs_dashboard_user_state.json")


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """Static dashboard server plus tiny JSON API for manual job status."""

    dashboard_data_path: Path = DEFAULT_DASHBOARD_DATA_PATH
    user_state_path: Path = DEFAULT_USER_STATE_PATH

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
        super().do_GET()

    def do_POST(self) -> None:
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
):
    class ConfiguredDashboardRequestHandler(DashboardRequestHandler):
        pass

    ConfiguredDashboardRequestHandler.dashboard_data_path = dashboard_data_path
    ConfiguredDashboardRequestHandler.user_state_path = user_state_path
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
    handler = make_handler(
        directory=root,
        dashboard_data_path=data_path,
        user_state_path=state_path,
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
