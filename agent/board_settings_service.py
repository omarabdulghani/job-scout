"""Editable job-board and application-safety settings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.user_workspace import UserWorkspace
from agent.search_scope import (
    EMPLOYMENT_PREFERENCES,
    SEARCH_MARKETS,
    build_search_scope,
    built_in_missions,
    market_profiles,
    normalize_radius,
    platform_capabilities,
)


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
        custom_missions = (
            preferences.get("search_missions")
            if isinstance(preferences.get("search_missions"), list)
            else []
        )
        return {
            "job_boards": deepcopy(boards),
            "application_behavior": deepcopy(behavior),
            "scraping_proxy_enabled": preferences.get("scraping_proxy_enabled", True),
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
                "search_market": defaults.get("search_market", "netherlands"),
                "radius_km": defaults.get("radius_km", 40),
                "employment": defaults.get("employment", "full-time-preferred"),
                "search_goal": defaults.get("search_goal", "career-growth"),
            },
            "market_profiles": market_profiles(),
            "platform_capabilities": platform_capabilities(),
            "built_in_missions": built_in_missions(),
            "search_missions": deepcopy(custom_missions),
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
            market = str(
                submitted_defaults.get("search_market") or "netherlands"
            ).strip().lower()
            defaults["search_market"] = (
                market if market in SEARCH_MARKETS else "netherlands"
            )
            defaults["radius_km"] = normalize_radius(
                "linkedin",
                submitted_defaults.get("radius_km", 40),
            )
            employment = str(
                submitted_defaults.get("employment") or "full-time-preferred"
            ).strip().lower()
            defaults["employment"] = (
                employment
                if employment in EMPLOYMENT_PREFERENCES
                else "full-time-preferred"
            )
            goal = str(
                submitted_defaults.get("search_goal") or "career-growth"
            ).strip().lower()
            defaults["search_goal"] = (
                goal
                if goal in {"career-growth", "career-focus", "broad", "income", "custom"}
                else "career-growth"
            )

        submitted_missions = payload.get("search_missions")
        if isinstance(submitted_missions, list):
            normalized_missions = [
                mission
                for mission in (
                    self._mission(value, index)
                    for index, value in enumerate(submitted_missions)
                )
                if mission
            ][:20]
            seen_ids: set[str] = set()
            seen_names = {
                str(mission.get("name") or "").strip().casefold()
                for mission in built_in_missions().values()
            }
            for mission in normalized_missions:
                mission_id = str(mission["id"]).casefold()
                mission_name = str(mission["name"]).casefold()
                if mission_id in seen_ids:
                    raise ValueError("Saved mission IDs must be unique")
                if mission_name in seen_names:
                    raise ValueError(
                        f"A saved mission named '{mission['name']}' already exists"
                    )
                seen_ids.add(mission_id)
                seen_names.add(mission_name)
            preferences["search_missions"] = normalized_missions

        preferences["scraping_proxy_enabled"] = self._bool(payload.get("scraping_proxy_enabled"), True)

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

    def _mission(self, value: Any, index: int) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        name = self._text(value.get("name"), 60)
        if not name:
            return None
        platform = str(value.get("platform") or "linkedin").strip().lower()
        if platform not in platform_capabilities():
            raise ValueError(f"Unsupported mission platform: {platform}")
        goal = str(value.get("search_goal") or "career-growth").strip().lower()
        if goal not in {"career-growth", "career-focus", "broad", "income", "custom"}:
            goal = "career-growth"
        scope = build_search_scope(
            platform=platform,
            search_market=value.get("search_market") or "netherlands",
            location=value.get("location"),
            radius_km=value.get(
                "radius_km",
                25 if platform == "indeed" else 40,
            ),
            employment=value.get(
                "employment",
                "any" if platform == "indeed" else "full-time-preferred",
            ),
            search_goal=goal,
            search_groups=value.get("search_groups", []),
            experience_levels=value.get("experience_levels"),
        )
        return {
            "id": self._text(value.get("id") or f"custom-{index + 1}", 80),
            "name": name,
            "platform": scope["platform"],
            "search_market": scope["search_market"],
            "location": scope["location"],
            "radius_km": scope["radius_km"],
            "search_goal": goal,
            "search_groups": [
                group
                for group in value.get("search_groups", [])
                if group in {"primary", "bridge", "fallback"}
            ],
            "employment": scope["employment"],
            "experience_levels": scope["experience_levels"],
        }

    def save_market(self, payload: dict[str, Any]) -> dict[str, Any]:
        market_id = str(payload.get("id") or "").strip().lower().replace("_", "-")
        if not market_id:
            raise ValueError("Market ID is required")
            
        profile = payload.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("Market profile details must be an object")
            
        # Validate required fields
        required_fields = ["label", "country", "default_location", "locations"]
        for field in required_fields:
            if not profile.get(field):
                raise ValueError(f"Market profile '{field}' is required")
                
        # Seed defaults for optional fields
        profile.setdefault("availability", "stable")
        profile.setdefault("country_codes", [])
        profile.setdefault("authorized_without_sponsorship", True)
        profile.setdefault("sponsorship_policy", "not_required")
        profile.setdefault("language_policy", "english_friendly")
        profile.setdefault("compatible_languages", ["English"])
        
        # Load current custom markets
        path = self.workspace.path / "custom_markets.json"
        import json
        custom = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    custom = json.load(f) or {}
            except Exception:
                pass
                
        custom[market_id] = profile
        
        # Save atomically
        from agent.safe_file_io import atomic_write_json
        atomic_write_json(path, custom)
        
        # Reload search_scope profiles in memory
        from agent.search_scope import reload_market_profiles
        reload_market_profiles()
        
        return self.payload()

    def delete_market(self, payload: dict[str, Any]) -> dict[str, Any]:
        market_id = str(payload.get("id") or "").strip().lower().replace("_", "-")
        if not market_id:
            raise ValueError("Market ID is required")
            
        path = self.workspace.path / "custom_markets.json"
        if path.exists():
            import json
            custom = {}
            try:
                with open(path, "r", encoding="utf-8") as f:
                    custom = json.load(f) or {}
            except Exception:
                pass
                
            if market_id in custom:
                custom.pop(market_id)
                from agent.safe_file_io import atomic_write_json
                atomic_write_json(path, custom)
                
                # Reload search_scope profiles in memory
                from agent.search_scope import reload_market_profiles
                reload_market_profiles()
                
        return self.payload()

