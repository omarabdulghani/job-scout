"""Private, versioned user workspace for profile and search configuration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any

from agent.safe_file_io import atomic_write_json, atomic_write_text, load_json_with_recovery


SCHEMA_VERSION = "job_agent_workspace.v1"
WORKSPACE_RELATIVE_PATH = Path("data/user_workspace")


class UserWorkspace:
    """Own user-editable data separately from source-controlled defaults."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).resolve()
        self.path = self.root / WORKSPACE_RELATIVE_PATH
        self.manifest_path = self.path / "workspace.json"
        self.profile_path = self.path / "profile.json"
        self.preferences_path = self.path / "preferences.json"
        self.strategy_path = self.path / "job_strategy.txt"
        self.portfolio_notes_path = self.path / "portfolio_notes.txt"
        self.search_queries_path = self.path / "search_queries.txt"
        self.cv_dir = self.path / "cv"
        self.backup_dir = self.path / "backups"

    def ensure_initialized(self) -> "UserWorkspace":
        self.path.mkdir(parents=True, exist_ok=True)
        self.cv_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        created_at = now_iso()
        profile = self._seed_json(
            self.profile_path,
            self.root / "config" / "profile.json",
            label="profile",
        )
        self._seed_json(
            self.preferences_path,
            self.root / "config" / "preferences.json",
            label="preferences",
        )
        self._seed_text(
            self.strategy_path,
            self.root / "PERFECT SUITABLE JOB PROFILE.txt",
        )
        self._seed_text(
            self.portfolio_notes_path,
            self.root / "data" / "portfolio_site_notes.txt",
        )
        self._seed_text(
            self.search_queries_path,
            self.root / "search_queries.txt",
        )

        if profile:
            migrated_profile = self._migrate_cv(profile)
            if migrated_profile != profile:
                self._atomic_json_write(self.profile_path, migrated_profile)

        manifest = self._load_json_if_valid(self.manifest_path)
        if manifest.get("schema_version") != SCHEMA_VERSION:
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "created_at": manifest.get("created_at") or created_at,
                "updated_at": now_iso(),
                "source": "migrated_from_project_defaults",
            }
            self._atomic_json_write(self.manifest_path, manifest)
        return self

    def load_profile(self) -> dict[str, Any]:
        self.ensure_initialized()
        return self._required_json(self.profile_path, "Profile")

    def load_preferences(self) -> dict[str, Any]:
        self.ensure_initialized()
        return self._required_json(self.preferences_path, "Preferences")

    def load_config(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.load_profile(), self.load_preferences()

    def save_profile(self, profile: dict[str, Any]) -> None:
        self._save_json(self.profile_path, profile)

    def save_preferences(self, preferences: dict[str, Any]) -> None:
        self._save_json(self.preferences_path, preferences)

    def save_text(self, destination: Path, value: str) -> None:
        self.ensure_initialized()
        self._backup(destination)
        self._atomic_text_write(destination, str(value or ""))
        self._touch_manifest()

    def public_paths(self) -> dict[str, str]:
        self.ensure_initialized()
        return {
            "workspace": str(self.path),
            "profile": str(self.profile_path),
            "preferences": str(self.preferences_path),
            "strategy": str(self.strategy_path),
            "portfolio_notes": str(self.portfolio_notes_path),
            "search_queries": str(self.search_queries_path),
            "cv_dir": str(self.cv_dir),
        }

    def _save_json(self, destination: Path, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Workspace JSON payload must be an object")
        self.ensure_initialized()
        self._backup(destination)
        self._atomic_json_write(destination, deepcopy(payload))
        self._touch_manifest()

    def _seed_json(self, destination: Path, source: Path, *, label: str) -> dict[str, Any]:
        if destination.exists():
            return self._required_json(destination, label.title())
        if not source.exists():
            raise FileNotFoundError(f"{label.title()} source not found at {source}")
        payload = self._required_json(source, label.title())
        self._atomic_json_write(destination, payload)
        return payload

    def _seed_text(self, destination: Path, source: Path) -> None:
        if destination.exists():
            return
        if source.exists():
            self._atomic_text_write(
                destination,
                source.read_text(encoding="utf-8", errors="replace"),
            )
        else:
            self._atomic_text_write(destination, "")

    def _migrate_cv(self, profile: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(profile.get("cv_path") or "").strip()
        if not raw_path:
            return profile
        source = Path(raw_path)
        if not source.is_absolute():
            source = self.root / source
        if not source.exists() or not source.is_file():
            return profile

        destination = self.cv_dir / source.name
        if not destination.exists():
            shutil.copy2(source, destination)

        relative_path = destination.relative_to(self.root).as_posix()
        if profile.get("cv_path") == relative_path:
            return profile
        migrated = deepcopy(profile)
        migrated["cv_path"] = relative_path
        return migrated

    def _backup(self, source: Path) -> None:
        if not source.exists():
            return
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        destination = self.backup_dir / f"{source.stem}_{timestamp}{source.suffix}"
        shutil.copy2(source, destination)

    def _touch_manifest(self) -> None:
        manifest = self._load_json_if_valid(self.manifest_path)
        manifest.update(
            {
                "schema_version": SCHEMA_VERSION,
                "created_at": manifest.get("created_at") or now_iso(),
                "updated_at": now_iso(),
            }
        )
        self._atomic_json_write(self.manifest_path, manifest)

    def _required_json(self, path: Path, label: str) -> dict[str, Any]:
        missing_marker = {"__job_scout_required_json_missing__": True}
        payload = load_json_with_recovery(path, default=missing_marker)
        if payload == missing_marker:
            if not path.exists():
                raise FileNotFoundError(f"{label} not found at {path}")
            raise ValueError(f"{label} contains invalid JSON")
        return payload

    def _load_json_if_valid(self, path: Path) -> dict[str, Any]:
        return load_json_with_recovery(path)

    def _atomic_json_write(self, path: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(path, payload)

    def _atomic_text_write(self, path: Path, text: str) -> None:
        atomic_write_text(path, text)


def load_user_config(root: Path | str = ".") -> tuple[dict[str, Any], dict[str, Any]]:
    return UserWorkspace(root).load_config()


def active_search_queries_path(root: Path | str = ".") -> Path:
    return UserWorkspace(root).ensure_initialized().search_queries_path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()
