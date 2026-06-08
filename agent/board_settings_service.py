"""Editable job-board and application-safety settings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.user_workspace import UserWorkspace


class BoardSettingsService:
    """Expose the operational preferences that belong in the GUI."""

    def __init__(self, workspace: UserWorkspace) -> None:
        self.workspace = workspace.ensure_initialized()

    def payload(self) -> dict[str, Any]:
        preferences = self.workspace.load_preferences()
        boards = preferences.get("job_boards") if isinstance(preferences.get("job_boards"), dict) else {}
        behavior = (
            preferences.get("application_behavior")
            if isinstance(preferences.get("application_behavior"), dict)
            else {}
        )
        defaults = (
            preferences.get("dashboard_defaults")
            if isinstance(preferences.get("dashboard_defaults"), dict)
            else {}
        )
        return {
            "job_boards": deepcopy(boards),
            "application_behavior": deepcopy(behavior),
            "limits": {
                "max_applications_per_run": preferences.get("max_applications_per_run", 1),
                "max_jobs_to_try_per_run": preferences.get("max_jobs_to_try_per_run", 5),
                "max_applications_per_day": preferences.get("max_applications_per_day", 10),
            },
            "dashboard_defaults": {
                "browser": defaults.get("browser", "chromium"),
                "location": defaults.get("location", "Amstelveen"),
                "human_mode": defaults.get("human_mode", True),
                "fresh_mode": defaults.get("fresh_mode", True),
                "ai_budget_mode": defaults.get("ai_budget_mode", "smart"),
            },
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Job-board settings payload must be an object")
        preferences = self.workspace.load_preferences()
        boards = preferences.setdefault("job_boards", {})
        submitted_boards = payload.get("job_boards")
        if not isinstance(submitted_boards, dict):
            raise ValueError("Job boards must be an object")

        linkedin = boards.setdefault("linkedin", {})
        submitted_linkedin = submitted_boards.get("linkedin", {})
        if isinstance(submitted_linkedin, dict):
            linkedin["enabled"] = self._bool(submitted_linkedin.get("enabled"), True)
            linkedin["easy_apply_only"] = self._bool(
                submitted_linkedin.get("easy_apply_only"),
                False,
            )
            linkedin["distance_miles"] = self._int(
                submitted_linkedin.get("distance_miles"),
                1,
                100,
                25,
            )
            linkedin["max_jobs_to_collect"] = self._int(
                submitted_linkedin.get("max_jobs_to_collect"),
                1,
                200,
                25,
            )
            levels = submitted_linkedin.get("experience_levels")
            if isinstance(levels, list):
                allowed_levels = {"internship", "entry", "associate", "mid_senior"}
                linkedin["experience_levels"] = [
                    str(item).strip()
                    for item in levels
                    if str(item).strip() in allowed_levels
                ]

        indeed = boards.setdefault("indeed", {})
        submitted_indeed = submitted_boards.get("indeed", {})
        if isinstance(submitted_indeed, dict):
            indeed["enabled"] = self._bool(submitted_indeed.get("enabled"), False)
            indeed["search_url"] = self._url(submitted_indeed.get("search_url"))
            indeed["radius_km"] = self._int(submitted_indeed.get("radius_km"), 1, 100, 25)
            indeed["max_jobs_to_collect"] = self._int(
                submitted_indeed.get("max_jobs_to_collect"),
                1,
                200,
                25,
            )
            indeed["manual_login_pause"] = True

        for board_name in ("glassdoor", "standalone_sites"):
            board = boards.setdefault(board_name, {})
            submitted = submitted_boards.get(board_name, {})
            if isinstance(submitted, dict):
                board["enabled"] = self._bool(submitted.get("enabled"), False)

        behavior = preferences.setdefault("application_behavior", {})
        submitted_behavior = payload.get("application_behavior")
        if isinstance(submitted_behavior, dict):
            for field, default in (
                ("skip_if_already_applied", True),
                ("skip_assessments", False),
                ("submit_cover_letter", True),
                ("generate_cover_letter_with_ai", True),
                ("answer_screening_questions", True),
                ("pause_on_unknown_question", True),
                ("pause_before_final_submit", True),
                ("add_human_like_delays", True),
            ):
                behavior[field] = self._bool(submitted_behavior.get(field), default)
        behavior["pause_before_final_submit"] = True

        limits = payload.get("limits")
        if isinstance(limits, dict):
            preferences["max_applications_per_run"] = self._int(
                limits.get("max_applications_per_run"), 1, 50, 1
            )
            preferences["max_jobs_to_try_per_run"] = self._int(
                limits.get("max_jobs_to_try_per_run"), 1, 100, 5
            )
            preferences["max_applications_per_day"] = self._int(
                limits.get("max_applications_per_day"), 1, 100, 10
            )

        defaults = preferences.setdefault("dashboard_defaults", {})
        submitted_defaults = payload.get("dashboard_defaults")
        if isinstance(submitted_defaults, dict):
            browser = str(submitted_defaults.get("browser") or "chromium").strip().lower()
            defaults["browser"] = browser if browser in {"chromium", "firefox"} else "chromium"
            defaults["location"] = self._text(
                submitted_defaults.get("location") or "Amstelveen",
                80,
            )
            defaults["human_mode"] = self._bool(submitted_defaults.get("human_mode"), True)
            defaults["fresh_mode"] = self._bool(submitted_defaults.get("fresh_mode"), True)
            budget = str(submitted_defaults.get("ai_budget_mode") or "smart").strip().lower()
            defaults["ai_budget_mode"] = budget if budget in {"smart", "deep", "off"} else "smart"

        self.workspace.save_preferences(preferences)
        return self.payload()

    def _bool(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _int(self, value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _text(self, value: Any, max_length: int) -> str:
        return " ".join(str(value or "").split())[:max_length]

    def _url(self, value: Any) -> str:
        cleaned = str(value or "").strip()
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("Indeed search URL must start with http:// or https://")
        return cleaned
