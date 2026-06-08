"""Application-answer knowledge and deliberate document tools."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from agent.brain import JobBrain
from agent.user_workspace import UserWorkspace


class ApplicationAssistantService:
    """Manage reusable application answers and cover-letter drafts."""

    def __init__(self, workspace: UserWorkspace) -> None:
        self.workspace = workspace.ensure_initialized()
        self.learned_answers_path = self.workspace.path / "learned_answers.json"

    def payload(self, jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        profile = self.workspace.load_profile()
        preferences = self.workspace.load_preferences()
        application_answers = profile.get("application_answers")
        if not isinstance(application_answers, dict):
            application_answers = {}
        selected_jobs = []
        for job in jobs or []:
            if not isinstance(job, dict):
                continue
            selected_jobs.append(
                {
                    "job_key": str(job.get("job_key") or ""),
                    "job_id": str(job.get("job_id") or ""),
                    "board": str(job.get("board") or "linkedin"),
                    "title": str(job.get("title") or ""),
                    "company": str(job.get("company") or ""),
                    "location": str(job.get("location") or ""),
                    "url": str(job.get("url") or ""),
                    "reason": str(job.get("reason") or ""),
                    "description_preview": str(job.get("description_preview") or ""),
                    "decision_category": str(job.get("decision_category") or ""),
                    "score": int(job.get("score") or 0),
                }
            )
        selected_jobs.sort(
            key=lambda item: (
                item["decision_category"] == "APPLY_FIRST",
                item["score"],
                item["title"],
            ),
            reverse=True,
        )
        return {
            "application_answers": deepcopy(application_answers),
            "learned_answers": self._load_learned_answers(),
            "cover_letter_style": str(profile.get("cover_letter_style") or ""),
            "pause_before_final_submit": bool(
                preferences.get("application_behavior", {}).get(
                    "pause_before_final_submit",
                    True,
                )
            ),
            "jobs": selected_jobs[:500],
            "ai_document_provider": "Anthropic Claude",
            "ai_document_configured": self._anthropic_configured(),
        }

    def save_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Application assistant payload must be an object")
        profile = self.workspace.load_profile()
        profile["application_answers"] = self._clean_application_answers(
            payload.get("application_answers"),
            max_items=150,
        )
        if "cover_letter_style" in payload:
            profile["cover_letter_style"] = str(payload.get("cover_letter_style") or "").strip()[:2000]
        learned_answers = self._clean_mapping(payload.get("learned_answers"), max_items=300)
        self.workspace.save_profile(profile)
        self.workspace.save_text(
            self.learned_answers_path,
            json.dumps(learned_answers, indent=2, ensure_ascii=False) + "\n",
        )
        return self.payload()

    def local_cover_letter_draft(self, job: dict[str, Any]) -> str:
        profile = self.workspace.load_profile()
        personal = profile.get("personal") if isinstance(profile.get("personal"), dict) else {}
        first_name = str(personal.get("first_name") or "the applicant").strip()
        about = str(profile.get("about_me") or "").strip()
        experience = profile.get("work_experience")
        latest = experience[0] if isinstance(experience, list) and experience and isinstance(experience[0], dict) else {}
        skills = profile.get("skills") if isinstance(profile.get("skills"), list) else []
        title = str(job.get("title") or "this role").strip()
        company = str(job.get("company") or "your organization").strip()
        reason = str(job.get("reason") or job.get("description_preview") or "").strip()
        experience_line = ""
        if latest:
            experience_line = (
                f"My experience as {latest.get('title', 'a professional')} at "
                f"{latest.get('company', 'my previous organization')} strengthened my ability to "
                "coordinate practical digital work, communicate with stakeholders, and turn ideas into usable outcomes."
            )
        skills_line = ", ".join(str(item) for item in skills[:6] if str(item).strip())
        return "\n\n".join(
            [
                "Dear Hiring Team,",
                (
                    f"I am interested in the {title} opportunity at {company}. "
                    f"{about[:520]}"
                ).strip(),
                (
                    f"{experience_line} "
                    + (f"My relevant strengths include {skills_line}. " if skills_line else "")
                    + (f"The role stands out because {reason[:360]}" if reason else "")
                ).strip(),
                (
                    f"I would welcome the opportunity to discuss how my background, curiosity, and practical working style "
                    f"could contribute to {company}. Thank you for your consideration.\n\nKind regards,\n{first_name}"
                ),
            ]
        ).strip()

    def ai_cover_letter_draft(self, job: dict[str, Any]) -> str:
        profile, preferences = self.workspace.load_config()
        return JobBrain(profile, preferences).generate_cover_letter(job).strip()

    def answer_question(self, question: str, context: str = "") -> dict[str, Any]:
        cleaned_question = str(question or "").strip()
        if not cleaned_question:
            raise ValueError("Question is required")
        profile, preferences = self.workspace.load_config()
        brain = JobBrain(profile, preferences)
        answer = brain.get_structured_question_answer(cleaned_question, str(context or ""))
        if answer:
            return {"answer": answer, "source": "saved_profile", "needs_ai": False}
        return {
            "answer": "",
            "source": "not_found",
            "needs_ai": True,
            "message": "No trustworthy saved answer matched. Review manually or use the existing application flow with human pause.",
        }

    def _load_learned_answers(self) -> dict[str, str]:
        candidates = (
            self.learned_answers_path,
            self.workspace.root / "data" / "learned_answers.json",
        )
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return {
                    str(key): str(value)
                    for key, value in payload.items()
                    if str(key).strip() and str(value).strip()
                }
        return {}

    def _clean_mapping(self, value: Any, *, max_items: int) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError("Answers must be an object")
        cleaned: dict[str, str] = {}
        for key, answer in list(value.items())[:max_items]:
            clean_key = " ".join(str(key or "").split())[:300]
            clean_answer = str(answer or "").strip()[:5000]
            if clean_key and clean_answer:
                cleaned[clean_key] = clean_answer
        return cleaned

    def _clean_application_answers(self, value: Any, *, max_items: int) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Application answers must be an object")
        cleaned: dict[str, Any] = {}
        for key, answer in list(value.items())[:max_items]:
            clean_key = " ".join(str(key or "").split())[:300]
            if not clean_key:
                continue
            if isinstance(answer, dict):
                clean_value = {
                    " ".join(str(inner_key or "").split())[:200]: inner_value
                    for inner_key, inner_value in list(answer.items())[:100]
                    if str(inner_key or "").strip()
                }
            elif isinstance(answer, list):
                clean_value = answer[:100]
            elif isinstance(answer, (bool, int, float)):
                clean_value = answer
            else:
                clean_value = str(answer or "").strip()[:5000]
            if clean_value not in ("", None, [], {}):
                cleaned[clean_key] = clean_value
        return cleaned

    def _anthropic_configured(self) -> bool:
        env_path = self.workspace.root / ".env"
        try:
            lines = env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            return False
        for line in lines:
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return bool(value and not value.lower().startswith("your_"))
        return False
