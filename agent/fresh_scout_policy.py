from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FreshScoutPolicy:
    """Smart Fresh Scout defaults shared by CLI and future page-decision logic."""

    enabled: bool = False
    max_pages_per_query: int = 4
    known_ratio_continue_threshold: float = 0.80
    duplicate_heavy_stop_threshold: float = 0.90
    stop_after_duplicate_heavy_pages: int = 2
    min_new_jobs_per_useful_query: int = 3
    target_apply_first_jobs: int = 8
    target_good_or_better_jobs: int = 20
    global_new_jobs_soft_cap: int = 80
    ai_budget_guard_enabled: bool = True
    ai_calls_quality_check: int = 40
    min_apply_first_after_ai_quality_check: int = 2
    min_good_or_better_after_ai_quality_check: int = 5
    ai_calls_strict_check: int = 80
    min_apply_first_after_ai_strict_check: int = 4
    min_good_or_better_after_ai_strict_check: int = 10
    ai_calls_soft_cap: int = 120

    @classmethod
    def from_preferences(cls, preferences: dict[str, Any] | None, *, enabled: bool = False) -> "FreshScoutPolicy":
        raw = {}
        preferences = preferences or {}
        if isinstance(preferences.get("fresh_scout"), dict):
            raw.update(preferences["fresh_scout"])
        linkedin = preferences.get("job_boards", {}).get("linkedin", {})
        if isinstance(linkedin.get("fresh_scout"), dict):
            raw.update(linkedin["fresh_scout"])

        policy = cls(
            enabled=enabled,
            max_pages_per_query=_int_setting(raw, "max_pages_per_query", cls.max_pages_per_query),
            known_ratio_continue_threshold=_ratio_setting(
                raw,
                "known_ratio_continue_threshold",
                cls.known_ratio_continue_threshold,
            ),
            duplicate_heavy_stop_threshold=_ratio_setting(
                raw,
                "duplicate_heavy_stop_threshold",
                cls.duplicate_heavy_stop_threshold,
            ),
            stop_after_duplicate_heavy_pages=_int_setting(
                raw,
                "stop_after_duplicate_heavy_pages",
                cls.stop_after_duplicate_heavy_pages,
            ),
            min_new_jobs_per_useful_query=_int_setting(
                raw,
                "min_new_jobs_per_useful_query",
                cls.min_new_jobs_per_useful_query,
                minimum=0,
            ),
            target_apply_first_jobs=_int_setting(raw, "target_apply_first_jobs", cls.target_apply_first_jobs),
            target_good_or_better_jobs=_int_setting(
                raw,
                "target_good_or_better_jobs",
                cls.target_good_or_better_jobs,
            ),
            global_new_jobs_soft_cap=_int_setting(
                raw,
                "global_new_jobs_soft_cap",
                cls.global_new_jobs_soft_cap,
            ),
            ai_budget_guard_enabled=_bool_setting(
                raw,
                "ai_budget_guard_enabled",
                cls.ai_budget_guard_enabled,
            ),
            ai_calls_quality_check=_int_setting(
                raw,
                "ai_calls_quality_check",
                cls.ai_calls_quality_check,
                minimum=0,
            ),
            min_apply_first_after_ai_quality_check=_int_setting(
                raw,
                "min_apply_first_after_ai_quality_check",
                cls.min_apply_first_after_ai_quality_check,
                minimum=0,
            ),
            min_good_or_better_after_ai_quality_check=_int_setting(
                raw,
                "min_good_or_better_after_ai_quality_check",
                cls.min_good_or_better_after_ai_quality_check,
                minimum=0,
            ),
            ai_calls_strict_check=_int_setting(
                raw,
                "ai_calls_strict_check",
                cls.ai_calls_strict_check,
                minimum=0,
            ),
            min_apply_first_after_ai_strict_check=_int_setting(
                raw,
                "min_apply_first_after_ai_strict_check",
                cls.min_apply_first_after_ai_strict_check,
                minimum=0,
            ),
            min_good_or_better_after_ai_strict_check=_int_setting(
                raw,
                "min_good_or_better_after_ai_strict_check",
                cls.min_good_or_better_after_ai_strict_check,
                minimum=0,
            ),
            ai_calls_soft_cap=_int_setting(
                raw,
                "ai_calls_soft_cap",
                cls.ai_calls_soft_cap,
                minimum=0,
            ),
        )
        return policy._normalized()

    def _normalized(self) -> "FreshScoutPolicy":
        target_good = max(self.target_good_or_better_jobs, self.target_apply_first_jobs)
        duplicate_stop = max(self.duplicate_heavy_stop_threshold, self.known_ratio_continue_threshold)
        return FreshScoutPolicy(
            enabled=self.enabled,
            max_pages_per_query=max(1, self.max_pages_per_query),
            known_ratio_continue_threshold=_clamp_ratio(self.known_ratio_continue_threshold),
            duplicate_heavy_stop_threshold=_clamp_ratio(duplicate_stop),
            stop_after_duplicate_heavy_pages=max(1, self.stop_after_duplicate_heavy_pages),
            min_new_jobs_per_useful_query=max(0, self.min_new_jobs_per_useful_query),
            target_apply_first_jobs=max(1, self.target_apply_first_jobs),
            target_good_or_better_jobs=max(1, target_good),
            global_new_jobs_soft_cap=max(1, self.global_new_jobs_soft_cap),
            ai_budget_guard_enabled=bool(self.ai_budget_guard_enabled),
            ai_calls_quality_check=max(0, self.ai_calls_quality_check),
            min_apply_first_after_ai_quality_check=max(0, self.min_apply_first_after_ai_quality_check),
            min_good_or_better_after_ai_quality_check=max(0, self.min_good_or_better_after_ai_quality_check),
            ai_calls_strict_check=max(0, self.ai_calls_strict_check),
            min_apply_first_after_ai_strict_check=max(0, self.min_apply_first_after_ai_strict_check),
            min_good_or_better_after_ai_strict_check=max(0, self.min_good_or_better_after_ai_strict_check),
            ai_calls_soft_cap=max(0, self.ai_calls_soft_cap),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_pages_per_query": self.max_pages_per_query,
            "known_ratio_continue_threshold": self.known_ratio_continue_threshold,
            "duplicate_heavy_stop_threshold": self.duplicate_heavy_stop_threshold,
            "stop_after_duplicate_heavy_pages": self.stop_after_duplicate_heavy_pages,
            "min_new_jobs_per_useful_query": self.min_new_jobs_per_useful_query,
            "target_apply_first_jobs": self.target_apply_first_jobs,
            "target_good_or_better_jobs": self.target_good_or_better_jobs,
            "global_new_jobs_soft_cap": self.global_new_jobs_soft_cap,
            "ai_budget_guard_enabled": self.ai_budget_guard_enabled,
            "ai_calls_quality_check": self.ai_calls_quality_check,
            "min_apply_first_after_ai_quality_check": self.min_apply_first_after_ai_quality_check,
            "min_good_or_better_after_ai_quality_check": self.min_good_or_better_after_ai_quality_check,
            "ai_calls_strict_check": self.ai_calls_strict_check,
            "min_apply_first_after_ai_strict_check": self.min_apply_first_after_ai_strict_check,
            "min_good_or_better_after_ai_strict_check": self.min_good_or_better_after_ai_strict_check,
            "ai_calls_soft_cap": self.ai_calls_soft_cap,
        }

    def panel_label(self) -> str:
        if not self.enabled:
            return "disabled"
        return (
            "enabled "
            f"(max {self.max_pages_per_query} pages/query; "
            f"continue at {self._pct(self.known_ratio_continue_threshold)} known; "
            f"stop after {self.stop_after_duplicate_heavy_pages} pages at "
            f"{self._pct(self.duplicate_heavy_stop_threshold)} known; "
            f"targets {self.target_apply_first_jobs} APPLY FIRST / "
            f"{self.target_good_or_better_jobs} good+; "
            f"cap {self.global_new_jobs_soft_cap} new jobs; "
            f"AI guard {'on' if self.ai_budget_guard_enabled else 'off'})"
        )

    @staticmethod
    def _pct(value: float) -> str:
        return f"{round(value * 100):.0f}%"


def _int_setting(settings: dict[str, Any], key: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(settings.get(key, default)))
    except (TypeError, ValueError):
        return default


def _ratio_setting(settings: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(settings.get(key, default))
    except (TypeError, ValueError):
        return default
    if value > 1:
        value = value / 100
    return _clamp_ratio(value)


def _bool_setting(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _clamp_ratio(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
