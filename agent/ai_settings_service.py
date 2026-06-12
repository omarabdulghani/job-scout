"""Secure AI-provider settings for the local dashboard."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from agent.safe_file_io import atomic_write_json, atomic_write_text, load_json_with_recovery
from agent.user_workspace import UserWorkspace, now_iso


SUPPORTED_BACKENDS = (
    "cerebras",
    "ollama_cloud",
    "gemini",
    "claude",
    "openai_compatible",
    "lmstudio",
)

PROVIDERS: dict[str, dict[str, Any]] = {
    "cerebras": {
        "label": "Cerebras",
        "description": "Fast hosted scorer using the OpenAI-compatible Cerebras API.",
        "key_env": "CEREBRAS_API_KEY",
        "model_env": "CEREBRAS_MODEL",
        "base_url_env": "CEREBRAS_BASE_URL",
        "default_model": "gpt-oss-120b",
        "default_base_url": "https://api.cerebras.ai/v1",
        "hosted": True,
    },
    "ollama_cloud": {
        "label": "Ollama Cloud",
        "description": "Hosted Ollama API fallback for models available to your account.",
        "key_env": "OLLAMA_API_KEY",
        "model_env": "OLLAMA_MODEL",
        "base_url_env": "OLLAMA_BASE_URL",
        "default_model": "gpt-oss:120b",
        "default_base_url": "https://ollama.com/api",
        "hosted": True,
    },
    "gemini": {
        "label": "Google Gemini",
        "description": "Google AI Studio scorer, useful as a reliable fallback within free-tier limits.",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "base_url_env": "",
        "default_model": "gemini-2.5-flash",
        "default_base_url": "",
        "hosted": True,
    },
    "claude": {
        "label": "Anthropic Claude",
        "description": "Optional Anthropic provider for scoring or application assistance.",
        "key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "base_url_env": "",
        "default_model": "claude-opus-4-5",
        "default_base_url": "",
        "hosted": True,
    },
    "openai_compatible": {
        "label": "OpenAI-compatible",
        "description": "Advanced provider slot for another service exposing an OpenAI-compatible API.",
        "key_env": "OPENAI_COMPATIBLE_API_KEY",
        "model_env": "OPENAI_COMPATIBLE_MODEL",
        "base_url_env": "OPENAI_COMPATIBLE_BASE_URL",
        "default_model": "",
        "default_base_url": "",
        "hosted": True,
    },
    "lmstudio": {
        "label": "LM Studio",
        "description": "Local model server. No API key is stored or required.",
        "key_env": "",
        "model_env": "LMSTUDIO_MODEL",
        "base_url_env": "LMSTUDIO_BASE_URL",
        "default_model": "google/gemma-4-e4b",
        "default_base_url": "http://127.0.0.1:1234/v1",
        "hosted": False,
    },
}

GLOBAL_FIELDS = {
    "backend": "AI_BACKEND",
    "backend_order": "AI_BACKEND_ORDER",
    "rate_limit_cooldown_seconds": "HOSTED_RATE_LIMIT_COOLDOWN_SECONDS",
}

PROVIDER_EXTRA_FIELDS = {
    "cerebras": {
        "max_output_tokens": "CEREBRAS_MAX_OUTPUT_TOKENS",
        "max_attempts": "CEREBRAS_MAX_ATTEMPTS",
    },
    "ollama_cloud": {
        "max_output_tokens": "OLLAMA_MAX_OUTPUT_TOKENS",
        "max_attempts": "OLLAMA_MAX_ATTEMPTS",
        "structured_outputs": "OLLAMA_STRUCTURED_OUTPUTS",
    },
    "gemini": {
        "max_output_tokens": "GEMINI_MAX_OUTPUT_TOKENS",
        "max_attempts": "GEMINI_MAX_ATTEMPTS",
        "thinking_budget": "GEMINI_THINKING_BUDGET",
    },
    "openai_compatible": {
        "max_output_tokens": "OPENAI_COMPATIBLE_MAX_OUTPUT_TOKENS",
        "max_attempts": "OPENAI_COMPATIBLE_MAX_ATTEMPTS",
    },
    "lmstudio": {
        "reasoning_enabled": "LMSTUDIO_REASONING_ENABLED",
        "reasoning_effort": "LMSTUDIO_REASONING_EFFORT",
    },
}


class AISettingsService:
    """Read and update provider settings without exposing stored secrets."""

    def __init__(self, workspace: UserWorkspace) -> None:
        self.workspace = workspace.ensure_initialized()
        self.root = workspace.root
        self.env_path = self.root / ".env"
        self.status_path = self.workspace.path / "ai_provider_status.json"

    def payload(self) -> dict[str, Any]:
        values = self._read_env()
        statuses = self._read_statuses()
        backend = self._normalize_backend(values.get("AI_BACKEND") or "auto", allow_auto=True)
        order = self._normalize_order(values.get("AI_BACKEND_ORDER") or "cerebras,ollama_cloud,gemini")
        providers: list[dict[str, Any]] = []
        for provider_id, definition in PROVIDERS.items():
            key_env = definition["key_env"]
            key_value = values.get(key_env, "") if key_env else ""
            provider = {
                "id": provider_id,
                "label": definition["label"],
                "description": definition["description"],
                "hosted": bool(definition["hosted"]),
                "configured": self._secret_is_configured(key_value) if key_env else self._local_provider_configured(values, definition),
                "requires_key": bool(key_env),
                "model": values.get(definition["model_env"], "") or definition["default_model"],
                "base_url": (
                    values.get(definition["base_url_env"], "")
                    if definition["base_url_env"]
                    else definition["default_base_url"]
                ) or definition["default_base_url"],
                "extra": {},
                "last_test": statuses.get(provider_id, {}),
            }
            for field_name, env_name in PROVIDER_EXTRA_FIELDS.get(provider_id, {}).items():
                provider["extra"][field_name] = values.get(env_name, "")
            providers.append(provider)
        return {
            "backend": backend,
            "backend_order": order,
            "rate_limit_cooldown_seconds": self._int_or_default(
                values.get("HOSTED_RATE_LIMIT_COOLDOWN_SECONDS"),
                90,
            ),
            "providers": providers,
            "env_exists": self.env_path.exists(),
            "security_note": "Stored API keys are never returned to the browser.",
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("AI settings payload must be an object")
        current_values = self._read_env()
        updates: dict[str, str] = {}
        removals: set[str] = set()

        backend = self._normalize_backend(payload.get("backend") or "auto", allow_auto=True)
        order = self._normalize_order(payload.get("backend_order") or [])
        active_provider_ids = set(order)
        if backend != "auto":
            active_provider_ids.add(backend)
        updates[GLOBAL_FIELDS["backend"]] = backend
        updates[GLOBAL_FIELDS["backend_order"]] = ",".join(order)
        updates[GLOBAL_FIELDS["rate_limit_cooldown_seconds"]] = str(
            self._bounded_int(payload.get("rate_limit_cooldown_seconds"), 5, 3600, 90)
        )

        submitted_providers = payload.get("providers")
        if not isinstance(submitted_providers, list):
            raise ValueError("Providers must be a list")
        submitted_by_id = {
            str(item.get("id") or ""): item
            for item in submitted_providers
            if isinstance(item, dict)
        }
        for provider_id, definition in PROVIDERS.items():
            submitted = submitted_by_id.get(provider_id)
            if not submitted:
                continue
            model = self._clean_text(submitted.get("model"), max_length=160)
            key_env = definition["key_env"]
            existing_key = current_values.get(key_env, "") if key_env else ""
            new_key = str(submitted.get("api_key") or "").strip()
            remove_key = bool(submitted.get("remove_key"))
            provider_is_required = (
                provider_id in active_provider_ids
                or bool(new_key)
                or (bool(key_env) and self._secret_is_configured(existing_key) and not remove_key)
                or (not key_env)
            )
            if provider_is_required and not model:
                raise ValueError(f"{definition['label']} model cannot be empty")
            if model:
                updates[definition["model_env"]] = model
            if definition["base_url_env"]:
                base_url = self._clean_url(
                    submitted.get("base_url"),
                    required=provider_is_required,
                )
                if base_url:
                    updates[definition["base_url_env"]] = base_url

            if new_key and key_env:
                updates[key_env] = new_key
            if remove_key and key_env:
                removals.add(key_env)

            extras = submitted.get("extra") if isinstance(submitted.get("extra"), dict) else {}
            for field_name, env_name in PROVIDER_EXTRA_FIELDS.get(provider_id, {}).items():
                if field_name not in extras:
                    continue
                updates[env_name] = self._normalize_extra(field_name, extras[field_name])

        for key in removals:
            updates.pop(key, None)
        self._write_env(updates, removals)
        return self.payload()

    def test_connection(self, provider_id: str) -> dict[str, Any]:
        provider_id = self._normalize_backend(provider_id, allow_auto=False)
        if provider_id not in PROVIDERS:
            raise ValueError("Unsupported AI provider")
        values = self._read_env()
        definition = PROVIDERS[provider_id]
        started_at = now_iso()
        try:
            model_count = self._request_provider_models(provider_id, definition, values)
            result = {
                "ok": True,
                "message": "Connection successful",
                "model_count": model_count,
                "tested_at": started_at,
            }
        except Exception as exc:
            result = {
                "ok": False,
                "message": self._safe_error_message(exc),
                "model_count": None,
                "tested_at": started_at,
            }
        statuses = self._read_statuses()
        statuses[provider_id] = result
        self._write_statuses(statuses)
        return result

    def _request_provider_models(
        self,
        provider_id: str,
        definition: dict[str, Any],
        values: dict[str, str],
    ) -> int | None:
        key_env = definition["key_env"]
        api_key = values.get(key_env, "").strip() if key_env else ""
        if key_env and not self._secret_is_configured(api_key):
            raise ValueError(f"{definition['label']} API key is not configured")

        headers = {"Accept": "application/json", "User-Agent": "JobScoutDashboard/1.0"}
        if provider_id == "gemini":
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models"
                f"?key={quote(api_key, safe='')}"
            )
        elif provider_id == "claude":
            url = "https://api.anthropic.com/v1/models"
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        elif provider_id == "ollama_cloud":
            base_url = self._clean_url(
                values.get(definition["base_url_env"]) or definition["default_base_url"],
                required=True,
            )
            url = base_url.rstrip("/") + "/tags"
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            base_url = self._clean_url(
                values.get(definition["base_url_env"]) or definition["default_base_url"],
                required=True,
            )
            url = urljoin(base_url.rstrip("/") + "/", "models")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=12) as response:
                raw = response.read()
        except HTTPError as exc:
            raise RuntimeError(f"Provider returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("Provider could not be reached") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(payload, dict):
            for key in ("data", "models"):
                if isinstance(payload.get(key), list):
                    return len(payload[key])
        return None

    def _read_env(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        values: dict[str, str] = {}
        for raw_line in self.env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                values[key] = value.strip().strip('"').strip("'")
        return values

    def _write_env(self, updates: dict[str, str], removals: set[str]) -> None:
        self.workspace.ensure_initialized()
        original = self.env_path.read_text(encoding="utf-8", errors="replace") if self.env_path.exists() else ""
        if self.env_path.exists():
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
            backup = self.workspace.backup_dir / f"environment_{timestamp}.backup"
            backup.write_text(original, encoding="utf-8")

        pending = dict(updates)
        output: list[str] = []
        for raw_line in original.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in raw_line:
                output.append(raw_line)
                continue
            key = raw_line.split("=", 1)[0].strip()
            if key in removals:
                continue
            if key in pending:
                output.append(f"{key}={self._env_value(pending.pop(key))}")
            else:
                output.append(raw_line)
        if pending:
            if output and output[-1].strip():
                output.append("")
            output.append("# Updated by the local Job Scout dashboard")
            for key, value in pending.items():
                output.append(f"{key}={self._env_value(value)}")
        text = "\n".join(output).rstrip() + "\n"
        atomic_write_text(self.env_path, text)

    def _read_statuses(self) -> dict[str, Any]:
        return load_json_with_recovery(self.status_path)

    def _write_statuses(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.status_path, payload)

    def _normalize_backend(self, value: Any, *, allow_auto: bool) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "ollama": "ollama_cloud",
            "openai": "openai_compatible",
            "openai_compat": "openai_compatible",
        }
        normalized = aliases.get(normalized, normalized)
        allowed = set(SUPPORTED_BACKENDS)
        if allow_auto:
            allowed.add("auto")
        if normalized not in allowed:
            raise ValueError("Unsupported AI backend")
        return normalized

    def _normalize_order(self, value: Any) -> list[str]:
        raw_items = value if isinstance(value, list) else str(value or "").split(",")
        order: list[str] = []
        for item in raw_items:
            normalized = self._normalize_backend(item, allow_auto=False)
            if normalized not in order:
                order.append(normalized)
        if not order:
            raise ValueError("At least one fallback provider is required")
        return order

    def _local_provider_configured(self, values: dict[str, str], definition: dict[str, Any]) -> bool:
        return bool(
            (values.get(definition["base_url_env"], "") or definition["default_base_url"]).strip()
            and (values.get(definition["model_env"], "") or definition["default_model"]).strip()
        )

    def _secret_is_configured(self, value: str) -> bool:
        cleaned = str(value or "").strip().lower()
        return bool(cleaned and not cleaned.startswith("your_") and not cleaned.endswith("_here"))

    def _normalize_extra(self, field_name: str, value: Any) -> str:
        if field_name in {"max_output_tokens"}:
            return str(self._bounded_int(value, 64, 8192, 512))
        if field_name in {"max_attempts"}:
            return str(self._bounded_int(value, 1, 10, 3))
        if field_name == "thinking_budget":
            cleaned = str(value or "0").strip().lower()
            if cleaned == "auto":
                return "auto"
            return str(self._bounded_int(cleaned, 0, 32768, 0))
        if field_name in {"structured_outputs", "reasoning_enabled"}:
            return "true" if self._as_bool(value) else "false"
        if field_name == "reasoning_effort":
            cleaned = str(value or "none").strip().lower()
            allowed = {"none", "minimal", "low", "medium", "high", "xhigh", "on", "off"}
            if cleaned not in allowed:
                raise ValueError("Unsupported LM Studio reasoning effort")
            return cleaned
        return self._clean_text(value, max_length=120)

    def _clean_url(self, value: Any, *, required: bool) -> str:
        cleaned = str(value or "").strip().rstrip("/")
        if required and not cleaned:
            raise ValueError("Base URL is required")
        if cleaned and not re.match(r"^https?://", cleaned, flags=re.IGNORECASE):
            raise ValueError("Base URL must start with http:// or https://")
        return cleaned

    def _clean_text(self, value: Any, *, max_length: int) -> str:
        return " ".join(str(value or "").split())[:max_length]

    def _bounded_int(self, value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _int_or_default(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    def _env_value(self, value: Any) -> str:
        text = str(value or "")
        if not text or re.search(r"\s|#|[\"']", text):
            return json.dumps(text)
        return text

    def _safe_error_message(self, exc: Exception) -> str:
        message = str(exc).strip() or "Connection test failed"
        message = re.sub(r"AIza[0-9A-Za-z_-]+", "[redacted]", message)
        message = re.sub(r"sk-[0-9A-Za-z_-]+", "[redacted]", message)
        return message[:240]
