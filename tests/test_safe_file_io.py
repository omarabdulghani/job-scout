import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.safe_file_io import (
    PersistenceError,
    atomic_write_json,
    atomic_write_text,
    load_json_with_recovery,
    temporary_candidates,
)


class SafeFileIOTests(unittest.TestCase):
    def test_transient_permission_error_retries_and_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("temporarily locked")
                return real_replace(source, destination)

            with patch("agent.safe_file_io.os.replace", side_effect=flaky_replace):
                atomic_write_json(target, {"status": "completed"}, sleep=lambda _delay: None)

            self.assertEqual(attempts, 3)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"status": "completed"},
            )
            self.assertEqual(temporary_candidates(target), [])

    def test_permanent_permission_error_preserves_recoverable_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            target.write_text('{"status":"old"}', encoding="utf-8")

            with patch(
                "agent.safe_file_io.os.replace",
                side_effect=PermissionError("still locked"),
            ):
                with self.assertRaises(PersistenceError) as raised:
                    atomic_write_json(
                        target,
                        {"status": "new"},
                        retry_delays=(0, 0),
                        sleep=lambda _delay: None,
                    )

            self.assertEqual(raised.exception.attempts, 3)
            self.assertTrue(raised.exception.temporary_path.exists())
            self.assertEqual(
                json.loads(raised.exception.temporary_path.read_text(encoding="utf-8")),
                {"status": "new"},
            )
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["status"], "old")

            recovered = load_json_with_recovery(
                target,
                candidate_min_age_seconds=0,
            )
            self.assertEqual(recovered["status"], "new")
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["status"],
                "new",
            )

    def test_concurrent_writers_leave_complete_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            errors = []

            def write(index):
                try:
                    atomic_write_json(target, {"writer": index, "items": list(range(50))})
                except Exception as exc:  # pragma: no cover - assertion reports any thread error
                    errors.append(exc)

            threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn(payload["writer"], range(12))
            self.assertEqual(payload["items"], list(range(50)))
            self.assertEqual(temporary_candidates(target), [])

    def test_newer_valid_legacy_candidate_is_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "state.json"
            recovery = root / "recovery"
            target.write_text(
                '{"updated_at":"2026-06-10T10:00:00+02:00","status":"old"}',
                encoding="utf-8",
            )
            candidate = target.with_suffix(".json.tmp")
            candidate.write_text(
                '{"updated_at":"2026-06-10T11:00:00+02:00","status":"new"}',
                encoding="utf-8",
            )

            payload = load_json_with_recovery(
                target,
                recovery_dir=recovery,
                candidate_min_age_seconds=0,
            )

            self.assertEqual(payload["status"], "new")
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["status"],
                "new",
            )
            events = list(recovery.glob("recovery_*.json"))
            self.assertEqual(len(events), 1)
            self.assertEqual(
                json.loads(events[0].read_text(encoding="utf-8"))["action"],
                "promoted",
            )

    def test_recent_candidate_is_not_recovered_while_writer_may_still_be_active(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "state.json"
            target.write_text(
                '{"updated_at":"2026-06-10T10:00:00+02:00","status":"old"}',
                encoding="utf-8",
            )
            candidate = target.with_suffix(".json.tmp")
            candidate.write_text(
                '{"updated_at":"2026-06-10T11:00:00+02:00","status":"new"}',
                encoding="utf-8",
            )

            payload = load_json_with_recovery(target)

            self.assertEqual(payload["status"], "old")
            self.assertTrue(candidate.exists())

    def test_invalid_candidate_is_archived_without_replacing_valid_main(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "state.json"
            recovery = root / "recovery"
            target.write_text('{"status":"completed"}', encoding="utf-8")
            candidate = target.with_name(".state.json.tmp")
            candidate.write_text('{"status":', encoding="utf-8")

            payload = load_json_with_recovery(
                target,
                recovery_dir=recovery,
                candidate_min_age_seconds=0,
            )

            self.assertEqual(payload["status"], "completed")
            self.assertFalse(candidate.exists())
            self.assertEqual(len(list(recovery.glob("*.invalid.*.tmp"))), 1)

    def test_atomic_text_preserves_exact_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "notes.txt"
            content = "first line\r\nsecond line; punctuation, preserved\n"

            atomic_write_text(target, content)

            self.assertEqual(target.read_text(encoding="utf-8", newline=""), content)


if __name__ == "__main__":
    unittest.main()
