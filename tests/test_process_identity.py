import os
import unittest

from agent.process_identity import inspect_process


class ProcessIdentityTests(unittest.TestCase):
    def test_current_process_has_stable_identity(self):
        first = inspect_process(os.getpid())
        second = inspect_process(os.getpid())

        self.assertTrue(first["alive"])
        self.assertEqual(first["process_id"], os.getpid())
        self.assertTrue(first["creation_token"])
        self.assertEqual(first["creation_token"], second["creation_token"])

    def test_invalid_process_is_not_alive(self):
        identity = inspect_process(0)

        self.assertFalse(identity["alive"])


if __name__ == "__main__":
    unittest.main()
