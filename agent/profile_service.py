"""Validated profile and CV operations for the local dashboard."""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader

from agent.user_workspace import UserWorkspace


MAX_CV_BYTES = 10 * 1024 * 1024


class ProfileService:
    def __init__(self, workspace: UserWorkspace) -> None:
        self.workspace = workspace.ensure_initialized()

    def payload(self) -> dict[str, Any]:
        profile = self.workspace.load_profile()
        cv_path = self._resolve_cv_path(profile)
        return {
            "profile": profile,
            "cv": self._cv_metadata(cv_path),
            "readiness": self._readiness(profile, cv_path),
        }

    def save_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_profile(profile)
        self._validate_profile(normalized)
        self.workspace.save_profile(normalized)
        return self.payload()

    def upload_cv(self, filename: str, content_base64: str) -> dict[str, Any]:
        safe_filename = self._safe_pdf_filename(filename)
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("CV upload is not valid base64 data") from exc
        if not content.startswith(b"%PDF"):
            raise ValueError("CV must be a valid PDF file")
        if len(content) > MAX_CV_BYTES:
            raise ValueError("CV must be 10 MB or smaller")

        destination = self.workspace.cv_dir / safe_filename
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)

        profile = self.workspace.load_profile()
        profile["cv_path"] = destination.relative_to(self.workspace.root).as_posix()
        self.workspace.save_profile(profile)
        return self.payload()

    def active_cv_path(self) -> Path | None:
        return self._resolve_cv_path(self.workspace.load_profile())

    def _resolve_cv_path(self, profile: dict[str, Any]) -> Path | None:
        raw_path = str(profile.get("cv_path") or "").strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.workspace.root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.workspace.root)
        except ValueError:
            return None
        return resolved if resolved.exists() and resolved.is_file() else None

    def _cv_metadata(self, path: Path | None) -> dict[str, Any]:
        if not path:
            return {
                "available": False,
                "filename": "",
                "size_bytes": 0,
                "preview_url": "",
                "extracted_text": "",
            }
        return {
            "available": True,
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "preview_url": "/api/profile/cv/file",
            "extracted_text": self._extract_pdf_text(path)[:12000],
        }

    def _readiness(self, profile: dict[str, Any], cv_path: Path | None) -> dict[str, Any]:
        personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
        location = personal.get("location", {}) if isinstance(personal.get("location"), dict) else {}
        checks = {
            "identity": bool(personal.get("first_name") and personal.get("last_name")),
            "contact": bool(personal.get("email") and personal.get("phone")),
            "location": bool(location.get("city") and location.get("country")),
            "summary": bool(str(profile.get("about_me") or "").strip()),
            "experience": bool(profile.get("work_experience")),
            "education": bool(profile.get("education")),
            "skills": bool(profile.get("skills")),
            "languages": bool(profile.get("languages")),
            "cv": bool(cv_path),
        }
        completed = sum(1 for value in checks.values() if value)
        return {
            "checks": checks,
            "completed": completed,
            "total": len(checks),
            "percent": round(completed / len(checks) * 100),
            "ready": completed == len(checks),
        }

    def _normalize_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, dict):
            raise ValueError("Profile must be a JSON object")
        normalized = deepcopy(profile)
        normalized.setdefault("personal", {})
        normalized["personal"].setdefault("location", {})
        for key in ("work_experience", "education", "skills", "languages", "certifications", "projects"):
            normalized.setdefault(key, [])
        return normalized

    def _validate_profile(self, profile: dict[str, Any]) -> None:
        personal = profile.get("personal", {})
        location = personal.get("location", {})
        required = {
            "First name": personal.get("first_name"),
            "Last name": personal.get("last_name"),
            "Email": personal.get("email"),
            "Phone": personal.get("phone"),
            "City": location.get("city"),
            "Country": location.get("country"),
        }
        missing = [label for label, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError("Missing required profile fields: " + ", ".join(missing))
        email = str(personal.get("email") or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Email address is not valid")
        for key in ("work_experience", "education", "skills", "languages", "certifications", "projects"):
            if not isinstance(profile.get(key), list):
                raise ValueError(f"{key} must be a list")

    def _safe_pdf_filename(self, filename: str) -> str:
        raw_name = Path(str(filename or "")).name
        if not raw_name.lower().endswith(".pdf"):
            raise ValueError("CV filename must end in .pdf")
        stem = re.sub(r"[^A-Za-z0-9 ._()-]+", "", Path(raw_name).stem).strip(" .")
        if not stem:
            stem = "cv"
        return f"{stem[:120]}.pdf"

    def _extract_pdf_text(self, path: Path) -> str:
        try:
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""
        return re.sub(r"\s+", " ", text).strip()
