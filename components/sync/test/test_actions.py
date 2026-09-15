from __future__ import annotations

import unittest
from pathlib import Path

from components.sync.api import actions


class SyncActionControllerTests(unittest.TestCase):
    def test_run_commands_result_uses_injected_command_runner(self) -> None:
        calls: list[tuple[str, list[list[str]]]] = []
        controller = actions.SyncActionController(
            {},
            app_dir=Path("/app"),
            fetch_project_listing=lambda _current_dir: [],
            save_config=lambda _config: None,
            run_commands=lambda title, commands: calls.append((title, commands)),
        )

        controller.run_action_result(None, {"kind": "run-commands", "title": "Sync", "commands": [["rsync"]]})

        self.assertEqual(calls, [("Sync", [["rsync"]])])

    def test_unknown_result_is_rejected(self) -> None:
        controller = actions.SyncActionController(
            {},
            app_dir=Path("/app"),
            fetch_project_listing=lambda _current_dir: [],
            save_config=lambda _config: None,
            run_commands=lambda _title, _commands: None,
        )

        with self.assertRaisesRegex(ValueError, "unsupported sync action result"):
            controller.run_action_result(None, {"kind": "unknown"})


if __name__ == "__main__":
    unittest.main()
