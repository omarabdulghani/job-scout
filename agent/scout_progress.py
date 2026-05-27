import json
from datetime import datetime
from pathlib import Path


class ScoutProgressStore:
    PROGRESS_PATH = Path("scout_progress.json")

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else self.PROGRESS_PATH

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def save(self, payload: dict) -> None:
        normalized = dict(payload or {})
        normalized["updated_at"] = datetime.now().astimezone().isoformat()
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
