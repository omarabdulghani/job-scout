"""Windows-safe atomic file writes and conservative JSON recovery."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable
from uuid import uuid4


DEFAULT_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0)
JSON_TIMESTAMP_FIELDS = (
    "updated_at",
    "dashboard_updated_at",
    "completed_at",
    "timestamp",
    "generated_at",
    "started_at",
)

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


class PersistenceError(OSError):
    """Raised when an atomic replacement cannot complete after bounded retries."""

    def __init__(
        self,
        target_path: Path,
        temporary_path: Path,
        attempts: int,
        original_error: OSError,
    ) -> None:
        self.target_path = Path(target_path)
        self.temporary_path = Path(temporary_path)
        self.attempts = int(attempts)
        self.original_error = original_error
        super().__init__(
            f"Could not replace {self.target_path} after {self.attempts} attempts; "
            f"recoverable data remains at {self.temporary_path}: {original_error}"
        )


def atomic_write_text(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Write text through a unique same-directory temporary file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _path_lock(target)
    with lock:
        temporary = _unique_temporary_path(target)
        try:
            with temporary.open("x", encoding=encoding, newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(
                temporary,
                target,
                retry_delays=retry_delays,
                sleep=sleep,
            )
        except PersistenceError:
            raise
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target


def atomic_write_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int = 2,
    trailing_newline: bool = True,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    text = json.dumps(payload, indent=indent, ensure_ascii=False)
    if trailing_newline:
        text += "\n"
    return atomic_write_text(
        path,
        text,
        retry_delays=retry_delays,
        sleep=sleep,
    )


def load_json_with_recovery(
    path: Path | str,
    *,
    default: dict[str, Any] | None = None,
    recovery_dir: Path | str | None = None,
    candidate_min_age_seconds: float = 15.0,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Load a JSON object and recover a newer valid interrupted write when safe."""

    target = Path(path)
    fallback = dict(default or {})
    lock = _path_lock(target)
    with lock:
        main_payload = _read_json_object(target)
        main_score = _payload_score(target, main_payload) if main_payload is not None else None
        eligible_candidates = _eligible_temporary_candidates(
            target,
            minimum_age_seconds=candidate_min_age_seconds,
        )
        valid_candidates: list[tuple[Path, dict[str, Any], tuple[float, int]]] = []
        invalid_candidates: list[Path] = []
        for candidate in eligible_candidates:
            payload = _read_json_object(candidate)
            if payload is None:
                invalid_candidates.append(candidate)
                continue
            valid_candidates.append((candidate, payload, _payload_score(candidate, payload)))

        destination = _recovery_directory(target, recovery_dir)
        for candidate in invalid_candidates:
            _archive_candidate(candidate, destination, "invalid", target)

        if not valid_candidates:
            return main_payload if main_payload is not None else fallback

        valid_candidates.sort(key=lambda item: item[2], reverse=True)
        candidate, candidate_payload, candidate_score = valid_candidates[0]
        should_promote = main_payload is None or main_score is None or candidate_score > main_score
        if should_promote:
            try:
                _replace_with_retry(
                    candidate,
                    target,
                    retry_delays=retry_delays,
                    sleep=sleep,
                )
            except PersistenceError:
                _record_recovery_event(
                    destination,
                    target=target,
                    candidate=candidate,
                    action="promotion_pending",
                )
                return candidate_payload
            _record_recovery_event(
                destination,
                target=target,
                candidate=candidate,
                action="promoted",
            )
            main_payload = candidate_payload
        else:
            _archive_candidate(candidate, destination, "superseded", target)

        for remaining, _payload, _score in valid_candidates[1:]:
            _archive_candidate(remaining, destination, "superseded", target)
        return main_payload if main_payload is not None else fallback


def temporary_candidates(path: Path | str) -> list[Path]:
    """Return recognized interrupted-write candidates for a target."""

    target = Path(path)
    candidates = {
        target.with_suffix(f"{target.suffix}.tmp"),
        target.with_name(f".{target.name}.tmp"),
    }
    candidates.update(target.parent.glob(f".{target.name}.*.tmp"))
    candidates.update(target.parent.glob(f"{target.name}.*.tmp"))
    return sorted(
        (candidate for candidate in candidates if candidate != target and candidate.exists()),
        key=lambda candidate: str(candidate).lower(),
    )


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _unique_temporary_path(path: Path) -> Path:
    return path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
    )


def _replace_with_retry(
    source: Path,
    target: Path,
    *,
    retry_delays: tuple[float, ...],
    sleep: Callable[[float], None],
) -> None:
    attempts = len(retry_delays) + 1
    for index in range(attempts):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            if not _is_transient_windows_lock(exc):
                source.unlink(missing_ok=True)
                raise
            if index >= len(retry_delays):
                raise PersistenceError(target, source, attempts, exc) from exc
            sleep(retry_delays[index])


def _is_transient_windows_lock(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32}


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _eligible_temporary_candidates(
    target: Path,
    *,
    minimum_age_seconds: float,
) -> list[Path]:
    cutoff = time.time() - max(0.0, float(minimum_age_seconds))
    output = []
    for candidate in temporary_candidates(target):
        try:
            if candidate.stat().st_mtime <= cutoff:
                output.append(candidate)
        except OSError:
            continue
    return output


def _payload_score(path: Path, payload: dict[str, Any]) -> tuple[float, int]:
    semantic_time = 0.0
    for field in JSON_TIMESTAMP_FIELDS:
        value = payload.get(field)
        if not value:
            continue
        try:
            semantic_time = max(semantic_time, datetime.fromisoformat(str(value)).timestamp())
        except (TypeError, ValueError):
            continue
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return semantic_time, modified_ns


def _recovery_directory(target: Path, recovery_dir: Path | str | None) -> Path:
    if recovery_dir:
        destination = Path(recovery_dir)
    else:
        cwd = Path.cwd().resolve()
        try:
            target.resolve().relative_to(cwd)
            destination = cwd / "backups" / "runtime-recovery"
        except ValueError:
            destination = target.parent / "runtime-recovery"
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _archive_candidate(
    candidate: Path,
    destination: Path,
    reason: str,
    target: Path,
) -> None:
    if not candidate.exists():
        return
    archived = destination / (
        f"{target.name}.{reason}.{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')}"
        f".{uuid4().hex}.tmp"
    )
    try:
        shutil.move(str(candidate), str(archived))
    except OSError:
        return
    _record_recovery_event(
        destination,
        target=target,
        candidate=archived,
        action=reason,
    )


def _record_recovery_event(
    destination: Path,
    *,
    target: Path,
    candidate: Path,
    action: str,
) -> None:
    event_path = destination / (
        f"recovery_{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')}"
        f"_{uuid4().hex}.json"
    )
    payload = {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "target": target.name,
        "candidate": candidate.name,
        "action": action,
    }
    try:
        with event_path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError:
        pass
