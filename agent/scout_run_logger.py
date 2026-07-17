from __future__ import annotations

import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class _TeeTextStream(io.TextIOBase):
    def __init__(self, original_stream, log_handle):
        self._original_stream = original_stream
        self._log_handle = log_handle

    @property
    def encoding(self):
        return getattr(self._original_stream, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._original_stream, "errors", "strict")

    @property
    def buffer(self):
        return getattr(self._original_stream, "buffer", None)

    def writable(self):
        return True

    def isatty(self):
        try:
            return bool(self._original_stream.isatty())
        except Exception:
            return False

    def fileno(self):
        return self._original_stream.fileno()

    def write(self, data):
        text = "" if data is None else str(data)
        if not text:
            return 0
        written = self._original_stream.write(text)
        self._log_handle.write(ANSI_ESCAPE_RE.sub("", text))
        return written if written is not None else len(text)

    def flush(self):
        try:
            self._original_stream.flush()
        finally:
            self._log_handle.flush()


class ScoutRunLogger:
    def __init__(self, log_dir: Path | str = "logs", prefix: str = "scout_log"):
        configured_log_dir = os.getenv("JOB_SCOUT_LOG_DIR", "").strip()
        self.log_dir = Path(configured_log_dir or log_dir)
        self.prefix = prefix
        self.log_path: Path | None = None
        self._log_handle = None
        self._stdout_original = None
        self._stderr_original = None
        self._installed = False

    def install(self) -> Path:
        if self._installed and self.log_path:
            return self.log_path

        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = self.log_dir / f"{self.prefix}_{timestamp}.txt"
        self._log_handle = self.log_path.open("w", encoding="utf-8", buffering=1)
        self._stdout_original = sys.stdout
        self._stderr_original = sys.stderr
        sys.stdout = _TeeTextStream(self._stdout_original, self._log_handle)
        sys.stderr = _TeeTextStream(self._stderr_original, self._log_handle)
        self._installed = True
        return self.log_path

    def close(self) -> None:
        if not self._installed:
            return

        try:
            if sys.stdout is not self._stdout_original:
                sys.stdout = self._stdout_original
            if sys.stderr is not self._stderr_original:
                sys.stderr = self._stderr_original
        finally:
            if self._log_handle:
                self._log_handle.flush()
                self._log_handle.close()
        self._installed = False
