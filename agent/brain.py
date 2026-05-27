import copy
import json
import os
from pathlib import Path
import re
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import anthropic
from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv()


class LMStudioRetryableScoringError(RuntimeError):
    """Retryable LM Studio scoring failure."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = (kind or "unknown").strip().lower() or "unknown"


class GeminiRetryableScoringError(RuntimeError):
    """Retryable Gemini scoring failure."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = (kind or "unknown").strip().lower() or "unknown"


class HostedProviderRetryableScoringError(RuntimeError):
    """Retryable hosted-provider scoring failure."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = (kind or "unknown").strip().lower() or "unknown"


SYSTEM_PROMPT = """You are an expert job application agent. You control a browser to apply for jobs on behalf of a user.

You will be given:
1. A screenshot of the current browser page (as an image)
2. The page's text content
3. The user's full profile (personal info, experience, skills, preferences)
4. The current task and application behavior rules

Your job is to decide exactly what browser action to take next.

You must respond ONLY with a valid JSON object in this exact format:
{
  "action": "<action_name>",
  "params": { ... },
  "reasoning": "brief explanation"
}

Available actions:
- click_selector: { "selector": "CSS selector" }
- click_text: { "text": "visible text to click" }
- type_text: { "selector": "CSS selector", "text": "text to type" }
- fill_field: { "selector": "CSS selector", "value": "text" }
- answer_question: { "selector": "CSS selector", "question": "question being asked", "context": "extra page context", "method": "type_text" | "fill_field" }
- select_option: { "selector": "CSS selector", "label": "option text" }
- upload_file: { "selector": "CSS selector", "path": "file path" }
- scroll_down: { "amount": 500 }
- scroll_to_bottom: {}
- navigate: { "url": "https://..." }
- wait: { "seconds": 2 }
- done: { "status": "applied" | "skipped" | "failed" | "needs_human", "reason": "..." }

Rules:
- Use ONLY information from the user's profile. Never invent information.
- Prefer answer_question for screening questions when that behavior is enabled.
- If a required field asks for something not in the profile, use the closest available truthful info.
- For salary fields, use the profile's salary target.
- Only use the provided cover letter if cover letter submission is enabled.
- If you encounter a CAPTCHA, return done with status "needs_human".
- If the job does not match the user's preferences, return done with status "skipped".
- If the current page is an assessment and skip_assessments is enabled, return done with status "skipped".
- Always prefer clicking visible buttons over brittle selectors when possible.
- Return done when the application is fully submitted.
"""


class JobBrain:
    """Claude-powered decision engine for the job agent."""

    LEARNED_ANSWERS_PATH = Path("data/learned_answers.json")
    PORTFOLIO_NOTES_PATH = Path("data/portfolio_site_notes.txt")
    LMSTUDIO_SCORING_BASE_MAX_TOKENS = 350
    LMSTUDIO_SCORING_REASONING_MAX_TOKENS = 900
    LMSTUDIO_SCORING_INITIAL_RETRY_DELAY_SECONDS = 5
    LMSTUDIO_SCORING_MAX_RETRY_DELAY_SECONDS = 60
    GEMINI_SCORING_MAX_OUTPUT_TOKENS = 512
    GEMINI_SCORING_MAX_ATTEMPTS = 3
    GEMINI_SCORING_INITIAL_RETRY_DELAY_SECONDS = 5
    GEMINI_SCORING_MAX_RETRY_DELAY_SECONDS = 60
    HOSTED_SCORING_MAX_OUTPUT_TOKENS = 512
    HOSTED_SCORING_MAX_ATTEMPTS = 3
    HOSTED_SCORING_INITIAL_RETRY_DELAY_SECONDS = 5
    HOSTED_SCORING_MAX_RETRY_DELAY_SECONDS = 60
    SCORING_REQUIREMENT_HEADINGS = (
        "requirements",
        "required skills",
        "required skills & competencies",
        "qualifications",
        "what you bring",
        "this is what you bring",
        "must-have technical skills",
        "skills",
        "who you are",
        "what we're looking for",
        "what we are looking for",
        "dit neem jij mee",
        "wat bied jij",
        "vereisten",
        "profiel",
    )
    SCORING_RESPONSIBILITY_HEADINGS = (
        "responsibilities",
        "key responsibilities",
        "what you'll do",
        "what you will do",
        "your role",
        "your tasks",
        "duties",
        "job description",
        "jouw baan",
        "jouw werkdag",
        "wat ga je doen",
        "taken",
        "werkzaamheden",
    )
    SCORING_BOILERPLATE_HEADINGS = (
        "about us",
        "about the company",
        "who we are",
        "what we offer",
        "what you get",
        "benefits",
        "why join us",
        "werken bij",
        "wat je van ons krijgt",
        "dit bieden wij",
    )
    SCORING_REQUIREMENT_MARKERS = (
        "required",
        "requirement",
        "requirements",
        "must have",
        "must-have",
        "you have",
        "you are",
        "we are looking for",
        "qualification",
        "qualifications",
        "experience with",
        "experience in",
        "knowledge of",
        "ability to",
        "degree",
        "bachelor",
        "master",
        "certificate",
        "certification",
        "skills",
        "strong ",
        "excellent ",
        "fluent",
        "proficiency",
        "native",
        "je hebt",
        "je bent",
        "kennis van",
        "ervaring met",
        "affiniteit met",
        "opleiding",
        "diploma",
        "vaardig",
        "vaardigheden",
        "beheerst",
        "communicatief",
        "analytisch",
    )
    SCORING_RESPONSIBILITY_MARKERS = (
        "responsible for",
        "you will",
        "you'll",
        "you will be",
        "provide",
        "support",
        "coordinate",
        "collaborate",
        "implement",
        "develop",
        "design",
        "analyze",
        "deliver",
        "create",
        "monitor",
        "gather",
        "translate",
        "work across",
        "perform",
        "assist",
        "lead",
        "manage",
        "jouw baan",
        "jouw werkdag",
        "wat ga je doen",
        "je gaat",
        "verantwoordelijk",
        "begeleid",
        "ontwikkel",
        "implementeer",
        "adviseer",
        "ondersteun",
        "werk samen",
    )
    SCORING_BOILERPLATE_MARKERS = (
        "about us",
        "about the company",
        "who we are",
        "equal opportunity",
        "equal opportunities",
        "diversity and inclusion",
        "diversity, equity and inclusion",
        "apply now",
        "how to apply",
        "application process",
        "benefits",
        "perks",
        "what we offer",
        "what you get",
        "why join us",
        "vacation days",
        "holiday allowance",
        "travel allowance",
        "pension",
        "bonus",
        "gym",
        "lunch",
        "breakfast",
        "chipcafé",
        "team outings",
        "borrels",
        "social activities",
        "salary where you",
        "salaris waar je",
        "warm welkom",
        "daily enjoy",
        "dagelijks genieten",
    )
    SCORING_SENTENCE_START_MARKERS = (
        "Provide",
        "Work",
        "Assess",
        "Perform",
        "Coordinate",
        "Collaborate",
        "Gather",
        "Ensure",
        "Support",
        "Develop",
        "Implement",
        "Analyze",
        "Design",
        "Create",
        "Monitor",
        "Drive",
        "Assist",
        "Lead",
        "Manage",
        "Required",
        "Must",
        "Strong",
        "Excellent",
        "Ability",
        "Knowledge",
        "Experience",
        "Kennis",
        "Ervaring",
        "Je bent",
        "Je hebt",
        "Je gaat",
        "Verantwoordelijk",
        "Wat bied jij",
        "Dit neem jij mee",
        "Jouw baan",
        "Wat ga je doen",
    )

    DUTCH_TITLE_MARKERS = {
        "afstudeerstage",
        "applicatiebeheerder",
        "communicatiemedewerker",
        "contentmedewerker",
        "copywriter nederlands",
        "digitale",
        "dutchtalige",
        "grafisch",
        "leeromgeving",
        "medewerker",
        "meewerkstage",
        "nederlandstalig",
        "nederlandstalige",
        "ontwerper",
        "stageplek",
        "stagiair",
        "vacature",
        "vormgever",
        "werkstudent",
    }
    DUTCH_LANGUAGE_MARKERS = {
        "aan",
        "afdeling",
        "als",
        "bij",
        "binnen",
        "bent",
        "ben",
        "beschikbaar",
        "dan",
        "de",
        "dit",
        "een",
        "en",
        "ervaring",
        "functie",
        "geen",
        "heb",
        "hebben",
        "het",
        "je",
        "jij",
        "jouw",
        "kan",
        "klant",
        "klanten",
        "met",
        "naar",
        "niet",
        "onze",
        "ons",
        "ontwikkelen",
        "om",
        "opleiding",
        "op",
        "over",
        "samen",
        "samenwerken",
        "sterke",
        "taken",
        "te",
        "team",
        "uit",
        "vacature",
        "van",
        "vereist",
        "verantwoordelijk",
        "vereisten",
        "voor",
        "werk",
        "werken",
        "werkzaamheden",
        "wij",
        "wordt",
        "zeer",
        "zoek",
    }
    ENGLISH_LANGUAGE_MARKERS = {
        "about",
        "and",
        "build",
        "design",
        "designer",
        "experience",
        "for",
        "in",
        "is",
        "join",
        "looking",
        "our",
        "product",
        "team",
        "the",
        "to",
        "we",
        "with",
        "work",
        "you",
        "your",
    }
    MANAGEMENT_TITLE_TERMS = {
        "manager",
        "director",
        "head",
        "chief",
    }
    HIGH_DUTCH_FLUENCY_MARKERS = {
        "professional dutch",
        "professional level dutch",
        "native dutch",
        "native-level dutch",
        "near native dutch",
        "near-native dutch",
        "excellent dutch",
        "dutch c1",
        "dutch c2",
        "c1 dutch",
        "c2 dutch",
        "professioneel nederlands",
        "uitstekend nederlands",
        "moedertaal nederlands",
        "nederlands op c1 niveau",
        "nederlands op c2 niveau",
    }
    FLUENT_DUTCH_CONTEXT_MARKERS = {
        "fluent dutch",
        "fluent in dutch",
        "must be fluent in dutch",
        "vloeiend nederlands",
    }
    DUTCH_HEAVY_COMMUNICATION_MARKERS = {
        "dutch copywriting",
        "copywriting in dutch",
        "newsletters",
        "social media content",
        "social content",
        "client calls",
        "sales calls",
        "recruitment calls",
        "customer-facing phone",
        "phone support",
        "telephone support",
        "call center",
        "dutch public sector",
        "public-sector communication",
        "dutch labour law",
        "labor law",
        "arbeidsrecht",
        "policy writing",
        "hr advisory",
        "legal",
        "compliance",
        "recruitment",
        "sales",
    }
    SOFT_DUTCH_EXCLUDE_KEYWORDS = {
        "dutch",
        "fluent dutch",
        "fluent in dutch",
        "professional dutch",
        "professional level dutch",
        "native dutch",
        "native-level dutch",
        "near native dutch",
        "near-native dutch",
        "excellent dutch",
        "business dutch",
        "c1 dutch",
        "c2 dutch",
        "c1 nederlands",
        "c2 nederlands",
        "vloeiend nederlands vereist",
        "vloeiend nederlands",
        "professioneel nederlands",
        "uitstekend nederlands",
        "moedertaal nederlands",
        "nederlandstalig",
        "nederlandstalige",
        "nederlands vereist",
    }
    TITLE_STOPWORDS = {
        "advisor",
        "associate",
        "consultant",
        "coordinator",
        "engineer",
        "executive",
        "programme",
        "program",
        "representative",
        "specialist",
        "technical",
        "and",
        "the",
        "for",
        "with",
        "junior",
        "senior",
        "lead",
        "principal",
        "mid",
        "level",
        "netherlands",
        "assistant",
    }

    def __init__(self, profile: dict, preferences: dict):
        self.profile = profile
        self.preferences = preferences
        self.client = None
        self.learned_answers = self._load_learned_answers()
        self.model = (
            os.getenv("ANTHROPIC_MODEL")
            or preferences.get("anthropic_model")
            or "claude-opus-4-5"
        )
        self.scoring_backend = (
            os.getenv("AI_BACKEND")
            or preferences.get("ai_backend")
            or "auto"
        ).strip().lower()
        self.scoring_backend = self._normalize_scoring_backend(self.scoring_backend)
        self.ai_backend_order = self._normalize_backend_order(
            os.getenv("AI_BACKEND_ORDER")
            or preferences.get("ai_backend_order")
            or "cerebras,ollama_cloud,gemini"
        )
        self.lmstudio_base_url = (
            os.getenv("LMSTUDIO_BASE_URL")
            or preferences.get("lmstudio_base_url")
            or "http://127.0.0.1:1234/v1"
        ).strip()
        self.lmstudio_model = (
            os.getenv("LMSTUDIO_MODEL")
            or preferences.get("lmstudio_model")
            or "google/gemma-4-e4b"
        ).strip()
        self.lmstudio_reasoning_enabled = self._env_bool(
            "LMSTUDIO_REASONING_ENABLED",
            preferences.get("lmstudio_reasoning_enabled", False),
        )
        self.lmstudio_reasoning_effort = (
            os.getenv("LMSTUDIO_REASONING_EFFORT")
            or preferences.get("lmstudio_reasoning_effort")
            or "none"
        ).strip().lower()
        self.gemini_api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()
        self.gemini_model = (
            os.getenv("GEMINI_MODEL")
            or preferences.get("gemini_model")
            or "gemini-2.5-flash"
        ).strip()
        self.gemini_max_output_tokens = self._env_int(
            "GEMINI_MAX_OUTPUT_TOKENS",
            preferences.get("gemini_max_output_tokens", self.GEMINI_SCORING_MAX_OUTPUT_TOKENS),
            minimum=64,
        )
        self.gemini_thinking_budget = self._env_optional_int(
            "GEMINI_THINKING_BUDGET",
            preferences.get("gemini_thinking_budget", 0),
            minimum=0,
        )
        self.gemini_max_attempts = self._env_int(
            "GEMINI_MAX_ATTEMPTS",
            preferences.get("gemini_max_attempts", self.GEMINI_SCORING_MAX_ATTEMPTS),
            minimum=1,
        )
        self.gemini_initial_retry_delay_seconds = self._env_int(
            "GEMINI_INITIAL_RETRY_DELAY_SECONDS",
            preferences.get(
                "gemini_initial_retry_delay_seconds",
                self.GEMINI_SCORING_INITIAL_RETRY_DELAY_SECONDS,
            ),
            minimum=1,
        )
        self.gemini_max_retry_delay_seconds = self._env_int(
            "GEMINI_MAX_RETRY_DELAY_SECONDS",
            preferences.get(
                "gemini_max_retry_delay_seconds",
                self.GEMINI_SCORING_MAX_RETRY_DELAY_SECONDS,
            ),
            minimum=1,
        )
        self.cerebras_api_key = (os.getenv("CEREBRAS_API_KEY") or "").strip()
        self.cerebras_base_url = (
            os.getenv("CEREBRAS_BASE_URL")
            or preferences.get("cerebras_base_url")
            or "https://api.cerebras.ai/v1"
        ).strip()
        self.cerebras_model = (
            os.getenv("CEREBRAS_MODEL")
            or preferences.get("cerebras_model")
            or "gpt-oss-120b"
        ).strip()
        self.cerebras_max_output_tokens = self._env_int(
            "CEREBRAS_MAX_OUTPUT_TOKENS",
            preferences.get("cerebras_max_output_tokens", self.HOSTED_SCORING_MAX_OUTPUT_TOKENS),
            minimum=64,
        )
        self.cerebras_max_attempts = self._env_int(
            "CEREBRAS_MAX_ATTEMPTS",
            preferences.get("cerebras_max_attempts", self.HOSTED_SCORING_MAX_ATTEMPTS),
            minimum=1,
        )
        self.ollama_api_key = (os.getenv("OLLAMA_API_KEY") or "").strip()
        self.ollama_base_url = (
            os.getenv("OLLAMA_BASE_URL")
            or preferences.get("ollama_base_url")
            or "https://ollama.com/api"
        ).strip()
        self.ollama_model = (
            os.getenv("OLLAMA_MODEL")
            or os.getenv("OLLAMA_CLOUD_MODEL")
            or preferences.get("ollama_model")
            or "gpt-oss:120b"
        ).strip()
        self.ollama_max_output_tokens = self._env_int(
            "OLLAMA_MAX_OUTPUT_TOKENS",
            preferences.get("ollama_max_output_tokens", self.HOSTED_SCORING_MAX_OUTPUT_TOKENS),
            minimum=64,
        )
        self.ollama_max_attempts = self._env_int(
            "OLLAMA_MAX_ATTEMPTS",
            preferences.get("ollama_max_attempts", self.HOSTED_SCORING_MAX_ATTEMPTS),
            minimum=1,
        )
        self.ollama_structured_outputs = self._env_bool(
            "OLLAMA_STRUCTURED_OUTPUTS",
            preferences.get("ollama_structured_outputs", False),
        )
        self.openai_compatible_api_key = (
            os.getenv("OPENAI_COMPATIBLE_API_KEY")
            or os.getenv("OPENAI_COMPAT_API_KEY")
            or ""
        ).strip()
        self.openai_compatible_base_url = (
            os.getenv("OPENAI_COMPATIBLE_BASE_URL")
            or os.getenv("OPENAI_COMPAT_BASE_URL")
            or preferences.get("openai_compatible_base_url")
            or ""
        ).strip()
        self.openai_compatible_model = (
            os.getenv("OPENAI_COMPATIBLE_MODEL")
            or os.getenv("OPENAI_COMPAT_MODEL")
            or preferences.get("openai_compatible_model")
            or ""
        ).strip()
        self.openai_compatible_max_output_tokens = self._env_int(
            "OPENAI_COMPATIBLE_MAX_OUTPUT_TOKENS",
            preferences.get("openai_compatible_max_output_tokens", self.HOSTED_SCORING_MAX_OUTPUT_TOKENS),
            minimum=64,
        )
        self.openai_compatible_max_attempts = self._env_int(
            "OPENAI_COMPATIBLE_MAX_ATTEMPTS",
            preferences.get("openai_compatible_max_attempts", self.HOSTED_SCORING_MAX_ATTEMPTS),
            minimum=1,
        )
        self._lmstudio_api_models_cache = None
        self.gemini_client = None
        self.scoring_event_logger = None
        self.scoring_audit_enabled = False
        self._lmstudio_request_settings_logged = False
        self._gemini_request_settings_logged = False
        self._hosted_request_settings_logged = set()
        self._last_scoring_audit_snapshot = None
        self.profile_knowledge = self._build_profile_knowledge()

    def _normalize_scoring_backend(self, backend: str) -> str:
        normalized = (backend or "").strip().lower().replace("-", "_")
        aliases = {
            "ollama": "ollama_cloud",
            "ollama_cloud_api": "ollama_cloud",
            "openai": "openai_compatible",
            "openai_compat": "openai_compatible",
            "compatible": "openai_compatible",
        }
        return aliases.get(normalized, normalized or "auto")

    def _normalize_backend_order(self, value) -> list[str]:
        if isinstance(value, (list, tuple)):
            raw_items = value
        else:
            raw_items = re.split(r"[,;\s]+", str(value or ""))
        order: list[str] = []
        for item in raw_items:
            backend = self._normalize_scoring_backend(str(item))
            if backend and backend not in order:
                order.append(backend)
        return order or ["cerebras", "ollama_cloud", "gemini"]

    @property
    def scoring_model_label(self) -> str:
        if self.scoring_backend == "lmstudio":
            model_name = self.lmstudio_model or "<unset>"
            return f"lmstudio:{model_name}"
        if self.scoring_backend == "gemini":
            model_name = self.gemini_model or "<unset>"
            return f"gemini:{model_name}"
        if self.scoring_backend == "cerebras":
            return self._hosted_model_label("cerebras")
        if self.scoring_backend == "ollama_cloud":
            return self._hosted_model_label("ollama_cloud")
        if self.scoring_backend == "openai_compatible":
            return self._hosted_model_label("openai_compatible")
        if self.scoring_backend == "auto":
            backend = self._first_configured_auto_backend()
            return self._hosted_model_label(backend) if backend else "auto:<no configured providers>"
        return self.model

    def scoring_model_labels_for_cache(self) -> set[str]:
        if self.scoring_backend != "auto":
            return {self.scoring_model_label}
        labels = {
            self._hosted_model_label(backend)
            for backend in self._configured_auto_backends()
        }
        return {label for label in labels if label}

    def _env_bool(self, name: str, default=False) -> bool:
        value = os.getenv(name)
        if value is None:
            value = default
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return bool(default)

    def _env_int(self, name: str, default: int, minimum: int = 0) -> int:
        value = os.getenv(name)
        if value is None:
            value = default
        try:
            return max(int(minimum), int(str(value).strip()))
        except (TypeError, ValueError):
            try:
                return max(int(minimum), int(default))
            except (TypeError, ValueError):
                return int(minimum)

    def _env_optional_int(self, name: str, default=None, minimum: int = 0) -> int | None:
        value = os.getenv(name)
        if value is None:
            value = default
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"", "none", "auto", "default", "omit", "omitted"}:
            return None
        try:
            return max(int(minimum), int(normalized))
        except (TypeError, ValueError):
            return None

    def _estimate_prompt_tokens(self, prompt: str) -> int:
        text = str(prompt or "")
        if not text:
            return 0
        return max(1, int(round(len(text) / 4)))

    def _set_scoring_audit_snapshot(self, snapshot: dict | None) -> None:
        if not self.scoring_audit_enabled:
            self._last_scoring_audit_snapshot = None
            return
        self._last_scoring_audit_snapshot = copy.deepcopy(snapshot or {})

    def _update_scoring_audit_usage(self, usage: dict | None) -> None:
        if not self.scoring_audit_enabled or not isinstance(self._last_scoring_audit_snapshot, dict):
            return
        usage_dict = usage if isinstance(usage, dict) else {}
        self._last_scoring_audit_snapshot["usage"] = copy.deepcopy(usage_dict)
        prompt_tokens = usage_dict.get("prompt_tokens")
        completion_tokens = usage_dict.get("completion_tokens")
        if prompt_tokens is not None:
            self._last_scoring_audit_snapshot["prompt_tokens_actual"] = prompt_tokens
        if completion_tokens is not None:
            self._last_scoring_audit_snapshot["completion_tokens_actual"] = completion_tokens

    def get_last_scoring_audit_snapshot(self) -> dict:
        if not isinstance(self._last_scoring_audit_snapshot, dict):
            return {}
        return copy.deepcopy(self._last_scoring_audit_snapshot)

    def _compact_scoring_text(self, text: str, max_length: int = 140) -> str:
        normalized = self._normalize_knowledge_text(text)
        normalized = re.sub(r"^[\-\*\u2022:;,\s]+", "", normalized).strip()
        normalized = re.sub(r"^(?:responsibilities?|requirements?|skills|qualifications|what you bring|what you'll do|jouw baan|wat ga je doen)\s*:\s*", "", normalized, flags=re.I)
        if len(normalized) <= max_length:
            return normalized
        shortened = normalized[:max_length].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return f"{shortened}..."

    def _extract_markdown_bullets_under_heading(
        self,
        text: str,
        heading_patterns: tuple[str, ...],
        max_items: int = 6,
        max_length: int = 80,
    ) -> list[str]:
        items: list[str] = []
        capture = False
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            normalized = self._normalize_knowledge_text(line).lower()
            if line.startswith("##"):
                capture = any(pattern in normalized for pattern in heading_patterns)
                continue
            if not capture:
                continue
            if line.startswith(("* ", "- ")):
                item = self._compact_scoring_text(line[2:], max_length=max_length)
                if item and item not in items:
                    items.append(item)
                if len(items) >= max_items:
                    break
        return items

    def _candidate_strength_phrases(self) -> list[str]:
        strengths: list[str] = []
        about_text = (self.profile.get("about_me") or "").lower()
        biggest_strength = (
            self.profile.get("common_questions", {}).get("biggest_strength") or ""
        ).lower()
        combined = f"{about_text}\n{biggest_strength}"

        if any(token in combined for token in ["creative", "branding", "strategy"]):
            strengths.append("creative strategy with structured problem-solving")
        if any(
            token in combined
            for token in ["ux", "user-centered", "user centred", "research", "prototyping"]
        ):
            strengths.append("user-centered research and digital solution design")
        if any(token in combined for token in ["analytics", "digital marketing", "seo"]):
            strengths.append("digital marketing, analytics, and cross-channel thinking")

        language_bits = []
        for item in self.profile.get("languages", []):
            language = (item.get("language") or "").strip()
            level = (item.get("level") or "").strip()
            if not language or not level:
                continue
            if language.lower() == "english":
                language_bits.append("English fluent")
            elif language.lower() == "dutch":
                language_bits.append("Dutch B1")
            elif language.lower() == "arabic":
                language_bits.append("Arabic native")
        if language_bits:
            strengths.append(", ".join(language_bits[:3]))

        deduped: list[str] = []
        for item in strengths:
            compact = self._compact_scoring_text(item, max_length=90)
            if compact and compact not in deduped:
                deduped.append(compact)
            if len(deduped) >= 2:
                break

        if not deduped:
            fallback_skills = [
                skill.strip()
                for skill in self.profile.get("skills", [])
                if str(skill or "").strip()
            ]
            if fallback_skills:
                deduped.append(
                    self._compact_scoring_text(
                        f"transferable strengths in {', '.join(fallback_skills[:3])}",
                        max_length=90,
                    )
                )

        return deduped[:2]

    def _build_candidate_scoring_summary(self, query: str, ideal_text: str) -> dict:
        search_query = self._compact_scoring_text(query.strip(), max_length=55)
        skill_levels = self.profile.get("skill_levels", {})
        strategy = self.profile.get("career_strategy", {})
        personal = self.profile.get("personal", {})

        return {
            "search_query": search_query,
            "experience_level": "recent graduate; entry/junior/graduate/trainee roles; 0-2 years preferred; 3+ only if clearly realistic",
            "primary_creative_product_paths": strategy.get("primary_paths", [])[:12],
            "strong_bridge_roles": strategy.get("strong_bridge_roles", [])[:14],
            "fallback_roles_for_income": strategy.get("fallback_roles_for_income", [])[:8],
            "weak_or_risky_roles": [
                "heavy performance marketing / paid ads",
                "pure SEO specialist",
                "strict independent data roles without training",
                "recruitment / BDR / SDR / cold calling",
                "standalone HR, finance, legal, compliance",
                "IT helpdesk requiring enterprise tooling and 2+ years support",
            ],
            "languages": {
                "english": "fluent/native-level",
                "arabic": "native",
                "dutch": "B1/intermediate; never claim fluent Dutch",
            },
            "work_authorization": "Authorized to work in the Netherlands/EU without sponsorship",
            "commute_base": "Amstelveen; Amsterdam/Amstelveen/Hoofddorp/Schiphol/Haarlem/Weesp are practical; Utrecht/Hilversum/Leiden/The Hague/Rotterdam/Almere need office-day review",
            "portfolio_url": personal.get("portfolio_url", "https://www.omarabdulghani.com"),
            "client_project_experience": self.profile.get("client_project_experience", ""),
            "pphe_internship_detail": self._compact_scoring_text(
                (self.profile.get("work_experience", [{}])[0] or {}).get("description", ""),
                max_length=320,
            ),
            "core_skills": skill_levels.get("core_skills", [])[:14],
            "foundational_exposure": skill_levels.get("basic_foundational_exposure", [])[:8],
            "ai_assisted_tools": [
                tool for tool in self.profile.get("tools", [])
                if tool in {"Cursor", "OpenAI Codex", "Claude Code", "ChatGPT", "GitHub Copilot"}
            ],
            "key_strengths": self._candidate_strength_phrases(),
            "openness": strategy.get(
                "openness",
                "Open to good career-growth opportunities outside the original creative/design comfort zone.",
            ),
        }

    def _build_opportunity_scope_summary(self) -> dict:
        return {
            "primary_goal": "Find realistic opportunities that are good for Omar's future, financially and career-wise.",
            "not_perfect_match_required": True,
            "do_not_limit_to_design_roles": True,
            "favorite_domain_not_required": "The job does not need to be Omar's favorite domain if it is realistic, growth-friendly, and useful.",
            "natural_strength_roles": [
                "UX/UI/product/digital design",
                "brand/creative strategy",
                "digital marketing/content/e-commerce",
                "product/web operations and project coordination",
            ],
            "broad_acceptable_domains": [
                "customer success/support/operations as income or SaaS/business bridge",
                "implementation consulting and business analysis",
                "junior/trainee data, reporting, insights, BI, and analytics",
                "product, e-commerce, web/content, and digital operations",
                "project/operations coordination",
                "procurement/supply-chain trainee or graduate tracks",
                "research assistant / clinical study assistant if no strict medical credential",
            ],
            "positive_signals": [
                "entry/junior/graduate/trainee/associate",
                "junior/coordinator/assistant/trainee manager titles",
                "training/mentorship/open to graduates",
                "transferable communication/analysis/problem-solving",
                "cross-functional digital/business exposure",
                "supportive environment, reputable company, stable pay",
            ],
            "hard_negative_signals": [
                "current student enrollment or thesis internship requirement",
                "5+ years or strict 4+ years required",
                "3+ years when also senior/specialist/domain-heavy/no training path",
                "strict senior/lead/head/director wording",
                "true line management: direct reports/hiring/firing/performance reviews",
                "full P&L ownership or strict prior management experience",
                "mandatory license/credential/specific degree",
                "high Dutch C1/C2/native/professional/excellent",
                "manual/warehouse/cashier/driver/physical work",
            ],
            "do_not_penalize_merely_because": [
                "outside UX/UI/design",
                "business/consulting/ops/marketing/IT",
                "manager title alone",
                "junior project/account/operations/community manager title",
                "soft ownership/stakeholder/planning/strategy/leadership language",
                "moderate Dutch, Dutch preferred, or plain fluent Dutch without Dutch-heavy communication duties",
                "SQL/Python/Power BI/Tableau/dashboard/reporting mentions in junior or training-based data roles",
            ],
            "lower_score_but_not_auto_reject": [
                "recruitment/BDR/outbound sales unless low-pressure, English-friendly, training-based, and stable",
                "heavy performance marketing or pure SEO",
                "fallback customer/admin/support roles unless strong income or bridge value",
                "low-paid internships",
            ],
            "junior_management_rule": "manager/ownership wording is OK unless clear senior evidence appears",
            "score_focus": [
                "realistic interview chance",
                "career-growth value",
                "financial/stability value",
                "learning curve feasibility",
                "clear hard blockers only",
            ],
        }

    def _classify_scoring_heading(self, line: str) -> str:
        normalized = self._normalize_knowledge_text(line).lower().strip(" :.-")
        for heading in self.SCORING_REQUIREMENT_HEADINGS:
            if normalized == heading or normalized.startswith(f"{heading} "):
                return "requirements"
        for heading in self.SCORING_RESPONSIBILITY_HEADINGS:
            if normalized == heading or normalized.startswith(f"{heading} "):
                return "responsibilities"
        for heading in self.SCORING_BOILERPLATE_HEADINGS:
            if normalized == heading or normalized.startswith(f"{heading} "):
                return "boilerplate"
        return ""

    def _prepare_scoring_description_text(self, text: str) -> str:
        prepared = (text or "").replace("\r", "\n")
        prepared = re.sub(r"[•●▪◦·]", "\n", prepared)
        prepared = re.sub(r"\s+\|\s+", "\n", prepared)

        headings = (
            list(self.SCORING_REQUIREMENT_HEADINGS)
            + list(self.SCORING_RESPONSIBILITY_HEADINGS)
            + list(self.SCORING_BOILERPLATE_HEADINGS)
        )
        for heading in sorted(headings, key=len, reverse=True):
            pattern = re.compile(rf"(?i)(?<!\w){re.escape(heading)}(?:\s*:)?")
            prepared = pattern.sub(lambda match: f"\n{match.group(0).strip()}:\n", prepared)

        start_markers = "|".join(re.escape(marker) for marker in self.SCORING_SENTENCE_START_MARKERS)
        prepared = re.sub(
            rf"(?<!^)(?<!\n)\s+(?=(?:{start_markers})\b)",
            "\n",
            prepared,
        )
        prepared = re.sub(r"\n{2,}", "\n", prepared)
        return prepared

    def _split_scoring_description_chunks(self, text: str) -> list[tuple[str, str]]:
        chunks: list[tuple[str, str]] = []
        current_section = ""
        prepared = self._prepare_scoring_description_text(text)
        for raw_line in prepared.splitlines():
            line = self._normalize_knowledge_text(raw_line)
            if not line:
                continue
            heading = self._classify_scoring_heading(line)
            if heading:
                current_section = heading
                continue
            sub_parts = re.split(r"(?<=[.!?])\s+", line)
            if len(sub_parts) == 1 and len(line) > 220:
                sub_parts = re.split(r"\s*[;]\s*|(?<=,)\s+(?=(?:and|or)\s)", line)
            for part in sub_parts:
                normalized = self._normalize_knowledge_text(part)
                if normalized:
                    chunks.append((normalized, current_section))
        return chunks

    def _is_scoring_boilerplate_chunk(self, text: str, section: str = "") -> bool:
        if section == "boilerplate":
            return True
        lowered = self._normalize_knowledge_text(text).lower()
        if any(marker in lowered for marker in self.SCORING_BOILERPLATE_MARKERS):
            return True
        boilerplate_score = sum(
            1
            for marker in ("salary", "benefits", "vacation", "pension", "bonus", "lunch", "gym")
            if marker in lowered
        )
        return boilerplate_score >= 2

    def _extract_required_experience_years(self, text: str) -> str:
        lowered = (text or "").lower()
        patterns = [
            re.compile(r"\b(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*(?:years?|yrs?|jaar)\b", re.I),
            re.compile(r"\b(\d+)\s*\+\s*(?:years?|yrs?|jaar)\b", re.I),
            re.compile(r"\bat least\s+(\d+)\s*(?:years?|yrs?|jaar)\b", re.I),
            re.compile(r"\bminimum(?: of)?\s+(\d+)\s*(?:years?|yrs?|jaar)\b", re.I),
            re.compile(r"\bmin\.?\s*(\d+)\s*(?:years?|yrs?|jaar)\b", re.I),
            re.compile(r"\b(\d+)\s*(?:years?|yrs?|jaar)\s+of\s+(?:relevant\s+)?experience\b", re.I),
            re.compile(r"\b(\d+)\s*(?:years?|yrs?|jaar)\s+experience\b", re.I),
        ]

        for pattern in patterns:
            match = pattern.search(lowered)
            if not match:
                continue
            if len(match.groups()) >= 2 and match.group(2):
                return f"{match.group(1)}-{match.group(2)}"
            return f"{match.group(1)}+"
        return ""

    def _should_keep_scoring_chunk(self, text: str) -> bool:
        normalized = self._normalize_knowledge_text(text)
        if len(normalized.split()) < 4:
            return False
        lowered = normalized.lower()
        if lowered.startswith(
            (
                "and ",
                "or ",
                "with ",
                "without ",
                "that ",
                "this ",
                "which ",
                "isn't ",
                "is not ",
            )
        ):
            return False
        return True

    def _extract_scoring_items(
        self,
        text: str,
        *,
        kind: str,
        max_items: int = 5,
    ) -> list[str]:
        markers = (
            self.SCORING_REQUIREMENT_MARKERS
            if kind == "requirements"
            else self.SCORING_RESPONSIBILITY_MARKERS
        )
        preferred_section = kind
        items: list[str] = []
        seen: set[str] = set()

        for chunk, section in self._split_scoring_description_chunks(text):
            if len(items) >= max_items:
                break
            if self._is_scoring_boilerplate_chunk(chunk, section):
                continue
            if not self._should_keep_scoring_chunk(chunk):
                continue
            lowered = chunk.lower()
            matches_section = section == preferred_section
            matches_marker = any(marker in lowered for marker in markers)
            if kind == "requirements" and self._extract_required_experience_years(chunk):
                matches_marker = True
            if not (matches_section or matches_marker):
                continue
            compact = self._compact_scoring_text(chunk)
            dedupe_key = compact.lower()
            if compact and dedupe_key not in seen:
                seen.add(dedupe_key)
                items.append(compact)

        if items:
            return items[:max_items]

        for chunk, section in self._split_scoring_description_chunks(text):
            if len(items) >= min(3, max_items):
                break
            if self._is_scoring_boilerplate_chunk(chunk, section):
                continue
            if not self._should_keep_scoring_chunk(chunk):
                continue
            lowered = chunk.lower()
            if len(chunk) < 40:
                continue
            if not (
                any(marker in lowered for marker in self.SCORING_REQUIREMENT_MARKERS)
                or any(marker in lowered for marker in self.SCORING_RESPONSIBILITY_MARKERS)
                or self._extract_required_experience_years(chunk)
            ):
                continue
            compact = self._compact_scoring_text(chunk)
            dedupe_key = compact.lower()
            if compact and dedupe_key not in seen:
                seen.add(dedupe_key)
                items.append(compact)

        return items[:max_items]

    def _build_job_scoring_summary(
        self,
        *,
        title: str,
        company: str,
        location: str,
        description: str,
    ) -> dict:
        return {
            "job_title": self._compact_scoring_text(title, max_length=90),
            "company_name": self._compact_scoring_text(company, max_length=60),
            "location": self._compact_scoring_text(location, max_length=60),
            "required_experience_years": self._extract_required_experience_years(description),
            "key_requirements": self._extract_scoring_items(
                description,
                kind="requirements",
                max_items=5,
            ),
            "key_responsibilities": self._extract_scoring_items(
                description,
                kind="responsibilities",
                max_items=5,
            ),
        }

    def _build_cv_scoring_summary(self, cv_excerpt: str) -> list[str]:
        highlights: list[str] = []
        seen: set[str] = set()
        for chunk, _ in self._split_scoring_description_chunks(cv_excerpt):
            lowered = chunk.lower()
            if len(chunk) < 35:
                continue
            if not any(
                marker in lowered
                for marker in (
                    "designed",
                    "developed",
                    "improved",
                    "researched",
                    "prototype",
                    "analytics",
                    "marketing",
                    "branding",
                    "project",
                    "managed",
                    "client",
                    "ux",
                    "ui",
                )
            ):
                continue
            compact = self._compact_scoring_text(chunk, max_length=110)
            dedupe_key = compact.lower()
            if compact and dedupe_key not in seen:
                seen.add(dedupe_key)
                highlights.append(compact)
            if len(highlights) >= 4:
                break
        return highlights

    def _build_scoring_input_payload(
        self,
        *,
        query: str,
        title: str,
        company: str,
        location: str,
        description: str,
        ideal_text: str,
        include_cv: bool,
        cv_excerpt: str,
        prior_assessment: Optional[dict],
        simplified: bool,
    ) -> dict:
        if simplified:
            payload = {
                "candidate_profile": self._build_candidate_scoring_summary(query, ideal_text),
                "opportunity_scope": self._build_opportunity_scope_summary(),
                "scoring_rubric": {
                    "goal": "realistic opportunity quality for Omar's future",
                    "score_dimensions": [
                        "realistic interview chance",
                        "career-growth value",
                        "financial/stability value",
                    ],
                    "entry_level_fit": "0-2 years preferred; 3+ only if realistic and not senior/domain-heavy",
                    "keep_broader_graduate_friendly_roles": True,
                    "do_not_reject_for_non_design_domain_alone": True,
                    "allow_training_based_data_and_bridge_roles": True,
                    "avoid_strict_credentials_or_license_gated_roles": True,
                    "tiers": {
                        "strong_match": "70-100",
                        "possible_match": "50-69",
                        "weak_match": "0-49",
                    },
                },
                "job": self._build_job_scoring_summary(
                    title=title,
                    company=company,
                    location=location,
                    description=description,
                ),
            }
            if prior_assessment:
                payload["prior_assessment"] = prior_assessment
            if include_cv and cv_excerpt:
                cv_summary = self._build_cv_scoring_summary(cv_excerpt)
                if cv_summary:
                    payload["cv_highlights"] = cv_summary
            return payload

        payload = {
            "candidate_profile": self._build_candidate_scoring_summary(query, ideal_text),
            "opportunity_scope": self._build_opportunity_scope_summary(),
            "candidate_context": {
                "candidate_level": "recent_graduate",
                "search_query": query,
            },
            "scoring_rubric": {
                "primary_goal": "realistic opportunity quality for Omar's future",
                "score_dimensions": [
                    "realistic interview chance",
                    "career-growth value",
                    "financial/stability value",
                ],
                "entry_level_fit_matters_most": True,
                "penalize_strict_advanced_experience_without_training": True,
                "accept_broader_graduate_friendly_roles": True,
                "allow_junior_training_based_data_and_bridge_roles": True,
                "avoid_manual_or_license_gated_roles": True,
                "tiers": {
                    "strong_match": "70-100",
                    "possible_match": "50-69",
                    "weak_match": "0-49",
                },
            },
            "perfect_suitable_job_profile": ideal_text[:7000],
            "job": {
                "title": title,
                "company": company,
                "location": location,
                "description": description[:12000],
            },
        }
        if prior_assessment:
            payload["prior_assessment"] = prior_assessment
        if include_cv and cv_excerpt:
            payload["cv_excerpt"] = cv_excerpt[:5000]
        return payload

    def _build_interview_scoring_prompt(
        self,
        *,
        query: str,
        title: str,
        company: str,
        location: str,
        description: str,
        ideal_text: str,
        include_cv: bool,
        cv_excerpt: str,
        prior_assessment: Optional[dict],
        simplified: bool = False,
    ) -> str:
        payload = self._build_scoring_input_payload(
            query=query,
            title=title,
            company=company,
            location=location,
            description=description,
            ideal_text=ideal_text,
            include_cv=include_cv,
            cv_excerpt=cv_excerpt,
            prior_assessment=prior_assessment,
            simplified=simplified,
        )

        if simplified:
            contract_lines = [
                "Return ONLY this JSON:",
                '{"interview_probability_score": <integer 0-100>, "reason": "<one short sentence>"}',
                "Rules:",
                "- No text before JSON",
                "- No text after JSON",
                "- No explanations",
                "- No markdown",
                "- No bullet points",
                "- Must start with { and end with }",
                "- Use opportunity_scope; do not reject only because role is outside UX/UI/design",
                "- Score all three dimensions: realistic interview chance, career-growth value, financial/stability value",
            ]
        else:
            contract_lines = [
                "You are a scoring API.",
                "You MUST return ONLY one valid JSON object.",
                'Output EXACTLY this shape: {"interview_probability_score": <integer 0-100>, "reason": "<one short sentence>"}',
                "The response is invalid unless the first character is { and the last character is }.",
                "No text before JSON.",
                "No text after JSON.",
                "No markdown.",
                "No bullet points.",
                "No analysis.",
                "No step-by-step reasoning.",
                "No explanations outside the reason field.",
                "Use an integer from 0 to 100.",
                "The reason must be exactly one short sentence.",
                "Score realistic opportunity quality for a recent graduate across interview chance, career-growth value, and financial/stability value.",
                "Broader graduate-friendly business, operations, customer success, product/web operations, marketing, consulting, trainee data, and creative roles can be valid.",
                "Customer success/support/operations can be valid as income or a SaaS/business bridge.",
                "Recruitment/BDR/outbound sales should score lower unless clearly low-pressure, English-friendly, training-based, and stable.",
                "Junior data analyst, data traineeship, BI trainee, analytics trainee, reporting analyst, and insights analyst roles should score fairly when junior or training-based.",
                "Plain fluent Dutch is a risk flag, not a hard blocker, unless the role is Dutch-heavy communication, sales, recruitment, HR, legal, compliance, or phone support.",
                "Do not reward jobs that clearly require seniority, hard credentials, licenses, or unrealistic prior experience.",
                "Mention the main concern in the reason when relevant: Dutch, commute, seniority, low pay, freelance/contractor, current student requirement, domain mismatch, heavy technical requirement, sales/cold-calling pressure, or low career alignment.",
            ]

        return "\n".join(contract_lines) + "\n\nINPUT JSON:\n" + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _normalize_lmstudio_base_url(self) -> str:
        base_url = (self.lmstudio_base_url or "").strip().rstrip("/")
        if not base_url:
            return ""
        if base_url.endswith("/v1"):
            return base_url
        return f"{base_url}/v1"

    def _validate_lmstudio_scoring_config(self) -> tuple[str, str, str]:
        base_url = self._normalize_lmstudio_base_url()
        if not base_url:
            raise RuntimeError(
                "LM Studio scoring is enabled but LMSTUDIO_BASE_URL is not set."
            )
        model = (self.lmstudio_model or "").strip()
        if not model:
            raise RuntimeError(
                "LM Studio scoring is enabled but LMSTUDIO_MODEL is not set."
            )
        effort = (self.lmstudio_reasoning_effort or "none").strip().lower()
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "on", "off"}:
            raise RuntimeError(
                "LMSTUDIO_REASONING_EFFORT must be one of: none, minimal, low, medium, high, xhigh, on, off."
            )
        return base_url, model, effort

    def _normalize_lmstudio_message_part(self, value) -> str:
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts).strip()
        return str(value or "").strip()

    def _extract_lmstudio_chat_text(self, payload: dict) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise LMStudioRetryableScoringError(
                "empty_choices",
                "LM Studio returned no choices.",
            )
        message = choices[0].get("message") or {}
        content = self._normalize_lmstudio_message_part(message.get("content", ""))
        if content:
            return content

        reasoning_content = self._normalize_lmstudio_message_part(
            message.get("reasoning_content", "")
        )
        finish_reason = str((choices[0] or {}).get("finish_reason", "") or "").strip().lower()
        if reasoning_content and finish_reason == "length":
            raise LMStudioRetryableScoringError(
                "reasoning_consumed_output_budget",
                "LM Studio returned no assistant content because reasoning_content consumed the output budget (finish_reason=length).",
            )
        if reasoning_content:
            raise LMStudioRetryableScoringError(
                "reasoning_without_content",
                "LM Studio returned reasoning_content but no assistant content.",
            )
        raise LMStudioRetryableScoringError(
            "empty_assistant_message",
            "LM Studio returned an empty assistant message.",
        )

    def _log_scoring_event(self, kind: str, message: str) -> None:
        callback = getattr(self, "scoring_event_logger", None)
        if not callable(callback):
            return
        try:
            callback(kind, message)
        except Exception:
            return

    def _hosted_provider_config(self, backend: str) -> dict:
        normalized = self._normalize_scoring_backend(backend)
        if normalized == "cerebras":
            return {
                "backend": "cerebras",
                "label": "Cerebras",
                "api_key": self.cerebras_api_key,
                "base_url": self.cerebras_base_url,
                "model": self.cerebras_model,
                "max_output_tokens": self.cerebras_max_output_tokens,
                "max_attempts": self.cerebras_max_attempts,
                "openai_compatible": True,
            }
        if normalized == "ollama_cloud":
            return {
                "backend": "ollama_cloud",
                "label": "Ollama Cloud",
                "api_key": self.ollama_api_key,
                "base_url": self.ollama_base_url,
                "model": self.ollama_model,
                "max_output_tokens": self.ollama_max_output_tokens,
                "max_attempts": self.ollama_max_attempts,
                "openai_compatible": False,
            }
        if normalized == "openai_compatible":
            return {
                "backend": "openai_compatible",
                "label": "OpenAI-compatible",
                "api_key": self.openai_compatible_api_key,
                "base_url": self.openai_compatible_base_url,
                "model": self.openai_compatible_model,
                "max_output_tokens": self.openai_compatible_max_output_tokens,
                "max_attempts": self.openai_compatible_max_attempts,
                "openai_compatible": True,
            }
        raise RuntimeError(f"Unsupported hosted AI backend '{backend}'.")

    def _hosted_model_label(self, backend: str) -> str:
        if backend == "gemini":
            model_name = self.gemini_model or "<unset>"
            return f"gemini:{model_name}"
        config = self._hosted_provider_config(backend)
        model_name = config.get("model") or "<unset>"
        return f"{config['backend']}:{model_name}"

    def _validate_hosted_scoring_config(self, backend: str) -> dict:
        config = self._hosted_provider_config(backend)
        if not (config.get("api_key") or "").strip():
            raise RuntimeError(
                f"{config['label']} scoring is enabled but the API key is not set."
            )
        if not (config.get("base_url") or "").strip():
            raise RuntimeError(
                f"{config['label']} scoring is enabled but the base URL is not set."
            )
        if not (config.get("model") or "").strip():
            raise RuntimeError(
                f"{config['label']} scoring is enabled but the model is not set."
            )
        return config

    def _backend_has_minimum_config(self, backend: str) -> bool:
        backend = self._normalize_scoring_backend(backend)
        if backend == "gemini":
            return bool(self.gemini_api_key and self.gemini_model)
        if backend == "claude":
            return bool(os.getenv("ANTHROPIC_API_KEY") and self.model)
        if backend == "lmstudio":
            return bool(self.lmstudio_base_url and self.lmstudio_model)
        if backend in {"cerebras", "ollama_cloud", "openai_compatible"}:
            try:
                config = self._hosted_provider_config(backend)
            except RuntimeError:
                return False
            return bool(config.get("api_key") and config.get("base_url") and config.get("model"))
        return False

    def _configured_auto_backends(self) -> list[str]:
        configured = [
            backend
            for backend in self.ai_backend_order
            if backend != "auto" and self._backend_has_minimum_config(backend)
        ]
        return configured

    def _first_configured_auto_backend(self) -> str:
        configured = self._configured_auto_backends()
        return configured[0] if configured else ""

    def _hosted_scoring_response_format(self) -> dict:
        return self._lmstudio_scoring_response_format()

    def _plain_scoring_json_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "interview_probability_score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
                "reason": {
                    "type": "string",
                },
            },
            "required": ["interview_probability_score", "reason"],
            "additionalProperties": False,
        }

    def _normalize_hosted_base_url(self, base_url: str, *, openai_compatible: bool) -> str:
        normalized = (base_url or "").strip().rstrip("/")
        if not normalized:
            return ""
        if openai_compatible and not normalized.endswith("/v1"):
            return f"{normalized}/v1"
        return normalized

    def _classify_hosted_exception(self, exc: Exception) -> str:
        message = f"{type(exc).__name__}: {exc}".lower()
        if any(marker in message for marker in ("api key", "unauthorized", "unauthenticated", "permission", "401", "403")):
            return "auth_or_permission"
        if any(marker in message for marker in ("429", "quota", "rate", "resource_exhausted", "too many requests", "limit exceeded")):
            return "rate_limit"
        if any(marker in message for marker in ("invalid_request", "invalid request", "bad request", "400")):
            return "invalid_request"
        if any(marker in message for marker in ("500", "502", "503", "504", "deadline", "timeout", "unavailable", "temporarily")):
            return "transient_api_error"
        return "api_error"

    def _hosted_retry_delay_seconds(self, next_attempt: int) -> int:
        initial_delay = max(1, int(self.HOSTED_SCORING_INITIAL_RETRY_DELAY_SECONDS))
        max_delay = max(initial_delay, int(self.HOSTED_SCORING_MAX_RETRY_DELAY_SECONDS))
        exponent = max(0, int(next_attempt) - 2)
        delay = initial_delay * (2 ** exponent)
        return min(max_delay, delay)

    def _extract_openai_compatible_chat_text(self, payload: dict, *, label: str) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise HostedProviderRetryableScoringError(
                "empty_choices",
                f"{label} returned no choices.",
            )
        message = choices[0].get("message") or {}
        content = self._normalize_lmstudio_message_part(message.get("content", ""))
        if content:
            return content
        raise HostedProviderRetryableScoringError(
            "empty_assistant_message",
            f"{label} returned an empty assistant message.",
        )

    def _log_hosted_request_settings_once(self, backend: str, *, max_tokens: int) -> None:
        if backend in self._hosted_request_settings_logged:
            return
        config = self._hosted_provider_config(backend)
        self._log_scoring_event(
            "config",
            (
                f"{config['label']} request config | "
                f"backend={config['backend']} model={config['model']} "
                f"max_output_tokens={int(max_tokens or 0)}"
            ),
        )
        self._hosted_request_settings_logged.add(backend)

    def _hosted_request_headers(self, api_key: str) -> dict:
        # Some hosted APIs sit behind WAF rules that reject Python's default urllib
        # user-agent before the request reaches the provider API.
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "job-agent/1.0",
        }

    def _openai_compatible_chat_completion(
        self,
        *,
        backend: str,
        prompt: str,
        max_tokens: int,
    ) -> tuple[str, str]:
        config = self._validate_hosted_scoring_config(backend)
        base_url = self._normalize_hosted_base_url(
            config["base_url"],
            openai_compatible=True,
        )
        self._log_hosted_request_settings_once(config["backend"], max_tokens=max_tokens)
        payload = {
            "model": config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "response_format": self._hosted_scoring_response_format(),
        }
        request = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._hosted_request_headers(config["api_key"]),
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = (
                f"{config['label']} chat completion failed with HTTP {exc.code}: "
                f"{body.strip() or exc.reason}"
            )
            kind = self._classify_hosted_exception(RuntimeError(message))
            if kind in {"rate_limit", "transient_api_error", "api_error"}:
                raise HostedProviderRetryableScoringError(kind, message) from exc
            raise RuntimeError(message) from exc
        except URLError as exc:
            raise HostedProviderRetryableScoringError(
                "unreachable",
                f"{config['label']} is not reachable at {base_url}: {exc.reason}",
            ) from exc

        try:
            response_payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HostedProviderRetryableScoringError(
                "invalid_response_json",
                f"{config['label']} chat completion returned invalid JSON.",
            ) from exc

        if response_payload.get("error"):
            error = response_payload.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            kind = self._classify_hosted_exception(RuntimeError(str(message)))
            raise HostedProviderRetryableScoringError(
                kind,
                f"{config['label']} returned an error: {message}",
            )

        self._update_scoring_audit_usage(response_payload.get("usage"))
        text = self._extract_openai_compatible_chat_text(
            response_payload,
            label=config["label"],
        )
        return text, self._hosted_model_label(config["backend"])

    def _extract_ollama_chat_text(self, payload: dict) -> str:
        message = payload.get("message") or {}
        content = self._normalize_lmstudio_message_part(message.get("content", ""))
        if content:
            return content
        raise HostedProviderRetryableScoringError(
            "empty_assistant_message",
            "Ollama Cloud returned an empty assistant message.",
        )

    def _ollama_cloud_chat_completion(
        self,
        *,
        prompt: str,
        max_tokens: int,
    ) -> tuple[str, str]:
        config = self._validate_hosted_scoring_config("ollama_cloud")
        base_url = self._normalize_hosted_base_url(
            config["base_url"],
            openai_compatible=False,
        )
        self._log_hosted_request_settings_once("ollama_cloud", max_tokens=max_tokens)
        payload = {
            "model": config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
            },
        }
        if self.ollama_structured_outputs:
            # Ollama Cloud currently documents structured outputs as unsupported.
            # Keep schema mode opt-in so local Ollama or future Cloud support can use it.
            payload["format"] = self._plain_scoring_json_schema()
        request = Request(
            f"{base_url}/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._hosted_request_headers(config["api_key"]),
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = (
                f"Ollama Cloud chat failed with HTTP {exc.code}: "
                f"{body.strip() or exc.reason}"
            )
            kind = self._classify_hosted_exception(RuntimeError(message))
            if kind in {"rate_limit", "transient_api_error", "api_error"}:
                raise HostedProviderRetryableScoringError(kind, message) from exc
            raise RuntimeError(message) from exc
        except URLError as exc:
            raise HostedProviderRetryableScoringError(
                "unreachable",
                f"Ollama Cloud is not reachable at {base_url}: {exc.reason}",
            ) from exc

        try:
            response_payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HostedProviderRetryableScoringError(
                "invalid_response_json",
                "Ollama Cloud chat returned invalid JSON.",
            ) from exc

        if response_payload.get("error"):
            message = response_payload.get("error")
            kind = self._classify_hosted_exception(RuntimeError(str(message)))
            raise HostedProviderRetryableScoringError(
                kind,
                f"Ollama Cloud returned an error: {message}",
            )

        self._update_scoring_audit_usage(
            {
                "prompt_tokens": response_payload.get("prompt_eval_count"),
                "completion_tokens": response_payload.get("eval_count"),
                "total_duration": response_payload.get("total_duration"),
            }
        )
        return self._extract_ollama_chat_text(response_payload), self._hosted_model_label("ollama_cloud")

    def _request_hosted_scoring_response_with_retries(
        self,
        *,
        backend: str,
        prompt: str,
    ) -> tuple[dict, str]:
        config = self._validate_hosted_scoring_config(backend)
        max_tokens = int(config.get("max_output_tokens") or self.HOSTED_SCORING_MAX_OUTPUT_TOKENS)
        max_attempts = max(1, int(config.get("max_attempts") or 1))
        attempt = 1
        model_label = self._hosted_model_label(config["backend"])
        while True:
            try:
                if config["backend"] == "ollama_cloud":
                    raw, model_label = self._ollama_cloud_chat_completion(
                        prompt=prompt,
                        max_tokens=max_tokens,
                    )
                else:
                    raw, model_label = self._openai_compatible_chat_completion(
                        backend=config["backend"],
                        prompt=prompt,
                        max_tokens=max_tokens,
                    )
                parsed = self._parse_scoring_payload(raw, backend=config["backend"])
                return parsed, model_label
            except HostedProviderRetryableScoringError as exc:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"{config['label']} scoring could not complete after {max_attempts} attempts: {str(exc).strip()}"
                    ) from exc
                next_attempt = attempt + 1
                delay_seconds = self._hosted_retry_delay_seconds(next_attempt)
                self._log_scoring_event(
                    "retry",
                    (
                        f"{config['label']} retry {next_attempt} | waiting {delay_seconds}s | "
                        f"cause={exc.kind} | backend={config['backend']} model={config['model']}"
                    ),
                )
                time.sleep(delay_seconds)
                attempt = next_attempt

    def _request_backend_scoring_response(self, backend: str, *, prompt: str) -> tuple[dict, str]:
        backend = self._normalize_scoring_backend(backend)
        if backend == "gemini":
            return self._request_gemini_scoring_response_with_retries(
                prompt=prompt,
                max_tokens=self.gemini_max_output_tokens,
            )
        if backend in {"cerebras", "ollama_cloud", "openai_compatible"}:
            return self._request_hosted_scoring_response_with_retries(
                backend=backend,
                prompt=prompt,
            )
        if backend == "lmstudio":
            parsed, model_label = self._request_lmstudio_scoring_response_with_retries(
                prompt=prompt,
                fallback_prompt=None,
                prompt_label="rich_prompt",
                fallback_prompt_label="rich_prompt",
                max_tokens=self._lmstudio_scoring_max_tokens(self.LMSTUDIO_SCORING_BASE_MAX_TOKENS),
            )
            return parsed, model_label
        raise RuntimeError(f"Unsupported auto AI backend '{backend}'.")

    def _request_auto_scoring_response(self, *, prompt: str) -> tuple[dict, str]:
        backends = self._configured_auto_backends()
        if not backends:
            raise RuntimeError(
                "AI_BACKEND=auto but no configured providers were found. Add CEREBRAS_API_KEY, OLLAMA_API_KEY, or GEMINI_API_KEY."
            )

        errors: list[str] = []
        for index, backend in enumerate(backends):
            try:
                if index > 0:
                    self._log_scoring_event(
                        "fallback",
                        f"Trying fallback AI backend: {self._hosted_model_label(backend)}",
                    )
                return self._request_backend_scoring_response(backend, prompt=prompt)
            except Exception as exc:
                message = str(exc).strip()
                errors.append(f"{self._hosted_model_label(backend)}: {message}")
                if index < len(backends) - 1:
                    self._log_scoring_event(
                        "fallback",
                        (
                            f"{self._hosted_model_label(backend)} failed; "
                            f"falling back to {self._hosted_model_label(backends[index + 1])}"
                        ),
                    )
                    continue
                break

        raise RuntimeError("All configured AI providers failed: " + " | ".join(errors))

    def _validate_gemini_scoring_config(self) -> tuple[str, str]:
        api_key = (self.gemini_api_key or "").strip()
        if not api_key:
            raise RuntimeError(
                "Gemini scoring is enabled but GEMINI_API_KEY is not set. Add it to .env before scouting."
            )
        model = (self.gemini_model or "").strip()
        if not model:
            raise RuntimeError(
                "Gemini scoring is enabled but GEMINI_MODEL is not set."
            )
        return api_key, model

    def _get_gemini_client(self):
        if self.gemini_client is None:
            api_key, _ = self._validate_gemini_scoring_config()
            try:
                from google import genai
            except ImportError as exc:
                raise RuntimeError(
                    "Gemini scoring requires the google-genai package. Run: pip install -r requirements.txt"
                ) from exc
            self.gemini_client = genai.Client(api_key=api_key)
        return self.gemini_client

    def _gemini_scoring_response_schema(self) -> dict:
        # Gemini structured output uses a plain JSON schema for the scorer contract.
        return {
            "type": "object",
            "properties": {
                "interview_probability_score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
                "reason": {
                    "type": "string",
                },
            },
            "required": ["interview_probability_score", "reason"],
        }

    def _gemini_request_config(self, *, max_tokens: int) -> dict:
        config = {
            "response_mime_type": "application/json",
            "response_schema": self._gemini_scoring_response_schema(),
            "max_output_tokens": max(64, int(max_tokens or self.gemini_max_output_tokens)),
        }
        if self.gemini_thinking_budget is not None:
            config["thinking_config"] = {
                "thinking_budget": int(self.gemini_thinking_budget)
            }
        return config

    def _log_gemini_request_settings_once(self, *, max_tokens: int) -> None:
        if self._gemini_request_settings_logged:
            return
        thinking_budget = (
            str(self.gemini_thinking_budget)
            if self.gemini_thinking_budget is not None
            else "omitted"
        )
        self._log_scoring_event(
            "config",
            (
                "Gemini request config | "
                f"backend=gemini model={self.gemini_model} "
                f"thinking_budget={thinking_budget} "
                f"max_output_tokens={int(max_tokens or 0)}"
            ),
        )
        self._gemini_request_settings_logged = True

    def _gemini_usage_to_dict(self, response) -> dict:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None and isinstance(response, dict):
            metadata = response.get("usage_metadata")
        if metadata is None:
            return {}

        if isinstance(metadata, dict):
            raw = dict(metadata)
        elif hasattr(metadata, "model_dump") and callable(metadata.model_dump):
            raw = metadata.model_dump()
        elif hasattr(metadata, "to_json_dict") and callable(metadata.to_json_dict):
            raw = metadata.to_json_dict()
        else:
            raw = {}
            for key in (
                "prompt_token_count",
                "candidates_token_count",
                "thoughts_token_count",
                "total_token_count",
            ):
                value = getattr(metadata, key, None)
                if value is not None:
                    raw[key] = value

        usage = {key: value for key, value in raw.items() if value is not None}
        prompt_tokens = usage.get("prompt_token_count")
        completion_tokens = usage.get("candidates_token_count")
        if prompt_tokens is not None:
            usage["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            usage["completion_tokens"] = completion_tokens
        return usage

    def _extract_gemini_response_text(self, response) -> str:
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False)
            if hasattr(parsed, "model_dump") and callable(parsed.model_dump):
                return json.dumps(parsed.model_dump(), ensure_ascii=False)
            if not isinstance(parsed, str):
                return json.dumps(parsed, ensure_ascii=False)

        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        if isinstance(response, dict):
            dict_text = response.get("text")
            if isinstance(dict_text, str) and dict_text.strip():
                return dict_text.strip()

        parts_text: list[str] = []
        candidates = getattr(response, "candidates", None)
        if candidates is None and isinstance(response, dict):
            candidates = response.get("candidates")
        for candidate in candidates or []:
            content = getattr(candidate, "content", None)
            if content is None and isinstance(candidate, dict):
                content = candidate.get("content")
            parts = getattr(content, "parts", None)
            if parts is None and isinstance(content, dict):
                parts = content.get("parts")
            for part in parts or []:
                part_text = getattr(part, "text", None)
                if part_text is None and isinstance(part, dict):
                    part_text = part.get("text")
                if isinstance(part_text, str) and part_text.strip():
                    parts_text.append(part_text.strip())
        if parts_text:
            return "\n".join(parts_text).strip()

        raise GeminiRetryableScoringError(
            "empty_response",
            "Gemini returned no usable text for the scoring response.",
        )

    def _classify_gemini_exception(self, exc: Exception) -> str:
        message = f"{type(exc).__name__}: {exc}".lower()
        if any(marker in message for marker in ("api key", "unauthenticated", "permission", "401", "403")):
            return "auth_or_permission"
        if any(marker in message for marker in ("invalid_argument", "invalid argument", "400")):
            return "invalid_request"
        if any(marker in message for marker in ("429", "quota", "rate", "resource_exhausted")):
            return "rate_limit"
        if any(marker in message for marker in ("500", "502", "503", "504", "deadline", "timeout", "unavailable", "temporarily")):
            return "transient_api_error"
        return "api_error"

    def _gemini_retry_delay_seconds(self, next_attempt: int) -> int:
        initial_delay = max(1, int(self.gemini_initial_retry_delay_seconds))
        max_delay = max(initial_delay, int(self.gemini_max_retry_delay_seconds))
        exponent = max(0, int(next_attempt) - 2)
        delay = initial_delay * (2 ** exponent)
        return min(max_delay, delay)

    def _gemini_generate_content(self, *, prompt: str, max_tokens: int) -> tuple[str, str]:
        _, model = self._validate_gemini_scoring_config()
        self._log_gemini_request_settings_once(max_tokens=max_tokens)
        config = self._gemini_request_config(max_tokens=max_tokens)
        try:
            response = self._get_gemini_client().models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            kind = self._classify_gemini_exception(exc)
            message = f"Gemini generate_content failed ({kind}): {str(exc).strip()}"
            if kind in {"rate_limit", "transient_api_error", "api_error"}:
                raise GeminiRetryableScoringError(kind, message) from exc
            raise RuntimeError(message) from exc

        self._update_scoring_audit_usage(self._gemini_usage_to_dict(response))
        return self._extract_gemini_response_text(response), f"gemini:{model}"

    def _request_gemini_scoring_response_with_retries(
        self,
        *,
        prompt: str,
        max_tokens: int,
    ) -> tuple[dict, str]:
        model_label = self.scoring_model_label
        attempt = 1
        max_attempts = max(1, int(self.gemini_max_attempts or 1))
        while True:
            try:
                raw, model_label = self._gemini_generate_content(
                    prompt=prompt,
                    max_tokens=max_tokens,
                )
                parsed = self._parse_scoring_payload(raw, backend="gemini")
                return parsed, model_label
            except GeminiRetryableScoringError as exc:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"Gemini scoring could not complete after {max_attempts} attempts: {str(exc).strip()}"
                    ) from exc
                next_attempt = attempt + 1
                delay_seconds = self._gemini_retry_delay_seconds(next_attempt)
                self._log_scoring_event(
                    "retry",
                    (
                        f"Gemini retry {next_attempt} | waiting {delay_seconds}s | "
                        f"cause={exc.kind} | backend=gemini model={self.gemini_model}"
                    ),
                )
                time.sleep(delay_seconds)
                attempt = next_attempt

    def _lmstudio_list_models(self) -> dict:
        base_url, _, _ = self._validate_lmstudio_scoring_config()
        request = Request(
            f"{base_url}/models",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"LM Studio model listing failed with HTTP {exc.code}: {body.strip() or exc.reason}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"LM Studio is not reachable at {base_url}: {exc.reason}"
            ) from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "LM Studio /v1/models returned invalid JSON."
            ) from exc

    def _lmstudio_api_models(self) -> dict:
        if self._lmstudio_api_models_cache is not None:
            return self._lmstudio_api_models_cache

        base_url, _, _ = self._validate_lmstudio_scoring_config()
        api_base_url = re.sub(r"/v1$", "/api/v1", base_url)
        request = Request(
            f"{api_base_url}/models",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
        except Exception:
            self._lmstudio_api_models_cache = {}
            return self._lmstudio_api_models_cache

        try:
            self._lmstudio_api_models_cache = json.loads(body)
        except json.JSONDecodeError:
            self._lmstudio_api_models_cache = {}
        return self._lmstudio_api_models_cache

    def _lmstudio_reasoning_capabilities(self) -> dict:
        payload = self._lmstudio_api_models() or {}
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return {}
        target = (self.lmstudio_model or "").strip().lower()
        for model in models:
            if not isinstance(model, dict):
                continue
            key = str(model.get("key", "") or "").strip().lower()
            if key != target:
                continue
            capabilities = model.get("capabilities", {}) or {}
            reasoning = capabilities.get("reasoning", {}) or {}
            return reasoning if isinstance(reasoning, dict) else {}
        return {}

    def _lmstudio_resolved_reasoning_config(self) -> dict:
        reasoning = self._lmstudio_reasoning_capabilities()
        allowed_options = [
            str(value or "").strip().lower()
            for value in (reasoning.get("allowed_options") or [])
            if str(value or "").strip()
        ]
        allowed_set = set(allowed_options)
        requested_effort = (self.lmstudio_reasoning_effort or "none").strip().lower()

        if not self.lmstudio_reasoning_enabled:
            return {
                "reasoning_enabled": False,
                "payload_reasoning_effort": "none",
                "allowed_options": allowed_options,
            }

        granular_options = {"minimal", "low", "medium", "high", "xhigh"}
        if allowed_set.intersection(granular_options):
            if requested_effort in {"off", "none"}:
                return {
                    "reasoning_enabled": False,
                    "payload_reasoning_effort": "none",
                    "allowed_options": allowed_options,
                }
            if requested_effort in allowed_set:
                chosen_effort = requested_effort
            else:
                chosen_effort = (
                    next((value for value in allowed_options if value in granular_options), "low")
                )
            return {
                "reasoning_enabled": True,
                "payload_reasoning_effort": chosen_effort,
                "allowed_options": allowed_options,
            }

        if allowed_set and allowed_set.issubset({"off", "on"}):
            return {
                "reasoning_enabled": True,
                "payload_reasoning_effort": None,
                "allowed_options": allowed_options,
            }

        if requested_effort in {"off", "none"}:
            return {
                "reasoning_enabled": False,
                "payload_reasoning_effort": "none",
                "allowed_options": allowed_options,
            }
        return {
            "reasoning_enabled": True,
            "payload_reasoning_effort": requested_effort if requested_effort not in {"on", "off"} else None,
            "allowed_options": allowed_options,
        }

    def _lmstudio_scoring_max_tokens(self, base_tokens: int) -> int:
        config = self._lmstudio_resolved_reasoning_config()
        if config.get("reasoning_enabled"):
            return max(int(base_tokens or 0), int(self.LMSTUDIO_SCORING_REASONING_MAX_TOKENS))
        return max(int(base_tokens or 0), int(self.LMSTUDIO_SCORING_BASE_MAX_TOKENS))

    def _log_lmstudio_request_settings_once(self, *, max_tokens: int) -> None:
        if self._lmstudio_request_settings_logged:
            return

        config = self._lmstudio_resolved_reasoning_config()
        payload_reasoning_effort = config.get("payload_reasoning_effort")
        reasoning_param = payload_reasoning_effort or "omitted"
        if reasoning_param == "omitted" and config.get("reasoning_enabled"):
            reasoning_param = "omitted(model_default)"

        self._log_scoring_event(
            "config",
            (
                "LM Studio request config | "
                f"backend=lmstudio model={self.lmstudio_model} "
                f"reasoning_enabled={str(bool(config.get('reasoning_enabled'))).lower()} "
                f"reasoning_param={reasoning_param} "
                f"max_tokens={int(max_tokens or 0)}"
            ),
        )
        self._lmstudio_request_settings_logged = True

    def _lmstudio_scoring_response_format(self) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "interview_probability_score",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "interview_probability_score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                        },
                        "reason": {
                            "type": "string",
                        },
                    },
                    "required": ["interview_probability_score", "reason"],
                    "additionalProperties": False,
                },
            },
        }

    def _lmstudio_chat_completion(
        self,
        *,
        prompt: str,
        max_tokens: int,
    ) -> tuple[str, str]:
        base_url, model, effort = self._validate_lmstudio_scoring_config()
        reasoning_config = self._lmstudio_resolved_reasoning_config()
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": self._lmstudio_scoring_response_format(),
        }
        payload_reasoning_effort = reasoning_config.get("payload_reasoning_effort")
        if payload_reasoning_effort:
            payload["reasoning_effort"] = payload_reasoning_effort
        request = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LMStudioRetryableScoringError(
                "http_error",
                f"LM Studio chat completion failed with HTTP {exc.code}: {body.strip() or exc.reason}"
            ) from exc
        except URLError as exc:
            raise LMStudioRetryableScoringError(
                "unreachable",
                f"LM Studio is not reachable at {base_url}: {exc.reason}"
            ) from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LMStudioRetryableScoringError(
                "invalid_response_json",
                "LM Studio chat completion returned invalid JSON."
            ) from exc

        if payload.get("error"):
            error = payload.get("error") or {}
            message = error.get("message") or str(error)
            raise LMStudioRetryableScoringError(
                "endpoint_error",
                f"LM Studio returned an error: {message}",
            )

        self._update_scoring_audit_usage(payload.get("usage"))
        text = self._extract_lmstudio_chat_text(payload)
        return text, f"lmstudio:{model}"

    def _lmstudio_retry_delay_seconds(self, next_attempt: int) -> int:
        initial_delay = max(1, int(self.LMSTUDIO_SCORING_INITIAL_RETRY_DELAY_SECONDS))
        max_delay = max(initial_delay, int(self.LMSTUDIO_SCORING_MAX_RETRY_DELAY_SECONDS))
        exponent = max(0, int(next_attempt) - 2)
        delay = initial_delay * (2 ** exponent)
        return min(max_delay, delay)

    def _parse_scoring_payload(self, raw: str, *, backend: str) -> dict:
        backend = self._normalize_scoring_backend(backend)
        structured_backends = {"lmstudio", "gemini", "cerebras", "ollama_cloud", "openai_compatible"}
        try:
            parsed = self._parse_json_object(
                raw,
                required_keys=("interview_probability_score", "reason"),
            )
        except json.JSONDecodeError as exc:
            if backend == "lmstudio":
                raise LMStudioRetryableScoringError(
                    "json_parse_failure",
                    "LM Studio returned a completion that could not be parsed as JSON.",
                ) from exc
            if backend == "gemini":
                raise GeminiRetryableScoringError(
                    "json_parse_failure",
                    "Gemini returned a completion that could not be parsed as JSON.",
                ) from exc
            if backend in {"cerebras", "ollama_cloud", "openai_compatible"}:
                label = self._hosted_provider_config(backend)["label"]
                raise HostedProviderRetryableScoringError(
                    "json_parse_failure",
                    f"{label} returned a completion that could not be parsed as JSON.",
                ) from exc
            raise

        if backend in structured_backends:
            if not isinstance(parsed, dict):
                error_cls = {
                    "lmstudio": LMStudioRetryableScoringError,
                    "gemini": GeminiRetryableScoringError,
                }.get(backend, HostedProviderRetryableScoringError)
                backend_label = {
                    "lmstudio": "LM Studio",
                    "gemini": "Gemini",
                }.get(backend, self._hosted_provider_config(backend)["label"])
                raise error_cls(
                    "json_parse_failure",
                    f"{backend_label} returned a non-object JSON payload.",
                )
            missing_keys = [
                key
                for key in ("interview_probability_score", "reason")
                if key not in parsed
            ]
            if missing_keys:
                error_cls = {
                    "lmstudio": LMStudioRetryableScoringError,
                    "gemini": GeminiRetryableScoringError,
                }.get(backend, HostedProviderRetryableScoringError)
                backend_label = {
                    "lmstudio": "LM Studio",
                    "gemini": "Gemini",
                }.get(backend, self._hosted_provider_config(backend)["label"])
                raise error_cls(
                    "json_parse_failure",
                    f"{backend_label} returned JSON missing required keys: "
                    + ", ".join(missing_keys),
                )
        return parsed

    def _request_lmstudio_scoring_response_with_retries(
        self,
        *,
        prompt: str,
        fallback_prompt: str | None = None,
        prompt_label: str = "primary_prompt",
        fallback_prompt_label: str = "simplified_json_contract",
        max_tokens: int,
    ) -> tuple[dict, str]:
        model_label = self.scoring_model_label
        self._log_lmstudio_request_settings_once(max_tokens=max_tokens)
        attempt = 1
        current_prompt = prompt
        current_prompt_label = prompt_label
        while True:
            try:
                raw, model_label = self._lmstudio_chat_completion(
                    prompt=current_prompt,
                    max_tokens=max_tokens,
                )
                parsed = self._parse_scoring_payload(raw, backend="lmstudio")
                return parsed, model_label
            except LMStudioRetryableScoringError as exc:
                if (
                    exc.kind == "json_parse_failure"
                    and fallback_prompt
                    and current_prompt != fallback_prompt
                ):
                    current_prompt = fallback_prompt
                    current_prompt_label = fallback_prompt_label
                next_attempt = attempt + 1
                delay_seconds = self._lmstudio_retry_delay_seconds(next_attempt)
                self._log_scoring_event(
                    "retry",
                    (
                        f"Gemma retry {next_attempt} | waiting {delay_seconds}s | "
                        f"cause={exc.kind} | prompt={current_prompt_label} | "
                        f"backend=lmstudio model={self.lmstudio_model}"
                    ),
                )
                time.sleep(delay_seconds)
                attempt = next_attempt

    def _request_scoring_response(self, prompt: str, max_tokens: int) -> tuple[str, str]:
        backend = self._normalize_scoring_backend(self.scoring_backend or "claude")
        if backend == "claude":
            response = self._get_client().messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip(), self.model
        if backend == "lmstudio":
            return self._lmstudio_chat_completion(prompt=prompt, max_tokens=max_tokens)
        if backend == "gemini":
            return self._gemini_generate_content(prompt=prompt, max_tokens=max_tokens)
        if backend in {"cerebras", "ollama_cloud", "openai_compatible"}:
            parsed, model_label = self._request_hosted_scoring_response_with_retries(
                backend=backend,
                prompt=prompt,
            )
            return json.dumps(parsed, ensure_ascii=False), model_label
        raise RuntimeError(
            f"Unsupported AI_BACKEND '{self.scoring_backend}'. Use 'auto', 'cerebras', 'ollama_cloud', 'openai_compatible', 'gemini', 'claude', or 'lmstudio'."
        )

    def _get_client(self):
        if self.client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Add it to .env before applying."
                )
            self.client = anthropic.Anthropic(api_key=api_key)
        return self.client

    def _load_learned_answers(self) -> dict:
        try:
            if self.LEARNED_ANSWERS_PATH.exists():
                return json.loads(self.LEARNED_ANSWERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_learned_answer(self, question: str, answer: str):
        normalized = self._normalize_question_key(question)
        cleaned_answer = self._normalize_learned_answer(question, answer)
        if not normalized or not cleaned_answer:
            return
        self.learned_answers[normalized] = cleaned_answer
        self.LEARNED_ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.LEARNED_ANSWERS_PATH.write_text(
            json.dumps(self.learned_answers, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _normalize_question_key(self, question: str) -> str:
        normalized = re.sub(r"\s+", " ", (question or "").strip().lower())
        return re.sub(r"[^a-z0-9 ?/+-]", "", normalized)

    def _expects_numeric_answer(self, question_lower: str) -> bool:
        lowered = (question_lower or "").lower()
        return self._is_years_experience_question(lowered) or any(
            token in lowered
            for token in [
                "average deal size",
                "deal size",
                "eur",
                "euro",
                "revenue",
                "quota",
                "pipeline",
                "amount",
                "budget",
                "how many",
                "how much",
                "hoeveel",
                "number of",
                "decimal number",
            ]
        )

    def _looks_like_decimal_metric_question(self, question_lower: str) -> bool:
        lowered = (question_lower or "").lower()
        return any(
            token in lowered
            for token in [
                "average deal size",
                "deal size",
                "eur",
                "euro",
                "revenue",
                "quota",
                "pipeline",
                "amount",
                "budget",
                "decimal",
                "thousands",
            ]
        )

    def _normalize_learned_answer(self, question: str, answer: str) -> str:
        normalized = (answer or "").strip()
        if not normalized:
            return ""

        question_lower = (question or "").lower()
        answer_lower = normalized.lower()

        if self._expects_numeric_answer(question_lower):
            if self._looks_like_decimal_metric_question(question_lower) and any(
                token in answer_lower
                for token in [
                    "not applicable",
                    "cannot provide",
                    "can't provide",
                    "does not apply",
                    "doesn't apply",
                    "unknown",
                ]
            ):
                return ""
            if any(token in answer_lower for token in ["none", "no direct experience", "no relevant experience"]):
                return "0"
            match = re.search(r"\d+(?:[.,]\d+)?", answer_lower)
            if match:
                try:
                    value = float(match.group(0).replace(",", "."))
                    if self._looks_like_decimal_metric_question(question_lower):
                        if value <= 1.0:
                            return ""
                        return str(value if value % 1 else int(value))
                    return str(max(0, int(value)))
                except ValueError:
                    return ""
            return ""

        if any(token in question_lower for token in [" are you ", " do you ", " have you ", " will you ", " comfortable "]):
            if answer_lower.startswith(("yes", "ja", "yep", "affirmative")):
                return "Yes"
            if answer_lower.startswith(("no", "nee", "nope", "negative")):
                return "No"

        return normalized

    def _build_profile_knowledge(self) -> dict:
        return {
            "cv_excerpt": self._extract_cv_excerpt(),
            "portfolio_excerpt": self._load_portfolio_excerpt(),
        }

    def _extract_cv_excerpt(self) -> str:
        cv_path = (self.profile.get("cv_path") or "").strip()
        if not cv_path:
            return ""

        path = Path(cv_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return ""

        try:
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""

        return self._normalize_knowledge_text(text)[:5000]

    def _load_portfolio_excerpt(self) -> str:
        local_notes = self._load_local_portfolio_notes()
        if local_notes:
            return local_notes[:5000]

        portfolio_url = (
            self.profile.get("personal", {}).get("portfolio_url")
            or ""
        ).strip()
        if not portfolio_url:
            return ""

        texts = []
        seen = set()
        for candidate_url in self._portfolio_candidate_urls(portfolio_url):
            fetched = self._fetch_url_text(candidate_url)
            normalized = self._normalize_knowledge_text(fetched)
            if len(normalized) < 120:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            texts.append(normalized)

        return "\n\n".join(texts)[:5000]

    def _load_local_portfolio_notes(self) -> str:
        try:
            if self.PORTFOLIO_NOTES_PATH.exists():
                return self._normalize_knowledge_text(
                    self.PORTFOLIO_NOTES_PATH.read_text(encoding="utf-8")
                )
        except Exception:
            return ""
        return ""

    def _portfolio_candidate_urls(self, base_url: str) -> list[str]:
        base = base_url.rstrip("/")
        return [
            base,
            urljoin(f"{base}/", "projects-overview"),
            urljoin(f"{base}/", "contact"),
            urljoin(f"{base}/", "projects"),
        ]

    def _fetch_url_text(self, url: str) -> str:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urlopen(request, timeout=10).read().decode("utf-8", "ignore")
        except (URLError, TimeoutError, ValueError):
            return ""
        except Exception:
            return ""

        html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        return text

    def _normalize_knowledge_text(self, text: str) -> str:
        normalized = (text or "").replace("\x00", " ")
        normalized = re.sub(
            r"(?<!\w)(?:[A-Za-z]\s+){3,}[A-Za-z](?!\w)",
            lambda match: match.group(0).replace(" ", ""),
            normalized,
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _knowledge_prompt_block(self) -> str:
        sections = []
        cv_excerpt = (self.profile_knowledge.get("cv_excerpt") or "").strip()
        if cv_excerpt:
            sections.append(f"CV PDF excerpt:\n{cv_excerpt[:3500]}")

        portfolio_excerpt = (self.profile_knowledge.get("portfolio_excerpt") or "").strip()
        if portfolio_excerpt:
            sections.append(f"Portfolio / website excerpt:\n{portfolio_excerpt[:3000]}")

        return "\n\n".join(sections) if sections else "No additional knowledge loaded."

    def get_structured_question_answer(self, question: str, context: str = "") -> Optional[str]:
        """Return a deterministic answer from the saved profile when possible."""
        question_text = (question or "").strip()
        question_lower = question_text.lower()
        combined_context = f"{question_text}\n{context or ''}".lower()

        personal = self.profile.get("personal", {})
        location = personal.get("location", {})
        salary = self.profile.get("salary", {})
        availability = self.profile.get("availability", {})
        work_auth = self.profile.get("work_authorization", {})
        common = self.profile.get("common_questions", {})
        answers = self.profile.get("application_answers", {})
        years_map = {
            (key or "").lower(): value
            for key, value in answers.get("experience_years", {}).items()
        }

        if not question_lower:
            return None

        language_answer = self._language_screening_answer(question_lower, combined_context)
        if language_answer is not None:
            return language_answer

        learned_key = self._normalize_question_key(question_text)
        learned_answer = self.learned_answers.get(learned_key)
        if learned_answer:
            normalized_learned = self._normalize_learned_answer(question_text, learned_answer)
            if normalized_learned:
                if normalized_learned != learned_answer:
                    self.learned_answers[learned_key] = normalized_learned
                    self.LEARNED_ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
                    self.LEARNED_ANSWERS_PATH.write_text(
                        json.dumps(self.learned_answers, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                return normalized_learned
            del self.learned_answers[learned_key]
            self.LEARNED_ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.LEARNED_ANSWERS_PATH.write_text(
                json.dumps(self.learned_answers, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        if self._is_consent_question(question_lower, combined_context):
            return "Yes"

        if self._matches_any(question_lower, ["sponsorship", "sponsor", "visa sponsorship"]):
            requires = answers.get(
                "requires_sponsorship",
                work_auth.get("requires_sponsorship"),
            )
            if requires is not None:
                return "Yes" if requires else "No"

        if self._matches_any(question_lower, ["work authorization support", "authorization support", "visa support"]):
            requires = answers.get(
                "requires_sponsorship",
                work_auth.get("requires_sponsorship"),
            )
            if requires is not None:
                return "Yes" if requires else "No"

        if self._matches_any(question_lower, ["authorized", "eligible", "work permit", "right to work"]):
            authorized_in = [value.lower() for value in work_auth.get("authorized_in", [])]
            if "netherlands" in combined_context and (
                answers.get("eligible_to_work_in_netherlands") is not None
            ):
                return "Yes" if answers.get("eligible_to_work_in_netherlands") else "No"
            if any(token in combined_context for token in ["eu", "europe", "european union"]) and (
                answers.get("eligible_to_work_in_eu") is not None
            ):
                return "Yes" if answers.get("eligible_to_work_in_eu") else "No"
            if any(token in combined_context for token in ["country", "here"]) and authorized_in:
                return "Yes"

        based_in_answer = self._based_in_location_answer(question_lower, location, answers)
        if based_in_answer is not None:
            return based_in_answer

        office_location_answer = self._office_location_answer(question_lower)
        if office_location_answer is not None:
            return office_location_answer

        if self._matches_any(
            question_lower,
            ["where are you located", "currently located", "current location", "where are you based", "based in"],
        ):
            current_location = answers.get("current_location")
            if current_location:
                return current_location

        if self._matches_any(question_lower, ["linkedin profile", "linkedin url", "profile url"]):
            linkedin_url = personal.get("linkedin_url")
            if linkedin_url:
                return linkedin_url

        if self._matches_any(question_lower, ["country of residence", "main country of residence"]):
            country = location.get("country")
            if country:
                return country

        if "postal code" in question_lower or "zip code" in question_lower:
            postal_code = answers.get("postal_code") or location.get("postal_code")
            if postal_code:
                return str(postal_code)

        if self._matches_any(question_lower, ["start date", "when can you start", "available to start"]):
            if answers.get("can_start_immediately"):
                return "Available immediately"
            start_date = availability.get("start_date")
            if start_date:
                return str(start_date)

        if "notice period" in question_lower:
            notice_weeks = answers.get("notice_period_weeks", availability.get("notice_period_weeks"))
            if notice_weeks is not None:
                return f"{notice_weeks} weeks"

        if self._matches_any(question_lower, ["salary expectation", "salary expectations", "expected salary", "desired salary"]):
            salary_answer = self._salary_expectation_answer(question_lower, combined_context, salary)
            if salary_answer:
                return salary_answer

        if self._matches_any(
            question_lower,
            [
                "how did you hear",
                "how did you find",
                "where did you find",
                "where did you hear",
                "hear about this role",
                "hear about this job",
            ],
        ):
            return "LinkedIn"

        previous_employer_answer = self._previous_employer_answer(question_text, context)
        if previous_employer_answer is not None:
            return previous_employer_answer

        commute_answer = self._commute_comfort_answer(question_lower, answers)
        if commute_answer is not None:
            return commute_answer

        if self._matches_any(question_lower, ["relocate", "relocation"]):
            relocate = answers.get(
                "willing_to_relocate",
                availability.get("willing_to_relocate"),
            )
            if relocate is not None:
                return "Yes" if relocate else "No"

        if self._matches_any(question_lower, ["travel", "commute"]):
            willing = answers.get("willing_to_travel")
            if willing is not None:
                return "Yes" if willing else "No"

        if self._matches_any(question_lower, ["references", "reference available"]):
            references = answers.get(
                "references_available",
                self.profile.get("references_available"),
            )
            if references is not None:
                return "Yes" if references else "No"

        hands_on_answer = self._hands_on_experience_answer(question_lower, years_map)
        if hands_on_answer is not None:
            return hands_on_answer

        if self._matches_any(question_lower, ["remote", "hybrid", "on-site", "onsite", "workplace"]):
            workplace = (
                answers.get("preferred_workplace")
                or common.get("remote_preference")
            )
            if workplace:
                return workplace

        motivation_answer = self._motivation_answer(question_lower, common)
        if motivation_answer:
            return motivation_answer

        years_answer = self._experience_years_answer(question_lower, years_map)
        if years_answer is not None:
            return years_answer

        return None

    def evaluate_job_match(self, job: dict) -> dict:
        """Score a job listing against preferences. Returns {score, reasons, apply}."""
        prefs = self.preferences
        score = 100
        reasons = []

        title = (job.get("title") or "").lower()
        description = (job.get("description") or "").lower()
        company = (job.get("company") or "").lower()
        location = (job.get("location") or "").lower()
        combined_text = self._combined_job_text(job)

        for blacklisted in prefs.get("companies_blacklist", []):
            if blacklisted.lower() in company:
                return {"score": 0, "apply": False, "reasons": ["Company is blacklisted"]}

        high_dutch_requirement = self._high_dutch_fluency_requirement(job)
        if high_dutch_requirement:
            return {
                "score": 0,
                "apply": False,
                "reasons": [f"Role explicitly requires high Dutch fluency: {high_dutch_requirement}"],
            }

        strict_keywords_exclude = self._strict_keywords_exclude(prefs)
        excluded_title_hits = self._matching_values(title, strict_keywords_exclude)
        if excluded_title_hits:
            return {
                "score": 0,
                "apply": False,
                "reasons": [
                    f"Title contains excluded keywords: {', '.join(excluded_title_hits[:3])}"
                ],
            }

        whitelist_hits = self._matching_values(company, prefs.get("companies_whitelist", []))
        if whitelist_hits:
            score += 15
            reasons.append(f"Whitelisted company match: {', '.join(whitelist_hits[:2])}")

        excluded_keyword_hits = self._matching_values(combined_text, strict_keywords_exclude)
        if excluded_keyword_hits:
            penalty = min(60, 25 * len(excluded_keyword_hits))
            score -= penalty
            reasons.append(
                f"Contains excluded keywords: {', '.join(excluded_keyword_hits[:3])}"
            )

        required_keywords = prefs.get("keywords_required", [])
        required_hits = self._matching_values(combined_text, required_keywords)
        if required_keywords and not required_hits:
            score -= 30
            reasons.append("Missing required keywords")
        elif required_hits:
            score += min(15, 5 * len(required_hits))
            reasons.append(f"Required keyword match: {', '.join(required_hits[:3])}")

        nice_to_have_hits = self._matching_values(
            combined_text, prefs.get("keywords_nice_to_have", [])
        )
        if nice_to_have_hits:
            score += min(12, 4 * len(nice_to_have_hits))
            reasons.append(f"Nice-to-have keywords matched: {', '.join(nice_to_have_hits[:3])}")

        soft_negative_hits = self._matching_values(
            combined_text,
            prefs.get("soft_negative_keywords", []),
        )
        if soft_negative_hits:
            penalty = min(24, 6 * len(soft_negative_hits))
            score -= penalty
            reasons.append(
                f"Soft risk signal: {', '.join(soft_negative_hits[:3])}"
            )

        fallback_hits = self._matching_values(
            combined_text,
            prefs.get("fallback_keywords", []),
        )
        if fallback_hits:
            score -= min(16, 5 * len(fallback_hits))
            reasons.append(
                f"Fallback/income role signal: {', '.join(fallback_hits[:3])}"
            )

        bridge_positive_hits = self._matching_values(
            combined_text,
            [
                "trainee",
                "traineeship",
                "graduate",
                "training",
                "customer success",
                "customer operations",
                "product operations",
                "business analyst",
                "data analyst",
                "reporting analyst",
                "insights analyst",
                "bi trainee",
                "analytics trainee",
                "implementation consultant",
                "procurement trainee",
                "supply chain trainee",
            ],
        )
        if bridge_positive_hits:
            score += min(18, 6 * len(bridge_positive_hits))
            reasons.append(
                f"Career-growth bridge signal: {', '.join(bridge_positive_hits[:3])}"
            )

        title_match = any(
            target.lower() in title or title in target.lower()
            for target in prefs.get("job_titles", [])
        )
        title_overlap = self._shared_title_terms(title, prefs.get("job_titles", []))
        target_title_terms = self._target_title_terms(prefs.get("job_titles", []))
        management_title_hits = sorted(
            term for term in self.MANAGEMENT_TITLE_TERMS
            if re.search(rf"\b{re.escape(term)}\b", title)
        )
        if title_match:
            score += 10
        elif title_overlap:
            score += min(10, 4 * len(title_overlap))
            reasons.append(f"Related title terms: {', '.join(title_overlap[:3])}")
        else:
            broad_junior_terms = {
                "junior",
                "associate",
                "assistant",
                "coordinator",
                "trainee",
                "graduate",
                "analyst",
                "specialist",
                "consultant",
                "operations",
                "product",
                "project",
                "customer",
                "success",
            }
            if any(re.search(rf"\b{re.escape(term)}\b", title) for term in broad_junior_terms):
                score -= 12
                reasons.append("Title is not a direct target match, but broad junior/bridge role is kept for scoring")
            else:
                score -= 25
                reasons.append("Title has limited overlap with target roles")

        hard_management_hits = [
            term for term in management_title_hits
            if term in {"director", "head", "chief"}
        ]
        senior_management_context = any(
            marker in combined_text
            for marker in [
                "direct reports",
                "performance reviews",
                "p&l",
                "p and l",
                "department ownership",
                "senior leadership",
                "5+ years",
                "6+ years",
                "8+ years",
            ]
        )
        if hard_management_hits or ("manager" in management_title_hits and senior_management_context):
            score -= 45
            reasons.append(
                f"Management/senior responsibility concern: {', '.join((hard_management_hits or management_title_hits)[:2])}"
            )
        elif "manager" in management_title_hits:
            score -= 6
            reasons.append("Manager title alone is treated as a risk flag, not a hard blocker")

        preferred_industries = self._matching_values(
            combined_text, prefs.get("industries_preferred", [])
        )
        if preferred_industries:
            score += min(12, 6 * len(preferred_industries))
            reasons.append(
                f"Preferred industry match: {', '.join(preferred_industries[:2])}"
            )

        excluded_industries = self._matching_values(
            combined_text, prefs.get("industries_excluded", [])
        )
        if excluded_industries:
            score -= min(50, 25 * len(excluded_industries))
            reasons.append(
                f"Excluded industry match: {', '.join(excluded_industries[:2])}"
            )

        workplace_type = self._infer_workplace_type(job)
        if workplace_type == "remote" and not prefs.get("remote_ok", True):
            score -= 35
            reasons.append("Remote role does not match preferences")
        elif workplace_type == "hybrid" and not prefs.get("hybrid_ok", True):
            score -= 35
            reasons.append("Hybrid role does not match preferences")
        elif workplace_type == "onsite" and not prefs.get("onsite_ok", True):
            score -= 35
            reasons.append("On-site role does not match preferences")
        elif workplace_type:
            score += 5

        if location == "remote" and not prefs.get("remote_ok", True):
            score -= 35
            reasons.append("Remote location does not match preferences")

        employment_type = self._infer_employment_type(job)
        allowed_types = [value.lower() for value in prefs.get("employment_types", [])]
        if employment_type and allowed_types:
            if employment_type in allowed_types:
                score += 6
            else:
                score -= 25
                reasons.append(
                    f"Employment type '{employment_type}' is outside preferred types"
                )

        salary_text = (job.get("salary") or "").lower()
        minimum_salary = prefs.get("salary_minimum")
        normalized_salary = self._estimate_salary_for_comparison(salary_text)
        if normalized_salary is not None and minimum_salary:
            if normalized_salary < minimum_salary:
                score -= 30
                reasons.append(
                    f"Estimated salary {normalized_salary} below minimum {minimum_salary}"
                )
            else:
                score += 8

        dutch_risk = self._dutch_language_risk(combined_text)
        if dutch_risk:
            score -= 8
            reasons.append(dutch_risk)

        commute_risk = self._commute_risk(location)
        if commute_risk:
            score -= 8
            reasons.append(commute_risk)

        if employment_type == "part-time":
            score -= 8
            reasons.append("Part-time role lowers financial/stability value")

        if employment_type == "internship":
            if normalized_salary is not None and normalized_salary < 800:
                score = min(score, 65)
                reasons.append("Low-paid internship kept for human review instead of APPLY")
            else:
                score = min(score, 69)
                reasons.append("Internship-style role kept for human review")

        research_bridge = any(
            marker in combined_text
            for marker in ["research assistant", "clinical study assistant"]
        )
        local_language_risk = any(
            marker in combined_text
            for marker in ["local language", "dutch preferred", "nederlands preferred"]
        )
        if research_bridge and employment_type == "part-time" and (local_language_risk or commute_risk):
            score = min(score, 65)
            reasons.append("Research/admin bridge kept as low-priority human review due to part-time/local-language/commute concerns")

        score = max(0, min(score, 140))
        min_match_score = prefs.get("filters", {}).get("min_match_score", 60)
        human_review_min = prefs.get(
            "human_review_score_min",
            prefs.get("filters", {}).get("human_review_score_min", 50),
        )
        apply = score >= min_match_score
        human_review = human_review_min <= score < min_match_score

        if not reasons:
            reasons.append("Strong overall match")
        reasons.append(
            "Scored across realistic interview chance, career-growth value, and financial/stability value"
        )

        return {"score": score, "apply": apply, "human_review": human_review, "reasons": reasons}

    def generate_cover_letter(self, job: dict) -> str:
        """Generate a tailored cover letter using Claude."""
        profile = self.profile
        name = f"{profile['personal']['first_name']} {profile['personal']['last_name']}"

        prompt = f"""Write a concise, genuine cover letter for this job application.

JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Description: {job.get('description', 'Not provided')[:1500]}

APPLICANT PROFILE:
Name: {name}
About: {profile.get('about_me')}
Most recent role: {profile['work_experience'][0]['title']} at {profile['work_experience'][0]['company']}
Key skills: {', '.join(profile.get('skills', [])[:10])}
Style preference: {profile.get('cover_letter_style', 'concise and specific')}

ADDITIONAL KNOWLEDGE:
{self._knowledge_prompt_block()}

Instructions:
- 3-4 paragraphs max
- Be specific to THIS role and company
- Do not use generic filler phrases like "I am writing to express my interest"
- Sound human and genuine
- End with a clear call to action
- Do not include a subject line or date header
- Start directly with "Dear Hiring Team," or the hiring manager's name if known
"""
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def answer_question(self, question: str, context: str = "") -> str:
        """Answer a specific application question using the user's profile."""
        structured_answer = self.get_structured_question_answer(question, context)
        if structured_answer:
            return structured_answer

        prompt = f"""Answer this job application question on behalf of the applicant.

QUESTION: {question}

APPLICANT PROFILE:
{json.dumps(self.profile, indent=2)}

ADDITIONAL KNOWLEDGE FROM CV / PORTFOLIO:
{self._knowledge_prompt_block()}

Additional page context:
{context[:900]}

Instructions:
- Answer truthfully based only on the profile information
- Use the CV/portfolio knowledge only to clarify or support profile facts, never to invent
- Be concise but complete
- Use first person ("I", "my")
- If it is a yes/no question, give a clear yes or no first
- For dropdowns or radio questions, return only the best matching option label
- If the profile does not contain the exact answer, use the closest truthful professional response
- For numeric fields (years of experience, notice period, salary, etc.), return only the requested value format
"""
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()

    def score_interview_probability(
        self,
        job: dict,
        query: str,
        ideal_job_profile: str,
        include_cv: bool = False,
        prior_assessment: Optional[dict] = None,
    ) -> dict:
        """Score realistic interview probability for scout mode."""
        description = (job.get("description") or job.get("preview_text") or "").strip()
        if not description:
            return {
                "interview_probability_score": 0,
                "reason": "No usable job description was available for AI scoring.",
                "model": self.scoring_model_label,
                "used_cv": include_cv,
            }

        title = (job.get("title") or "").strip()
        company = (job.get("company") or "").strip()
        location = (job.get("location") or "").strip()
        ideal_text = (ideal_job_profile or "").strip()
        if not ideal_text:
            raise RuntimeError(
                "The Perfect Suitable Job profile is empty. Update the file before AI scoring."
            )

        cv_excerpt = ""
        if include_cv:
            cv_excerpt = (self.profile_knowledge.get("cv_excerpt") or "").strip()

        default_lmstudio_payload = self._build_scoring_input_payload(
            query=query,
            title=title,
            company=company,
            location=location,
            description=description,
            ideal_text=ideal_text,
            include_cv=include_cv,
            cv_excerpt=cv_excerpt,
            prior_assessment=prior_assessment,
            simplified=True,
        )
        default_lmstudio_prompt_text = self._build_interview_scoring_prompt(
            query=query,
            title=title,
            company=company,
            location=location,
            description=description,
            ideal_text=ideal_text,
            include_cv=include_cv,
            cv_excerpt=cv_excerpt,
            prior_assessment=prior_assessment,
            simplified=True,
        )
        rich_payload = self._build_scoring_input_payload(
            query=query,
            title=title,
            company=company,
            location=location,
            description=description,
            ideal_text=ideal_text,
            include_cv=include_cv,
            cv_excerpt=cv_excerpt,
            prior_assessment=prior_assessment,
            simplified=False,
        )
        rich_prompt_text = self._build_interview_scoring_prompt(
            query=query,
            title=title,
            company=company,
            location=location,
            description=description,
            ideal_text=ideal_text,
            include_cv=include_cv,
            cv_excerpt=cv_excerpt,
            prior_assessment=prior_assessment,
            simplified=False,
        )
        scoring_max_tokens = self.LMSTUDIO_SCORING_BASE_MAX_TOKENS
        if self.scoring_backend == "lmstudio":
            scoring_max_tokens = self._lmstudio_scoring_max_tokens(
                self.LMSTUDIO_SCORING_BASE_MAX_TOKENS
            )
            reasoning_config = self._lmstudio_resolved_reasoning_config()
            self._set_scoring_audit_snapshot(
                {
                    "backend": self.scoring_backend,
                    "model": self.scoring_model_label,
                    "prompt_variant": "simplified_json_contract",
                    "include_cv": include_cv,
                    "compressed_ai_payload": default_lmstudio_payload,
                    "prompt_char_count": len(default_lmstudio_prompt_text),
                    "prompt_word_count": len(default_lmstudio_prompt_text.split()),
                    "prompt_token_estimate": self._estimate_prompt_tokens(
                        default_lmstudio_prompt_text
                    ),
                    "request_config": {
                        "max_tokens": scoring_max_tokens,
                        "reasoning_enabled": bool(
                            reasoning_config.get("reasoning_enabled")
                        ),
                        "reasoning_param": reasoning_config.get(
                            "payload_reasoning_effort"
                        )
                        or "omitted",
                    },
                    "usage": {},
                }
            )
            parsed, model_label = self._request_lmstudio_scoring_response_with_retries(
                prompt=default_lmstudio_prompt_text,
                fallback_prompt=None,
                prompt_label="simplified_json_contract",
                fallback_prompt_label="simplified_json_contract",
                max_tokens=scoring_max_tokens,
            )
        elif self.scoring_backend == "gemini":
            scoring_max_tokens = self.gemini_max_output_tokens
            self._set_scoring_audit_snapshot(
                {
                    "backend": self.scoring_backend,
                    "model": self.scoring_model_label,
                    "prompt_variant": "rich_prompt",
                    "include_cv": include_cv,
                    "compressed_ai_payload": rich_payload,
                    "prompt_char_count": len(rich_prompt_text),
                    "prompt_word_count": len(rich_prompt_text.split()),
                    "prompt_token_estimate": self._estimate_prompt_tokens(
                        rich_prompt_text
                    ),
                    "request_config": {
                        "max_output_tokens": scoring_max_tokens,
                        "thinking_budget": (
                            self.gemini_thinking_budget
                            if self.gemini_thinking_budget is not None
                            else "omitted"
                        ),
                        "max_attempts": self.gemini_max_attempts,
                    },
                    "usage": {},
                }
            )
            parsed, model_label = self._request_gemini_scoring_response_with_retries(
                prompt=rich_prompt_text,
                max_tokens=scoring_max_tokens,
            )
        elif self.scoring_backend in {"auto", "cerebras", "ollama_cloud", "openai_compatible"}:
            if self.scoring_backend == "auto":
                configured_backends = self._configured_auto_backends()
                request_config = {
                    "backend_order": configured_backends,
                    "max_output_tokens_by_backend": {
                        backend: (
                            self._hosted_provider_config(backend).get("max_output_tokens")
                            if backend in {"cerebras", "ollama_cloud", "openai_compatible"}
                            else self.gemini_max_output_tokens
                        )
                        for backend in configured_backends
                    },
                }
            else:
                configured_backends = [self.scoring_backend]
                request_config = {
                    "backend": self.scoring_backend,
                    "max_output_tokens": self._hosted_provider_config(self.scoring_backend).get("max_output_tokens"),
                    "max_attempts": self._hosted_provider_config(self.scoring_backend).get("max_attempts"),
                }
            self._set_scoring_audit_snapshot(
                {
                    "backend": self.scoring_backend,
                    "model": self.scoring_model_label,
                    "prompt_variant": "rich_prompt",
                    "include_cv": include_cv,
                    "compressed_ai_payload": rich_payload,
                    "prompt_char_count": len(rich_prompt_text),
                    "prompt_word_count": len(rich_prompt_text.split()),
                    "prompt_token_estimate": self._estimate_prompt_tokens(
                        rich_prompt_text
                    ),
                    "request_config": request_config,
                    "usage": {},
                }
            )
            if self.scoring_backend == "auto":
                parsed, model_label = self._request_auto_scoring_response(
                    prompt=rich_prompt_text,
                )
            else:
                parsed, model_label = self._request_hosted_scoring_response_with_retries(
                    backend=self.scoring_backend,
                    prompt=rich_prompt_text,
                )
        else:
            self._set_scoring_audit_snapshot(
                {
                    "backend": self.scoring_backend,
                    "model": self.scoring_model_label,
                    "prompt_variant": "rich_prompt",
                    "include_cv": include_cv,
                    "compressed_ai_payload": rich_payload,
                    "prompt_char_count": len(rich_prompt_text),
                    "prompt_word_count": len(rich_prompt_text.split()),
                    "prompt_token_estimate": self._estimate_prompt_tokens(
                        rich_prompt_text
                    ),
                    "request_config": {
                        "max_tokens": scoring_max_tokens,
                    },
                    "usage": {},
                }
            )
            raw, model_label = self._request_scoring_response(
                rich_prompt_text,
                max_tokens=scoring_max_tokens,
            )
            parsed = self._parse_scoring_payload(raw, backend="claude")
        score = parsed.get("interview_probability_score", 0)
        reason = parsed.get("reason", "")

        try:
            score = int(float(str(score).strip()))
        except (TypeError, ValueError):
            score = 0

        score = max(0, min(score, 100))
        reason = re.sub(r"\s+", " ", str(reason or "").strip())
        if not reason:
            reason = "AI scoring returned no usable explanation."

        return {
            "interview_probability_score": score,
            "reason": reason[:320],
            "model": model_label,
            "used_cv": include_cv,
        }

    def _parse_json_object(self, raw: str, required_keys: tuple[str, ...] = ()) -> dict:
        cleaned = (raw or "").strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for match in re.finditer(r"\{", cleaned):
                start = match.start()
                candidate = cleaned[start:]
                try:
                    parsed, _ = decoder.raw_decode(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict) and all(
                    key in parsed for key in required_keys
                ):
                    return parsed
            raise

    async def decide_next_action(
        self,
        screenshot_b64: str,
        page_text: str,
        task: str,
        cover_letter: str = "",
        history: list = None
    ) -> dict:
        """
        Look at the current page and decide what action to take next.
        Returns a dict: { action, params, reasoning }
        """
        behavior = self.preferences.get("application_behavior", {})
        common_answers = json.dumps(
            self.profile.get("common_questions", {}),
            indent=2,
            ensure_ascii=False,
        )[:1200]
        structured_answers = json.dumps(
            self.profile.get("application_answers", {}),
            indent=2,
            ensure_ascii=False,
        )[:1200]

        context = f"""CURRENT TASK: {task}

USER PROFILE SUMMARY:
Name: {self.profile['personal']['first_name']} {self.profile['personal']['last_name']}
Email: {self.profile['personal']['email']}
Phone: {self.profile['personal']['phone']}
Location: {self.profile['personal']['location']['city']}, {self.profile['personal']['location']['country']}
CV path: {self.profile.get('cv_path', 'cv/Omar Abdulghani - CV Resume (English).pdf')}
Target salary: {self.profile['salary']['target']} {self.profile['salary']['currency']}
Skills: {', '.join(self.profile.get('skills', [])[:12])}
Current role: {self.profile['work_experience'][0]['title']} at {self.profile['work_experience'][0]['company']}
Years experience: ~{self._years_of_experience()} years

APPLICATION BEHAVIOR:
- submit_cover_letter: {behavior.get('submit_cover_letter', True)}
- answer_screening_questions: {behavior.get('answer_screening_questions', True)}
- skip_assessments: {behavior.get('skip_assessments', False)}
- pause_before_final_submit: {behavior.get('pause_before_final_submit', False)}

COMMON QUESTION ANSWERS:
{common_answers}

STRUCTURED APPLICATION ANSWERS:
{structured_answers}

ADDITIONAL KNOWLEDGE FROM CV / PORTFOLIO:
{self._knowledge_prompt_block()[:1800]}

COVER LETTER (use only if submit_cover_letter is true):
{cover_letter[:1000] if cover_letter else 'Not available'}

PAGE TEXT (first 3500 chars):
{page_text[:3500]}

Previous steps taken:
{json.dumps(history or [], indent=2)[-1200:]}

Special instructions:
- If answer_screening_questions is false, do not answer custom screening questions; stop with done/skipped instead.
- If submit_cover_letter is false, do not paste or upload any cover letter text.
- Use answer_question when a text field asks a question and the answer should come from the profile.

Now look at the screenshot and decide the next action. Respond with JSON only.
"""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64
                        }
                    },
                    {"type": "text", "text": context}
                ]
            }
        ]

        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=messages
        )

        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "action": "wait",
                "params": {"seconds": 2},
                "reasoning": "Parse error, waiting"
            }

    def _combined_job_text(self, job: dict) -> str:
        parts = [
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("preview_text", ""),
            job.get("description", ""),
            job.get("salary", ""),
            job.get("employment_type", ""),
        ]
        return " ".join(part for part in parts if part).lower()

    def _is_dutch_language_job(self, job: dict) -> bool:
        filters = self.preferences.get("filters", {})
        if not filters.get("exclude_dutch_language_jobs", False):
            return False
        return bool(self._high_dutch_fluency_requirement(job))

    def _high_dutch_fluency_requirement(self, job: dict) -> str:
        combined_text = self._combined_job_text(job)
        markers = sorted(self.HIGH_DUTCH_FLUENCY_MARKERS, key=len, reverse=True)
        matches = self._matching_values(combined_text, markers)
        if matches:
            return matches[0]

        fluent_matches = self._matching_values(
            combined_text,
            sorted(self.FLUENT_DUTCH_CONTEXT_MARKERS, key=len, reverse=True),
        )
        if not fluent_matches:
            return ""
        context_matches = self._matching_values(
            combined_text,
            sorted(self.DUTCH_HEAVY_COMMUNICATION_MARKERS, key=len, reverse=True),
        )
        if context_matches:
            return f"{fluent_matches[0]} in Dutch-heavy context ({context_matches[0]})"
        return ""

    def _strict_keywords_exclude(self, prefs: dict) -> list:
        if "hard_exclude_keywords" in prefs:
            return [
                value for value in prefs.get("hard_exclude_keywords", [])
                if str(value or "").strip()
            ]

        filtered = []
        for value in prefs.get("keywords_exclude", []):
            normalized = (value or "").strip().lower()
            if not normalized:
                continue
            if normalized in self.SOFT_DUTCH_EXCLUDE_KEYWORDS:
                continue
            filtered.append(value)
        return filtered

    def _matching_values(self, haystack: str, values: list) -> list:
        haystack = (haystack or "").lower()
        matches = []
        for value in values:
            if not value:
                continue
            pattern = rf"(?<!\w){re.escape(value.lower())}(?!\w)"
            if re.search(pattern, haystack):
                matches.append(value)
        return matches

    def _target_title_terms(self, titles: list) -> set:
        terms = set()
        for title in titles:
            terms.update(self._title_terms(title))
        return terms

    def _shared_title_terms(self, title: str, target_titles: list) -> list:
        current_terms = self._title_terms(title)
        target_terms = self._target_title_terms(target_titles)
        return sorted(current_terms.intersection(target_terms))

    def _title_terms(self, title: str) -> set:
        normalized = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
        return {
            token for token in normalized.split()
            if len(token) > 2 and token not in self.TITLE_STOPWORDS
        }

    def _language_tokens(self, text: str) -> list:
        return re.findall(r"[a-zA-ZÀ-ÿ]+", (text or "").lower())

    def _marker_hits(self, tokens: list, markers: set) -> int:
        return sum(1 for token in tokens if token in markers)

    def _matches_any(self, haystack: str, needles: list) -> bool:
        return any(needle in haystack for needle in needles)

    def _is_consent_question(self, question_lower: str, combined_context: str = "") -> bool:
        text = f"{question_lower} {combined_context}".lower()
        consent_markers = [
            "has my consent",
            "i consent",
            "consent to collect",
            "consent to store",
            "consent to process",
            "collect, store, and process",
            "collect store and process",
            "process my data",
            "store my data",
            "my data for the purpose",
            "privacy policy",
            "privacy notice",
            "data processing",
            "toestemming",
            "gegevens",
            "vink selectievakje",
            "selectievakje aan",
        ]
        return any(marker in text for marker in consent_markers)

    def _language_screening_answer(self, question_lower: str, combined_context: str) -> Optional[str]:
        text = f"{question_lower} {combined_context}".lower()
        asks_dutch_and_english = (
            ("dutch" in text and "english" in text)
            or ("nederlands" in text and ("engels" in text or "english" in text))
        )
        asks_fluency = any(
            marker in text
            for marker in ["fluent", "fluency", "vloeiend", "professioneel", "native"]
        )
        if not (asks_dutch_and_english and asks_fluency):
            return None

        binary_only = any(
            marker in text
            for marker in [
                "radio",
                "dropdown",
                "select one",
                "choose one",
                "yes/no",
                "yes or no",
                "options: yes",
                "option yes",
            ]
        )
        if binary_only:
            return "No"
        return (
            "No. I am fluent in English, and my Dutch is B1/intermediate. "
            "I am actively improving my Dutch for professional communication."
        )

    def _salary_expectation_answer(self, question_lower: str, combined_context: str, salary: dict) -> Optional[str]:
        target = salary.get("target")
        currency = salary.get("currency", "")
        period = salary.get("period", "")
        if not target:
            return None

        text = f"{question_lower} {combined_context}".lower()
        if any(marker in text for marker in ["internship", "intern ", "stagevergoeding", "allowance"]):
            return "In line with the stated internship allowance"

        stated_hourly = self._extract_stated_hourly_rate(text)
        if stated_hourly is not None:
            return f"{stated_hourly:g} {currency} gross per hour".strip()

        range_value = self._salary_value_inside_stated_range(text, int(target))
        if range_value is not None:
            if any(token in question_lower for token in ["per year", "yearly", "annual", "annually"]):
                return f"{range_value * 12} {currency}".strip()
            return f"{range_value} {currency}".strip()

        if any(token in question_lower for token in ["per month", "monthly", "month"]):
            return f"{target} {currency}".strip()
        if any(token in question_lower for token in ["per year", "yearly", "annual", "annually"]):
            return f"{target * 12} {currency}".strip()
        return f"{target} {currency} gross per {period}".strip()

    def _extract_stated_hourly_rate(self, text: str) -> Optional[float]:
        if not any(marker in text for marker in ["per hour", "hourly", "/hour", "per uur", "uurloon"]):
            return None
        values = []
        for raw in re.findall(r"\d[\d,.]*", text):
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                continue
            if 8 <= value <= 80:
                values.append(value)
        return max(values) if values else None

    def _salary_value_inside_stated_range(self, text: str, monthly_target: int) -> Optional[int]:
        if not any(marker in text for marker in ["salary", "salaris", "compensation", "eur", "€"]):
            return None
        values = []
        for raw in re.findall(r"\d[\d,.]*", text):
            normalized = raw.replace(".", "").replace(",", "")
            try:
                value = int(normalized)
            except ValueError:
                continue
            if 1000 <= value <= 200000:
                values.append(value)
        if len(values) < 2:
            return None

        low, high = min(values), max(values)
        if high > 20000:
            low = int(low / 12) if low > 20000 else low
            high = int(high / 12)
        if low <= monthly_target <= high:
            return monthly_target
        return max(low, min(high, monthly_target))

    def _based_in_location_answer(self, question_lower: str, location: dict, answers: dict) -> Optional[str]:
        english_binary_location_question = re.search(r"\b(are|do)\s+you\b", question_lower)
        dutch_binary_location_question = self._matches_any(
            question_lower,
            [
                "woont u",
                "woon je",
                "woont jij",
                "bent u woonachtig",
                "ben je woonachtig",
                "woonachtig in",
                "gevestigd in",
                "verblijft u",
            ],
        )
        if not english_binary_location_question and not dutch_binary_location_question:
            return None
        if not self._matches_any(
            question_lower,
            [
                "currently based in",
                "based in",
                "located in",
                "live in",
                "living in",
                "resident in",
                "reside in",
                "woont",
                "woon je",
                "woon jij",
                "wonen",
                "woonachtig",
                "gevestigd",
                "verblijft",
            ],
        ):
            return None

        current_city = (answers.get("current_city") or location.get("city") or "").strip().lower()
        current_country = (answers.get("current_country") or location.get("country") or "").strip().lower()
        current_location = (answers.get("current_location") or "").strip().lower()

        if not any(token in question_lower for token in ["amsterdam", "amstelveen", "netherlands", "nederland", "randstad"]):
            return None

        if "randstad" in question_lower:
            randstad_cities = {
                "amsterdam",
                "amstelveen",
                "haarlem",
                "hoofddorp",
                "utrecht",
                "leiden",
                "the hague",
                "den haag",
                "rotterdam",
                "delft",
                "zoetermeer",
                "almere",
            }
            return "Yes" if current_city in randstad_cities or any(city in current_location for city in randstad_cities) else "No"

        if any(token in question_lower for token in ["netherlands", "nederland"]):
            return "Yes" if current_country in {"netherlands", "nederland"} else "No"

        if "amstelveen" in question_lower:
            return "Yes" if "amstelveen" in {current_city, current_location} or "amstelveen" in current_location else "No"

        if "amsterdam area" in question_lower or "greater amsterdam" in question_lower:
            return "Yes" if current_city in {"amsterdam", "amstelveen"} or "amstelveen" in current_location else "No"

        if "amsterdam" in question_lower:
            return "Yes" if current_city == "amsterdam" else "No"

        return None

    def _office_location_answer(self, question_lower: str) -> Optional[str]:
        office_markers = [
            "office is mandatory",
            "work from our",
            "work from the office",
            "work from our office",
            "our amsterdam office",
            "our office in",
            "our location",
            "work from our amsterdam location",
            "cannot work from our",
            "work on-site",
            "work onsite",
            "work on site",
            "onsite is mandatory",
            "on-site is mandatory",
            "working from",
        ]
        if not self._matches_any(question_lower, office_markers):
            return None

        acceptable_cities = self._acceptable_commute_cities()
        if not acceptable_cities:
            return None

        for city in acceptable_cities:
            if city and city in question_lower:
                return "Yes"

        if any(token in question_lower for token in ["netherlands", "nederland"]):
            return "Yes"

        return None

    def _acceptable_commute_cities(self) -> set[str]:
        cities = set()

        personal_location = self.profile.get("personal", {}).get("location", {})
        personal_city = (personal_location.get("city") or "").strip().lower()
        if personal_city:
            cities.add(personal_city)

        answers = self.profile.get("application_answers", {})
        current_location = (answers.get("current_location") or "").strip().lower()
        if current_location:
            for token in re.split(r"[,/]", current_location):
                token = token.strip().lower()
                if token:
                    cities.add(token)

        for location_value in self.preferences.get("locations", []):
            city = (location_value or "").split(",")[0].strip().lower()
            if city and city != "remote":
                cities.add(city)

        if "amstelveen" in cities:
            cities.update({"amsterdam", "amsterdam area", "randstad"})

        return cities

    def _previous_employer_answer(self, question: str, context: str = "") -> Optional[str]:
        combined = f"{question} {context}".lower()
        if not any(
            phrase in combined
            for phrase in ["worked for", "worked here before", "worked previously", "previously employed"]
        ):
            return None

        employers = [
            (item.get("company") or "").strip().lower()
            for item in self.profile.get("work_experience", [])
            if item.get("company")
        ]
        if any(employer and employer in combined for employer in employers):
            return "Yes"

        return "No"

    def _motivation_answer(self, question_lower: str, common: dict) -> Optional[str]:
        if self._matches_any(question_lower, ["why do you want", "why are you interested", "motivation for applying"]):
            return common.get("why_this_company") or common.get("why_looking_for_new_role")
        if self._matches_any(question_lower, ["why are you looking for", "why looking for new role", "why new role"]):
            return common.get("why_looking_for_new_role")
        if self._matches_any(question_lower, ["biggest strength", "strengths"]):
            return common.get("biggest_strength")
        if self._matches_any(question_lower, ["biggest weakness", "weaknesses"]):
            return common.get("biggest_weakness")
        if self._matches_any(question_lower, ["describe yourself", "tell us about yourself", "introduce yourself"]):
            return common.get("describe_yourself")
        if self._matches_any(question_lower, ["team or solo", "work independently", "team player"]):
            return common.get("team_or_solo")
        return None

    def _hands_on_experience_answer(self, question_lower: str, years_map: dict) -> Optional[str]:
        if not re.search(r"\b(do|did|have|hands-on|handson)\b", question_lower):
            return None
        if not self._matches_any(
            question_lower,
            [
                "hands-on experience",
                "hands on experience",
                "experience with",
                "ervaring met",
                "ervaring in",
                "bekend met",
            ],
        ):
            return None

        normalized_question = self._normalize_question_key(question_lower)
        extracted_subject = self._normalize_question_key(self._extract_experience_subject(question_lower))
        haystack = f"{normalized_question} {extracted_subject}".strip()

        yes_aliases = [
            ("figma", ["figma", "design system", "wireframing", "prototyping"]),
            ("google analytics", ["google analytics", "analytics", "tracking"]),
            ("react", ["react", "frontend", "web development"]),
            ("sql", ["sql", "database", "data"]),
            ("seo", ["seo", "search engine optimization"]),
            ("ux ui design", ["ux", "ui", "design", "user research", "product design"]),
        ]
        for key, aliases in yes_aliases:
            if any(alias in haystack for alias in aliases):
                years = years_map.get(key)
                if years is not None:
                    try:
                        return "Yes" if float(years) > 0 else "No"
                    except (TypeError, ValueError):
                        return "Yes"

        explicit_no_aliases = [
            "3d printer",
            "3d printers",
            "slicer",
            "slicers",
            "filament",
            "cad",
            "solidworks",
            "autocad",
            "mechanical engineering",
            "cnc",
        ]
        if any(alias in haystack for alias in explicit_no_aliases):
            return "No"

        return None

    def _commute_comfort_answer(self, question_lower: str, answers: dict) -> Optional[str]:
        commute_markers = [
            "comfortable commuting",
            "commuting to",
            "commuting",
            "commute to",
            "commute",
            "travel to this job",
            "travel to the office",
        ]
        if not self._matches_any(question_lower, commute_markers):
            return None

        willing = answers.get("willing_to_travel")
        if willing is not None:
            return "Yes" if willing else "No"

        workplace = (answers.get("preferred_workplace") or "").lower()
        if any(token in workplace for token in ["on-site", "onsite", "hybrid"]):
            return "Yes"

        return None

    def _experience_years_answer(self, question_lower: str, years_map: dict) -> Optional[str]:
        if not self._is_years_experience_question(question_lower):
            return None

        normalized_question = self._normalize_question_key(question_lower)
        for skill, years in years_map.items():
            normalized_skill = self._normalize_question_key(skill)
            if (
                skill
                and years is not None
                and (
                    skill in question_lower
                    or normalized_skill in normalized_question
                )
            ):
                return self._format_experience_years_value(years)

        extracted_skill = self._extract_experience_subject(question_lower)
        alias_answer = self._experience_years_alias_answer(
            normalized_question,
            self._normalize_question_key(extracted_skill),
            years_map,
        )
        if alias_answer is not None:
            return alias_answer

        if "figma" in question_lower and years_map.get("figma") is not None:
            return self._format_experience_years_value(years_map["figma"])
        if "google analytics" in question_lower and years_map.get("google analytics") is not None:
            return self._format_experience_years_value(years_map["google analytics"])
        if "digital marketing" in question_lower and years_map.get("digital marketing") is not None:
            return self._format_experience_years_value(years_map["digital marketing"])
        if ("ux" in question_lower or "ui" in question_lower) and years_map.get("ux ui design") is not None:
            return self._format_experience_years_value(years_map["ux ui design"])

        return None

    def _is_years_experience_question(self, question_lower: str) -> bool:
        return any(
            token in question_lower
            for token in [
                "year",
                "years",
                "experience",
                "jaar",
                "werkervaring",
                "ervaring",
                "hoeveel jaar",
            ]
        )

    def _extract_experience_subject(self, question_lower: str) -> str:
        patterns = [
            r"\bwith\s+(.+?)(?:\?|$)",
            r"\bin\s+(.+?)(?:\?|$)",
            r"\bmet\s+(.+?)(?:\?|$)",
            r"\bin\s+(.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, question_lower, flags=re.IGNORECASE)
            if match:
                subject = match.group(1)
                subject = re.sub(r"\b(required|verplicht)\b", "", subject, flags=re.IGNORECASE)
                return re.sub(r"\s+", " ", subject).strip(" .:;?*")
        return ""

    def _experience_years_alias_answer(
        self,
        normalized_question: str,
        normalized_subject: str,
        years_map: dict,
    ) -> Optional[str]:
        def mapped_years(keys: list[str]) -> Optional[str]:
            values = []
            for key in keys:
                value = years_map.get(key)
                if value is not None:
                    try:
                        values.append(float(value))
                    except (TypeError, ValueError):
                        continue
            if not values:
                return None
            best = max(values)
            return self._format_experience_years_value(best)

        def derived_years(keywords: list[str]) -> Optional[str]:
            years = self._experience_years_from_work_history(keywords)
            if years is None:
                return None
            return self._format_experience_years_value(years)

        haystack = f"{normalized_question} {normalized_subject}".strip()
        alias_groups = [
            (
                ["branded content", "brand content", "content", "content marketing"],
                ["branding", "digital marketing", "brand activation"],
                None,
            ),
            (
                ["brand", "branding", "brand activation"],
                ["branding", "digital marketing"],
                None,
            ),
            (
                ["analytics", "data analytics", "google analytics"],
                ["google analytics", "digital marketing"],
                None,
            ),
            (
                ["seo", "search engine optimization"],
                ["seo", "digital marketing"],
                None,
            ),
            (
                ["user research", "ux research", "research"],
                ["user research", "ux"],
                None,
            ),
            (
                ["ux", "ui", "ux ui", "product design", "design"],
                ["ux ui design", "ux", "ui", "figma"],
                None,
            ),
            (
                ["web development", "html", "react", "frontend", "front end"],
                ["react", "html"],
                None,
            ),
            (
                ["sql", "database", "data"],
                ["sql"],
                None,
            ),
            (
                ["video editing", "video edit", "video production", "premiere pro", "after effects"],
                [],
                "0",
            ),
            (
                ["campaign", "campaigns", "campaign management", "marketing campaign", "marketing campaigns"],
                ["digital marketing", "branding"],
                "1",
            ),
            (
                ["retail apparel and fashion", "apparel and fashion", "retail fashion", "fashion retail"],
                [],
                "0",
            ),
            (
                ["horeca", "hospitality", "hotel", "restaurant", "brunch", "cafe", "food service", "foodservice"],
                [],
                "0",
            ),
            (
                ["management", "managerial", "manager", "leadership", "supervisor", "team lead"],
                [],
                "0",
            ),
        ]

        for aliases, keys, default_answer in alias_groups:
            if any(alias in haystack for alias in aliases):
                answer = mapped_years(keys)
                if answer is not None:
                    return answer
                derived = derived_years(aliases)
                if derived is not None:
                    return derived
                if default_answer is not None:
                    return default_answer

        return None

    def _format_experience_years_value(self, value) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value).strip()
        whole_years = max(0, int(numeric))
        return str(whole_years)

    def _experience_years_from_work_history(self, keywords: list[str]) -> Optional[float]:
        work_experience = self.profile.get("work_experience", [])
        if not work_experience:
            return None

        matched_any = False
        matched_months = 0.0
        for item in work_experience:
            combined = " ".join(
                str(item.get(key, "") or "")
                for key in ["title", "company", "location", "description"]
            ).lower()
            if not any(keyword in combined for keyword in keywords):
                continue
            matched_any = True
            matched_months += self._role_duration_months(item)

        if not matched_any:
            return None
        return matched_months / 12

    def _role_duration_months(self, item: dict) -> float:
        from datetime import datetime

        def parse_month(value: str):
            value = (value or "").strip()
            if not value:
                return None
            try:
                return datetime.strptime(value, "%Y-%m")
            except ValueError:
                return None

        start = parse_month(item.get("start_date", ""))
        end = parse_month(item.get("end_date", "")) or datetime.now()
        if not start or end < start:
            return 0.0

        months = (end.year - start.year) * 12 + (end.month - start.month)
        if months <= 0:
            return 1.0 / 12.0
        return float(months)

    def _infer_workplace_type(self, job: dict) -> str:
        combined_text = self._combined_job_text(job)
        if "hybrid" in combined_text:
            return "hybrid"
        if "remote" in combined_text or "work from home" in combined_text:
            return "remote"
        if "on-site" in combined_text or "onsite" in combined_text or "on site" in combined_text:
            return "onsite"
        return ""

    def _infer_employment_type(self, job: dict) -> str:
        combined_text = self._combined_job_text(job)
        if re.search(r"(?<!\w)(internship|intern|stagiaire|meewerkstage|afstudeerstage|stageplek)(?!\w)", combined_text):
            return "internship"
        if "full-time" in combined_text or "full time" in combined_text:
            return "full-time"
        if "part-time" in combined_text or "part time" in combined_text:
            return "part-time"
        if "contract" in combined_text:
            return "contract"
        if "temporary" in combined_text or "temp" in combined_text:
            return "temporary"
        return ""

    def _dutch_language_risk(self, combined_text: str) -> str:
        risk_markers = [
            "fluent dutch",
            "fluent in dutch",
            "b2 dutch",
            "dutch b2",
            "dutch preferred",
            "local language",
            "nederlands preferred",
            "vloeiend nederlands",
        ]
        for marker in risk_markers:
            if marker in combined_text:
                return f"Dutch/local-language risk: {marker}"
        return ""

    def _commute_risk(self, location: str) -> str:
        lowered = (location or "").lower()
        risk_locations = {
            "utrecht",
            "hilversum",
            "leiden",
            "the hague",
            "den haag",
            "rotterdam",
            "almere",
        }
        for place in risk_locations:
            if place in lowered:
                return f"Commute/location concern: {place}"
        return ""

    def _estimate_salary_for_comparison(self, salary_text: str):
        if not salary_text:
            return None

        numeric_values = re.findall(r"\d[\d,.]*", salary_text)
        if not numeric_values:
            return None

        cleaned_values = []
        for value in numeric_values:
            normalized = value.replace(",", "").strip()
            try:
                cleaned_values.append(float(normalized))
            except ValueError:
                continue

        if not cleaned_values:
            return None

        offered_amount = max(cleaned_values)
        lowered = salary_text.lower()

        if any(token in lowered for token in ["per year", "a year", "yearly", "annual"]):
            return int(offered_amount / 12)
        if any(token in lowered for token in ["per month", "monthly", "/month"]):
            return int(offered_amount)
        if any(token in lowered for token in ["per hour", "hourly", "/hour"]):
            return int(offered_amount * 160)
        return int(offered_amount)

    def _years_of_experience(self) -> int:
        """Rough calculation of total years of experience."""
        from datetime import datetime

        total = 0
        for job in self.profile.get("work_experience", []):
            start = job.get("start_date", "")
            end = job.get("end_date", "")
            try:
                start_year = int(start[:4])
                end_year = datetime.now().year if end == "present" else int(end[:4])
                total += end_year - start_year
            except Exception:
                pass
        return total
