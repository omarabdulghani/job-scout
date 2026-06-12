"""Structured job-search strategy operations for the local dashboard."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from agent.query_learning import order_queries_with_learning
from agent.user_workspace import UserWorkspace


LIST_BULLET_PREFIX = re.compile(r"^(?:[-*\u2022]\s+|\d+[.)]\s+)")


class StrategyService:
    def __init__(self, workspace: UserWorkspace) -> None:
        self.workspace = workspace.ensure_initialized()

    def payload(self) -> dict[str, Any]:
        profile, preferences = self.workspace.load_config()
        queries = self._load_queries()
        _, query_learning = order_queries_with_learning(
            queries,
            preferences=preferences,
            multi_output_path=self.workspace.root / "high_success_probability_jobs_multi.json",
            run_history_path=self.workspace.root / "scout_run_history.json",
        )
        return {
            "career_strategy": deepcopy(profile.get("career_strategy", {})),
            "preferences": self._public_preferences(preferences),
            "strategy_text": self.workspace.strategy_path.read_text(encoding="utf-8"),
            "portfolio_notes": self.workspace.portfolio_notes_path.read_text(encoding="utf-8"),
            "queries": queries,
            "query_learning": query_learning,
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Strategy payload must be an object")
        profile, preferences = self.workspace.load_config()

        career_strategy = payload.get("career_strategy", {})
        if not isinstance(career_strategy, dict):
            raise ValueError("Career strategy must be an object")
        normalized_strategy = deepcopy(career_strategy)
        for key in ("primary_paths", "strong_bridge_roles", "fallback_roles_for_income"):
            normalized_strategy[key] = self._string_list(normalized_strategy.get(key, []))
        profile["career_strategy"] = normalized_strategy

        incoming_preferences = payload.get("preferences", {})
        if not isinstance(incoming_preferences, dict):
            raise ValueError("Preferences must be an object")
        self._merge_public_preferences(preferences, incoming_preferences)

        queries = self._string_list(payload.get("queries", []))
        if not queries:
            raise ValueError("At least one search query is required")

        strategy_text = str(payload.get("strategy_text") or "").strip()
        if not strategy_text:
            raise ValueError("Recruiter strategy instructions cannot be empty")

        self.workspace.save_profile(profile)
        self.workspace.save_preferences(preferences)
        self.workspace.save_text(self.workspace.strategy_path, strategy_text + "\n")
        self.workspace.save_text(
            self.workspace.portfolio_notes_path,
            str(payload.get("portfolio_notes") or "").strip() + "\n",
        )
        self.workspace.save_text(
            self.workspace.search_queries_path,
            "\n".join(queries) + "\n",
        )
        return self.payload()

    def _public_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        linkedin = preferences.get("job_boards", {}).get("linkedin", {})
        return {
            "job_titles": deepcopy(preferences.get("job_titles", [])),
            "locations": deepcopy(preferences.get("locations", [])),
            "hard_exclude_keywords": deepcopy(preferences.get("hard_exclude_keywords", [])),
            "soft_negative_keywords": deepcopy(preferences.get("soft_negative_keywords", [])),
            "fallback_keywords": deepcopy(preferences.get("fallback_keywords", [])),
            "companies_blacklist": deepcopy(preferences.get("companies_blacklist", [])),
            "companies_whitelist": deepcopy(preferences.get("companies_whitelist", [])),
            "salary_preferred_monthly_full_time": preferences.get("salary_preferred_monthly_full_time", 0),
            "salary_bridge_minimum_monthly_full_time": preferences.get(
                "salary_bridge_minimum_monthly_full_time",
                0,
            ),
            "salary_part_time_hourly_minimum": preferences.get("salary_part_time_hourly_minimum", 0),
            "human_review_score_min": preferences.get("human_review_score_min", 50),
            "min_match_score": preferences.get("filters", {}).get("min_match_score", 70),
            "max_active_applications_per_company_14_days": preferences.get(
                "max_active_applications_per_company_14_days",
                2,
            ),
            "avoid_multiple_unrelated_roles_same_company": bool(
                preferences.get("avoid_multiple_unrelated_roles_same_company", True)
            ),
            "distance_miles": linkedin.get("distance_miles", 25),
            "fresh_scout": deepcopy(linkedin.get("fresh_scout", {})),
            "query_learning": deepcopy(linkedin.get("query_learning", {})),
        }

    def _merge_public_preferences(
        self,
        preferences: dict[str, Any],
        incoming: dict[str, Any],
    ) -> None:
        for key in (
            "job_titles",
            "locations",
            "hard_exclude_keywords",
            "soft_negative_keywords",
            "fallback_keywords",
            "companies_blacklist",
            "companies_whitelist",
        ):
            if key in incoming:
                preferences[key] = self._string_list(incoming.get(key))

        for key in (
            "salary_preferred_monthly_full_time",
            "salary_bridge_minimum_monthly_full_time",
            "salary_part_time_hourly_minimum",
            "human_review_score_min",
            "max_active_applications_per_company_14_days",
        ):
            if key in incoming:
                preferences[key] = self._number(incoming.get(key), preferences.get(key, 0))

        if "avoid_multiple_unrelated_roles_same_company" in incoming:
            preferences["avoid_multiple_unrelated_roles_same_company"] = bool(
                incoming.get("avoid_multiple_unrelated_roles_same_company")
            )

        preferences.setdefault("filters", {})
        if "min_match_score" in incoming:
            preferences["filters"]["min_match_score"] = int(
                self._number(incoming.get("min_match_score"), 70)
            )

        preferences.setdefault("job_boards", {}).setdefault("linkedin", {})
        linkedin = preferences["job_boards"]["linkedin"]
        if "distance_miles" in incoming:
            linkedin["distance_miles"] = int(self._number(incoming.get("distance_miles"), 25))
        if isinstance(incoming.get("fresh_scout"), dict):
            linkedin["fresh_scout"] = deepcopy(incoming["fresh_scout"])
        if isinstance(incoming.get("query_learning"), dict):
            linkedin["query_learning"] = deepcopy(incoming["query_learning"])

    def _load_queries(self) -> list[str]:
        return self._string_list(
            line
            for line in self.workspace.search_queries_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

    def _string_list(self, values) -> list[str]:
        if isinstance(values, str):
            values = values.splitlines()
        output: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            cleaned = " ".join(str(value or "").split())
            cleaned = LIST_BULLET_PREFIX.sub("", cleaned).strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                output.append(cleaned)
        return output

    def _number(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default or 0)
