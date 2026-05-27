from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path


class DescriptionLogWriter:
    """Progressively writes extracted job descriptions as JSONL records."""

    def __init__(self, directory: Path | str = "description_logs") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = self.directory / f"job_descriptions_{timestamp}.jsonl"
        self.path.touch(exist_ok=True)
        self.seen_keys: set[str] = set()
        self.records_written = 0

    def write(self, record: dict, identity_keys: list[str]) -> bool:
        keys = self._normalized_identity_keys(identity_keys)
        if keys and any(key in self.seen_keys for key in keys):
            return False

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        for key in keys:
            self.seen_keys.add(key)
        self.records_written += 1
        return True

    def _normalized_identity_keys(self, identity_keys: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for value in identity_keys or []:
            cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized
