"""Shared normalization for job metadata used by JSON and SQLite views."""

from __future__ import annotations

from typing import Any


APPLY_METHOD_LABELS = {
    "easy_apply": "Easy Apply",
    "external_apply": "External Apply",
    "unknown": "Unknown",
}


def normalize_apply_method(event: dict[str, Any] | str | None) -> str:
    if isinstance(event, dict):
        raw = _normalize_value(event.get("apply_method"))
        flags = {
            str(flag).strip().lower().replace("-", "_").replace(" ", "_")
            for flag in event.get("flags", [])
            if str(flag).strip()
        }
        if raw in APPLY_METHOD_LABELS:
            return raw
        if bool(event.get("easy_apply")) or "easy_apply" in flags:
            return "easy_apply"
        if "external_apply" in flags:
            return "external_apply"
        return "unknown"

    raw = _normalize_value(event)
    return raw if raw in APPLY_METHOD_LABELS else "unknown"


def normalize_apply_method_fields(job: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with consistent apply-method fields and flags."""

    normalized = dict(job or {})
    method = normalize_apply_method(normalized)
    flags = [
        str(flag).strip()
        for flag in normalized.get("flags", [])
        if str(flag).strip()
    ]
    lowered_flags = {
        flag.lower().replace("-", "_").replace(" ", "_")
        for flag in flags
    }
    if method in {"easy_apply", "external_apply"} and method not in lowered_flags:
        flags.append(method)
    normalized["flags"] = flags
    normalized["apply_method"] = method
    normalized["apply_method_label"] = APPLY_METHOD_LABELS[method]
    normalized["easy_apply"] = method == "easy_apply"
    return normalized


def _normalize_value(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
