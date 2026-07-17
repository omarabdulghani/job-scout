"""Cooperative stop requests for dashboard-started scout runs."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


STOP_REQUEST_PATH = Path("data/scout_stop_request.json")
VALID_STOP_MODES = {"after_current_job", "after_current_page", "now"}


def clear_stop_request(path: Path | str = STOP_REQUEST_PATH) -> None:
    request_path = Path(path)
    if request_path.exists():
        request_path.unlink()


def request_stop(
    mode: str,
    *,
    reason: str = "",
    path: Path | str = STOP_REQUEST_PATH,
) -> dict[str, Any]:
    normalized = (mode or "").strip().lower()
    if normalized not in VALID_STOP_MODES:
        raise ValueError("Unsupported stop mode")
    request_path = Path(path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": normalized,
        "reason": reason or _default_reason(normalized),
        "requested_at": datetime.now().astimezone().isoformat(),
    }
    request_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def read_stop_request(path: Path | str = STOP_REQUEST_PATH) -> dict[str, Any]:
    request_path = Path(path)
    if not request_path.exists():
        return {}
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    mode = str(payload.get("mode", "")).strip().lower()
    if mode not in VALID_STOP_MODES:
        return {}
    return payload


def stop_requested(
    *modes: str,
    path: Path | str = STOP_REQUEST_PATH,
) -> bool:
    payload = read_stop_request(path)
    if not payload:
        return False
    if not modes:
        return True
    wanted = {str(mode).strip().lower() for mode in modes}
    return str(payload.get("mode", "")).strip().lower() in wanted


def stop_reason(path: Path | str = STOP_REQUEST_PATH) -> str:
    payload = read_stop_request(path)
    return str(payload.get("reason", "")).strip() if payload else ""


def _default_reason(mode: str) -> str:
    if mode == "after_current_job":
        return "Dashboard stop requested after the current job."
    if mode == "after_current_page":
        return "Dashboard stop requested after the current page."
    return "Dashboard stop requested now."
