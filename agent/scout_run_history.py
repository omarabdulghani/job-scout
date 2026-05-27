import json
from datetime import datetime
from pathlib import Path


class ScoutRunHistoryStore:
    HISTORY_PATH = Path("scout_run_history.json")

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else self.HISTORY_PATH
        self.entries = self._load()

    def append_run(self, record: dict) -> None:
        entry = {
            "timestamp": record.get("timestamp") or datetime.now().astimezone().isoformat(),
            "started_at": record.get("started_at", ""),
            "completed_at": record.get("completed_at", record.get("timestamp", "")),
            "query": record.get("query", ""),
            "location": record.get("location", ""),
            "total_scanned": int(record.get("total_scanned", 0) or 0),
            "new_recommendations": int(record.get("new_recommendations", 0) or 0),
            "cached_previous_recommendations": int(
                record.get("cached_previous_recommendations", 0) or 0
            ),
            "rejected_or_below_threshold": int(
                record.get("rejected_or_below_threshold", 0) or 0
            ),
            "results_layout_types": list(record.get("results_layout_types", []) or []),
        }
        self.entries.append(entry)
        self._write()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        runs = raw.get("runs", []) if isinstance(raw, dict) else []
        if not isinstance(runs, list):
            return []
        return [entry for entry in runs if isinstance(entry, dict)]

    def _write(self) -> None:
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(),
            "runs": sorted(
                self.entries,
                key=lambda item: item.get("timestamp", ""),
                reverse=True,
            ),
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
