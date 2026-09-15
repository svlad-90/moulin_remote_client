from __future__ import annotations

import unittest

from components.process.api import script


class ProcessScriptServiceTests(unittest.TestCase):
    def test_local_log_command_quotes_lines_and_exit_code(self) -> None:
        service = script.process_script_service()

        self.assertEqual(
            service.local_log_command("hello", "path: /tmp/a b", exit_code=7),
            [
                "bash",
                "-lc",
                "printf '%s\\n' hello\nprintf '%s\\n' 'path: /tmp/a b'\nexit 7\n",
            ],
        )


if __name__ == "__main__":
    unittest.main()
