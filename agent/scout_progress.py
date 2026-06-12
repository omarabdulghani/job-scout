from datetime import datetime
from pathlib import Path

from agent.safe_file_io import (
    DEFAULT_RETRY_DELAYS,
    atomic_write_json,
    load_json_with_recovery,
    temporary_candidates,
)


class ScoutProgressStore:
    PROGRESS_PATH = Path("scout_progress.json")

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else self.PROGRESS_PATH

    def load(self) -> dict:
        return load_json_with_recovery(self.path)

    def save(
        self,
        payload: dict,
        *,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        normalized = dict(payload or {})
        normalized["updated_at"] = datetime.now().astimezone().isoformat()
        atomic_write_json(
            self.path,
            normalized,
            trailing_newline=False,
            retry_delays=retry_delays,
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        for candidate in temporary_candidates(self.path):
            candidate.unlink(missing_ok=True)
